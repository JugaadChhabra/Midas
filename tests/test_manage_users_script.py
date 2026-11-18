"""scripts/manage_users.py: logins are made, reset and deactivated from the
command line, the password always from a prompt (team tracker #144)."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app import main, session
from scripts import manage_users
from tests.fakes import FakeSupabase


@pytest.fixture
def store():
    sb = FakeSupabase({"app_users": [], "app_sessions": []}, serial=("app_users",))
    with patch.object(session, "supabase", return_value=sb):
        yield sb


def _run(argv, *typed):
    with patch.object(manage_users.getpass, "getpass", side_effect=list(typed)):
        return manage_users.main(argv)


def _can_log_in(email, password):
    r = TestClient(main.app).post("/session/login",
                                  json={"email": email, "password": password})
    return r.status_code == 200


def test_create_then_log_in(store, capsys):
    code = _run(["create", "--email", "Justin@Example.com", "--name", "Justin",
                 "--role", "manager"], "pw-1", "pw-1")

    assert code == 0
    [user] = store.rows("app_users")
    assert (user["email"], user["name"], user["role"], user["is_active"]) == \
        ("justin@example.com", "Justin", "manager", True)
    assert "pw-1" not in str(user)
    assert _can_log_in("justin@example.com", "pw-1")


def test_the_password_is_never_an_argument():
    with pytest.raises(SystemExit):
        manage_users._parser().parse_args(
            ["create", "--email", "a@b.com", "--name", "A", "--role", "admin",
             "--password", "x"])


def test_mismatched_passwords_create_nothing(store, capsys):
    code = _run(["create", "--email", "a@b.com", "--name", "A", "--role", "admin"],
                "one", "two")

    assert code == 1
    assert store.rows("app_users") == []
    assert "don't match" in capsys.readouterr().err


def test_an_unknown_role_is_refused(store):
    with pytest.raises(SystemExit):
        _run(["create", "--email", "a@b.com", "--name", "A", "--role", "owner"])


def test_reset_password_and_deactivate(store):
    _run(["create", "--email", "a@b.com", "--name", "A", "--role", "exec"], "old", "old")

    assert _run(["reset-password", "--email", "a@b.com"], "new", "new") == 0
    assert not _can_log_in("a@b.com", "old")
    assert _can_log_in("a@b.com", "new")

    assert _run(["deactivate", "--email", "a@b.com"]) == 0
    assert not _can_log_in("a@b.com", "new")
    assert store.rows("app_sessions") == []


def test_an_unknown_email_exits_1(store, capsys):
    assert _run(["deactivate", "--email", "nobody@b.com"]) == 1
    assert "no user" in capsys.readouterr().err
