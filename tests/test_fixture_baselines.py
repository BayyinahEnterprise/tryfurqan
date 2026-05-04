"""Per-version fixture baseline gate.

Runs every playground fixture against the installed furqan-lint and
asserts the verdict matches the locked baseline for that version
(tests/baselines/furqan_lint_v<MAJOR>_<MINOR>_<PATCH>.json).

Upgrade discipline (matches furqan-lint v0.8.5 §7.6):
  1. Bump furqan-lint pin in requirements.txt.
  2. Run pytest. Failures are expected; review each one.
  3. Copy the prior baseline to a new file with the new version
     in the name, update the verdict where the change is
     intentional, and commit BOTH the new baseline and the
     requirements bump in the same PR. The diff IS the audit.
  4. Old baselines stay in the repo as historical record.

This test is skipped if furqan-lint is not installed - we keep
the fast unit tests independent of the toolchain.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from tests.fixtures import CHECK_FIXTURES, DIFF_FIXTURES

_HERE = Path(__file__).resolve().parent
_BASELINES_DIR = _HERE / "baselines"


def _furqan_lint_available() -> bool:
    return shutil.which("furqan-lint") is not None


pytestmark = pytest.mark.skipif(
    not _furqan_lint_available(),
    reason="furqan-lint not on PATH; baseline gate requires the runtime",
)


def _get_installed_version() -> str:
    """Return the installed furqan-lint version, e.g. '0.8.5'."""
    proc = subprocess.run(
        ["furqan-lint", "version"], capture_output=True, text=True, check=True
    )
    # Output: "furqan-lint 0.8.5"
    parts = proc.stdout.strip().split()
    if len(parts) >= 2:
        return parts[1]
    raise RuntimeError(f"unexpected furqan-lint version output: {proc.stdout!r}")


def _baseline_path_for(version: str) -> Path:
    safe = version.replace(".", "_")
    return _BASELINES_DIR / f"furqan_lint_v{safe}.json"


def _load_baseline() -> dict:
    version = _get_installed_version()
    p = _baseline_path_for(version)
    if not p.exists():
        pytest.skip(
            f"no baseline pinned for furqan-lint v{version}; "
            f"create {p.name} to enable baseline-gated CI"
        )
    return json.loads(p.read_text(encoding="utf-8"))


_SUFFIX = {"python": ".py", "rust": ".rs", "go": ".go"}


def _run_check(source: str, language: str) -> tuple[int, str, str]:
    suffix = _SUFFIX[language]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, prefix="fixture_", dir="/tmp",
        delete=False, encoding="utf-8"
    ) as f:
        f.write(source)
        path = f.name
    try:
        proc = subprocess.run(
            ["furqan-lint", "check", path],
            capture_output=True, text=True, timeout=10
        )
        return proc.returncode, proc.stdout, proc.stderr
    finally:
        Path(path).unlink(missing_ok=True)


def _run_diff(old: str, new: str, language: str) -> tuple[int, str, str]:
    suffix = _SUFFIX[language]
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, prefix="fixture_old_", dir="/tmp",
        delete=False, encoding="utf-8"
    ) as f:
        f.write(old)
        old_path = f.name
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=suffix, prefix="fixture_new_", dir="/tmp",
        delete=False, encoding="utf-8"
    ) as f:
        f.write(new)
        new_path = f.name
    try:
        proc = subprocess.run(
            ["furqan-lint", "diff", old_path, new_path],
            capture_output=True, text=True, timeout=10
        )
        return proc.returncode, proc.stdout, proc.stderr
    finally:
        Path(old_path).unlink(missing_ok=True)
        Path(new_path).unlink(missing_ok=True)


def _verdict_from_exit(exit_code: int, stdout: str) -> str:
    if exit_code == 0:
        return "advisory" if "ADVISORY" in stdout else "pass"
    if exit_code == 1:
        return "marad"
    if exit_code == 2:
        return "parse_error"
    return "internal_error"


# ---------------------------------------------------------------------------
# Parametrize over every fixture id
# ---------------------------------------------------------------------------

_check_cases: list = []
for lang, m in CHECK_FIXTURES.items():
    for fid in m:
        _check_cases.append((lang, fid))

_diff_cases: list = []
for lang, m in DIFF_FIXTURES.items():
    for fid in m:
        _diff_cases.append((lang, fid))


@pytest.mark.parametrize("language,fixture_id", _check_cases)
def test_check_fixture_matches_baseline(language: str, fixture_id: str) -> None:
    baseline = _load_baseline()
    expected = baseline["fixtures"]["check"][language][fixture_id]
    source = CHECK_FIXTURES[language][fixture_id]
    exit_code, stdout, stderr = _run_check(source, language)
    actual_verdict = _verdict_from_exit(exit_code, stdout)
    assert actual_verdict == expected["verdict"], (
        f"check {language}/{fixture_id}: "
        f"expected {expected['verdict']} got {actual_verdict}\n"
        f"stdout: {stdout[:400]}\nstderr: {stderr[:400]}"
    )
    assert exit_code == expected["exit_code"], (
        f"check {language}/{fixture_id}: "
        f"expected exit {expected['exit_code']} got {exit_code}"
    )


@pytest.mark.parametrize("language,fixture_id", _diff_cases)
def test_diff_fixture_matches_baseline(language: str, fixture_id: str) -> None:
    baseline = _load_baseline()
    expected = baseline["fixtures"]["diff"][language][fixture_id]
    old, new = DIFF_FIXTURES[language][fixture_id]
    exit_code, stdout, stderr = _run_diff(old, new, language)
    actual_verdict = _verdict_from_exit(exit_code, stdout)
    assert actual_verdict == expected["verdict"], (
        f"diff {language}/{fixture_id}: "
        f"expected {expected['verdict']} got {actual_verdict}\n"
        f"stdout: {stdout[:400]}\nstderr: {stderr[:400]}"
    )
    assert exit_code == expected["exit_code"], (
        f"diff {language}/{fixture_id}: "
        f"expected exit {expected['exit_code']} got {exit_code}"
    )


def test_baseline_covers_every_fixture() -> None:
    """If a fixture is added to fixtures.py without updating the
    baseline, this test fails."""
    baseline = _load_baseline()
    for lang, m in CHECK_FIXTURES.items():
        for fid in m:
            assert fid in baseline["fixtures"]["check"][lang], (
                f"check {lang}/{fid} missing from baseline; "
                f"add it before merging"
            )
    for lang, m in DIFF_FIXTURES.items():
        for fid in m:
            assert fid in baseline["fixtures"]["diff"][lang], (
                f"diff {lang}/{fid} missing from baseline; "
                f"add it before merging"
            )
