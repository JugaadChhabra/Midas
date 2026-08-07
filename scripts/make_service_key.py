#!/usr/bin/env python3
"""Mint the service-role JWT the app presents to a self-hosted PostgREST.

Hosted Supabase issues this for you (Project Settings → API). Self-hosted, you
sign it yourself with the same secret PostgREST verifies against.

    export PGRST_JWT_SECRET="$(openssl rand -base64 48)"
    python scripts/make_service_key.py

Put the secret in .env as PGRST_JWT_SECRET and the printed token as
SUPABASE_SERVICE_KEY. They are a matched pair — rotating the secret invalidates
the token.

The token carries {"role": "service_role"}, which is the role PostgREST switches
to and the one the migrations grant execute on the RPCs to. It has no expiry:
this is a machine credential on a private network, and an expired token would
take the app down at an arbitrary hour with a confusing 401.
"""
from __future__ import annotations

import os
import sys

try:
    import jwt  # PyJWT
except ImportError:
    sys.exit("PyJWT is required: pip install PyJWT")

SECRET_MIN_LEN = 32


def main() -> int:
    secret = os.getenv("PGRST_JWT_SECRET", "")
    if not secret:
        sys.exit(
            "PGRST_JWT_SECRET is not set. Generate one:\n"
            '  export PGRST_JWT_SECRET="$(openssl rand -base64 48)"'
        )
    if len(secret) < SECRET_MIN_LEN:
        sys.exit(
            f"PGRST_JWT_SECRET is only {len(secret)} chars; PostgREST requires at "
            f"least {SECRET_MIN_LEN} for HS256. Generate a longer one."
        )

    token = jwt.encode({"role": "service_role"}, secret, algorithm="HS256")

    # app/db.py rejects anything that doesn't look like a JWT, which is the
    # check that catches "pasted the wrong field from the dashboard".
    assert token.startswith("eyJ"), "unexpected token shape"

    print("\nAdd to .env:\n")
    print(f"PGRST_JWT_SECRET={secret}")
    print(f"SUPABASE_SERVICE_KEY={token}")
    print("\nSUPABASE_URL is set for you in docker-compose.yml "
          "(http://postgrest:3000).")
    print("Running the app outside compose? Use http://localhost:3000 and "
          "publish PostgREST's port.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
