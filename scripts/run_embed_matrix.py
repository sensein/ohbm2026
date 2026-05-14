#!/usr/bin/env python3
"""Stage 3 entry-point wrapper — generate the multi-model embeddings matrix.

Canonical invocation:

    PYTHONPATH=src .venv/bin/python scripts/run_embed_matrix.py [options]

Forwards ``sys.argv[1:]`` to ``ohbm2026.embed.stage.main`` and returns
its exit code. Mirrors ``scripts/run_enrich_abstracts.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC_DIR = _REPO_ROOT / "src"
if _SRC_DIR.exists() and str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))

from ohbm2026.embed.stage import main  # noqa: E402  (post sys.path setup)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
