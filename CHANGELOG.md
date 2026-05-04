# Changelog

All notable changes to tryfurqan.com are documented here. Format
follows the audit-discipline conventions in use across the
furqan-lint and furqan repositories: entries are organized by
release, each release lists the work in load-bearing sections
(added / changed / removed / fixed), and verdicts of any locked
gates that ran during the release are summarized in the
release block.

## [1.0.0] - 2026-05-04

### Added

- `/playground` page and deep-link routes
  (`/playground/{python,rust,go,diff}`) hosting a live
  furqan-lint v0.8.5 sandbox. Three language tabs and a
  Check / Diff mode toggle share one editor surface; state
  is mirrored into the URL so links are restorable.
- Backend endpoints (`playground.py`):
  - `POST /playground/check` - single-file check, exit-code
    -> verdict envelope `{verdict, verdict_label,
    exit_code, stdout, stderr, elapsed_ms, language}`.
  - `POST /playground/diff` - paired old/new check; same
    envelope plus `mode: "diff"`.
  - `POST /playground/share` - persist a snapshot, return a
    12-character urlsafe-base64 share id.
  - `GET /s/{share_id}` - resolve a share id back to its
    snapshot JSON. 30-day TTL; lazy sweep on every write.
- Pre-loaded fixtures per tab grounded in real v0.8.5
  outputs: PASS, status-collapse MARAD, parse-error per
  language; additive PASS and removed-name MARAD per diff.
  Twelve fixtures total.
- Sandbox discipline: 100 KiB cap per source, 5 s wall-clock
  timeout, per-request tmp file under `/tmp` unlinked in
  `finally`, absolute paths rewritten in stdout/stderr so
  responses are portable, stripped subprocess environment.
- `tests/` suite (37 tests, all green against
  furqan-lint==0.8.5 + furqan==0.11.1):
  - `test_playground_api.py` - verdict classification,
    share-id format, round-trip, TTL sweep, request schema,
    size cap, error envelopes.
  - `test_fixture_baselines.py` - runs every fixture against
    the installed furqan-lint and asserts the locked
    verdict in `tests/baselines/furqan_lint_v<X_Y_Z>.json`.
    Skipped if furqan-lint is not on PATH.
  - `test_fixtures_sync.py` - drift gate: every fixture id
    in `playground.js` must exist in `tests/fixtures.py`
    and the v0.8.5 baseline.
- `tests/baselines/furqan_lint_v0_8_5.json` - locked verdict
  baseline for the 16 playground fixtures against
  furqan-lint v0.8.5. Per-version baselines mirror the
  furqan-lint §7.6 cadence: when upgrading furqan-lint,
  copy this file to a new versioned baseline, re-run the
  harness, review every diff, commit both the new baseline
  and the requirements bump in the same PR.
- `nixpacks.toml` - extends Railway's Python auto-detection
  with the Go toolchain. Required at install time so
  `furqan-lint[go]`'s PEP 517 build hook can compile the
  bundled `goast` binary.
- `.github/workflows/ci.yml` - runs the test suite plus the
  fixture baseline gate on every push and PR.

### Changed

- `requirements.txt` now pins furqan and furqan-lint to
  release tags via `git+https`. Pins:
  - `furqan @ git+...@v0.11.1`
  - `furqan-lint[go] @ git+...@v0.8.5`
  Once both packages publish to PyPI in lockstep, the
  follow-up PR swaps the git+ URLs for plain version pins
  without changing site behavior.
- `api.py` includes the playground router and adds the page
  routes. The existing `/`, `/demo`, and `/demo/check`
  surfaces are unchanged.

### Verdict gates run during this release

- 37 / 37 backend + sync + fixture-baseline tests PASS.
- Every fixture verdict matches the v0.8.5 baseline.
- End-to-end smoke (12 / 12 cases): every tab fires the
  expected verdict against the live API.

### Known follow-ups

- One-line PR after `furqan==0.11.1` publishes to PyPI:
  swap `furqan @ git+...@v0.11.1` for `furqan==0.11.1` in
  `requirements.txt`. Same for `furqan-lint[go]==0.8.5`
  once the lockstep is restored.
- The Go toolchain installs at every Railway build. If
  build time becomes a bottleneck, cache the goast binary.

[1.0.0]: https://github.com/BayyinahEnterprise/tryfurqan/releases/tag/v1.0.0
