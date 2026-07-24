# tests/test_nas_settings.py
import sys
from unittest.mock import MagicMock, patch


def test_nas_settings_have_expected_defaults():
    from app.config import Settings
    s = Settings()
    assert s.NAS_MODE in ("smb", "local")
    assert isinstance(s.NAS_PORT, int)
    # Root paths default to the real NAS layout when unset in env.
    assert s.NAS_SOURCE_ROOT_PATH
    assert s.NAS_DESTINATION_ROOT_PATH
    # Standalone NAS (raw IP, no domain) can't do Kerberos, so default to NTLM.
    assert s.NAS_AUTH_PROTOCOL == "ntlm"


def test_connect_passes_auth_protocol_to_register_session():
    from app.services.nas_service import NASService
    nas = NASService()
    nas.mode = "smb"
    nas.server = "10.1.1.3"
    fake_smbclient = MagicMock()  # smbclient only ships in the container image
    with patch.dict(sys.modules, {"smbclient": fake_smbclient}), \
         patch("app.services.nas_service.settings") as st:
        st.NAS_USERNAME = "Admin1"
        st.NAS_PASSWORD = "secret"
        st.NAS_PORT = 445
        st.NAS_DOMAIN = ""
        st.NAS_AUTH_PROTOCOL = "ntlm"
        nas._connect()
    reg = fake_smbclient.register_session
    reg.assert_called_once()
    assert reg.call_args.kwargs["auth_protocol"] == "ntlm"
