"""State-key discovery for Stage 6 builds (T011a).

Per CA-007 the UI data-package build MUST NOT hardcode state-keys. This module
discovers them at build time from the canonical artifact locations.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ohbm2026.exceptions import Stage6Error


class Stage6BuildError(Stage6Error):
    """Raised when the Stage 6 builder cannot resolve a required input."""


_ROLLUP_RE = re.compile(r"^annotations__([0-9a-f]{8,16})\.sqlite$")
_MINILM_RE = re.compile(r"^([a-z_]+)__([0-9a-f]{8,16})$")


def discover_corpus_state_key(corpus_path: Path) -> str:
    """Return the canonical state-key for the corpus at *corpus_path*.

    If the corpus JSON carries a ``meta.state_key`` field it is used verbatim.
    Otherwise the state-key is derived as the first 12 chars of the SHA-256 of
    the corpus bytes — stable across rebuilds for unchanged corpora.
    """

    corpus_path = Path(corpus_path)
    with corpus_path.open("rb") as fh:
        raw = fh.read()
    # Fast peek for a meta.state_key
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise Stage6BuildError(
            f"Cannot decode corpus JSON at {corpus_path}: {exc}"
        ) from exc
    meta = data.get("meta") if isinstance(data, dict) else None
    if isinstance(meta, dict) and isinstance(meta.get("state_key"), str):
        return str(meta["state_key"])
    digest = hashlib.sha256(raw).hexdigest()
    return digest[:12]


def discover_rollup_state_key(analysis_root: Path) -> str:
    """Return the active Stage 4 rollup state-key under *analysis_root*.

    Globs ``annotations__*.sqlite`` and picks the most recent by mtime.
    Raises :class:`Stage6BuildError` when zero matches are found OR when
    multiple matches exist and the operator hasn't disambiguated (forcing
    explicit selection in production builds).
    """

    analysis_root = Path(analysis_root)
    if not analysis_root.exists():
        raise Stage6BuildError(
            f"Analysis root does not exist: {analysis_root}"
        )
    candidates: list[tuple[float, str, Path]] = []
    for path in analysis_root.glob("annotations__*.sqlite"):
        match = _ROLLUP_RE.match(path.name)
        if not match:
            continue
        candidates.append((path.stat().st_mtime, match.group(1), path))
    if not candidates:
        raise Stage6BuildError(
            f"No annotations__*.sqlite rollups found under {analysis_root}; "
            "run Stage 4 (`ohbmcli analyze-matrix`) first."
        )
    if len(candidates) > 1:
        names = ", ".join(sorted({c[1] for c in candidates}))
        raise Stage6BuildError(
            f"Multiple Stage 4 rollups under {analysis_root}: {names}. "
            "Pass --rollup explicitly to disambiguate."
        )
    return candidates[0][1]


def discover_minilm_bundle(
    embeddings_root: Path, component: str = "introduction"
) -> Path:
    """Return the path to the MiniLM embedding bundle for *component*.

    Used by the deploy workflow to locate the int8-quantizable vectors for
    semantic search (FR-007 / SC-006). The bundle directory name encodes
    ``<component>__<state-key>``; we pick the most recent match.
    """

    embeddings_root = Path(embeddings_root)
    if not embeddings_root.exists():
        raise Stage6BuildError(
            f"MiniLM embeddings root does not exist: {embeddings_root}"
        )
    candidates: list[tuple[float, Path]] = []
    for path in embeddings_root.iterdir():
        if not path.is_dir():
            continue
        match = _MINILM_RE.match(path.name)
        if not match:
            continue
        if match.group(1) != component:
            continue
        candidates.append((path.stat().st_mtime, path))
    if not candidates:
        raise Stage6BuildError(
            f"No MiniLM bundle for component={component!r} under {embeddings_root}; "
            "expected a directory named `<component>__<state-key>`."
        )
    candidates.sort(reverse=True)
    return candidates[0][1]


def main() -> int:
    """CLI entry — print a discovered path on stdout for shell substitution.

    Usage:
        python -m ohbm2026.ui_data.state_key rollup data/outputs/analysis
        python -m ohbm2026.ui_data.state_key minilm data/outputs/embeddings/minilm introduction
        python -m ohbm2026.ui_data.state_key corpus data/primary/abstracts.json
    """

    import sys

    args = sys.argv[1:]
    if len(args) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    kind, path = args[0], Path(args[1])
    try:
        if kind == "rollup":
            print(discover_rollup_state_key(path))
        elif kind == "minilm":
            component = args[2] if len(args) >= 3 else "introduction"
            print(str(discover_minilm_bundle(path, component=component)))
        elif kind == "corpus":
            print(discover_corpus_state_key(path))
        else:
            print(f"unknown kind: {kind}", file=sys.stderr)
            return 2
    except Stage6BuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
