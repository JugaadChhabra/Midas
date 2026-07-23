# scripts/backfill_nas_folder.py
"""One-off: set channels.nas_folder from the language word in each channel name.

Idempotent — only fills channels where nas_folder is NULL and exactly one
folder name appears in the channel name. Ambiguous / no-match channels are
printed for manual assignment via the UI dropdown.

Usage: python -m scripts.backfill_nas_folder
"""
from app.db import supabase
from app.shorts.nas_source import list_source_languages


def derive_folder(name: str, folders: list[str]) -> str | None:
    upper = (name or "").upper()
    hits = [f for f in folders if f in upper]
    return hits[0] if len(hits) == 1 else None


def main() -> int:
    folders = list_source_languages()
    chans = supabase().table("channels").select("id,name,nas_folder").execute().data or []
    for c in chans:
        if c.get("nas_folder"):
            continue
        folder = derive_folder(c.get("name") or "", folders)
        if folder:
            supabase().table("channels").update({"nas_folder": folder}).eq("id", c["id"]).execute()
            print(f"{c.get('name')} -> {folder}")
        else:
            print(f"{c.get('name')} -> (no unique match; set it in the UI)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
