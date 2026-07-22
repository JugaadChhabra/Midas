# tests/test_nas_settings.py
def test_nas_settings_have_expected_defaults():
    from app.config import Settings
    s = Settings()
    assert s.NAS_MODE in ("smb", "local")
    assert isinstance(s.NAS_PORT, int)
    # Root paths default to the real NAS layout when unset in env.
    assert s.NAS_SOURCE_ROOT_PATH
    assert s.NAS_DESTINATION_ROOT_PATH
