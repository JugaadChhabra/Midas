"""The live probes parse their arguments without touching an API.

The probes themselves are run by hand (docs/PHASE_A_FINDINGS.md); this only
proves each one imports with no side effect, answers --help, and rejects a
bad command line with usage — all before any client is built, so it runs
under the offline socket guard.
"""
import importlib
import sys

import pytest

PROBES = [
    "scripts.create_reporting_job",
    "scripts.probes.probe_i18n_languages",
    "scripts.probes.probe_traffic_source_report",
    "scripts.probes.probe_traffic_source_analytics",
    "scripts.probes.probe_short_link",
]


def _run(name, argv, monkeypatch):
    # sys.argv, not main(argv): the i18n probe's main() takes no arguments.
    mod = importlib.import_module(name)
    monkeypatch.setattr(sys, "argv", [name, *argv])
    mod.main()


@pytest.mark.parametrize("name", PROBES)
def test_help_parses(name, capsys, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run(name, ["--help"], monkeypatch)
    assert exc.value.code == 0
    assert "usage:" in capsys.readouterr().out


@pytest.mark.parametrize("name", PROBES)
def test_bad_input_prints_usage(name, capsys, monkeypatch):
    with pytest.raises(SystemExit) as exc:
        _run(name, [], monkeypatch)
    assert exc.value.code == 2
    assert "usage:" in capsys.readouterr().err


def test_short_link_finds_every_path_holding_the_id():
    from scripts.probes.probe_short_link import find_paths

    resp = {"items": [{"id": "S1", "snippet": {"description": "watch abc123 next"},
                       "tags": ["x", "abc123"], "abc123": 1}]}
    assert find_paths(resp, "abc123") == [
        ("$.items[0].snippet.description", "watch abc123 next"),
        ("$.items[0].tags[1]", "abc123"),
        ("$.items[0].abc123", "<key> abc123"),
    ]
