# Frontend review — Midas dashboard

Scope: the four hand-rolled pages in `app/static/` — `index.html` (Dashboard),
`channel.html` (Channel detail, 5 tabs), `performance.html` (Performance),
`shorts.html` (Shorts jobs). All CSS/JS is inline; no build step, no framework.

This is a review of **what doesn't make sense as a UI**, not a rewrite. Each
item has what's wrong, why it matters, and how I'd change it. Grouped by
severity. Line references are to the files as they stand today.

---

## Progress checklist
Work in this order. Check the box and append `— done <one-line note>` when a fix
is implemented and verified.

- [x] #1 Reflection panel: replace Tailwind classes with the native design system — done markup + both JS renderers use .card/.pill/.muted; added `.hidden{display:none}` so the classList toggles work; escaped titles/status while rewriting
- [x] #2 `shorts.html`: add viewport meta tag — done added standard viewport meta; the 640px mobile-stack media query now fires
- [x] #3 `shorts.html`: fix the impossible "paste a link above" empty state — done empty state now points to Dashboard → channel → Videos → Make shorts (real, reachable path) instead of a nonexistent input
- [x] #4 Performance: fix orphaned nav / missing active state (see #6 for the structural call) — done added an active "Performance" nav marker (span, channel-scoped) + made nav selectors element-agnostic so it styles; safe regardless of #6's fold decision
- [x] #5 Performance: collapse the two back-links into one breadcrumb — done replaced the two `←` links with `All channels / <channel name> / Performance`; middle crumb is labelled via a non-fatal /auth/channels fetch
- [ ] #6 Resolve tabbed-SPA vs separate-page split for Performance — BLOCKED: needs a product decision. Folding Performance into a 6th channel tab is a ~500-line migration that discards the working performance.html (and the #4/#5 nav marker + breadcrumb just added), changes the URL from `/performance?channel_id=X` to `/channel?id=X#performance`, and roughly doubles channel.html's size/complexity — high breakage risk to auto-apply. The alternative (keep it a separate page, which #4/#5 already made feel integrated) is a legitimate resolution. Deferring to a human call; see the two options presented in the loop summary.
- [x] #7 Channel page: lazy-load per-tab data instead of eager `Promise.all` — done loadChannel() stays eager (header + form defaults); each tab's loaders run once on first activation via ensureTabLoaded(); autopilot 30s poll starts only when that tab is first opened
- [x] #8 Unify status→label vocabulary across all pages (shared map) — done aligned labels in place: index activity feed now says "Bad output" (not "Quarantined"); shorts.html renders friendly Title-case labels (Queued/Downloading/… not raw CREATED). Chose in-place alignment over a global map because some labels are context-specific (channel's "Shorts done" vs shorts page's "Done")
- [x] #9 Dashboard: use real `audited_*` counts instead of the proxy bar — done channel-table Pipeline bar now uses audited_regular+audited_shorts / video_count (all in the /dashboard payload); dropped the applied+pending proxy and its apology comment; added a "N of M audited" tooltip
- [ ] #10 Dashboard: make the "funnel" honest (proportional or drop the metaphor)
- [ ] #11 Replace native `confirm()`/`alert()` with the toast/confirm system
- [ ] #12 One destination for "open uploaded clip" (Studio vs watch)
- [ ] #13 Route both apply-pending paths through one server endpoint
- [ ] #14 Autopilot config placement + shorts controls layout
- [ ] #15 Co-locate playlist-health enable toggle with its card
- [ ] #16 Don't nuke `document.body` on missing id — render error in content area
- [ ] #17 Remove reliance on global `event` in `triggerReflection`
- [ ] #18 Videos table: responsive fallback + clearer `#`/column trimming
- [ ] #19 Unify quota reset copy (countdown vs "midnight Pacific")
- [ ] #20 Factor shared time/number formatting helpers

