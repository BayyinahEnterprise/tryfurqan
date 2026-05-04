"""Sync gate: every fixture id used in playground.js must exist in
tests/fixtures.py and the v0.8.5 baseline. Drift fails CI.

We do not parse the JS file; we just grep for the `id:` keys with a
simple regex. The regex is intentionally narrow to avoid matching
unrelated `id:` text.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from tests.fixtures import CHECK_FIXTURES, DIFF_FIXTURES

_HERE = Path(__file__).resolve().parent
_REPO = _HERE.parent
_PG_JS = _REPO / "static" / "playground.js"
_BASELINE = _HERE / "baselines" / "furqan_lint_v0_8_5.json"

_ID_PATTERN = re.compile(r"id:\s*'([a-z0-9-]+)'")


def _ids_in_js() -> set[str]:
    text = _PG_JS.read_text(encoding="utf-8")
    return set(_ID_PATTERN.findall(text))


def _ids_in_python_check() -> set[str]:
    return {fid for m in CHECK_FIXTURES.values() for fid in m}


def _ids_in_python_diff() -> set[str]:
    return {fid for m in DIFF_FIXTURES.values() for fid in m}


def _ids_in_baseline() -> set[str]:
    data = json.loads(_BASELINE.read_text(encoding="utf-8"))
    out: set[str] = set()
    for lang_map in data["fixtures"]["check"].values():
        out.update(lang_map.keys())
    for lang_map in data["fixtures"]["diff"].values():
        out.update(lang_map.keys())
    return out


def test_js_ids_match_python_fixtures() -> None:
    js_ids = _ids_in_js()
    py_ids = _ids_in_python_check() | _ids_in_python_diff()
    missing_in_py = js_ids - py_ids
    missing_in_js = py_ids - js_ids
    assert not missing_in_py, (
        f"playground.js declares fixture ids absent from "
        f"tests/fixtures.py: {sorted(missing_in_py)}"
    )
    assert not missing_in_js, (
        f"tests/fixtures.py declares fixture ids absent from "
        f"playground.js: {sorted(missing_in_js)}"
    )


def test_baseline_covers_every_python_fixture() -> None:
    py_ids = _ids_in_python_check() | _ids_in_python_diff()
    base_ids = _ids_in_baseline()
    missing = py_ids - base_ids
    assert not missing, (
        f"v0.8.5 baseline missing fixture ids: {sorted(missing)}"
    )
