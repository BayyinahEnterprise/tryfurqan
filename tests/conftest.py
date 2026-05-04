"""Pytest config: make the repo root importable so `import api`/`import playground`
works without installing the site as a package.

This mirrors how Railway runs the app: `uvicorn api:app` from the repo root.
"""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
