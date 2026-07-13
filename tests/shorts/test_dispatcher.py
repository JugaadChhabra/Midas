from unittest.mock import MagicMock, patch


def _created_query(sb, created_ids):
    """Wire sb so the 'fetch next CREATED not in running' query returns rows.

    The plain .limit(1) branch is used when _running is empty.
    The .not_.in_(col, ids) branch is used when there are running jobs; its
    side_effect actually filters created_ids so the dispatcher sees only ids
    that aren't already running (mirroring what the real DB would return).
    """
    q = sb.table.return_value.select.return_value.eq.return_value.order.return_value
    # plain branch — no running jobs, return all created rows
    q.limit.return_value.execute.return_value.data = [{"id": i} for i in created_ids]

    # not_.in_ branch — filter out the excluded ids, just like the real DB does
    def _not_in_side_effect(col, excluded_ids):
        filtered = [{"id": i} for i in created_ids if i not in excluded_ids]
        stub = MagicMock()
        stub.limit.return_value.execute.return_value.data = filtered
        return stub

    q.not_.in_.side_effect = _not_in_side_effect


def _reset():
    from app.shorts import dispatcher
    dispatcher._running.clear()
    return dispatcher


def test_fills_up_to_cap():
    d = _reset()
    sb = MagicMock()
    _created_query(sb, [1, 2, 3])
    procs = [MagicMock(), MagicMock()]
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn", side_effect=procs) as spawn:
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert spawn.call_count == 2                      # only cap launched
    assert set(d._running.keys()) == {1, 2}


def test_does_not_relaunch_running_job():
    d = _reset()
    d._running[1] = MagicMock(poll=lambda: None)     # job 1 already running
    sb = MagicMock()
    _created_query(sb, [1, 2])                        # 1 still CREATED, 2 new
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn", return_value=MagicMock()) as spawn:
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    spawn.assert_called_once_with(2)                  # never re-spawns 1


def test_reap_frees_slot_and_fails_nonterminal():
    d = _reset()
    dead = MagicMock(poll=lambda: 1, returncode=1)    # exited, non-zero
    d._running[7] = dead
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "RENDERING"}
    _created_query(sb, [])                            # no new CREATED work
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn"):
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert 7 not in d._running                        # slot freed
    upd = sb.table.return_value.update.call_args[0][0]
    assert upd["status"] == "FAILED"
    assert "rc=1" in upd["error_message"]


def test_reap_leaves_done_job_alone():
    d = _reset()
    done = MagicMock(poll=lambda: 0, returncode=0)
    d._running[8] = done
    sb = MagicMock()
    sb.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {"status": "DONE"}
    _created_query(sb, [])
    with patch("app.shorts.dispatcher.supabase", return_value=sb), \
         patch("app.shorts.dispatcher.settings") as st, \
         patch("app.shorts.dispatcher._spawn"):
        st.SHORTS_MAX_CONCURRENT_JOBS = 2
        d.dispatch_tick()
    assert 8 not in d._running
    sb.table.return_value.update.assert_not_called()  # DONE is terminal, untouched
