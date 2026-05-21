"""Stage 11.1 — per-abstract PDF cache.

Key derivation per `research.md § R1`:
    sha256(md_body || pandoc_version || engine_version ||
           header_includes_hash || style)
truncated to 16 hex chars.

The cache is keyed by content + toolchain so an upstream pandoc /
Tectonic / header-template change invalidates every entry without
operator intervention (CA-007: no hardcoded version allow-list).

Storage layout under `cache_dir`:

    <key>.pdf            # the pre-rendered chunk bytes
    <key>.json           # sidecar: {page_count}

Writes use the `temp + os.replace` pattern so concurrent joblib
workers never observe a half-written `<key>.pdf`. The sidecar lets a
cache-hit path return without re-opening the PDF (saving a pikepdf
load in the warm-cache codepath).
"""

from __future__ import annotations

import hashlib
import json
import os
import pathlib
import shutil
import tempfile


_CACHE_KEY_LEN = 16


def compute_cache_key(
    *,
    md_body: str,
    pandoc_version: str,
    engine_version: str,
    header_includes_hash: str,
    style: str,
) -> str:
    """Return the 16-hex content+toolchain digest for a single abstract.

    Stable across calls with identical inputs; changes whenever ANY
    input changes (T006 verifies all five sensitivities).
    """

    h = hashlib.sha256()
    for part in (
        md_body,
        pandoc_version,
        engine_version,
        header_includes_hash,
        style,
    ):
        h.update(b"\x00")  # field separator so concat collisions can't trip us
        h.update(part.encode("utf-8"))
    return h.hexdigest()[:_CACHE_KEY_LEN]


def hash_header_includes(path: pathlib.Path) -> str:
    """Return a stable 16-hex digest of a header-includes .tex file's bytes.

    Used as the `header_includes_hash` input to `compute_cache_key`.
    Pure read; no I/O outside the named path.
    """

    h = hashlib.sha256(path.read_bytes())
    return h.hexdigest()[:_CACHE_KEY_LEN]


def cache_pdf_path(cache_dir: pathlib.Path, key: str) -> pathlib.Path:
    return cache_dir / f"{key}.pdf"


def cache_sidecar_path(cache_dir: pathlib.Path, key: str) -> pathlib.Path:
    return cache_dir / f"{key}.json"


def load_cached_pdf(
    cache_dir: pathlib.Path,
    key: str,
) -> tuple[bytes, dict] | None:
    """Return `(pdf_bytes, sidecar_dict)` on hit; None on miss.

    A hit requires BOTH the PDF and the sidecar to exist; a stale
    half-write (one without the other) is treated as a miss so the
    next render rebuilds the entry cleanly.
    """

    pdf = cache_pdf_path(cache_dir, key)
    side = cache_sidecar_path(cache_dir, key)
    if not (pdf.exists() and side.exists()):
        return None
    try:
        sidecar = json.loads(side.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return pdf.read_bytes(), sidecar


def store_cached_pdf(
    cache_dir: pathlib.Path,
    key: str,
    pdf_bytes: bytes,
    *,
    page_count: int,
) -> pathlib.Path:
    """Atomically persist a rendered chunk + its sidecar.

    Returns the final `<key>.pdf` path. Both files land via temp +
    os.replace so a concurrent reader never sees a partial write
    (POSIX guarantees rename atomicity on the same filesystem).

    Prefer :func:`store_cached_pdf_from_path` when the caller has
    already written the PDF bytes to disk — it avoids the
    read-bytes → write-temp → rename round-trip and is the hot path
    used by ``render_per_abstract.render_one``.
    """

    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_final = cache_pdf_path(cache_dir, key)

    pdf_tmp = _atomic_temp_path(pdf_final)
    try:
        pdf_tmp.write_bytes(pdf_bytes)
        _commit_chunk(pdf_tmp, pdf_final, cache_dir, key, page_count)
    finally:
        if pdf_tmp.exists():
            try:
                pdf_tmp.unlink()
            except OSError:
                pass
    return pdf_final


def store_cached_pdf_from_path(
    cache_dir: pathlib.Path,
    key: str,
    src_pdf: pathlib.Path,
    *,
    page_count: int,
) -> pathlib.Path:
    """Atomically move an already-written PDF into the cache + write sidecar.

    Used by ``render_per_abstract.render_one`` to avoid the
    read-then-write-back cycle: pandoc writes to a temp path inside
    ``cache_dir`` (same filesystem, so ``os.replace`` is atomic),
    pikepdf measures pages, then this helper moves the temp to its
    final ``<key>.pdf`` location and writes the sidecar.

    ``src_pdf`` is consumed — caller MUST NOT touch the path after
    this returns. If ``src_pdf`` is on a different filesystem than
    ``cache_dir``, falls back to a copy + unlink (rare; same-fs is
    the documented contract).
    """

    cache_dir.mkdir(parents=True, exist_ok=True)
    pdf_final = cache_pdf_path(cache_dir, key)
    _commit_chunk(src_pdf, pdf_final, cache_dir, key, page_count)
    return pdf_final


def _commit_chunk(
    src_pdf: pathlib.Path,
    pdf_final: pathlib.Path,
    cache_dir: pathlib.Path,
    key: str,
    page_count: int,
) -> None:
    """Move ``src_pdf`` to its final ``<key>.pdf`` location + write sidecar.

    Order: sidecar first (cheap), then PDF rename. If the rename
    fails the sidecar gets orphaned — ``load_cached_pdf`` checks for
    both, so an orphan is treated as a miss and the next render
    cleans it up.
    """

    side_final = cache_sidecar_path(cache_dir, key)
    side_tmp = _atomic_temp_path(side_final)
    sidecar_payload = {"page_count": int(page_count)}
    try:
        side_tmp.write_text(
            json.dumps(sidecar_payload, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(side_tmp, side_final)
    finally:
        if side_tmp.exists():
            try:
                side_tmp.unlink()
            except OSError:
                pass
    try:
        os.replace(src_pdf, pdf_final)
    except OSError:
        # Cross-filesystem fallback: copy + unlink.
        shutil.copy2(src_pdf, pdf_final)
        try:
            src_pdf.unlink()
        except OSError:
            pass


def _atomic_temp_path(final: pathlib.Path) -> pathlib.Path:
    """Return a sibling temp path for atomic-replace into `final`.

    Uses `tempfile.mkstemp` (vs a plain `.tmp` suffix) so concurrent
    workers writing to the SAME cache key don't collide on the temp
    filename. The temp file is closed immediately — we only need the
    unique path; the actual write happens in the caller.
    """

    final.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(
        prefix=f"{final.name}.",
        suffix=".tmp",
        dir=str(final.parent),
    )
    os.close(fd)
    return pathlib.Path(name)
