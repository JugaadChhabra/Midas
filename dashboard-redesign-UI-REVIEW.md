# Dashboard Redesign — UI Review

**Audited:** 2026-05-12
**Baseline:** Abstract 6-pillar standards (no UI-SPEC.md)
**Screenshots:** Not captured (Playwright ran against port 5173 but Flask app did not serve static HTML directly; all findings are code-only)

---

## Pillar Scores

| Pillar | Score | Key Finding |
|--------|-------|-------------|
| 1. Copywriting | 3/4 | Actionable empty/error strings; two bare "Save" buttons with no context label; one `alert()` on revert still in performance.html |
| 2. Visuals | 2/4 | Zero `aria-*` attributes across all three files; no `@media` breakpoints; tables will overflow on mobile; inconsistent max-width values across pages (1100/1180/1280px) |
| 3. Color | 2/4 | All semantic colors are raw hex literals with no CSS custom properties — same value repeated 30+ times across files; dark mode relies solely on `color-scheme: light dark` but hardcoded `#fff1` button background breaks in dark mode |
| 4. Typography | 2/4 | 21 distinct font-size values in use across the three files — spans from .67rem to 1.5rem with no step scale; h3 elements inline-override their own size to `.95rem`, defeating heading semantics |
| 5. Spacing | 3/4 | Mostly rem-based, flex-wrap used throughout; ~25 distinct padding combinations with no reusable tokens; a handful of `width:88` and `min-width:200px` px-value inline styles |
| 6. Experience Design | 2/4 | Loading states present but plain text "Loading…" with no skeleton/spinner; `alert()` used for two feedback cases in performance.html (inconsistent with toast system on channel.html); `confirm()` dialogs are system-native (inconsistent with tool's own toast UX); no global error boundary; `channels` div on index.html gets no retry affordance on fetch failure |

**Overall: 14/24**

---

## Top 3 Priority Fixes

1. **Zero aria attributes across all three pages** — Screen readers cannot interpret the dashboard's dynamic content regions, pill statuses, or icon-free action buttons (e.g., "Open →", "Diff", "Revert →"). Impact: the tool is inaccessible to any assistive-technology user. Fix: add `role="status"` + `aria-live="polite"` to the activity feed and health bar containers; add `aria-label` to every button whose label is a symbol or abbreviated ("Open →", "Diff", "Revert →", "Sync stats now"); add `role="tablist"` / `role="tab"` to channel.html's tab strip (it has the CSS class but not the ARIA role).

2. **`alert()` and `confirm()` system dialogs co-exist with a custom toast system** — In performance.html lines 437–439, `alert()` and `confirm()` are used for revert feedback. Channel.html has a fully functional `toast()` system with ok/warn/err variants. The inconsistency produces jarring native browser dialogs mid-workflow. Impact: breaks interaction consistency and blocks the page thread. Fix: replace all `alert(...)` calls in performance.html with `toast(...)` matching the channel.html pattern; replace `confirm(...)` with an inline confirmation UI or a toast with an undo affordance.

3. **21 distinct font-size values with no scale** — Sizes from `.67rem` to `1.5rem` in 1–3px increments (`.67`, `.68`, `.7`, `.72`, `.74`, `.76`, `.78`, `.8`, `.82`, `.84`, `.85`, `.87`, `.88`, `.9`, `.92`, `.95`) create visual noise and make future changes inconsistent. Impact: information hierarchy is unclear; editors can't maintain consistency. Fix: collapse to a 6-step scale defined in `:root` as CSS custom properties (e.g., `--text-xs: .75rem`, `--text-sm: .825rem`, `--text-base: .92rem`, `--text-md: 1rem`, `--text-lg: 1.3rem`, `--text-xl: 1.5rem`) and replace all inline font-size declarations.

---

## Detailed Findings

### Pillar 1: Copywriting (3/4)

**What passes:** Empty states are specific and instructional rather than generic. Examples:
- index.html:274 — "No channels yet — connect one above." (tells the user exactly what to do)
- index.html:307 — "No recent activity." (plain but appropriate)
- performance.html:229 — "No videos with ≥7 days post-apply data yet." (precise)
- channel.html:415/419 — "No videos yet — run a sync from the Overview tab." / "No videos match the current filters." (both contextual)

Error states surface technical detail directly: "Failed to load. Is Supabase configured?" (index.html:185) — appropriate for a solo-operator tool.

**WARNING — bare "Save" buttons:** channel.html:141, 171 render as unlabeled "Save" with no adjacent context label beyond proximity. On the Autopilot tab the button is `Save` with nothing to signal "Save autopilot settings" vs "Save language". The Save on the language row (line 171) is visually adjacent enough, but the autopilot Save (line 141) is next to multiple fields. Low risk for solo operator but violates specificity best practice.

**WARNING — `alert()` for revert feedback:** performance.html:437 uses `alert(j.status === 'dry_run' ? 'DRY_RUN — payload logged but not pushed.' : 'Reverted.')`. This is the only success toast in the entire codebase that uses the system alert dialog. The message content is good; the mechanism is wrong.

**PASS — CTA labels are generally action-verb + object:** "Apply to YouTube →", "Audit selected", "Apply all pending", "Export CSV", "Sync videos", "Generate prompt", "Save prompt". No generic "Submit" or "Click Here" found.

---

### Pillar 2: Visuals (2/4)

**BLOCKER — Zero ARIA attributes across all three files:** `grep -n "aria-"` returns empty for index.html, performance.html, and channel.html. Dynamic content regions (health bar, activity feed, KPI grid, pipeline funnel) all update via JS with no `aria-live` announcements. The channel.html tab strip uses `.tab` CSS classes but no `role="tablist"` / `role="tab"` / `aria-selected`. The toast system on channel.html has no `role="alert"`.

**WARNING — No `@media` breakpoints:** The only responsive gesture is `flex-wrap` and CSS grid `auto-fit`. The performance.html table has 11 columns; on viewports below ~900px it will overflow horizontally with no scroll affordance. index.html's funnel has 5 columns in a single row. No `@media (max-width: ...)` rule exists in any file. The tool targets solo operators who likely use desktop, but the spec says "work in both light and dark mode" which typically implies mobile consideration too.

**WARNING — Inconsistent page max-widths:** index.html uses `max-width: 1100px`, channel.html uses `1180px`, performance.html uses `1280px`. These three pages share a navigation hierarchy but present different-width layouts, making the experience feel unrelated rather than a coherent app.

**WARNING — h3 elements override their own size:** Multiple h3 elements carry `style="font-size:.95rem"` inline (index.html:95, 125; performance.html:76, 93, 100, 136). Using h3 semantics while forcing the font down to body size undermines heading hierarchy. The sections read as body-level labels, not sub-headings.

**PASS — Visual hierarchy through color coding:** The status color system (green `#2a7` = applied/good, blue `#6af` = pending/info, amber `#d80` = warning, red `#c33` = error/failed) is used consistently across pills, KPI values, and bar fills. The health-pill border colors reinforce the same semantic mapping.

**PASS — Dark mode declared:** All three files declare `color-scheme: light dark` at `:root`. Most colors use alpha-channel hex values (`#8884`, `#8882`) that adapt to the OS color scheme automatically.

---

### Pillar 3: Color (2/4)

**WARNING — No CSS custom properties; same values repeated 30+ times:** The semantic palette (`#2a7`, `#6af`, `#c33`, `#d80`, `#888`) is hardcoded as raw hex in every file independently. `#2a7` appears as the "positive/applied" green across CSS rules, JS template literals (inline `style="color:#2a7"`), and JS data structures (`bg:'#2a7'`). A single brand color change requires global search-and-replace across three files and JavaScript strings. Count of `#2a7` occurrences alone: 18 across the three files.

**WARNING — `#fff1` button background breaks in dark mode:** index.html:15 and performance.html:15 define `button { background: #fff1 }`. The `#fff1` is white at 6% opacity — near-invisible on a white light background but renders as a barely-visible white tint on a dark background. channel.html uses the same pattern but has the explicit dark-mode toast override, suggesting awareness of the issue but no fix for buttons.

**PASS — The 60/30/10 color distribution is reasonable:** Background/surface colors use neutral alpha-channel greys (`#8882`–`#8886`) for the 60% base. The semantic status colors (green, red, amber, blue) are the 30% supporting tier. No single accent color dominates all interactive elements — only the active tab indicator and "after apply" bars use `#6af` / `#2a7` as accents.

**PASS — No arbitrary brand colors or rainbow palette:** The four-value semantic system is disciplined. No gradient fills, no decorative color blocks.

---

### Pillar 4: Typography (2/4)

**WARNING — 21 distinct font-size values:** The audit found these unique values in CSS across the three files:
`.67rem`, `.68rem`, `.7rem`, `.72rem`, `.74rem`, `.76rem`, `.78rem`, `.8rem`, `.82rem`, `.84rem`, `.85rem`, `.87rem`, `.88rem`, `.9rem`, `.92rem`, `.95rem`, `1.25rem`, `1.3rem`, `1.35rem`, `1.4rem`, `1.5rem`

The sub-1rem range alone has 16 distinct sizes. Many differ by only 0.01–0.02rem (e.g., `.84rem` vs `.85rem`, `.87rem` vs `.88rem`) — a difference imperceptible to users but creating maintenance debt. The abstract standard flags more than 4 sizes as a finding; 21 is extreme.

**WARNING — h3 elements with inline font-size override:** At index.html:95 (`<h3 style="margin:0; font-size:.95rem;">`), performance.html:76, 93, 100, 136, and channel.html:76, the h3 heading is styled down to body-text size. The heading tag signals structural importance to assistive tech and search engines but the visual rendering eliminates any size differentiation from paragraph text.

**PASS — Font weights are disciplined:** Only three weights in use — `600`, `700`, `800`. `800` appears only on the new `insight-stat .iv` large metric values (performance.html:41), which is appropriate. `700` is used for KPI values and bold data. `600` for sub-headings and column headers. Consistent and purposeful.

**PASS — Font family is system-ui stack:** All three pages use the same family declaration. No web font loading, no FOUT risk.

---

### Pillar 5: Spacing (3/4)

**WARNING — ~25 distinct padding values with no token system:** The padding audit found values including `.15rem .55rem`, `.45rem .55rem`, `.4rem .55rem`, `.55rem .35rem`, `.55rem 1rem`, `.5rem .35rem`, `.5rem .9rem`, `.5rem .7rem`, `.5rem .8rem`, `.65rem .8rem`, `.65rem .9rem`, `.75rem .9rem`, `.75rem 1rem`, `.7rem .6rem`, `.7rem .85rem`. While all values are rem-based (good), there is no consistent padding scale. Cards in index.html use `1.1rem 1.25rem` while the health bar card overrides to `.75rem 1rem`. Funnel steps use `.7rem .6rem`. No two component types share a consistent padding pattern.

**WARNING — Inline `width:88` and `min-width:200px/220px` px values:** performance.html:378 and channel.html:440 hardcode `width="88"` on thumbnail `img` elements as an HTML attribute (not CSS), which bypasses `box-sizing` and can cause layout shifts. channel.html:102, 156 and performance.html:125 use `min-width:200px` / `min-width:220px` inline styles — not harmful, but not part of a declared spacing system.

**PASS — All layout spacing uses rem:** No `margin: 10px` or `padding: 8px` absolute values in the main component CSS. Flex-wrap and `auto-fit` grids handle reflow gracefully.

**PASS — Consistent card shell across all three pages:** All three files define `.card { border: 1px solid #8884; border-radius: 10px; padding: 1.1rem 1.25rem; margin: 1rem 0; }` identically — this is the one token that is consistent, even if it's duplicated rather than shared.

---

### Pillar 6: Experience Design (2/4)

**WARNING — Loading states are plain text strings, not skeletons:** Every async region initializes with literal "Loading…" text (index.html:90, 99, 111, 126, 132; performance.html:77, 95, 101, 105, 141; channel.html:82). For a data-heavy dashboard, text loading placeholders produce a jarring layout shift when content arrives — the health bar goes from one line of text to 4 pills, the KPI grid from one word to 7 boxes. Even a simple grid of grey placeholder divs matching the expected output shape would eliminate cumulative layout shift.

**BLOCKER — `alert()` used for success/error feedback in performance.html:** performance.html:437 calls `alert(...)` for revert success and performance.html:439 calls `alert('Revert failed: ' + e)` for errors. These are the only two places in the entire codebase using native browser alerts. Channel.html has a purpose-built `toast()` function; performance.html did not import or reuse it. This inconsistency means the revert workflow on the Performance page is the only action that halts the page thread and requires a mouse click to dismiss.

**WARNING — `confirm()` dialogs for all destructive confirmations:** Six `confirm()` calls exist across performance.html and channel.html. These native dialogs cannot be styled, do not match the tool's visual language, and block the browser thread. They work for a solo-operator tool but are inconsistent with the toast notification system already in place.

**WARNING — No global fetch error boundary on index.html:** index.html:184–186 catches the top-level `loadDashboard()` failure and shows a raw technical message: `'Failed to load. Is Supabase configured?'`. No retry button is provided. If Supabase has a transient error, the user must manually refresh. The 30-second auto-refresh `setInterval` on line 365 will eventually retry, but there is no user-visible indication that a retry is pending.

**WARNING — Performance page sync error feedback disappears:** performance.html:454 sets `$('sync-status').textContent = 'Refreshed ${j.refreshed} videos'` on success but on error (line not shown, falls to the `finally`) the error from `catch` is silently lost — the `sync-status` span never gets an error message written to it in the catch block. Users who trigger a failed sync see the button re-enable with no explanation.

**PASS — Disabled states are implemented and styled:** channel.html:17 defines `button:disabled { opacity: .5; cursor: progress; }` and every long-running action (sync, apply, bulk-audit, generate) correctly disables its button during the async operation and re-enables in `finally`. This is thorough and correct.

**PASS — Quota awareness is deeply integrated:** Quota cost preview (`/quota-cost-preview`) is called before bulk-apply and single-apply, with user-visible "Cannot afford" blocking toast. The health bar shows quota in real time with color-coded status. The dashboard auto-refreshes every 30 seconds.

---

## Additional Findings (Not in Top 3)

- **index.html channels section missing loading state:** `<div id="channels">Loading…</div>` shows plain text but the channels table is the most important element on the page. A placeholder table row or shimmer would prevent layout jump.
- **performance.html filter change on `f-status` triggers full `load()` (network)** while other filters trigger local `render()`. This asymmetry is correct behavior but the UX gives no feedback that the status filter change is making a network request (no spinner, no disabled state on the filter).
- **channel.html has `#toasts` system; performance.html and index.html do not.** Users on the performance page get native `alert()`; users on the channel page get styled toasts. The toast system should be extracted to a shared JS snippet.
- **The `channels` container in index.html (line 121) renders `<div id="channels" style="margin-top:.5rem">Loading…</div>` as a raw string inside a `.card`.** When the fetch fails (line 185), the error message is an `<em>` inside the same div — fine. But when the channels table loads, the card has no heading to label it, relying solely on the adjacent "Connected channels" h3 above the div to provide context. That h3 is inside the flex container at line 116, not wrapping the table — a minor DOM structure issue.
- **Regression warning in performance table uses raw ⚠ character (Unicode, not styled):** line 383 `'⚠ Regression detected...'`. This is technically fine but inconsistent with the pill-based status system used everywhere else.

---

## Registry Safety

Registry audit: shadcn not initialized (no `components.json`). Audit skipped.

---

## Files Audited

- `/Users/jugaadchhabra/Documents/Github/Midas/app/static/index.html` (369 lines)
- `/Users/jugaadchhabra/Documents/Github/Midas/app/static/performance.html` (462 lines)
- `/Users/jugaadchhabra/Documents/Github/Midas/app/static/channel.html` (776 lines)
