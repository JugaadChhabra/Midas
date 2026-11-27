#!/usr/bin/env bash
# Run the SEO Results tickets (#168-#175, spec #167) one by one with headless Claude Code.
#
# Prompts, models and effort levels live in docs/agents/seo-results-promptbook.md.
# Branches are stacked: each ticket branches off the previous ticket's branch and opens
# its own PR against that branch. Stops at the first ticket that fails its checks.
#
# Usage:
#   scripts/run_seo_results.sh               # run everything not yet done
#   scripts/run_seo_results.sh --from 05     # start at ticket 05 (earlier ones must have PRs)
#   scripts/run_seo_results.sh --only 03     # run a single ticket
#   scripts/run_seo_results.sh --dry-run     # print the plan and the prompts, run nothing
#
# Env:
#   CLAUDE_FLAGS  flags for `claude -p` (default: --permission-mode bypassPermissions).
#                 The run is unattended, so the agent needs Bash/git/gh without prompts.
#                 The prompts forbid touching production; review each PR before merging.
#   MODEL         overrides every ticket's model (else the per-ticket one below).
#   EFFORT        overrides every ticket's effort (else the per-ticket one below).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"
BOOK="docs/agents/seo-results-promptbook.md"
LOG_DIR="logs/seo-results"
CLAUDE_FLAGS="${CLAUDE_FLAGS:---permission-mode bypassPermissions}"
PYTEST=(venv/bin/python -m pytest -q -m "not live" -p no:cacheprovider)

# NN:issue:slug:model:effort, in run order. Model and effort follow each ticket's
# complexity (the promptbook's table says why).
TICKETS=(
  "01:168:prefactor:sonnet:medium"
  "02:169:tracer-backlinks:opus:high"
  "03:170:titles:sonnet:high"
  "04:171:playlist-short-links:sonnet:medium"
  "05:172:early-read:opus:high"
  "06:173:drill-down:sonnet:medium"
  "07:174:timeline:sonnet:medium"
  "08:175:csv-handover:sonnet:low"
)

FROM=""; ONLY=""; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --from) FROM="$2"; shift 2 ;;
    --only) ONLY="$2"; shift 2 ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

die() { echo "ERROR: $*" >&2; exit 1; }

prompt_block() {  # prompt_block NN -> the text between <!-- prompt:NN --> and <!-- /prompt -->
  awk -v id="$1" '
    $0 == "<!-- prompt:" id " -->" { on = 1; next }
    on && $0 == "<!-- /prompt -->" { exit }
    on { print }' "$BOOK"
}

branch_for() { echo "seo-results/$1-$3"; }

pr_for_branch() {  # number of the open-or-merged PR whose head is this branch, or empty
  gh pr list --head "$1" --state all --json number,state \
    --jq '[.[] | select(.state != "CLOSED")][0].number // empty' 2>/dev/null || true
}

[ -f "$BOOK" ] || die "missing $BOOK"
[ -x venv/bin/python ] || die "missing venv/bin/python"
command -v claude >/dev/null || die "claude CLI not on PATH"
command -v gh >/dev/null || die "gh CLI not on PATH"
[ -n "$(prompt_block common)" ] || die "no prompt:common block in $BOOK"
if [ "$DRY" -eq 0 ] && [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  die "working tree has uncommitted changes to tracked files; commit or stash first"
fi
mkdir -p "$LOG_DIR"

base="main"
started=0
[ -z "$FROM" ] && [ -z "$ONLY" ] && started=1

for t in "${TICKETS[@]}"; do
  IFS=: read -r nn issue slug tmodel teffort <<<"$t"
  model="${MODEL:-$tmodel}"; effort="${EFFORT:-$teffort}"
  branch="$(branch_for "$nn" "$issue" "$slug")"

  if [ -n "$ONLY" ] && [ "$nn" != "$ONLY" ]; then
    # Still advance the base so --only stacks on the right parent.
    git show-ref --quiet "refs/heads/$branch" && base="$branch"
    continue
  fi
  if [ "$started" -eq 0 ] && [ -n "$FROM" ]; then
    if [ "$nn" = "$FROM" ]; then started=1; else
      git show-ref --quiet "refs/heads/$branch" && base="$branch"
      continue
    fi
  fi

  state="$(gh issue view "$issue" --json state --jq .state 2>/dev/null || echo UNKNOWN)"
  existing_pr="$(pr_for_branch "$branch")"
  if [ "$state" = "CLOSED" ] || [ -n "$existing_pr" ]; then
    echo "== $nn (#$issue) already done (issue $state, PR ${existing_pr:-none}); skipping"
    git show-ref --quiet "refs/heads/$branch" && base="$branch"
    continue
  fi

  prompt="$(prompt_block common)

---
Your ticket: issue #$issue (ticket $nn). Your branch: $branch (already checked out).
Open the PR with: gh pr create --base $base

$(prompt_block "$nn")"
  [ -n "$(prompt_block "$nn")" ] || die "no prompt:$nn block in $BOOK"

  echo "== $nn (#$issue) on $branch, base $base, model $model, effort $effort"
  if [ "$DRY" -eq 1 ]; then
    printf '%s\n\n' "$prompt" | sed 's/^/   | /'
    base="$branch"
    continue
  fi

  git fetch --quiet origin || true
  if git show-ref --quiet "refs/heads/$branch"; then
    git checkout --quiet "$branch"
  else
    git checkout --quiet -b "$branch" "$base"
  fi
  start_sha="$(git rev-parse HEAD)"

  log="$LOG_DIR/$nn-$slug.log"
  echo "   running claude (log: $log)"
  # shellcheck disable=SC2086
  if ! claude -p "$prompt" $CLAUDE_FLAGS --model "$model" --effort "$effort" >"$log" 2>&1; then
    die "claude exited non-zero on $nn; see $log"
  fi
  last="$(grep -E '^(TICKET DONE|TICKET BLOCKED)' "$log" | tail -1 || true)"
  case "$last" in
    "TICKET DONE"*) ;;
    "TICKET BLOCKED"*) die "$nn reported: $last (see $log)" ;;
    *) die "$nn ended without TICKET DONE; see $log" ;;
  esac

  # Independent checks; the agent's word is not enough.
  [ "$(git rev-parse HEAD)" != "$start_sha" ] || die "$nn made no commits"
  [ -z "$(git status --porcelain --untracked-files=no)" ] || die "$nn left uncommitted changes"
  echo "   running the offline test suite"
  if ! "${PYTEST[@]}" >"$LOG_DIR/$nn-pytest.log" 2>&1; then
    tail -20 "$LOG_DIR/$nn-pytest.log"
    die "tests fail after $nn; see $LOG_DIR/$nn-pytest.log"
  fi
  pr="$(pr_for_branch "$branch")"
  [ -n "$pr" ] || die "$nn has no PR for $branch"
  echo "   done: PR #$pr"
  base="$branch"
done

echo
echo "== All tickets done. Next:"
echo "   - review and merge the stacked PRs in order (retarget each child to main before"
echo "     deleting its parent branch)"
echo "   - at the office: pull the new image and restart; no migration, .env or snapshot needed"
