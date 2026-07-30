-- Auto-expiring autopilot pauses.
--
-- `autopilot_paused_reason` is a latch with no auto-recovery: a transient burst
-- of 3 failures sets 'repeated_failures' and the channel is skipped by the
-- autopilot picker forever, until a human hits Resume. Combined with the pause
-- gating BOTH the audit and the (NAS) shorts paths, one audit-side blip silently
-- benches a whole channel's shorts cutting even though its NAS folder is full.
--
-- This adds a paused-at timestamp so the picker can auto-clear 'repeated_failures'
-- pauses after a cooldown (see AUTOPILOT_PAUSE_COOLDOWN_MINUTES). token_expired /
-- unsafe_model do NOT auto-expire — they need explicit action (reconnect / config)
-- — so only the transient reason is cleared by time.
alter table channels add column if not exists autopilot_paused_at timestamptz;

-- Backfill: stamp already-paused channels so they participate in the cooldown
-- instead of being stuck with a NULL paused_at that never matches the `< cutoff`
-- auto-clear predicate.
update channels
   set autopilot_paused_at = now()
 where autopilot_paused_reason is not null
   and autopilot_paused_at is null;
