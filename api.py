"""tryfurqan.com — landing + live demo for the Furqan type-checker.

The site has two surfaces:

  GET  /              Editorial landing page (single static HTML).
  GET  /demo          Editorial demo page with paste-area + 5 fixtures.
  POST /demo/check    Sandboxed execution of `furqan check` on the
                      submitted source. Returns a structured verdict
                      JSON envelope.
  GET  /healthz       Liveness probe for Railway.
  GET  /version       Returns the installed furqan version.

Sandbox discipline
------------------
The /demo/check endpoint accepts user-submitted Furqan source. The
checker itself is pure-Python, has zero runtime dependencies, and
performs no I/O beyond reading the source file. Even so, the
endpoint:

  * Caps the source at 64 KiB (no pathological-size inputs).
  * Writes the source to a per-request tmp file under /tmp.
  * Invokes `python -m furqan check <tmp>` as a subprocess.
  * Imposes a wall-clock timeout of 5 seconds.
  * Captures stdout, stderr, and exit code, then deletes the tmp file.

The verdict is derived from the exit code, mirroring the Furqan CLI
contract documented in src/furqan/__main__.py:

  0  PASS
  1  MARAD     (one or more violations)
  2  PARSE ERROR
  3  STRICT MODE failure (not used here)

ADVISORY is a sub-state of PASS: exit code is 0, but the stdout
contains an "ADVISORY" block. The endpoint distinguishes PASS from
ADVISORY by inspecting stdout.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ROOT = Path(__file__).resolve().parent
_STATIC_DIR = _ROOT / "static"
_FIXTURES_DIR = _ROOT / "fixtures"

_MAX_SOURCE_BYTES = 64 * 1024  # 64 KiB
_CHECK_TIMEOUT_S = 5.0

# Strict whitelist of fixtures servable via /demo/fixtures/<name>.
# Any other name returns 404. Prevents path traversal and locks down
# what the site can serve as canonical examples.
_FIXTURE_WHITELIST = {
    "clean_module.furqan",
    "advisory_empty_tanzil.furqan",
    "marad_status_collapse.furqan",
    "marad_missing_return.furqan",
    "parse_error.furqan",
}

try:
    import furqan
    _FURQAN_VERSION = getattr(furqan, "__version__", "unknown")
except ImportError:  # pragma: no cover - furqan is a runtime dep
    _FURQAN_VERSION = "unknown"


app = FastAPI(
    title="tryfurqan",
    description="Live demo of the Furqan honest-programming-language type-checker.",
    version=_FURQAN_VERSION,
)


# ---------------------------------------------------------------------------
# Health and meta
# ---------------------------------------------------------------------------

@app.get("/healthz")
def healthz() -> dict[str, Any]:
    return {"status": "ok", "service": "tryfurqan", "furqan_version": _FURQAN_VERSION}


@app.get("/version")
def version() -> dict[str, str]:
    return {"furqan_version": _FURQAN_VERSION}


# ---------------------------------------------------------------------------
# Static surfaces (landing + demo)
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Editorial landing page."""
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/demo", response_class=HTMLResponse)
def demo_page() -> HTMLResponse:
    """Editorial demo page."""
    html = (_STATIC_DIR / "demo.html").read_text(encoding="utf-8")
    return HTMLResponse(content=html)


@app.get("/demo/demo.js")
def demo_js() -> FileResponse:
    return FileResponse(_STATIC_DIR / "demo.js", media_type="application/javascript")


@app.get("/og-tryfurqan.png")
def og_card() -> FileResponse:
    return FileResponse(_STATIC_DIR / "og-tryfurqan.png", media_type="image/png")


@app.get("/robots.txt")
def robots() -> FileResponse:
    return FileResponse(_STATIC_DIR / "robots.txt", media_type="text/plain")


