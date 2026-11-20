# Channel targets, the uploads table of tables, and the Board

Owner-approved in conversation, 2026-11-20.

## Why

Targets were per member (`member_targets`, 2026-11-20 morning). The owner wants
them on the channel: a channel has a daily target, and whoever is assigned the
channel carries it. The Roster's buttons-and-checklists are replaced by a
Scratch-like board that is fun to use and shows the team's structure at a glance.

## Rules (owner)

- A channel has a target per ISO weekday, Shorts and long-form apart
  (`channel_targets`). A member's target on a day = the sum of the targets of the
  channels credited to them that day (the grid's own crediting rule,
  `team_uploads._holder`, so target and credit always agree).
- `member_targets` is dropped: a member's number can't be split across channels,
  and it was a day old.
- A channel belongs to a manager (`channels.manager_id`); a member holds it.
- Dragging a channel onto a member assigns it from today (IST); if that member is
  under another manager, the channel's manager changes to theirs. That is the
  only way a channel changes manager besides dropping it in a manager's tray.
- Dragging a member onto another manager (admin only) moves the member; their
  channels stay with the old manager, their assignments end today, and the
  channels land in the old manager's loose tray. Asked to confirm first.
- Who edits: the admin, anything; a manager, channels within their own block
  (assign, move between members, unassign to their tray) and their channels'
  targets; exec, read only.

## Server

- Migration `20261121000000_channel_targets.sql`: `channel_targets`
  (`channel_id, weekday, shorts, long_form, updated_by, updated_at`, key
  `(channel_id, weekday)`), drop `member_targets`, and `move_channel()` (plpgsql,
  one transaction): to a member → set the channel's manager to the member's and
  `assign_channel`; to a tray → set the manager given and end the open row.
- `PUT /channels/{id}/targets` (manager: own channels; admin: any; exec 403).
- `POST /channels/{id}/move` `{team_member_id}` or `{manager_id}` (tray; null =
  no manager, admin only) → `{before, after}`, so the page can undo.
- `PATCH /team/members/{id}` gains `manager_id` (admin only; ends assignments).
- `GET /team/board` → managers, members, channels with holder, targets and
  today's uploads (the grid's crediting code).
- `GET /team/uploads` gains `sections` (per member: their channels' rows with
  per-day targets, member totals with summed targets; Unassigned last).
  `rows[].targets` and the By member / By channel switch go.
- The drill-down filters by member and channel together for a section's cell.

## Approaches considered

1. Hand-written pointer-event dragging: full control, ~200 lines of fiddly code.
2. SortableJS (vendored, 45 KB, no build step): solid nested-list dragging
   with touch and auto-scroll; the look is all our CSS.
3. Free-form canvas: Scratch-like but positions need storing.

**Picked: 2 + 3 hybrid** (owner wants it fun and good-looking): manager blocks
float on a pannable canvas, dragged by their hat, positions kept in the browser
(`localStorage`, nothing server-side); inside a block SortableJS does the
nesting. A "Tidy up" button resets the layout.

## The Board's look and feel

- Scratch shapes: hat blocks for managers, C-blocks for members wrapping their
  channels, puzzle-piece channel blocks with notch and bump; one hue per
  manager, lighter tints for members and channels.
- Lift with shadow and tilt on pick-up, siblings part, valid drop zones glow,
  spring on drop.
- Each channel shows today's uploads against today's target as a bar; a member
  who meets every target today turns gold, with confetti the first time a day.
- A loose channel with a target today pulses red.
- Click a channel: a card with its weekly targets and a "Move to…" picker (the
  keyboard / trackpad fallback). Click a member: rename, deactivate/reactivate.
- Undo toast after every move. No sound.

## The Uploads page

No By member / By channel switch. One table, a section per member (member row
with their totals and summed target, then their channels' rows with each
channel's target), Unassigned last; sections collapse. Red = below target on a
finished day, per channel and per member.

## Left to the builder

Exact colours, animation timings, confetti shape, empty states.
