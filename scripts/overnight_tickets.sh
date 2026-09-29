#!/usr/bin/env bash
# overnight_tickets.sh — run a chain of GitHub-issue tickets unattended, one fresh
# Claude Code session per ticket, driven by a prompt playbook.
#
# For each ticket, in playbook order:
#   1. branch  <prefix>/<nn>-<slug>, stacked on the previous ticket's branch
#   2. fresh headless session: /implement + the playbook's shared preamble + that
#      ticket's block
#   3. verify independently of the model: RESULT line, commits exist, tree clean,
#      no uncommitted new files, no new test failures vs the base branch's baseline,
#      guard-rail files untouched
#   4. independent clean-context reviewer session -> VERDICT line
#   5. on failure: resume the implementer with the reasons (up to MAX_ATTEMPTS)
#   6. on success: push, open a PR on main, close the issue with a link
# At the end: an optional read-only review session, and a morning report.
#
# Playbook format (markdown):
#   Source spec: `path/to/spec.md`         optional; handed to the reviewer
#   ## ... Shared preamble ...             first ``` block = preamble for every ticket
#   ### #<issue>: <title>                  first ``` block = that ticket's prompt,
#                                          starting with `/implement`
#   ## ... Morning report ...              optional; first ``` block = final review prompt
#   Any block may use {{WORK}}; it becomes .scratch/<run name>, the runner's dir.
#   The model finds {{WORK}}/issue-<n>.md and {{WORK}}/baseline-failures.txt there
#   and must write {{WORK}}/ticket-<n>-report.md. Its final line must be
#   `RESULT: PASS` or `RESULT: FAIL - <reason>`.
#
# Survives the night:
#   - usage/session limits: parses the reset time, sleeps until then (polling if it
#     can't parse), then resumes the SAME session. It never exits because of a limit.
#   - API overload/5xx/network errors: exponential backoff, then resume.
#   - hung sessions: wall-clock timeout, then resume.
#   - Mac sleep: re-execs itself under `caffeinate`.
#   - being killed: re-run it; finished tickets (DONE) are skipped and a half-done
#     ticket continues on its existing branch.
#
# Hard guards on the model (the runner does all outward actions itself):
#   - `git push` is disabled for the session (origin's pushurl is swapped out, then restored)
#   - `gh` is disabled for the session (GH_TOKEN set to an invalid value)
#   - --disallowedTools for push/gh/docker/psql/pg_dump/ssh
#   - verify fails if tests/conftest.py or pytest.ini change, or (unless
#     ALLOW_MIGRATIONS=1) a migration is added
#
# Usage:
#   scripts/overnight_tickets.sh <playbook.md> --dry-run      # preflight + print prompts
#   _CAFFEINATED=1 nohup caffeinate -dimsu scripts/overnight_tickets.sh <playbook.md> >/dev/null 2>&1 &
#   ONLY="11 12" scripts/overnight_tickets.sh <playbook.md>   # subset (stacks on earlier DONE)
# Env: RUN_NAME (default: playbook basename), BRANCH_PREFIX (default: RUN_NAME),
#      SPEC_PATH, MODEL, PR_BASE, SESSION_BUDGET_USD, TICKET_BUDGET_USD, MAX_ATTEMPTS,
#      STOP_ON_FAIL, ALLOW_MIGRATIONS, IMPLEMENT_CMD.
# Keep the laptop on power with the lid open, or it will still sleep.
#
# Morning: .scratch/<run name>/overnight-report.md

set -o pipefail   # not -u: bash 3.2 treats an empty "${arr[@]}" as unbound

# ── config (env-overridable) ───────────────────────────────────────────
PLAYBOOK_ARG=""; DRY_RUN=0
for arg in "$@"; do
  if [ "$arg" = "--dry-run" ]; then DRY_RUN=1; else PLAYBOOK_ARG="$arg"; fi
done
if [ -z "$PLAYBOOK_ARG" ] || [ ! -f "$PLAYBOOK_ARG" ]; then
  echo "usage: $0 <playbook.md> [--dry-run]" >&2; exit 2
fi
PLAYBOOK_SRC="$(cd "$(dirname "$PLAYBOOK_ARG")" && pwd)/$(basename "$PLAYBOOK_ARG")"
REPO_DIR="${REPO_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
RUN_NAME="${RUN_NAME:-$(basename "$PLAYBOOK_SRC" .md)}"
BRANCH_PREFIX="${BRANCH_PREFIX:-$RUN_NAME}"
IMPLEMENT_CMD="${IMPLEMENT_CMD:-/mattpocock-skills:implement}"
MODEL="${MODEL:-}"                              # empty = your CLI default
PR_BASE="${PR_BASE:-main}"
SESSION_BUDGET_USD="${SESSION_BUDGET_USD:-30}"  # per claude invocation (hitting it = checkpoint + resume)
TICKET_BUDGET_USD="${TICKET_BUDGET_USD:-120}"   # per ticket, all sessions summed (the real cap)
SESSION_TIMEOUT_S="${SESSION_TIMEOUT_S:-10800}" # 3h wall clock per invocation
TEST_TIMEOUT_S="${TEST_TIMEOUT_S:-1800}"
MAX_ATTEMPTS="${MAX_ATTEMPTS:-3}"               # implement passes per ticket (1 + fix-ups)
MAX_RESUMES="${MAX_RESUMES:-8}"                 # interruptions tolerated per session
MAX_LIMIT_WAIT_S="${MAX_LIMIT_WAIT_S:-64800}"   # give up waiting on a limit after 18h
STOP_ON_FAIL="${STOP_ON_FAIL:-1}"
ALLOW_MIGRATIONS="${ALLOW_MIGRATIONS:-0}"