@app.get("/demo/fixtures/{name}")
def demo_fixture(name: str) -> FileResponse:
    """Serve a whitelisted fixture as text/plain.

    The whitelist is the only allowed name set; an arbitrary path
    component returns 404 to defeat traversal attempts.
    """
    if name not in _FIXTURE_WHITELIST:
        raise HTTPException(status_code=404, detail="fixture not found")
    return FileResponse(_FIXTURES_DIR / name, media_type="text/plain; charset=utf-8")


# ---------------------------------------------------------------------------
# /demo/check — sandboxed execution
# ---------------------------------------------------------------------------

class CheckRequest(BaseModel):
    source: str = Field(..., description="Furqan source code as a UTF-8 string.")


def _classify_verdict(exit_code: int, stdout: str) -> tuple[str, str]:
    """Map (exit_code, stdout) to a verdict tag and a UI label.

    Returns
    -------
    (verdict_tag, verdict_label) where verdict_tag is one of
    {"pass", "advisory", "marad", "parse_error", "internal_error"}.
    """
    if exit_code == 0:
        # Exit 0 covers both "no diagnostics at all" (PASS) and
        # "advisories only, no marads" (ADVISORY). The CLI prints
        # the literal string "ADVISORY" when advisories fire.
        if "ADVISORY" in stdout:
            return "advisory", "ADVISORY"
        return "pass", "PASS"
    if exit_code == 1:
        return "marad", "MARAD"
    if exit_code == 2:
        return "parse_error", "PARSE ERROR"
    return "internal_error", "INTERNAL ERROR"


def _run_check(source: str) -> dict[str, Any]:
    """Run `python -m furqan check <tmpfile>` on the submitted source.

    Always returns a JSON-serialisable dict; never raises. Errors are
    surfaced as a verdict tag of "internal_error" so the caller's UI
    can still render a panel.
    """
    if not isinstance(source, str):
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": "source must be a string",
        }
    if len(source.encode("utf-8")) > _MAX_SOURCE_BYTES:
        return {
            "verdict": "internal_error",
            "verdict_label": "INPUT TOO LARGE",
            "error": (
                f"source exceeds {_MAX_SOURCE_BYTES} bytes "
                f"({len(source.encode('utf-8'))} bytes submitted)"
            ),
        }

    started = time.perf_counter()
    tmp_path: Path | None = None
    try:
        # tempfile.NamedTemporaryFile with delete=False so we control
        # cleanup explicitly in finally; .furqan suffix is required by
        # the CLI's file-extension guard.
        with tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".furqan",
            prefix="tryfurqan_",
            dir="/tmp",
            delete=False,
            encoding="utf-8",
        ) as f:
            f.write(source)
            tmp_path = Path(f.name)

        proc = subprocess.run(
            [sys.executable, "-m", "furqan", "check", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT_S,
            # Empty env keeps the subprocess from inheriting anything
            # surprising. PATH is reset minimally; PYTHONPATH and
            # virtualenv resolution flow through sys.executable.
            env={
                "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                "PYTHONUNBUFFERED": "1",
            },
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "internal_error",
            "verdict_label": "TIMEOUT",
            "error": f"check exceeded {_CHECK_TIMEOUT_S:.0f}s wall-clock limit",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except Exception as e:  # pragma: no cover - defensive
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": f"{type(e).__name__}: {e}",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink()
            except OSError:
                pass

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    verdict, label = _classify_verdict(proc.returncode, proc.stdout)

    # Strip the tmp path from output so the response is portable and
    # does not leak the per-request filename.
    stdout = proc.stdout.replace(str(tmp_path), "<source>") if tmp_path else proc.stdout
    stderr = proc.stderr.replace(str(tmp_path), "<source>") if tmp_path else proc.stderr

    return {
        "verdict": verdict,
        "verdict_label": label,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_ms": elapsed_ms,
        "furqan_version": _FURQAN_VERSION,
    }


@app.post("/demo/check")
def demo_check(req: CheckRequest) -> JSONResponse:
    """Run the Furqan checker on user-submitted source.

    Always returns 200 with a JSON envelope. The caller inspects the
    "verdict" field and renders the appropriate panel.
    """
    result = _run_check(req.source)
    return JSONResponse(content=result)
