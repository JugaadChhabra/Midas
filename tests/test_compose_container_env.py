"""`.env` is written for the HOST; compose must override what breaks in a container.

The same `.env` is read twice with different meanings: host tooling
(`scripts/apply_migrations.py`, an ad-hoc `snapshot_to_nas()`) needs published
ports and whatever binaries that machine happens to have, while the `midas`
service inherits the whole file via `env_file` and needs in-network hostnames and
the image's own binaries. Compose's `environment:` block is where that
translation lives — it takes precedence over `env_file`, so every setting whose
correct value differs between the two has to appear there.

Every one of these has already failed in production on 2026-08-13, on a machine
whose `.env` was copied from a Mac:

  DATABASE_URL    localhost:55432 -> the container dialled its own loopback
  RESTORE_PSQL    /opt/homebrew/... -> FileNotFoundError mid-restore
  BACKUP_PG_DUMP  /opt/homebrew/... -> would have failed silently at 00:00,
                  which is the one failure that loses data rather than uptime

They fail at different times (startup, first empty-DB boot, midnight), so a
missing override is not something a smoke test finds. Hence this test.
"""
from __future__ import annotations

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]

#: Setting -> why the host value is wrong inside the container.
MUST_OVERRIDE = {
    "DATABASE_URL": "host value uses the published port on 127.0.0.1",
    "SUPABASE_URL": "host value uses the published port on 127.0.0.1",
    "BACKUP_PG_DUMP": "host value may be an absolute path to that machine's psql install",
    "RESTORE_PSQL": "host value may be an absolute path to that machine's psql install",
}

#: These must resolve on the image's PATH, not point into a host filesystem.
#: The Dockerfile installs postgresql-client-16 and asserts its major version,
#: so a bare name is both correct and version-checked; an absolute path is
#: neither.
MUST_BE_BARE_BINARIES = ("BACKUP_PG_DUMP", "RESTORE_PSQL")


def _midas_environment() -> dict[str, str]:
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    env = compose["services"]["midas"]["environment"]
    if isinstance(env, list):                      # `- KEY=value` form
        return dict(item.split("=", 1) for item in env)
    return {k: str(v) for k, v in env.items()}


def test_compose_overrides_every_host_specific_setting():
    env = _midas_environment()
    missing = {k: why for k, why in MUST_OVERRIDE.items() if k not in env}
    assert not missing, (
        "docker-compose.yml's midas service does not override these, so the "
        f"host-oriented .env values reach the container: {missing}"
    )


def test_postgres_binaries_are_resolved_on_the_image_path():
    env = _midas_environment()
    for key in MUST_BE_BARE_BINARIES:
        value = env[key]
        assert "/" not in value and "\\" not in value, (
            f"{key}={value!r} is a filesystem path. It must be a bare binary "
            f"name so it resolves on the image's PATH, where the Dockerfile "
            f"has already pinned and version-asserted postgresql-client."
        )


def test_env_example_does_not_teach_absolute_binary_paths():
    """A fresh .env must not start life with a host path in it.

    `.env.example` is what a new machine copies. It omits these keys today, which
    is correct — the defaults in app/config.py are already the bare names. This
    pins that, so nobody "helpfully" adds their own Homebrew path to the template.
    """
    example = (REPO / ".env.example").read_text()
    for key in MUST_BE_BARE_BINARIES:
        for line in example.splitlines():
            stripped = line.strip()
            if stripped.startswith(f"{key}="):
                value = stripped.split("=", 1)[1].split("#")[0].strip()
                assert "/" not in value and "\\" not in value, (
                    f".env.example sets {key} to a path ({value!r}); a new "
                    f"machine would inherit another machine's layout."
                )