REL_WORK=".scratch/$RUN_NAME"
WORK="$REPO_DIR/$REL_WORK"
STATE="$WORK/state"
LOGS="$WORK/logs"
STATUS_TSV="$WORK/runner-status.tsv"
REPORT="$WORK/overnight-report.md"
BASELINE="$WORK/baseline-failures.txt"
PLAYBOOK="$WORK/playbook.snapshot.md"
RUNLOG="$LOGS/runner.log"
PHASE_REVIEW_OUT="final-review.md"

# ── keep the Mac awake ─────────────────────────────────────────────────
if [ "$DRY_RUN" = 0 ] && [ -z "${_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null; then
  export _CAFFEINATED=1
  exec caffeinate -dimsu "$0" "$@"
fi

mkdir -p "$STATE" "$LOGS"
cd "$REPO_DIR" || exit 1

log()  { printf '%s  %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" | tee -a "$RUNLOG" >&2; }
die()  { log "FATAL: $*"; report_final "aborted: $*"; exit 1; }

notify() {
  command -v osascript >/dev/null && \
    osascript -e "display notification \"$1\" with title \"Midas overnight\"" >/dev/null 2>&1 || true
}

# ── single instance ────────────────────────────────────────────────────
LOCK="$WORK/.lock"
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -f "$LOCK/pid" ] && kill -0 "$(cat "$LOCK/pid")" 2>/dev/null; then
    echo "another run is active (pid $(cat "$LOCK/pid"))" >&2; exit 1
  fi
  rm -rf "$LOCK"; mkdir "$LOCK"
fi
echo $$ > "$LOCK/pid"

# ── git push guard: restore origin's pushurl however we exit ───────────
ORIG_PUSHURL="$(git config --get remote.origin.pushurl || true)"
case "$ORIG_PUSHURL" in no-push://*) ORIG_PUSHURL=""; git config --unset remote.origin.pushurl ;; esac  # left by a killed run
push_guard_on()  { git config remote.origin.pushurl "no-push://disabled-during-agent-session"; }
push_guard_off() {
  if [ -n "$ORIG_PUSHURL" ]; then git config remote.origin.pushurl "$ORIG_PUSHURL"
  else git config --unset remote.origin.pushurl 2>/dev/null || true; fi
}
cleanup() { push_guard_off; rm -rf "$LOCK"; }
trap cleanup EXIT
trap 'log "interrupted"; exit 130' INT TERM

# ── status file ────────────────────────────────────────────────────────
touch "$STATUS_TSV"
status_get() { awk -F'\t' -v t="$1" '$1==t {s=$2} END{print s}' "$STATUS_TSV"; }
field_get()  { awk -F'\t' -v t="$1" -v c="$2" '$1==t {s=$c} END{print s}' "$STATUS_TSV"; }
status_set() { # ticket status branch pr cost note
  local tmp; tmp="$(mktemp)"
  awk -F'\t' -v t="$1" '$1!=t' "$STATUS_TSV" > "$tmp"
  printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$6" >> "$tmp"
  sort -n "$tmp" > "$STATUS_TSV"; rm -f "$tmp"
}

# ── retry helper for network-y commands (git push, gh) ─────────────────
retry() { # retry <tries> <cmd...>
  local n="$1"; shift; local i=1 d=30
  while :; do
    "$@" && return 0
    [ "$i" -ge "$n" ] && return 1
    log "  retry $i/$n in ${d}s: $*"; sleep "$d"; i=$((i+1)); d=$((d*2)); [ "$d" -gt 900 ] && d=900
  done
}

# ── wall-clock timeout (macOS has no `timeout`) ────────────────────────
run_with_timeout() { # run_with_timeout <secs> <cmd...>
  local secs="$1"; shift
  "$@" & local pid=$!
  ( sleep "$secs"; kill -TERM "$pid" 2>/dev/null; sleep 30; kill -KILL "$pid" 2>/dev/null ) &
  local wd=$!
  wait "$pid"; local rc=$?
  kill "$wd" 2>/dev/null; pkill -P "$wd" 2>/dev/null; wait "$wd" 2>/dev/null
  return "$rc"
}

# ── playbook extraction ────────────────────────────────────────────────
# First fenced block after the first line matching <regex>.
extract_block() {
  awk -v pat="$1" '
    !found && $0 ~ pat { found=1; next }
    found && /^```/ { if (inb) exit; inb=1; next }
    inb { print }
  ' "$PLAYBOOK"
}

# ── pytest: failing node ids, one per line ─────────────────────────────
run_tests() { # run_tests <outfile-of-failures> <logfile>; returns pytest rc
  local out="$1" lg="$2"
  run_with_timeout "$TEST_TIMEOUT_S" \
    env PYTHONPATH=. venv/bin/python -m pytest -m "not live" -q -rfE -p no:cacheprovider > "$lg" 2>&1
  local rc=$?
  grep -E '^(FAILED|ERROR) ' "$lg" | awk '{print $2}' | sort -u > "$out"
  return "$rc"
}

# ── usage-limit reset time → epoch seconds (0 = unknown) ───────────────
parse_reset_epoch() {
  local txt="$1" ep h m ap day now target
  ep="$(printf '%s' "$txt" | grep -oE '\|[0-9]{10}' | head -1 | tr -d '|')"
  [ -n "$ep" ] && { echo "$ep"; return; }
  # "resets 3am", "resets at 3:30 PM", "resets 11pm (Asia/Calcutta)"
  local frag
  frag="$(printf '%s' "$txt" | grep -oiE 'reset[s]?( at)? [0-9]{1,2}(:[0-9]{2})? ?(am|pm)' | head -1)"
  if [ -n "$frag" ]; then
    h="$(printf '%s' "$frag" | grep -oE '[0-9]{1,2}(:[0-9]{2})?' | head -1)"
    m="${h#*:}"; [ "$m" = "$h" ] && m=00; h="${h%%:*}"
    ap="$(printf '%s' "$frag" | grep -oiE '(am|pm)$' | tr 'A-Z' 'a-z')"
    h=$((10#$h)); [ "$ap" = pm ] && [ "$h" -lt 12 ] && h=$((h+12)); [ "$ap" = am ] && [ "$h" -eq 12 ] && h=0
    day="$(date +%Y-%m-%d)"; now="$(date +%s)"
    target="$(date -j -f '%Y-%m-%d %H:%M' "$day $(printf '%02d:%s' "$h" "$m")" +%s 2>/dev/null || echo 0)"
    [ "$target" -gt 0 ] && [ "$target" -le "$now" ] && target=$((target+86400))
    echo "$target"; return
  fi
  echo 0
}

is_limit_text()    { printf '%s' "$1" | grep -qiE 'usage limit|limit reached|hit your (usage |session |weekly )?limit|out of (extra )?usage|rate[ _-]?limit|429|resets? (at )?[0-9]'; }
is_transient_text(){ printf '%s' "$1" | grep -qiE 'overloaded|529|50[0234]|api error|internal server error|ECONNRESET|ETIMEDOUT|ENOTFOUND|EAI_AGAIN|socket hang up|fetch failed|network|connection (refused|reset|error)|timed out'; }
is_unknown_cmd()   { printf '%s' "$1" | grep -qiE 'unknown (slash )?command|unknown skill|command not found: ?/'; }

cheap_probe_ok() { # is the account usable again?
  local o
  o="$(cd "$WORK" && run_with_timeout 300 env GH_TOKEN=x claude -p "Reply with the single word OK." \
        --output-format json --no-session-persistence </dev/null 2>&1)"
  printf '%s' "$o" | jq -e '.is_error == false' >/dev/null 2>&1
}

wait_for_limit_reset() { # wait_for_limit_reset <text>
  local ep now waited=0 s
  ep="$(parse_reset_epoch "$1")"; now="$(date +%s)"
  if [ "$ep" -gt "$now" ]; then
    s=$((ep - now + 180))
    log "  usage limit: sleeping until $(date -r "$ep" '+%H:%M') (+3m buffer), ${s}s"
    notify "Usage limit hit — sleeping until $(date -r "$ep" '+%H:%M')"
    sleep "$s"; waited=$s
  else
    log "  usage limit: reset time not parseable, polling every 20m"
  fi
  until cheap_probe_ok; do
    [ "$waited" -ge "$MAX_LIMIT_WAIT_S" ] && return 1
    log "  still limited; next check in 20m (waited ${waited}s)"
    sleep 1200; waited=$((waited+1200))
  done
  log "  limit cleared"
  return 0
}

# ── one claude session, driven to completion through interruptions ─────
# claude_session <label> <prompt-file> <sid-file> <out-json> <extra-disallowed...>
# Resumes the session in <sid-file> if it exists. Leaves the final JSON in <out-json>.
# Returns 0 when the session finished normally, 1 when it could not be completed.
SESSION_COST=0
claude_session() {
  local label="$1" pfile="$2" sidf="$3" out="$4"; shift 4
  local extra_deny=("$@")
  local deny=(
    "Bash(git push:*)" "Bash(git push)" "Bash(git remote:*)" "Bash(git config:*)"
    "Bash(gh:*)" "Bash(docker:*)" "Bash(docker-compose:*)" "Bash(psql:*)" "Bash(pg_dump:*)"
    "Bash(pg_restore:*)" "Bash(ssh:*)" "Bash(scp:*)"
  )
  local model_args=(); [ -n "$MODEL" ] && model_args=(--model "$MODEL")
  local resumes=0 backoff=60 sid prompt rc text subtype iserr cost
  SESSION_COST=0

  while :; do
    local raw="$out.raw"
    if [ -s "$sidf" ]; then
      sid="$(cat "$sidf")"
      if [ "$resumes" -eq 0 ] && [ ! -f "$sidf.fresh" ]; then
        prompt="The previous run of this session was interrupted (the runner restarted). Continue the task exactly where you left off: check \`git status\` and \`git log\` first to see what is already done. All rules from the original prompt still apply, including the final RESULT/VERDICT line."
      else
        prompt="${RESUME_MSG:-You were interrupted. Continue exactly where you left off: check \`git status\` and \`git log\` first to see what is already done. All rules from the original prompt still apply, including the final RESULT/VERDICT line.}"
      fi
      rm -f "$sidf.fresh"
      log "  [$label] resuming session $sid"
      push_guard_on
      run_with_timeout "$SESSION_TIMEOUT_S" env GH_TOKEN="disabled-for-agent" GITHUB_TOKEN="disabled-for-agent" \
          claude -p "$prompt" --resume "$sid" \
          --output-format json --permission-mode bypassPermissions \
          --max-budget-usd "$SESSION_BUDGET_USD" "${model_args[@]}" \
          --disallowedTools "${deny[@]}" "${extra_deny[@]}" </dev/null > "$raw" 2>>"$out.stderr"
      rc=$?
      push_guard_off
    else
      sid="$(uuidgen | tr 'A-Z' 'a-z')"; echo "$sid" > "$sidf"
      log "  [$label] new session $sid"
      push_guard_on
      run_with_timeout "$SESSION_TIMEOUT_S" env GH_TOKEN="disabled-for-agent" GITHUB_TOKEN="disabled-for-agent" \
          claude -p "$(cat "$pfile")" --session-id "$sid" \
          --output-format json --permission-mode bypassPermissions \
          --max-budget-usd "$SESSION_BUDGET_USD" "${model_args[@]}" \
          --disallowedTools "${deny[@]}" "${extra_deny[@]}" </dev/null > "$raw" 2>>"$out.stderr"
      rc=$?
      push_guard_off
    fi

    # Parse. A crash may leave non-JSON (or nothing) on stdout.
    if jq -e . "$raw" >/dev/null 2>&1; then
      text="$(jq -r '.result // ""' "$raw")"
      subtype="$(jq -r '.subtype // ""' "$raw")"
      iserr="$(jq -r '.is_error // false' "$raw")"
      cost="$(jq -r '.total_cost_usd // 0' "$raw")"
      local newsid; newsid="$(jq -r '.session_id // ""' "$raw")"
      [ -n "$newsid" ] && echo "$newsid" > "$sidf"
    else
      text="$(cat "$raw" 2>/dev/null; tail -c 4000 "$out.stderr" 2>/dev/null)"
      subtype="crash"; iserr=true; cost=0
    fi
    SESSION_COST="$(echo "$SESSION_COST + $cost" | bc)"
    cp "$raw" "$out" 2>/dev/null

    # Normal completion.
    if [ "$rc" -eq 0 ] && [ "$iserr" = false ] && [ "$subtype" = success ] && ! { [ "${#text}" -lt 600 ] && is_limit_text "$text"; }; then
      log "  [$label] finished (cost \$$cost)"
      return 0
    fi

    resumes=$((resumes+1))
    if [ "$resumes" -gt "$MAX_RESUMES" ]; then
      log "  [$label] gave up after $MAX_RESUMES interruptions (last: rc=$rc subtype=$subtype)"
      return 1
    fi
    local diag="$text $(tail -c 2000 "$out.stderr" 2>/dev/null)"

    if [ "$rc" -eq 143 ] || [ "$rc" -eq 137 ]; then
      log "  [$label] hit the ${SESSION_TIMEOUT_S}s wall clock; resuming"
    elif is_unknown_cmd "$diag" && [ "$resumes" -eq 1 ]; then
      log "  [$label] slash command not recognised; retrying with the skill's instructions inlined"
      inline_implement_skill "$pfile"; rm -f "$sidf"
    elif is_limit_text "$diag"; then
      wait_for_limit_reset "$diag" || { log "  [$label] limit never cleared"; return 1; }
      resumes=$((resumes-1))        # limits don't count against the resume cap
    elif [ "$subtype" = error_max_budget_usd ]; then
      log "  [$label] hit the per-session budget (\$$SESSION_BUDGET_USD); resuming"
    elif [ "$subtype" = error_max_turns ]; then
      log "  [$label] hit max turns; resuming"
    elif is_transient_text "$diag" || [ "$subtype" = crash ]; then
      log "  [$label] transient error (rc=$rc subtype=$subtype); backoff ${backoff}s"
      sleep "$backoff"; backoff=$((backoff*2)); [ "$backoff" -gt 1800 ] && backoff=1800
      until curl -s -m 20 -o /dev/null https://api.anthropic.com; do log "  network down; waiting 2m"; sleep 120; done
    else
      log "  [$label] unexpected stop (rc=$rc subtype=$subtype is_error=$iserr); resuming"
    fi
    # If the session never got persisted, start it over rather than resuming nothing.
    if [ "$subtype" = crash ] && grep -qiE 'no conversation found|session.*not found' "$out.stderr" 2>/dev/null; then
      rm -f "$sidf"
    fi
  done
}

inline_implement_skill() { # replace the leading slash command with the skill body
  local pfile="$1" skill
  skill="$(ls ~/.claude/plugins/cache/mattpocock/mattpocock-skills/*/skills/engineering/implement/SKILL.md 2>/dev/null | tail -1)"
  [ -n "$skill" ] || return 0
  { echo "Follow this skill (\"implement\") for the task below:"; echo
    awk '/^---$/ && c<2 {c++; next} c>=2' "$skill"
    echo; sed "1s#^$IMPLEMENT_CMD ##" "$pfile"; } > "$pfile.inl" && mv "$pfile.inl" "$pfile"
}

# ── runner-side verification ───────────────────────────────────────────
# verify <ticket> <start-sha> <branch> <reasons-file>; 0 = pass
verify() {
  local t="$1" start="$2" br="$3" rf="$4" ok=0 cur
  : > "$rf"
  cur="$(git rev-parse --abbrev-ref HEAD)"
  if [ "$cur" != "$br" ]; then
    echo "- The session left the repo on branch \`$cur\`, not \`$br\`. Work must be committed on \`$br\`." >> "$rf"
    git switch -q "$br" 2>>"$RUNLOG" || { echo "- could not switch back to $br" >> "$rf"; return 1; }
    ok=1
  fi
  local last; last="$(jq -r '.result // ""' "$STATE/$t.impl.json" 2>/dev/null | grep -E '^RESULT:' | tail -1)"
  case "$last" in
    "RESULT: PASS"*) ;;
    *) echo "- Final message did not end with \`RESULT: PASS\` (got: \`${last:-nothing}\`)." >> "$rf"; ok=1 ;;
  esac
  if [ "$(git rev-list --count "$start..HEAD")" -eq 0 ]; then
    echo "- No commits on \`$br\` since the ticket started." >> "$rf"; ok=1
  fi
  if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
    echo "- Uncommitted changes to tracked files remain:" >> "$rf"
    git status --porcelain --untracked-files=no | sed 's/^/    /' >> "$rf"; ok=1
  fi
  local newun; newun="$(git ls-files --others --exclude-standard | sort | comm -13 "$STATE/untracked.before" -)"
  if [ -n "$newun" ]; then
    echo "- New files were created but not committed:" >> "$rf"
    printf '%s\n' "$newun" | sed 's/^/    /' >> "$rf"; ok=1
  fi
  if [ -n "$(git diff --name-only "$start..HEAD" -- tests/conftest.py pytest.ini)" ]; then
    echo "- tests/conftest.py or pytest.ini changed. The offline guard must not be touched." >> "$rf"; ok=1
  fi
  if [ "$ALLOW_MIGRATIONS" != 1 ] && [ -n "$(git diff --name-only --diff-filter=A "$start..HEAD" -- supabase/migrations)" ]; then
    echo "- A migration was added (ALLOW_MIGRATIONS=0 for this run)." >> "$rf"; ok=1
  fi
  if [ ! -s "$WORK/ticket-$t-report.md" ]; then
    echo "- \`$REL_WORK/ticket-$t-report.md\` is missing." >> "$rf"; ok=1
  fi
  log "  running offline tests"
  run_tests "$STATE/$t.fail.txt" "$LOGS/ticket-$t-tests.log"; local prc=$?
  local newf; newf="$(comm -13 "$BASELINE" "$STATE/$t.fail.txt")"
  if [ -n "$newf" ]; then
    echo "- New test failures vs main's baseline:" >> "$rf"
    printf '%s\n' "$newf" | sed 's/^/    /' >> "$rf"; ok=1
  elif [ "$prc" -ne 0 ] && [ "$prc" -ne 1 ]; then
    echo "- pytest exited $prc (collection error, interrupt or timeout). Tail:" >> "$rf"
    tail -20 "$LOGS/ticket-$t-tests.log" | sed 's/^/    /' >> "$rf"; ok=1
  fi
  tail -1 "$LOGS/ticket-$t-tests.log" > "$STATE/$t.testsummary"
  return "$ok"
}

review() { # review <ticket> <start-sha> <branch> <reasons-file>; 0 = approved
  local t="$1" start="$2" br="$3" rf="$4" task="$5"
  local p="$STATE/$t.review.prompt" sidf="$STATE/$t.review.sid"
  rm -f "$sidf" "$STATE/$t.review.json"
  cat > "$p" <<EOF
You are an independent reviewer with a clean context and no stake in this change.
You are READ-ONLY: do not edit, create, or delete files, and do not run any git
command that changes state.

Ticket: GitHub issue #$t. Its text is at $REL_WORK/issue-$t.md.
Ticket title: $task${SPEC_PATH:+
Spec: $SPEC_PATH (read the part this ticket implements).}
Anything built beyond what the ticket asks for is a defect.
The implementer's instructions: $REL_WORK/ticket-$t.prompt.md
The implementer's report: $REL_WORK/ticket-$t-report.md
The change: \`git log --oneline $start..HEAD\` and \`git diff $start..HEAD\` on branch $br.

Check:
1. Every acceptance criterion in the issue is met, and each has a test where the
   issue asks for one. Read the tests. Don't trust the report.
2. Nothing outside the ticket's scope was built; the change is surgical.
3. Repo rules from CLAUDE.md: STATE.md updated in the same change wherever it
   describes what changed, with cited paths and a bumped Generated/Commit line.
4. Tests pass offline: \`PYTHONPATH=. venv/bin/python -m pytest -m "not live" -q\`
   (failures listed in $REL_WORK/baseline-failures.txt are pre-existing).

Request changes only for real acceptance or spec misses, rule breaks, or bugs.
Not for style. List each finding with file:line and what's wrong.
Your final line must be exactly \`VERDICT: APPROVE\` or \`VERDICT: CHANGES_REQUESTED\`.
EOF
  claude_session "review #$t" "$p" "$sidf" "$STATE/$t.review.json" "Edit" "Write" "NotebookEdit" || {
    echo "- The review session could not complete." > "$rf"; return 1; }
  local body; body="$(jq -r '.result // ""' "$STATE/$t.review.json")"
  printf '%s\n' "$body" > "$WORK/ticket-$t-review.md"
  if printf '%s' "$body" | grep -qE '^VERDICT: APPROVE'; then return 0; fi
  { echo "- The independent reviewer requested changes:"; echo; printf '%s\n' "$body"; } > "$rf"
  return 1
}

# ── reporting ──────────────────────────────────────────────────────────
report_final() {
  local why="${1:-}"
  {
    echo "# Overnight run: $RUN_NAME"
    echo
    echo "Started: ${RUN_STARTED:-?} · Finished: $(date '+%Y-%m-%d %H:%M')${why:+ · **$why**}"
    echo
    echo "| Ticket | Status | Branch | PR | Cost (USD) | Note |"
    echo "|---|---|---|---|---|---|"
    for t in "${TICKETS[@]}"; do
      local s; s="$(status_get "$t")"
      if [ -z "$s" ]; then echo "| #$t | not run | | | | |"
      else awk -F'\t' -v t="$t" '$1==t {printf "| #%s | %s | `%s` | %s | %s | %s |\n",$1,$2,$3,$4,$5,$6}' "$STATUS_TSV"; fi
    done
    echo
    echo "## Per ticket"
    for t in "${TICKETS[@]}"; do
      [ -f "$WORK/ticket-$t-report.md" ] || [ -f "$STATE/$t.lastreasons" ] || continue
      echo; echo "### #$t"
      [ -f "$STATE/$t.testsummary" ] && echo "Runner's test run: \`$(cat "$STATE/$t.testsummary")\`"
      if [ -s "$STATE/$t.lastreasons" ]; then echo; echo "**Last verification failure:**"; cat "$STATE/$t.lastreasons"; fi
      if [ -f "$WORK/ticket-$t-report.md" ]; then echo; echo "<details><summary>Implementer's report</summary>"; echo; cat "$WORK/ticket-$t-report.md"; echo; echo "</details>"; fi
      if [ -f "$WORK/ticket-$t-review.md" ]; then echo; echo "<details><summary>Independent review</summary>"; echo; cat "$WORK/ticket-$t-review.md"; echo; echo "</details>"; fi
    done
    echo
    echo "## Final review"
    if [ -s "$WORK/$PHASE_REVIEW_OUT" ]; then cat "$WORK/$PHASE_REVIEW_OUT"; else echo "_Not produced._"; fi
    echo
    echo "## Waiting for you"
    echo "- Merge the stacked PRs **in order** (#${TICKETS[0]}'s first). Each PR targets \`$PR_BASE\` and includes the earlier tickets' commits until those are merged."
    echo "- Anything a ticket report lists as waiting for a human (see \"Per ticket\" above)."
    echo
    echo "Logs: \`$REL_WORK/logs/\` · runner log: \`$REL_WORK/logs/runner.log\`"
  } > "$REPORT"
}

# ══ main ═══════════════════════════════════════════════════════════════
RUN_STARTED="$(date '+%Y-%m-%d %H:%M')"
log "=== overnight run $RUN_NAME (pid $$, dry_run=$DRY_RUN) ==="

# Keep runner files out of every commit without touching .gitignore.
grep -qxF '.scratch/' .git/info/exclude 2>/dev/null || echo '.scratch/' >> .git/info/exclude

# Preflight.
for c in claude gh jq git uuidgen bc curl; do command -v "$c" >/dev/null || die "missing command: $c"; done
[ -x venv/bin/python ] || die "venv/bin/python not found"
[ -f "$PLAYBOOK_SRC" ] || die "playbook not found: $PLAYBOOK_SRC"
gh auth status >/dev/null 2>&1 || die "gh is not authenticated"
if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  die "tracked files have uncommitted changes. Commit or stash your in-flight work first: $(git status --porcelain --untracked-files=no | tr '\n' ' ')"
fi
[ -d .git/rebase-merge ] || [ -d .git/rebase-apply ] || [ -f .git/MERGE_HEAD ] && die "a merge/rebase is in progress"

# Untracked files that already exist (your spec, diagram, this script) aren't the model's.
[ -f "$STATE/untracked.before" ] || git ls-files --others --exclude-standard | sort > "$STATE/untracked.before"

# Snapshot the playbook so a branch switch or model edit can't change it mid-run.
sed "s#{{WORK}}#$REL_WORK#g" "$PLAYBOOK_SRC" > "$PLAYBOOK"
SPEC_PATH="${SPEC_PATH:-$(grep -m1 -E '^Source spec:' "$PLAYBOOK" | grep -oE '`[^`]+`' | head -1 | tr -d '`')}"
[ -z "$SPEC_PATH" ] || [ -f "$SPEC_PATH" ] || die "spec named in the playbook not found: $SPEC_PATH"
PREAMBLE="$(extract_block '^## .*[Ss]hared preamble')"
[ -n "$PREAMBLE" ] || die "couldn't find a '## ... Shared preamble' block in the playbook"
TICKETS=(); SLUGS=(); TASKS=()
while IFS= read -r h; do
  TICKETS+=("$(printf '%s' "$h" | sed -E 's/^### #([0-9]+):.*/\1/')")
  title="$(printf '%s' "$h" | sed -E 's/^### #[0-9]+:[[:space:]]*//')"
  TASKS+=("$title")
  SLUGS+=("$(printf '%s' "$title" | tr 'A-Z' 'a-z' | sed -E 's/[^a-z0-9]+/-/g; s/^-+//; s/-+$//' | cut -c1-40 | sed -E 's/-+$//')")
done < <(grep -E '^### #[0-9]+:' "$PLAYBOOK")
[ "${#TICKETS[@]}" -gt 0 ] || die "no '### #<n>: <title>' ticket headings in the playbook"
for i in "${!TICKETS[@]}"; do
  t="${TICKETS[$i]}"
  blk="$(extract_block "^### #$t:")"
  [ -n "$blk" ] || die "couldn't extract the block for #$t"
  first="$(printf '%s\n' "$blk" | head -1)"
  case "$first" in /implement*) ;; *) die "block for #$t doesn't start with /implement";; esac
  echo "${TASKS[$i]}" > "$STATE/$t.task"
  {
    printf '%s GitHub issue #%s. Instructions follow.\n\n' "$IMPLEMENT_CMD" "$t"
    printf '%s\n\n' "$PREAMBLE"
    printf '%s\n' "Runner notes for this session (these override the preamble where they differ):"
    printf '%s\n' "- \`gh\` and \`git push\` are disabled in this session. The issue text is already at"
    printf '%s\n' "  $REL_WORK/issue-$t.md; read it there instead of \`gh issue view\`."
    printf '%s\n' "- The offline-test baseline is $REL_WORK/baseline-failures.txt."
    printf '%s\n' "- Write your report to $REL_WORK/ticket-$t-report.md."
    [ -n "$SPEC_PATH" ] && printf '%s\n' "- When the code-review skill needs the spec, use the issue file above plus $SPEC_PATH."
    echo; echo "## This ticket"; echo
    printf '%s\n' "$blk" | sed '1s#^/implement ##'
  } > "$WORK/ticket-$t.prompt.md"
done
log "extracted prompts for: ${TICKETS[*]}"

if [ "$DRY_RUN" = 1 ]; then
  for t in "${TICKETS[@]}"; do
    echo "────────── #$t ($(cat "$STATE/$t.task")) → $REL_WORK/ticket-$t.prompt.md"
    head -3 "$WORK/ticket-$t.prompt.md"; echo "  … ($(wc -l < "$WORK/ticket-$t.prompt.md") lines)"
  done
  echo; echo "limit parser self-test:"
  for s in "Claude AI usage limit reached|1790000000" "5-hour limit reached ∙ resets 3am" "You've hit your limit · resets 11:30pm (Asia/Calcutta)"; do
    e="$(parse_reset_epoch "$s")"; printf '  %-58s → %s\n' "$s" "$( [ "$e" -gt 0 ] && date -r "$e" '+%Y-%m-%d %H:%M' || echo unknown)"
  done
  echo; echo "Dry run OK. Nothing was changed."; exit 0
fi

# Fetch issue texts (the model can't use gh).
for t in "${TICKETS[@]}"; do
  retry 5 gh issue view "$t" --json number,title,body,state --jq '"# #\(.number // "") \(.title)\n\nstate: \(.state)\n\n\(.body)"' \
    > "$WORK/issue-$t.md" || die "could not fetch issue #$t"
done

# Baseline failures on the PR base.
# The baseline is per ticket set: each set starts from whatever main is then.
if [ ! -s "$BASELINE.done" ]; then
  log "recording test baseline on $PR_BASE"
  git switch -q "$PR_BASE" || die "cannot switch to $PR_BASE"
  retry 5 git pull -q --ff-only origin "$PR_BASE" || log "  (pull failed; using local $PR_BASE)"
  run_tests "$BASELINE" "$LOGS/baseline-tests.log"; rc=$?
  [ "$rc" -le 1 ] || die "baseline test run failed to execute (rc=$rc); see logs/baseline-tests.log"
  tail -1 "$LOGS/baseline-tests.log" > "$BASELINE.done"
  log "  baseline: $(cat "$BASELINE.done") ($(wc -l < "$BASELINE" | tr -d ' ') failing ids)"
fi

prev_branch="$PR_BASE"; prev_pr=""
for i in "${!TICKETS[@]}"; do
  t="${TICKETS[$i]}"; br="$BRANCH_PREFIX/$(printf '%02d' "$t")-${SLUGS[$i]}"; task="$(cat "$STATE/$t.task")"
  if [ "$(status_get "$t")" = DONE ]; then
    log "#$t already DONE; skipping"; prev_branch="$br"; prev_pr="$(field_get "$t" 4)"; continue
  fi
  if [ -n "${ONLY:-}" ] && ! printf ' %s ' "$ONLY" | grep -q " $t "; then
    log "#$t not in ONLY; stopping here (later tickets stack on it)"; break
  fi
  log "=== #$t ($task) on $br (base: $prev_branch) ==="
  notify "Starting #$t"

  if git show-ref -q --verify "refs/heads/$br"; then
    git switch -q "$br" || die "cannot switch to $br"
    start="$(cat "$STATE/$t.start" 2>/dev/null || git merge-base "$prev_branch" "$br")"
    log "  continuing existing branch (start $start)"
  else
    git switch -q "$prev_branch" && git switch -q -c "$br" || die "cannot create $br"
    start="$(git rev-parse HEAD)"; echo "$start" > "$STATE/$t.start"
    rm -f "$STATE/$t.impl.sid"
  fi
  status_set "$t" RUNNING "$br" "" "" "attempt 1"

  ticket_cost=0; passed=0; attempt=1
  while [ "$attempt" -le "$MAX_ATTEMPTS" ]; do
    if [ "$attempt" -gt 1 ]; then
      RESUME_MSG="The runner's checks after your last pass FAILED. Fix every point below, re-run the offline tests and the code-review step, commit on this branch, rewrite $REL_WORK/ticket-$t-report.md, and end with the RESULT line.

$(cat "$STATE/$t.lastreasons")"
      export RESUME_MSG
    else
      unset RESUME_MSG
    fi
    [ -s "$STATE/$t.impl.sid" ] && [ "$attempt" -gt 1 ] && touch "$STATE/$t.impl.sid.fresh"
    log "  implement pass $attempt/$MAX_ATTEMPTS"
    claude_session "impl #$t" "$WORK/ticket-$t.prompt.md" "$STATE/$t.impl.sid" "$STATE/$t.impl.json"
    ok=$?; ticket_cost="$(echo "$ticket_cost + $SESSION_COST" | bc)"
    unset RESUME_MSG
    if [ "$ok" -ne 0 ]; then
      echo "- The implementer session could not be completed (see logs)." > "$STATE/$t.lastreasons"
    elif verify "$t" "$start" "$br" "$STATE/$t.lastreasons"; then
      log "  verification passed; independent review"
      if review "$t" "$start" "$br" "$STATE/$t.lastreasons" "$task"; then
        ticket_cost="$(echo "$ticket_cost + $SESSION_COST" | bc)"; passed=1; break
      fi
      ticket_cost="$(echo "$ticket_cost + $SESSION_COST" | bc)"
      log "  reviewer requested changes"
    else
      log "  verification failed:"; sed 's/^/      /' "$STATE/$t.lastreasons" | tee -a "$RUNLOG" >&2
    fi
    if [ "$(echo "$ticket_cost > $TICKET_BUDGET_USD" | bc)" -eq 1 ]; then
      log "  ticket budget \$$TICKET_BUDGET_USD exceeded"; echo "- Ticket budget exceeded." >> "$STATE/$t.lastreasons"; break
    fi
    attempt=$((attempt+1))
    status_set "$t" RUNNING "$br" "" "$ticket_cost" "attempt $attempt"
  done

  # Publish (runner-side; the model never touches the remote).
  body="$STATE/$t.prbody.md"
  {
    [ -f "$WORK/ticket-$t-report.md" ] && cat "$WORK/ticket-$t-report.md" || echo "_No implementer report._"
    echo; echo "---"; echo
    echo "**Ticket:** #$t · $task${SPEC_PATH:+ · **Spec:** \`$SPEC_PATH\`}"
    [ -n "$prev_pr" ] && echo "**Stacked on:** $prev_pr. Merge that first; until then this diff includes its commits."
    echo "**Runner tests:** \`$(cat "$STATE/$t.testsummary" 2>/dev/null)\` (baseline on $PR_BASE: \`$(cat "$BASELINE.done")\`)"
    if [ "$passed" = 1 ]; then echo "**Independent review:** approved."
    else echo; echo "**Not passing: needs a human.** Last verification failure:"; echo; cat "$STATE/$t.lastreasons"; fi
    [ -f "$WORK/ticket-$t-review.md" ] && { echo; echo "<details><summary>Independent review</summary>"; echo; cat "$WORK/ticket-$t-review.md"; echo; echo "</details>"; }
    echo; [ "$passed" = 1 ] && echo "Closes #$t"
    echo; echo "🤖 Generated with [Claude Code](https://claude.com/claude-code)"
  } > "$body"

  pr=""
  if [ "$(git rev-list --count "$start..HEAD")" -gt 0 ]; then
    if retry 6 git push -q -u origin "$br"; then
      title="$(head -1 "$WORK/issue-$t.md" | sed 's/^# #[0-9]* //')"
      pr="$(gh pr view "$br" --json url --jq .url 2>/dev/null || true)"
      if [ -n "$pr" ]; then
        retry 4 gh pr edit "$br" --body-file "$body" >/dev/null || true
      else
        draft=(); [ "$passed" = 1 ] || draft=(--draft)
        pr="$(retry 4 gh pr create --base "$PR_BASE" --head "$br" --title "$title" --body-file "$body" "${draft[@]}" | tail -1)"
      fi
      [ "$passed" = 1 ] || { gh pr ready "$br" --undo >/dev/null 2>&1 || true; }
    else
      log "  push failed after retries; branch kept locally"
    fi
  fi

  if [ "$passed" = 1 ]; then
    if [ -n "$pr" ]; then
      retry 4 gh issue close "$t" --comment "Implemented in $pr (runner verified tests + independent review). Merge the $RUN_NAME PRs in order." >/dev/null \
        || log "  couldn't close #$t"
      status_set "$t" DONE "$br" "$pr" "$ticket_cost" "verified + approved"
    else
      status_set "$t" DONE "$br" "(not pushed)" "$ticket_cost" "verified + approved; push/PR failed. Push manually"
    fi
    log "#$t DONE ${pr:+→ $pr}"; notify "#$t done"
    prev_branch="$br"; prev_pr="$pr"
  else
    status_set "$t" FAILED "$br" "${pr:-}" "$ticket_cost" "$(head -1 "$STATE/$t.lastreasons" | cut -c1-120)"
    log "#$t FAILED"; notify "#$t failed"
    if [ "$STOP_ON_FAIL" = 1 ]; then log "stopping the chain (STOP_ON_FAIL=1)"; break; fi
    prev_branch="$br"; prev_pr="$pr"
  fi
  report_final   # keep the morning report current after every ticket
done

# Final review (read-only), if the playbook has one.
if [ -n "$(extract_block '^## .*[Mm]orning report')" ]; then
  log "=== final review ==="
  last_branch="$(git rev-parse --abbrev-ref HEAD)"
  {
    extract_block '^## .*[Mm]orning report'
    echo
    echo "Runner notes: gh is disabled; issue texts are at $REL_WORK/issue-<n>.md; per-ticket status is in $REL_WORK/runner-status.tsv. The last branch is \`$last_branch\`."
    echo "Branches are stacked, so \`git diff $PR_BASE..$last_branch\` is the whole chain. Write your review to $REL_WORK/$PHASE_REVIEW_OUT and edit nothing else."
  } > "$STATE/phase.prompt"
  rm -f "$STATE/phase.sid"
  claude_session "final review" "$STATE/phase.prompt" "$STATE/phase.sid" "$STATE/phase.json" "Edit" "NotebookEdit" \
    || log "final review session failed"
  [ -s "$WORK/$PHASE_REVIEW_OUT" ] || jq -r '.result // ""' "$STATE/phase.json" > "$WORK/$PHASE_REVIEW_OUT" 2>/dev/null
fi

report_final
done_n=0; for t in "${TICKETS[@]}"; do [ "$(status_get "$t")" = DONE ] && done_n=$((done_n+1)); done
log "=== finished: $done_n/${#TICKETS[@]} DONE. Report: $REPORT ==="
notify "Finished: $done_n/${#TICKETS[@]} tickets done"
