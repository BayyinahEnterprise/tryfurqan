"""tryfurqan playground: live furqan-lint sandbox for Python, Rust, Go.

Three surfaces:

  POST /playground/check  Single-file `furqan-lint check` invocation.
  POST /playground/diff   Paired old/new `furqan-lint diff` invocation.
  POST /playground/share  Persist a snapshot, return a 12-char share id.
  GET  /s/{share_id}      Resolve a share id back to its snapshot JSON.

Sandbox discipline (mirrors api.py /demo/check):

  * Source caps: 100 KiB per file (one per check, two per diff).
  * Per-request tmp file under /tmp with the language's expected suffix.
  * Subprocess invocation of `furqan-lint` (the bundled CLI) with a
    5 s wall-clock timeout and a stripped environment.
  * Exit code -> verdict tag: 0 PASS / 1 MARAD / 2 PARSE ERROR /
    other INTERNAL ERROR. ADVISORY is reserved for future use; the
    current furqan-lint never emits it.
  * tmp file is unlinked in finally; absolute paths in stdout/stderr
    are rewritten to <source> / <old> / <new> so responses are
    portable.

Share storage:

  * SQLite at /tmp/tryfurqan_shares.db (ephemeral on Railway; that is
    intentional - shares are best-effort short-lived links, not a
    durable store).
  * Schema: share(id TEXT PRIMARY KEY, payload TEXT NOT NULL,
                  created_at INTEGER NOT NULL).
  * Payload is the raw JSON the client posted, validated against
    SharePayload.
  * TTL: 30 days. A lazy sweep on every write deletes expired rows.
  * id: 12 chars, urlsafe base64 of os.urandom(9). Collision-resilient
    (~52 bits of entropy); on the rare collision we retry up to 4x.

The router is wired into api.py via `app.include_router(playground_router)`.
"""
from __future__ import annotations

import base64
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MAX_SOURCE_BYTES = 100 * 1024  # 100 KiB per the v1.0 plan §4.4
_CHECK_TIMEOUT_S = 5.0
_SHARE_TTL_S = 30 * 24 * 60 * 60  # 30 days
_SHARE_DB_PATH = Path(os.environ.get("TRYFURQAN_SHARE_DB", "/tmp/tryfurqan_shares.db"))
_SHARE_ID_LEN = 12

# Language -> file suffix used by furqan-lint to dispatch the right adapter.
# furqan-lint guards on the suffix; using the wrong one will either parse-error
# or be rejected outright, so we keep this mapping authoritative.
_LANG_SUFFIX: dict[str, str] = {
    "python": ".py",
    "rust": ".rs",
    "go": ".go",
}

Language = Literal["python", "rust", "go"]

# CLI to invoke. We use the installed entry point (`furqan-lint`) so the
# wheel's [go] build hook (which writes goast into the package) works.
# `python -m furqan_lint` would also work; the entry-point form is what
# users will type in their own terminals, so it is what we exercise here.
_FURQAN_LINT_BIN = "furqan-lint"


# ---------------------------------------------------------------------------
# Verdict classification
# ---------------------------------------------------------------------------

def _classify(exit_code: int, stdout: str) -> tuple[str, str]:
    """Map (exit_code, stdout) to (verdict_tag, verdict_label).

    Mirrors the CLI contract documented in furqan_lint/__main__.py.
    """
    if exit_code == 0:
        if "ADVISORY" in stdout:
            return "advisory", "ADVISORY"
        return "pass", "PASS"
    if exit_code == 1:
        return "marad", "MARAD"
    if exit_code == 2:
        return "parse_error", "PARSE ERROR"
    return "internal_error", "INTERNAL ERROR"


# ---------------------------------------------------------------------------
# Subprocess invocation primitives
# ---------------------------------------------------------------------------

def _too_large(source: str) -> dict[str, Any] | None:
    """Return an error envelope if source exceeds the cap, else None."""
    encoded_len = len(source.encode("utf-8"))
    if encoded_len > _MAX_SOURCE_BYTES:
        return {
            "verdict": "internal_error",
            "verdict_label": "INPUT TOO LARGE",
            "error": (
                f"source exceeds {_MAX_SOURCE_BYTES} bytes "
                f"({encoded_len} bytes submitted)"
            ),
        }
    return None


def _write_tmp(source: str, suffix: str) -> Path:
    """Write `source` to a per-request tmp file with the given suffix.

    Caller is responsible for unlinking; we use delete=False so the
    subprocess can read it after the with-block closes.
    """
    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=suffix,
        prefix="tryfurqan_pg_",
        dir="/tmp",
        delete=False,
        encoding="utf-8",
    ) as f:
        f.write(source)
        return Path(f.name)


