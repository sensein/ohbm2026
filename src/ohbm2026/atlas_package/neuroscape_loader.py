"""NeuroScape v1.0.1 release loader.

Spec: ``specs/015-neuroscape-context/`` — research R-001 + data-model
``NeuroScapeArticle`` / ``NeuroScapeCluster`` + research R-009
(``NeuroScapeInputError``).

This module extends the discovery conventions of
``scripts/derive_neuroscape_centroids.py`` into a callable surface
the Stage-15 orchestrator can drive at build time. The loader is
build-time-internal — it reads the on-disk release once per
orchestrator run and never feeds the browser bundle. Per the
2026-05-23 user clarification, only locally rendered fields (pmid,
title, year, cluster id, UMAP coords, neighbours) are passed onward
to ``neuroscape.parquet``; authors / journal / abstract text / DOI
stay in the source release and are fetched at view time by the
SvelteKit ``/neuroscape/abstract/<id>/`` page via NCBI E-utilities
(R-015).

Public surface:

- :func:`discover_inputs` — sweep the release root, resolve CSV /
  HDF5 / model-checkpoint paths, compute SHAs, return an
  :class:`InputBundle`. Raises :class:`NeuroScapeInputError` with
  structured kwargs on any missing input.
- :func:`iter_stage2_vectors` — yield ``(pmid, vector)`` pairs by
  walking the discovered HDF5 shards. Vectors are 64-dim float32 and
  are unit-norm in the upstream release.
- :func:`load_clusters` — return one :class:`NeuroScapeCluster` per
  top-level cluster id that appears in the articles CSV (filters out
  sub-cluster rows the upstream release mixes into the same CSV).
- :func:`iter_articles` — yield :class:`ArticleHeader` records
  carrying only the locally-stored fields (pmid, title, year,
  cluster_id). Body fields are deliberately omitted; see the
  clarification cited above.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator

import h5py
import numpy as np

from ohbm2026.exceptions import NeuroScapeInputError

__all__ = [
    "InputBundle",
    "NeuroScapeCluster",
    "ArticleHeader",
    "discover_inputs",
    "iter_stage2_vectors",
    "iter_articles",
    "load_clusters",
]


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InputBundle:
    """A discovered NeuroScape v1.0.1 release on disk.

    All paths are absolute. SHA-256 digests are computed at discovery
    time so the orchestrator can record them in provenance (CA-008)
    and surface drift as :class:`NeuroScapeInputError` on a later
    rerun.
    """

    root: Path
    articles_csv: Path
    clusters_csv: Path
    hdf5_shards: tuple[Path, ...]
    model_checkpoint: Path
    articles_csv_sha256: str
    clusters_csv_sha256: str
    hdf5_shard_manifest_sha256: str
    model_checkpoint_sha256: str


@dataclass(frozen=True)
class NeuroScapeCluster:
    """A top-level NeuroScape cluster, as it lands in
    ``neuroscape.parquet`` / ``atlas.parquet`` after palette assignment."""

    cluster_id: int
    title: str
    description: str
    keywords: tuple[str, ...]
    focus: str


@dataclass(frozen=True)
class ArticleHeader:
    """Locally-stored fields per article (the parquet's ``articles``
    inner table). Body fields (authors, journal, abstract text, DOI)
    are NOT exposed here per the 2026-05-23 clarification — they are
    fetched at view time by the SvelteKit subsite via NCBI EFetch."""

    pubmed_id: int
    title: str
    year: int
    cluster_id: int


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def _sha256_of_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_one(
    root: Path,
    pattern: str,
    label: str,
) -> Path:
    """Resolve a unique path matching *pattern* under *root*, or raise.

    Mirrors the discover-at-runtime convention in
    ``scripts/derive_neuroscape_centroids.py`` (CA-007 — never
    hardcode release-relative paths beyond the glob).
    """

    matches = sorted(root.rglob(pattern))
    if not matches:
        raise NeuroScapeInputError(
            f"Could not find {label} under {root} (pattern {pattern!r})",
            file=label,
            expected=pattern,
            actual="<not found>",
        )
    # Multiple matches → take the lexicographically latest so a
    # release containing an older snapshot under e.g. `archive/`
    # doesn't override a current file.
    return matches[-1]


def discover_inputs(root: Path) -> InputBundle:
    """Discover and SHA-check the four input artefacts under *root*."""

    root = Path(root)
    if not root.exists() or not root.is_dir():
        raise NeuroScapeInputError(
            f"NeuroScape release root {root!r} does not exist or is not a directory",
            file=str(root),
            expected="<existing directory>",
            actual="<missing>",
        )

    articles_csv = _resolve_one(root, "neuroscience_articles_*.csv", "articles_csv")
    clusters_csv = _resolve_one(root, "neuroscience_clusters_*.csv", "clusters_csv")
    model_checkpoint = _resolve_one(root, "domain_embedding_model.pth", "domain_embedding_model.pth")

    # HDF5 shards: restrict to DomainEmbeddings/ so VoyageAIEmbeddings
    # shards (also *.h5) are not mistakenly read as Stage-2 vectors.
    hdf5_shards = tuple(sorted(root.rglob("DomainEmbeddings/*.h5")))
    if not hdf5_shards:
        raise NeuroScapeInputError(
            f"No HDF5 shards under {root}/**/DomainEmbeddings/",
            file="hdf5_domain_embeddings",
            expected="DomainEmbeddings/*.h5",
            actual="<not found>",
        )

    articles_sha = _sha256_of_path(articles_csv)
    clusters_sha = _sha256_of_path(clusters_csv)
    model_sha = _sha256_of_path(model_checkpoint)

    # Per-shard digests rolled into a single manifest sha so an
    # operator can detect drift in any shard with one comparison.
    per_shard: list[tuple[str, str]] = [
        (p.name, _sha256_of_path(p)) for p in hdf5_shards
    ]
    manifest_sha = hashlib.sha256(
        b"".join(f"{n}:{s}\n".encode() for n, s in per_shard)
    ).hexdigest()

    return InputBundle(
        root=root,
        articles_csv=articles_csv,
        clusters_csv=clusters_csv,
        hdf5_shards=hdf5_shards,
        model_checkpoint=model_checkpoint,
        articles_csv_sha256=articles_sha,
        clusters_csv_sha256=clusters_sha,
        hdf5_shard_manifest_sha256=manifest_sha,
        model_checkpoint_sha256=model_sha,
    )


# ---------------------------------------------------------------------------
# Vector iteration
# ---------------------------------------------------------------------------


def _decode_scalar(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if isinstance(value, np.bytes_):
        return value.decode("utf-8")
    return str(value)


def iter_stage2_vectors(bundle: InputBundle) -> Iterator[tuple[int, np.ndarray]]:
    """Yield ``(pmid, vector)`` for every article in the release.

    Vectors are float32 64-dim. The upstream Stage-2 model produces
    unit-norm vectors; this loader preserves them as-is (no
    re-normalisation) so a downstream UMAP fit with ``metric='cosine'``
    behaves as documented.
    """

    for shard in bundle.hdf5_shards:
        with h5py.File(shard, "r") as fh:
            if "embeddings" not in fh or "pmid" not in fh:
                raise NeuroScapeInputError(
                    f"{shard.name}: expected 'embeddings' group + 'pmid' dataset",
                    file=str(shard),
                    expected="embeddings/* group + pmid dataset",
                    actual=f"keys={sorted(fh.keys())!r}",
                )
            pmids = np.asarray(fh["pmid"][()], dtype=np.int64)
            embeddings = fh["embeddings"]
            keys = sorted(
                embeddings.keys(),
                key=lambda k: int(k) if str(k).isdigit() else str(k),
            )
            if len(pmids) != len(keys):
                raise NeuroScapeInputError(
                    f"{shard.name}: pmid count {len(pmids)} != embeddings count {len(keys)}",
                    file=str(shard),
                    expected=str(len(pmids)),
                    actual=str(len(keys)),
                )
            for index, key in enumerate(keys):
                vec = np.asarray(embeddings[key][()], dtype=np.float32)
                if vec.shape != (64,):
                    raise NeuroScapeInputError(
                        f"{shard.name}: embedding {key} has shape {vec.shape}",
                        file=str(shard),
                        expected="(64,)",
                        actual=str(vec.shape),
                    )
                yield int(pmids[index]), vec


# ---------------------------------------------------------------------------
# Article headers (local-only fields)
# ---------------------------------------------------------------------------


def _articles_csv_rows(bundle: InputBundle) -> Iterable[dict[str, str]]:
    with bundle.articles_csv.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            yield row


def iter_articles(bundle: InputBundle) -> Iterator[ArticleHeader]:
    """Yield :class:`ArticleHeader` per row of the articles CSV.

    Skips rows whose ``Year`` is outside [1999, 2023] or whose
    ``Cluster ID`` is missing — both Edge Cases from spec 015. The
    orchestrator counts the omissions and records them in provenance.
    """

    for row in _articles_csv_rows(bundle):
        pmid_raw = row.get("Pmid") or row.get("pmid") or ""
        year_raw = row.get("Year") or ""
        cluster_raw = row.get("Cluster ID") or ""
        title = row.get("Title") or ""
        if not pmid_raw or not year_raw or not cluster_raw:
            continue
        try:
            pmid = int(pmid_raw)
            year = int(year_raw)
            cluster_id = int(cluster_raw)
        except ValueError:
            continue
        if year < 1999 or year > 2023:
            continue
        yield ArticleHeader(
            pubmed_id=pmid,
            title=title,
            year=year,
            cluster_id=cluster_id,
        )


# ---------------------------------------------------------------------------
# Cluster table
# ---------------------------------------------------------------------------


def _parse_keywords(raw: str) -> tuple[str, ...]:
    """Decode the upstream JSON-encoded ``Keywords`` cell into a tuple.

    The CSV stores keywords as ``["k1", "k2", "k3"]``. Falls back to a
    semicolon split if the cell is not valid JSON (some upstream rows
    use plain ``k1; k2; k3``).
    """

    if not raw:
        return ()
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return tuple(s.strip() for s in raw.split(";") if s.strip())
    if isinstance(parsed, list):
        return tuple(str(s) for s in parsed)
    return (str(parsed),)


def load_clusters(bundle: InputBundle) -> list[NeuroScapeCluster]:
    """Load every top-level cluster referenced by the articles CSV.

    The upstream clusters CSV mixes top-level clusters (those actually
    used to tag articles) with sub-clusters / hierarchical entries.
    The Stage-15 orchestrator only persists clusters that are
    referenced by at least one article — both to keep the cluster
    table small and to ensure ``neuroscape.parquet/clusters`` is
    row-for-row equal to ``atlas.parquet/clusters`` (R-003 +
    ``CrossParquetDriftError`` invariant).
    """

    # Collect the set of cluster ids actually used by the articles CSV.
    referenced_ids: set[int] = set()
    for row in _articles_csv_rows(bundle):
        cid_raw = row.get("Cluster ID") or ""
        if not cid_raw:
            continue
        try:
            referenced_ids.add(int(cid_raw))
        except ValueError:
            continue

    out: list[NeuroScapeCluster] = []
    with bundle.clusters_csv.open("r", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cid_raw = row.get("Cluster ID") or ""
            try:
                cid = int(cid_raw)
            except ValueError:
                continue
            if cid not in referenced_ids:
                continue
            out.append(
                NeuroScapeCluster(
                    cluster_id=cid,
                    title=row.get("Title") or "",
                    description=row.get("Description") or "",
                    keywords=_parse_keywords(row.get("Keywords") or ""),
                    focus=row.get("Focus") or "",
                )
            )
    # Sorting by cluster_id keeps the row order deterministic across
    # rebuilds — feeds the byte-identity invariant for the parquets.
    out.sort(key=lambda c: c.cluster_id)
    return out
