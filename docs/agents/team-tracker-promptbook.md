# Team tracker promptbook

One prompt per agent ticket of the team upload tracker (spec #142, tickets #143–#153).
`scripts/run_team_tracker.sh` reads the prompts out of this file: each one sits between
`<!-- prompt:NN -->` and `<!-- /prompt -->`, and the shared preamble (`prompt:common`) is
put in front of every ticket's prompt. Edit the prompts here, not in the script.

| NN | Issue | Ticket | Blocked by | Who |
|---|---|---|---|---|
| 01 | #143 | Run the upload-timestamp probe | — | **human** |
| 02 | #144 | Logins, sessions, login page, global gate | — | agent |
| 03 | #145 | Access module, channel-path routes, coverage guard | #144 | agent |
| 04 | #146 | Object-id routes scoped | #145 | agent |
| 05 | #147 | List/global + admin-only routes, guard pending list emptied | #146 | agent |
| 07 | #148 | Team page and roster | #145 | agent |
| 08 | #149 | Channel assignments | #148 | agent |
| 06 | #150 | Upload capture in sync | #143 | agent |
| 09 | #151 | Uploads grid | #147, #150, #149 | agent |
| 10 | #152 | Uploads drill-down | #151 | agent |
| 11 | #153 | Office rollout | all | **human** |

**Run order** (the script's order): 02 → 03 → 04 → 05 → 07 → 08 → 06 → 09 → 10. Upload
capture (06) comes after 07/08 to give the probe (01, human) time to land. The script
refuses to start 06 until #143 is closed.

**Branches.** These are stacked: each ticket branches off the previous ticket's branch
(`team-tracker/NN-slug`) and opens its own PR against that branch. Merge them in order.
Before merging a parent PR with `--delete-branch`, retarget its child PR to `main`,
otherwise GitHub closes the child.

---

<!-- prompt:common -->
You are implementing one ticket of the Midas team upload tracker, unattended. Nobody will
answer questions; make the sensible call, and record any judgment call in the PR body.

Context to read first, in this order:
1. The ticket issue (number below): `gh issue view <n> --comments`.
2. The parent spec: `gh issue view 142`. Its decisions are locked.
3. `docs/TEAM_UPLOAD_TRACKING.md` (the design) and `CLAUDE.md` (the repo rules).
4. The STATE.md sections relevant to what you're touching (routes §5, schema §2).

How to work:
- Test-first, at the two agreed seams only: (a) the HTTP app via FastAPI `TestClient`
  with `tests/fakes.py` `FakeSupabase` (prior art: `tests/test_list_videos_shorts.py`,
  `tests/test_audits_agent_guard.py`); (b) `sync_channel` with a stubbed YouTube client
  (prior art: `tests/test_sync.py`). Test behaviour (status codes, bodies, rows written),
  not call sequences. Do not add new seams or mocks of internal functions.
- Persisted status strings go in `app/status_vocab.py` with its mirror test.
- Postgres is reached only through PostgREST; new SQL goes in a new timestamped file under
  `supabase/migrations/`. Responses cap at 1000 rows; read lists with the helpers in
  `app/rows.py`.
- Keep the existing Midas flow working: scheduled jobs, autopilot and levers are not
  changed by this work.
- Update `STATE.md` in the same commit for anything it describes (tables, routes,
  modules, pages, config), following its own rules, and bump its Generated line.
- Never touch a production database, the office machine, `.env`, or the NAS. Don't run
  migrations against any live DB, don't run `@pytest.mark.live` tests, and don't call
  YouTube.

Definition of done:
- `venv/bin/python -m pytest -q -m "not live"` passes in full (it is fully green on main,
  2,944 tests on 2026-11-18). The runner script re-runs it and stops on any failure.
- The work is committed on the current branch (already created for you) in small
  commits. Every commit message ends with:
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`
- Push the branch and open a PR with `gh pr create --base <base branch given below>`, titled
  like the issue, the body starting `Closes #<n>` and listing the acceptance criteria as
  ticked checkboxes, plus any judgment calls. End the PR body with:
  `🤖 Generated with [Claude Code](https://claude.com/claude-code)`
- Print `TICKET DONE` as the last line of your final message. If you could not finish,
  print `TICKET BLOCKED: <reason>` instead and don't open a PR.
<!-- /prompt -->

<!-- prompt:02 -->
Ticket #144: logins, sessions, login page, global gate.

Build the auth layer exactly as the issue says: `app_users`/`app_sessions` migration,
argon2 hashing (pin `argon2-cffi` exactly in requirements.txt and check that it installs
in `venv`), `/session/login|logout|me`, a `/login` page on the shared `theme.css`, one
global gate (middleware) with an explicit public allowlist (`/login`, `/session/login`,
login-page static assets, `/health`), HTML routes redirecting to `/login`, the Origin check
on non-GET requests, a 401 → `/login` redirect in the shared frontend fetch helper, a sidebar user pill +
logout, and a CLI script for create user / reset password / deactivate (password from a
prompt via getpass, never an argument).

The gate will break existing route tests: add one shared authenticated-client fixture in
`tests/conftest.py` (a logged-in admin through FakeSupabase rows) and move the existing
route tests onto it. Don't weaken the gate to make them pass. Sessions: store only the
sha256 of the token; a deactivated user's session fails on the next request; expired
sessions are rejected and deleted lazily.
<!-- /prompt -->

<!-- prompt:03 -->
Ticket #145: the access module, channel-path routes scoped, the coverage guard.

Create the access module (`current_user`, `visible_channel_ids`, `require_channel` → 404,
`require_role` → 403), add `channels.manager_id`, admin-only `PATCH /channels/{id}/manager`,
and scope `/channels` and `/auth/channels`. Apply `require_channel` to every route whose
path has a channel id. Enumerate them from `app.routes`, not from memory.

Write the route-coverage guard test: walk `app.routes`, and fail on any route with neither
an access dependency nor a public-allowlist entry. Routes left for #146/#147 go on a
commented PENDING list in that test, and the test also fails if a PENDING route turns out
to be scoped (so the list can only shrink). Add the parametrised isolation test (manager A
→ 404 on manager B's channel for every channel-id route; exec allowed).
<!-- /prompt -->

<!-- prompt:04 -->
Ticket #146: object-id routes scoped.

Add one resolver per object type to the access module (video, audit, intervention,
Short-link recommendation, Shorts job, Shorts clip): object id → channel_id → the same
visibility check, 404 when unknown or not visible. Apply them to every route addressed by
those ids (`/videos/{id}…`, `/audits/{id}…` including measurement, `/interventions/{id}/revert`,
`/short-links/{id}/set|dismiss`, `/shorts/jobs/{id}`, `/shorts/clips/{id}/…`,
`POST /videos/{id}/short`). Remove exactly those routes from the guard's PENDING list. Add
the parametrised cross-team 404 test per object type.
<!-- /prompt -->

<!-- prompt:05 -->
Ticket #147: list/global routes scoped, admin-only routes, the guard's pending list emptied.

Filter every list/global route by `visible_channel_ids` (`/dashboard` keeps its unfiltered
cache and filters per user on read; don't change `dashboard_summary()` or cache
invalidation). Make OAuth connect/callback, `/quota`, `/quota-cost-preview`, `/health/jobs`,
`/health/channels`, `/measurement/evaluate` and `/jobs` admin-only. Check the Shorts and
autoshorts routes carefully: they create jobs for a channel taken from the request body,
so validate that channel too. Empty and delete the PENDING list; the guard now fails CI on any
unscoped route. Add the list isolation tests (A never sees B's rows; dashboard totals are
A's only).
<!-- /prompt -->

<!-- prompt:07 -->
Ticket #148: the Team page and roster.

Add the `team_members` migration, `GET/POST/PATCH /team/members` (scoped: a manager sees
and edits only their own members, others → 404; admin/exec choose the manager on create),
and a new Team page linked from the sidebar, built on the shared theme and existing
vanilla-JS components, with a Roster tab (list, add, rename, deactivate). Leave room for
an Uploads tab (#151) and the assignments UI (#149), but don't build them.
<!-- /prompt -->

<!-- prompt:08 -->
Ticket #149: channel assignments.

Add `channel_assignments` with the partial unique index (one open row per channel) and a
SQL function that closes the open row and opens the new one in one transaction, called as
an RPC (grant it to service_role like the other functions). Endpoints:
`POST /channels/{id}/assign` (starts_on defaults to today in Asia/Kolkata; never before the
open row's start) and `GET /team/assignments` (scoped). A manager may assign only their own
members to their own channels; deactivating a member (the existing PATCH) ends their open
assignments. In the Roster tab, add a member dropdown per visible channel, the assignment
history, and the admin-only channel → manager control (using `PATCH /channels/{id}/manager`).
Stub the RPC in FakeSupabase for the HTTP tests, and add a migration-text guard on the
function (style of `tests/test_dashboard_summary_baseline_sql.py`).
<!-- /prompt -->

<!-- prompt:06 -->
Ticket #150: upload capture in sync.

First read #143's comments and `docs/TEAM_UPLOAD_TRACKING.md` §3 for the probe's answers,
and use the timestamp they chose as uploaded_at. If they say scheduled videos are NOT in
the uploads playlist, stop: print `TICKET BLOCKED: probe says redesign` and change nothing.

Add `channel_uploads` with its index and the freeze trigger. Change the uploads-playlist
page request to `snippet,contentDetails` (still 1 unit; keep `tests/test_quota_costs.py`
green) and carry the timestamp per video through `sync_channel`. Record every fetched
video BEFORE the opted-out-Shorts skip and the private skip. Write-once in app code: insert
new rows with ignore-duplicates, then update only the mutable fields of existing ones;
uploaded_at is never in an update. Re-check is_short for rows still private or NULL within
the existing per-sync probe cap. A failure writing channel_uploads is logged and never
fails the sync (like `_record_human_edits`). Don't let private or opted-out Shorts into
`videos`. All tests go through the `sync_channel` seam.
<!-- /prompt -->

<!-- prompt:09 -->
Ticket #151: the uploads grid.

Build `GET /team/uploads?from=&to=&manager_id=` in a new module, computed in Python (no SQL
RPC): read channel_uploads for the visible channels in the IST window (via `app/rows.py`,
so paging past 1000 rows works) plus the assignments, credit each upload to the member whose
[starts_on, ends_on) covers its IST upload date, else Unassigned, and return per-member
per-day {total, shorts, long_form} plus each channel's last_synced_at. NULL is_short counts
as long-form. manager_id is honoured only for admin/exec. Default 7 days, range cap
92 days (422 above). The IST helper is this module's own; don't reuse the quota day
(`America/Los_Angeles`). Add the Uploads tab to the Team page: the grid (`total (S / L)`),
a date range, the exec/admin manager filter, and the freshness note. Use the test list in
the issue.
<!-- /prompt -->

<!-- prompt:10 -->
Ticket #152: the uploads drill-down.

Add `GET /team/uploads/videos?member_id=&day=` (member_id omitted = Unassigned) using the
same assignment mapping as the grid (share the code with #151's module; don't duplicate
it), scoped to visible channels. Make a grid cell clickable to open the list: thumbnail,
title, channel, IST upload time, a status pill (scheduled with go-live time / public /
unlisted / private), and "?" for NULL is_short. Test that the drill-down count equals the
grid cell. Finally, mark `docs/TEAM_UPLOAD_TRACKING.md` as built and point it at STATE.md.
<!-- /prompt -->
