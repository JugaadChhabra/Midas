"""Midas logins, from the command line (team tracker #144). There is no signup.

    PYTHONPATH=. python scripts/manage_users.py create --email a@b.com --name "Justin" --role manager
    PYTHONPATH=. python scripts/manage_users.py reset-password --email a@b.com
    PYTHONPATH=. python scripts/manage_users.py deactivate --email a@b.com

The password is always typed at a prompt (twice), never passed as an argument,
so it stays out of shell history and the process list. Roles: admin, exec,
manager (app/status_vocab.py UserRole). A reset or a deactivation also ends the
user's sessions, so they're signed out on their next request.

Writes: `app_users` (one row created or updated) and `app_sessions` (the user's
rows deleted on reset/deactivate), through PostgREST like the app. No YouTube.
"""
from __future__ import annotations

import argparse
import getpass
import sys

from app import session
from app.status_vocab import ALL_USER_ROLES


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Create, reset or deactivate a Midas login.")
    sub = p.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create", help="create a user (password at a prompt)")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=sorted(ALL_USER_ROLES))
    reset = sub.add_parser("reset-password", help="set a new password (at a prompt)")
    reset.add_argument("--email", required=True)
    deactivate = sub.add_parser("deactivate", help="deactivate a user and end their sessions")
    deactivate.add_argument("--email", required=True)
    return p


def _prompt_password() -> str:
    first = getpass.getpass("Password: ")
    if not first:
        raise session.UserError("a password is required")
    if getpass.getpass("Password again: ") != first:
        raise session.UserError("the passwords don't match")
    return first


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create":
            user = session.create_user(args.email, args.name, args.role, _prompt_password())
            print(f"Created {user['role']} {user['name']} <{user['email']}>.")
        elif args.command == "reset-password":
            session.set_password(args.email, _prompt_password())
            print(f"Password reset for {args.email.strip().lower()}; their sessions ended.")
        else:
            session.deactivate_user(args.email)
            print(f"Deactivated {args.email.strip().lower()}; their sessions ended.")
    except session.UserError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
