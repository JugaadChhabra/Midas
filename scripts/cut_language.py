"""Enqueue NAS shorts jobs for a language folder from the command line.

Usage:
    python -m scripts.cut_language HINDI
    python -m scripts.cut_language --list
"""
import sys

from app.shorts.nas_source import enqueue_language_jobs, list_source_languages


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        print("usage: python -m scripts.cut_language <LANGUAGE> | --list")
        return 0
    if argv[0] == "--list":
        for lang in list_source_languages():
            print(lang)
        return 0
    language = argv[0].strip().upper()
    try:
        n = enqueue_language_jobs(language)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    print(f"Enqueued {n} job(s) for {language}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
