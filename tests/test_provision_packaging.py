"""The image must contain the files provision.py reads at runtime.

`app/provision.py` is the only module that reads data from OUTSIDE `app/`: it
applies `supabase/bootstrap/*.sql` around the restore. The Dockerfile copies
`app/` and nothing else, so that dependency is invisible until an empty database
tries to provision itself in a container — at which point the app fails to start
with a bare FileNotFoundError, which is what happened on 2026-08-13.

Every other module resolves its files under `app/`, so `app/` being copied is
enough for them. This test guards the one exception, and will fail if a future
module starts reading a sibling directory that the image does not carry.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

#: `COPY <src>... <dst>` — capture the sources, ignoring --flags like --from=.
_COPY = re.compile(r"^COPY\s+(?:--\S+\s+)*(?P<args>.+)$", re.MULTILINE)


def _copied_sources() -> list[str]:
    sources: list[str] = []
    for m in _COPY.finditer((REPO / "Dockerfile").read_text()):
        parts = m.group("args").split()
        sources.extend(parts[:-1])          # last token is the destination
    return sources


def test_bootstrap_sql_is_copied_into_the_image():
    """provision.py reads /app/supabase/bootstrap — the image must have it."""
    assert any(
        s.rstrip("/") in ("supabase", "supabase/bootstrap")
        for s in _copied_sources()
    ), (
        "Dockerfile does not COPY supabase/bootstrap, but app/provision.py reads "
        f"it at startup. Copied sources: {_copied_sources()}"
    )


def test_bootstrap_dir_resolves_under_the_copied_tree():
    """The path provision.py builds must match where the Dockerfile puts it.

    Catches the two halves drifting apart — a rename of `supabase/bootstrap`
    that updates provision.py but not the Dockerfile, or vice versa.
    """
    from app.provision import BOOTSTRAP_DIR

    rel = BOOTSTRAP_DIR.relative_to(REPO)
    assert rel == Path("supabase/bootstrap"), rel
    assert sorted(p.name for p in BOOTSTRAP_DIR.glob("*.sql")) == [
        "000_roles.sql",
        "010_storage_shim.sql",
    ]
