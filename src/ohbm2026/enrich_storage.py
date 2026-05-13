"""SQLite + zlib storage helper for Stage 2 enriched corpus.

Module body in this commit is intentionally just the version
constants — the I/O surface (``EnrichedCorpusWriter`` context manager,
``read_one_by_id``, ``iter_enriched``, ``corpus_metadata``) lands in
T014 alongside the red-phase tests that drive its contract.
"""

from __future__ import annotations

__all__ = ["STORAGE_VERSION", "CACHE_VERSION", "PROVENANCE_VERSION"]

STORAGE_VERSION = "enrich.storage.v1"
CACHE_VERSION = "enrich.cache.v1"
PROVENANCE_VERSION = "enrich.provenance.v1"