def _strip_paths(text: str, *replacements: tuple[Path, str]) -> str:
    """Replace each (path, label) pair in text. Used to scrub tmp paths."""
    for path, label in replacements:
        text = text.replace(str(path), label)
    return text


def _subproc_env() -> dict[str, str]:
    """Minimal environment for the furqan-lint subprocess.

    PATH is preserved (so we find the entry-point shim and, in deploy,
    the Go toolchain if any runtime path needed it). PYTHONUNBUFFERED
    keeps stderr coherent. Nothing else leaks through.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "PYTHONUNBUFFERED": "1",
    }


def _run_check(source: str, language: Language) -> dict[str, Any]:
    """Run `furqan-lint check <tmp>` on `source`. Always returns dict."""
    if not isinstance(source, str):
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": "source must be a string",
        }
    err = _too_large(source)
    if err is not None:
        return err
    suffix = _LANG_SUFFIX.get(language)
    if suffix is None:
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": f"unsupported language: {language!r}",
        }

    started = time.perf_counter()
    tmp_path: Path | None = None
    try:
        tmp_path = _write_tmp(source, suffix)
        proc = subprocess.run(
            [_FURQAN_LINT_BIN, "check", str(tmp_path)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT_S,
            env=_subproc_env(),
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "internal_error",
            "verdict_label": "TIMEOUT",
            "error": f"check exceeded {_CHECK_TIMEOUT_S:.0f}s wall-clock limit",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except FileNotFoundError:
        # furqan-lint not on PATH. Surface a clean error rather than 500.
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": "furqan-lint binary not found on PATH",
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
    verdict, label = _classify(proc.returncode, proc.stdout)
    stdout = _strip_paths(proc.stdout, (tmp_path, "<source>")) if tmp_path else proc.stdout
    stderr = _strip_paths(proc.stderr, (tmp_path, "<source>")) if tmp_path else proc.stderr
    return {
        "verdict": verdict,
        "verdict_label": label,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_ms": elapsed_ms,
        "language": language,
    }


def _run_diff(old_source: str, new_source: str, language: Language) -> dict[str, Any]:
    """Run `furqan-lint diff <old_tmp> <new_tmp>`. Always returns dict."""
    if not isinstance(old_source, str) or not isinstance(new_source, str):
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": "old_source and new_source must be strings",
        }
    for s, name in ((old_source, "old"), (new_source, "new")):
        err = _too_large(s)
        if err is not None:
            err["error"] = err["error"].replace("source exceeds", f"{name}_source exceeds")
            return err
    suffix = _LANG_SUFFIX.get(language)
    if suffix is None:
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": f"unsupported language: {language!r}",
        }

    started = time.perf_counter()
    old_path: Path | None = None
    new_path: Path | None = None
    try:
        old_path = _write_tmp(old_source, suffix)
        new_path = _write_tmp(new_source, suffix)
        proc = subprocess.run(
            [_FURQAN_LINT_BIN, "diff", str(old_path), str(new_path)],
            capture_output=True,
            text=True,
            timeout=_CHECK_TIMEOUT_S,
            env=_subproc_env(),
        )
    except subprocess.TimeoutExpired:
        return {
            "verdict": "internal_error",
            "verdict_label": "TIMEOUT",
            "error": f"diff exceeded {_CHECK_TIMEOUT_S:.0f}s wall-clock limit",
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
        }
    except FileNotFoundError:
        return {
            "verdict": "internal_error",
            "verdict_label": "INTERNAL ERROR",
            "error": "furqan-lint binary not found on PATH",
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
        for p in (old_path, new_path):
            if p is not None:
                try:
                    p.unlink()
                except OSError:
                    pass

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    verdict, label = _classify(proc.returncode, proc.stdout)
    repls: list[tuple[Path, str]] = []
    if old_path is not None:
        repls.append((old_path, "<old>"))
    if new_path is not None:
        repls.append((new_path, "<new>"))
    stdout = _strip_paths(proc.stdout, *repls)
    stderr = _strip_paths(proc.stderr, *repls)
    return {
        "verdict": verdict,
        "verdict_label": label,
        "exit_code": proc.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_ms": elapsed_ms,
        "language": language,
        "mode": "diff",
    }


# ---------------------------------------------------------------------------
# Share storage (SQLite)
# ---------------------------------------------------------------------------

_db_lock = threading.Lock()


def _share_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_SHARE_DB_PATH))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS share (
            id         TEXT PRIMARY KEY,
            payload    TEXT NOT NULL,
            created_at INTEGER NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS share_created_at_idx ON share(created_at)"
    )
    return conn


def _gen_share_id() -> str:
    raw = os.urandom(9)
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")[:_SHARE_ID_LEN]


def _sweep_expired(conn: sqlite3.Connection, *, now: int) -> None:
    cutoff = now - _SHARE_TTL_S
    conn.execute("DELETE FROM share WHERE created_at < ?", (cutoff,))


def _put_share(payload: dict[str, Any]) -> str:
    """Insert a share record and return the id. Sweeps expired rows."""
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if len(blob.encode("utf-8")) > _MAX_SOURCE_BYTES * 3:
        # Defensive cap; one share holds at most three sources (old/new
        # for diff plus a pasted snippet).
        raise HTTPException(status_code=413, detail="share payload too large")
    now = int(time.time())
    with _db_lock:
        conn = _share_conn()
        try:
            _sweep_expired(conn, now=now)
            for _ in range(4):
                share_id = _gen_share_id()
                try:
                    conn.execute(
                        "INSERT INTO share (id, payload, created_at) VALUES (?, ?, ?)",
                        (share_id, blob, now),
                    )
                    conn.commit()
                    return share_id
                except sqlite3.IntegrityError:
                    continue
            raise HTTPException(
                status_code=503, detail="could not allocate a unique share id"
            )
        finally:
            conn.close()


def _get_share(share_id: str) -> dict[str, Any] | None:
    """Return the share payload dict, or None if missing/expired."""
    if not _is_valid_share_id(share_id):
        return None
    now = int(time.time())
    with _db_lock:
        conn = _share_conn()
        try:
            _sweep_expired(conn, now=now)
            row = conn.execute(
                "SELECT payload, created_at FROM share WHERE id = ?",
                (share_id,),
            ).fetchone()
            if row is None:
                return None
            blob, _created_at = row
            try:
                return json.loads(blob)
            except json.JSONDecodeError:
                return None
        finally:
            conn.close()


_SHARE_ID_ALPHABET = set(
    "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
)


def _is_valid_share_id(s: str) -> bool:
    if not isinstance(s, str):
        return False
    if len(s) != _SHARE_ID_LEN:
        return False
    return all(c in _SHARE_ID_ALPHABET for c in s)


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------

class CheckRequest(BaseModel):
    language: Language = Field(..., description="One of python, rust, go.")
    source: str = Field(..., description="Source code as a UTF-8 string.")

    @field_validator("source")
    @classmethod
    def _source_nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("source must be non-empty")
        return v


class DiffRequest(BaseModel):
    language: Language
    old_source: str
    new_source: str

    @field_validator("old_source", "new_source")
    @classmethod
    def _nonempty(cls, v: str) -> str:
        if not v:
            raise ValueError("old_source and new_source must be non-empty")
        return v


class SharePayload(BaseModel):
    """Snapshot of the playground's UI state at share time.

    Stored verbatim and replayed on the client by /s/{id}. The server
    does not interpret the contents beyond the schema check; the
    client is responsible for rendering.
    """
    mode: Literal["check", "diff"]
    language: Language
    source: str | None = None
    old_source: str | None = None
    new_source: str | None = None

    @field_validator("source", "old_source", "new_source")
    @classmethod
    def _bounded(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if len(v.encode("utf-8")) > _MAX_SOURCE_BYTES:
            raise ValueError(
                f"field exceeds {_MAX_SOURCE_BYTES} bytes "
                f"({len(v.encode('utf-8'))} submitted)"
            )
        return v


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

playground_router = APIRouter()


@playground_router.post("/playground/check")
def playground_check(req: CheckRequest) -> JSONResponse:
    return JSONResponse(content=_run_check(req.source, req.language))


@playground_router.post("/playground/diff")
def playground_diff(req: DiffRequest) -> JSONResponse:
    return JSONResponse(content=_run_diff(req.old_source, req.new_source, req.language))


@playground_router.post("/playground/share")
def playground_share(payload: SharePayload) -> JSONResponse:
    # Cross-validate that the right fields are populated for the mode.
    if payload.mode == "check":
        if payload.source is None:
            raise HTTPException(status_code=422, detail="check mode requires source")
    else:
        if payload.old_source is None or payload.new_source is None:
            raise HTTPException(
                status_code=422,
                detail="diff mode requires old_source and new_source",
            )
    share_id = _put_share(payload.model_dump())
    return JSONResponse(content={"share_id": share_id})


@playground_router.get("/s/{share_id}")
def playground_share_resolve(share_id: str) -> JSONResponse:
    payload = _get_share(share_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="share not found or expired")
    return JSONResponse(content=payload)


# ---------------------------------------------------------------------------
# Public surface for tests
# ---------------------------------------------------------------------------

__all__ = (
    "CheckRequest",
    "DiffRequest",
    "SharePayload",
    "playground_router",
    # exposed for unit tests
    "_classify",
    "_run_check",
    "_run_diff",
    "_put_share",
    "_get_share",
    "_is_valid_share_id",
    "_MAX_SOURCE_BYTES",
    "_SHARE_TTL_S",
)