> **Structural items (#4, #6, #13, #18) change behavior or layout meaningfully.**
> Do the mechanical/local fixes autonomously; for these four, implement the
> recommended approach but flag the decision in the commit/PR body so a human can
> veto. #6 recommendation: fold Performance in as a 6th channel tab.

---

## Blockers — things that are actually broken

### 1. An entire feature is styled for a CSS framework that isn't loaded
`channel.html:281–321` (Self-Improvement / Reflection block) and the JS that
renders into it (`renderShadowComparisons` 1360–1374, `renderReflectionHistory`
1384–1392) are written in **Tailwind utility classes** — `mt-4 p-3 bg-gray-50
rounded border`, `text-indigo-600`, `bg-white text-gray-700`, `grid grid-cols-2`,
etc. No Tailwind (or any external stylesheet) is loaded anywhere — confirmed:
`grep` for `tailwind|cdn|<link|stylesheet` across `app/static/` returns nothing.

**Why it matters:** every one of those classes is a no-op. This whole panel
renders as unstyled stacked `<div>`s — no card, no padding, no grid, no color —
while the rest of the page uses the custom design system (`.card`, `.pill`,
`.kpi`). It's the single most "nonsense-looking" region because it visibly
doesn't match anything else. It also hardcodes light-mode assumptions
(`bg-white`, `text-gray-*`) in a page that otherwise declares
`color-scheme: light dark`.

**Fix:** rewrite the Reflection block using the existing system — `.card`,
`.pill`, `.muted`, `.kpi`, the `toast()` helper — exactly like the other
Settings cards. Delete every Tailwind class. This is the highest-value single
change on the whole frontend.

### 2. `shorts.html` has no viewport meta tag
`shorts.html:3–6` — head is charset + title + style only. The other three pages
have `<meta name="viewport" content="width=device-width, initial-scale=1">`.

**Why it matters:** the page ships a `@media (max-width: 640px)` block that
stacks the jobs table for mobile (100–105), but without the viewport tag mobile
browsers render at a fake ~980px width and the media query never triggers. The
responsive work is dead.

**Fix:** add the viewport meta line. One line.

### 3. Shorts empty-state tells the user to do something that's impossible here
`shorts.html:261` — empty state: *"No jobs yet — paste a YouTube link above to
cut your first short."* But there is no input on this page. The code comment at
177–179 explicitly states the page *intentionally* has no URL/cut form (cuts are
started from the dashboard / autopilot).

**Why it matters:** it's a dead-end instruction — points at UI that doesn't
exist. Same fictional "paste above" copy.

**Fix:** change to what's actually true and actionable, e.g. *"No shorts jobs
yet. Open a channel → Videos and use **Make shorts** on a long-form video, or
enable auto-shorts in Autopilot settings."* with a real link to a channel.

---

## High — confusing information architecture

### 4. Performance page is orphaned from navigation
The top nav on every page has only **Dashboard** and **Shorts**
(`index.html:83–87`, `channel.html:76–80`, `shorts.html:109–113`,
`performance.html:84–88`). Performance is reachable only via a per-channel
"View performance →" button. Worse, on the Performance page itself **neither nav
link is marked active** (`performance.html:85–87` — both plain `.navlink`).

**Why it matters:** the user lands on Performance and the nav gives no signal of
where they are. A whole top-level view is invisible to anyone who doesn't happen
to click the right button.

**Fix:** Performance is inherently per-channel (it requires `channel_id`), so it
shouldn't be a global nav item — instead make it the **6th tab inside
`channel.html`** alongside Overview/Videos/Autopilot/Playlists/Settings. That
removes the orphan page and the paradigm split (see #6). If it must stay a
separate page, at minimum give its nav a proper active state and a clear "you are
in <channel name>" heading.

### 5. Two stacked back-links, both left-arrows, one of them lying about direction
`performance.html:89` — `← All channels · ← Back to channel`. Two `←` in a row;
the second is labeled "Back to channel" but navigates *forward/into* a channel
detail page.

**Fix:** collapse to a single breadcrumb: `All channels / <Channel name> /
Performance`, where each segment is a real link. Drop the double arrows.

### 6. Channel detail is a tabbed SPA, but Performance is a separate page — mixed paradigm
Channel-scoped views are split two ways: Overview/Videos/Autopilot/Playlists/
Settings are **tabs** in `channel.html`; Performance is a **separate page**
(`performance.html`) you bounce out to and back from. Same object (one channel),
two navigation models.

**Fix:** pick one. Folding Performance in as a tab (#4) is the cleaner
resolution.

### 7. The channel page eagerly loads every tab's data on open
`channel.html:1316–1320` — on load it fires `loadConfig, loadVideos,
loadAutopilotLog, loadOverview, loadPlaylistStatus, loadProposals, loadHealth,
loadReflectionData` all at once, though only one tab is visible. Several are
heavy (full video list, playlist embed status, health recommendations, three
reflection endpoints).

**Why it matters:** slow first paint, and it hammers the backend (and YouTube
quota-adjacent endpoints) for tabs the user may never open.

**Fix:** load Overview + channel meta eagerly; lazy-load each other tab's data on
first activation of that tab (`switchTab`), and cache it.

---

## Medium — inconsistency that erodes trust

### 8. The same status word reads differently on different pages
`quarantined` is relabeled **"Bad output"** in `channel.html:366` and
`performance.html:186`, but the dashboard activity feed still calls it
**"Quarantined"** (`index.html:311`). `CREATED` shows as **"Queued"** in
`channel.html:371` but as raw **"CREATED"** on `shorts.html` (the pill just
prints the status string, 154–156).

**Why it matters:** the interface's vocabulary is how users learn their way
around. When one status has three names, they can't tell if it's the same thing.

**Fix:** one shared status→label map (with colors), defined once and reused. The
`STATE_META` object in `channel.html:361` is already the best version — hoist it
into a tiny shared `status.js` and delete the divergent copies in `index.html`
and `shorts.html`.

### 9. The dashboard "Pipeline" column knowingly shows a wrong number
`index.html:281–284` computes each channel's progress bar as
`touched = applied_total + pending_count` over `video_count`, with a comment
admitting: *"we don't have exact per-channel audited count … Use … as a proxy."*
But the exact count **does** exist — `/dashboard` returns `audited_regular` /
`audited_shorts` per channel (`app/dashboard.py:124–136,177`), and the Channel
Overview already uses them (`channel.html:417`).

**Why it matters:** the main table on the landing page displays a
deliberately-approximate progress bar when the real value is already in the same
payload.

**Fix:** use `audited_regular (+ audited_shorts)` / `regular_count (+ shorts)`
for the bar and drop the proxy math and the apologetic comment.

### 10. The "funnel" isn't a funnel
`index.html:233–253` renders five **equal-width** steps — Total, Audited,
Pending apply, Applied, Not yet audited — and calls the container `.funnel`
(`55–60`). It's not a funnel: the widths don't encode magnitude, and the steps
aren't a single sequence (Total = Audited + Not-audited; Pending/Applied are
*subsets* of Audited, shown as peers).

**Why it matters:** the funnel shape promises "each stage is a subset of the one
left of it, sized by count." This one implies a flow that the numbers don't have.

**Fix:** either make it a real proportional funnel (widths ∝ counts, strict
subset ordering: Total → Audited → Applied), or drop the funnel metaphor and
present it as a labeled stat row. Move "Not yet audited" out of the sequence — it's
the complement of Audited, not a later stage.

### 11. Native `confirm()` / `alert()` used alongside the nice toast system
The app has a polished `toast()` system (channel/performance), yet destructive
and routine actions use blocking browser dialogs: `confirm()` in
`channel.html:704, 724, 749, 919, 941, 1053, 1421` and `performance.html:459`;
and `promoteCandidate` even reports success with `alert('Candidate promoted to
live.')` (`channel.html:1424`) while everything else uses a toast.

**Why it matters:** inconsistent voice (alert vs toast for the same kind of
event), unstyleable, and the dialogs are OS-native so they break the visual
language established everywhere else.

**Fix:** for confirmations, a small in-page confirm component (or an "are you
sure?" inline state on the button). For success/failure, always `toast()`. At
minimum, replace the lone `alert()` with a toast for consistency.

### 12. Two different destinations for "the uploaded clip"
An uploaded short's link points to **YouTube Studio edit**
(`shorts.html:227` → `studio.youtube.com/video/{id}/edit`) but to the **public
watch page** in the channel view (`channel.html:1004` →
`youtube.com/watch?v={id}`).

**Fix:** decide which one "open" means for an uploaded clip (Studio is more
useful since clips upload as private) and use it in both places.

### 13. Bulk-apply reimplements a server endpoint in the browser
"Apply all pending" calls one endpoint, `/audits/apply-pending`
(`channel.html:1058`). But "Apply selected pending" instead loops in JS —
fetching each video's audits to find an id, then POSTing `/audits/{id}/apply`
one by one, hand-rolling quota-429 handling (`channel.html:740–772`).

**Why it matters:** two code paths for the same operation, and the client-side
one is fragile (N+1 fetches, partial-failure states, no atomicity) and can drift
from server behavior.

**Fix:** extend the server endpoint to accept an explicit id list and route both
buttons through it.

---

## Low — polish and consistency

### 14. Autopilot config is a tab; other settings are a Settings tab — arbitrary split
Enable-autopilot + daily-cap (`channel.html:159–186`) are settings, but they live
in their own **Autopilot** tab while language / sync / prompts / playlist-health
live in **Settings**. And the shorts-autopilot row crams five controls (enabled,
videos/day, upload-top, mode, camera) onto one flex line (166–186) that wraps
untidily. Consider merging autopilot config into Settings (keeping the Autopilot
tab for *activity/status* only), and laying the shorts controls out as a small
labeled grid rather than one wrapping row.

### 15. Playlist-health appears in two places
There's a health **toggle** under Settings (`channel.html:263–271`) and a health
**card with Run/Refresh** under the Playlists tab (`209–218`). Reasonable, but
the relationship isn't signposted — enabling in Settings then having to switch
tabs to act is a hidden dependency (the empty-state text at 1227–1229 does point
back, which helps). Consider co-locating the enable toggle at the top of the
Playlists health card.

### 16. Whole-page nuke on a missing id
`performance.html:165` and `channel.html:329` do
`document.body.innerHTML = '<p>Missing …</p>'`, destroying the nav and all
chrome. Render the error inside the content area and keep the nav so the user can
navigate out.

### 17. `event.target` global relied on in an inline handler
`triggerReflection` (`channel.html:1404–1406`) reads the deprecated global
`event` (`const btn = event.target`) rather than a passed argument. Pass the
element in, or wire it with `addEventListener` like the rest of the page (this
section is the only place using inline `onclick="fn()"` + global `event`).

### 18. The Videos table is 12 columns wide with no responsive fallback
`channel.html:620–634` — Select, Thumb, Title, State, Issues, #, Views, v/day,
Published, Last audit, Shorts, Actions. The `#` header (audit_count, 627) is
cryptic. Unlike `shorts.html`, there's no mobile stacking, so it overflows
horizontally on narrow screens. Consider a "details" disclosure per row on small
screens, a clearer header for `#` (e.g. "Audits"), and demoting rarely-scanned
columns (v/day, Last audit) behind a toggle.

### 19. Reset-time copy is inconsistent
Some places show a live countdown ("resets in `Xh Ym`",
`index.html:205,341`) while others hardcode *"retry after midnight Pacific"*
(`channel.html:765`, `performance.html:481`). Pick one phrasing; if the countdown
is available, prefer it everywhere.

### 20. Time-formatting and number-formatting are re-implemented per page
`timeAgo` / `freshnessText` (index), inline `.slice(0,16).replace('T',' ')`
(channel/performance), and mixed use of `fmt()` vs raw numbers (e.g.
`index.html:267` prints `applied_7d_total` without `fmt()` while neighbors use
it). Factor a tiny shared `format.js` (relative time, date, number) and use it
consistently.

---

## Suggested order of work
1. #1 Reflection panel restyle (most visibly broken).
2. #2 shorts viewport, #3 shorts empty state (one-liners, real bugs).
3. #4/#6 fold Performance into channel tabs (fixes the biggest IA problem).
4. #8/#20 shared status + format helpers (kills a class of inconsistency).
5. #9/#10 dashboard accuracy + honest funnel.
6. The rest as polish.
