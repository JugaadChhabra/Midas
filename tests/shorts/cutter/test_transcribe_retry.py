from app.shorts.cutter.cutplan import TranscriptSegment
from app.shorts.cutter.transcribe import should_retry_without_vad


def seg(start, end, text="la"):
    return TranscriptSegment(start, end, text)


def test_retry_when_no_segments():
    assert should_retry_without_vad([], 120.0) is True


def test_retry_when_coverage_is_a_sliver():
    # 2 short scraps on a 137s song — the Johny Johny failure mode
    units = [seg(15.8, 16.4), seg(16.6, 18.0)]
    assert should_retry_without_vad(units, 137.0) is True


def test_no_retry_with_healthy_coverage():
    units = [seg(i * 10.0, i * 10.0 + 6.0) for i in range(10)]  # 60s of 120s
    assert should_retry_without_vad(units, 120.0) is False


def test_short_video_threshold_scales():
    units = [seg(0.0, 8.0)]  # 8s of a 30s video: fine
    assert should_retry_without_vad(units, 30.0) is False


def test_hallucinated_blob_over_silence_triggers_retry():
    # one 26s blob spanning mostly vocal silence — the Johny Johny v2 failure
    units = [seg(15.8, 16.4), seg(16.6, 43.0)]
    silence = [(17.4, 20.5), (20.9, 23.2), (23.3, 24.3), (34.6, 42.5)]
    assert should_retry_without_vad(units, 137.0, silence) is True
    # without silence info the blob defeats the check (documented limitation)
    assert should_retry_without_vad(units, 137.0) is False
