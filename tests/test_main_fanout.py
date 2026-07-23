from unittest.mock import patch


def test_run_per_channel_calls_every_channel():
    from app import main

    seen = []
    with patch.object(main, "_all_channel_ids", return_value=["a", "b", "c"]):
        main._run_per_channel(lambda cid: seen.append(cid), "Test job")

    assert seen == ["a", "b", "c"]


def test_run_per_channel_isolates_failures():
    from app import main

    seen = []

    def fn(cid):
        seen.append(cid)
        if cid == "b":
            raise RuntimeError("boom on b")

    with patch.object(main, "_all_channel_ids", return_value=["a", "b", "c"]):
        # One channel failing must not stop the others.
        main._run_per_channel(fn, "Test job")

    assert seen == ["a", "b", "c"]


def test_run_per_channel_uses_explicit_channel_ids():
    from app import main

    seen = []
    # When channel_ids is supplied, _all_channel_ids must not be consulted.
    with patch.object(main, "_all_channel_ids", side_effect=AssertionError("should not be called")):
        main._run_per_channel(lambda cid: seen.append(cid), "Test job", channel_ids=["x", "y"])

    assert seen == ["x", "y"]
