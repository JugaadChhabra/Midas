def test_shorts_concurrency_settings_defaults():
    from app.config import settings
    assert settings.SHORTS_MAX_CONCURRENT_JOBS == 2
    assert settings.SHORTS_DISPATCH_INTERVAL_SECONDS == 5
