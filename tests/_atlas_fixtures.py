"""Synthetic Stage 15 NeuroScape v1.0.1 release fixture builder.

Spec: ``specs/015-neuroscape-context/`` — T032.

The full NeuroScape v1.0.1 release is 5.47 GB compressed / 10 GB
unzipped (461,316 articles, 175 clusters, 2,307 HDF5 shards). Unit
tests for the Stage-15 pipeline MUST NOT load it — per the user's
2026-05-23 directive, no test loads the entire corpus until it has
been written into a Stage-15 parquet. This module produces a tiny
fixture that mirrors the real release's directory layout, CSV
columns, and HDF5 schema so the orchestrator + loader + writer can
be unit-tested in <2 s.

Fixture layout — built deterministically into the caller's *root*:

    <root>/
    └── Data/
        ├── CSV/
        │   ├── neuroscience_articles_1999-2023.csv     (6 articles)
        │   ├── neuroscience_clusters_1999-2023.csv     (3 top-level + 1 sub-cluster)
        │   └── neuroscience_dimensions_1999-2023.csv   (2 rows; unused by Stage 15)
        ├── HDF5/
        │   └── DomainEmbeddings/
        │       ├── shard_0000.h5    (3 articles, pmids 10001–10003, all cluster 0)
        │       └── shard_0001.h5    (3 articles, pmids 10004–10006, cluster 1 + cluster 2)
        └── Models/
            └── domain_embedding_model.pth   (deterministic 64-byte stub)

The 64-dim Stage-2 vectors are deterministic (seed=0, drawn from a
unit-norm gaussian) so SHA-based caching tests reproduce. The model
checkpoint stub is a fixed ASCII payload — the Stage-15 pipeline
records its SHA but never loads it (OHBM 2026 Stage-2 vectors come
from the pre-computed ``voyage_stage2_published`` recipe, not from
re-running the model).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import h5py
import numpy as np

__all__ = [
    "write_v101_fixture",
    "FIXTURE_PMIDS",
    "FIXTURE_CLUSTERS_TOP_LEVEL",
    "FIXTURE_CLUSTER_FOR_PMID",
    "MODEL_CHECKPOINT_STUB_BYTES",
]


# ---------------------------------------------------------------------------
# Fixture constants (referenced by tests for assertions)
# ---------------------------------------------------------------------------

FIXTURE_PMIDS: tuple[int, ...] = (10001, 10002, 10003, 10004, 10005, 10006)

# Top-level cluster ids that appear in the articles CSV (filtered set).
FIXTURE_CLUSTERS_TOP_LEVEL: tuple[int, ...] = (0, 1, 2)

# Cluster assignments per pmid — matches the rows below.
FIXTURE_CLUSTER_FOR_PMID: dict[int, int] = {
    10001: 0,
    10002: 0,
    10003: 0,
    10004: 1,
    10005: 1,
    10006: 2,
}

# Deterministic 64-byte model checkpoint stub. The Stage-15 pipeline
# records the SHA but never loads it as a real PyTorch state dict.
MODEL_CHECKPOINT_STUB_BYTES: bytes = (
    b"STAGE-15 SYNTHETIC FIXTURE NEUROSCAPE MODEL CHECKPOINT STUB v1\n"
)


# ---------------------------------------------------------------------------
# CSV bodies
# ---------------------------------------------------------------------------

_ARTICLES_HEADER = [
    "Pmid",
    "Doi",
    "Type",
    "Title",
    "Year",
    "Month",
    "Age",
    "Citations",
    "Citation Rate",
    "Cluster ID",
    "Journal",
    "Disciplines",
    "Abstract",
]

_ARTICLES_ROWS = [
    [
        "10001",
        "10.1234/a",
        "article",
        "Hippocampal place cells in synthetic rodent navigation",
        "2020",
        "3",
        "4",
        "10",
        "2.5",
        "0",
        "Synthetic Journal of Neuroscience",
        "Neuroscience",
        "Body text for pmid 10001; this stays in the source release only.",
    ],
    [
        "10002",
        "10.1234/b",
        "article",
        "Cortical microcircuits and place-cell remapping",
        "2021",
        "5",
        "3",
        "5",
        "1.7",
        "0",
        "Synthetic Journal of Neuroscience",
        "Neuroscience",
        "Body text for pmid 10002.",
    ],
    [
        "10003",
        "",
        "review",
        "Review: integrating hippocampal and entorhinal models",
        "2019",
        "7",
        "5",
        "20",
        "4.0",
        "0",
        "Synthetic Journal of Neuroscience",
        "Neuroscience",
        "Body text for pmid 10003. No DOI; the loader handles this gracefully.",
    ],
    [
        "10004",
        "10.1234/d",
        "article",
        "Synthetic fMRI evidence for parietal attention",
        "2022",
        "1",
        "2",
        "3",
        "1.5",
        "1",
        "Other Synthetic Journal",
        "Neuroscience",
        "Body text for pmid 10004.",
    ],
    [
        "10005",
        "10.1234/e",
        "article",
        "Attention and the synthetic visual cortex",
        "2023",
        "9",
        "1",
        "1",
        "1.0",
        "1",
        "Other Synthetic Journal",
        "Neuroscience",
        "Body text for pmid 10005.",
    ],
    [
        "10006",
        "10.1234/f",
        "review",
        "Cerebellar contributions to motor learning — a synthetic review",
        "2018",
        "11",
        "6",
        "50",
        "8.3",
        "2",
        "Third Synthetic Journal",
        "Neuroscience",
        "Body text for pmid 10006.",
    ],
]

_CLUSTERS_HEADER = [
    "Cluster ID",
    "Title",
    "Size",
    "Year First Article",
    "MCR Research",
    "MCR Review",
    "Reference Krackhardt",
    "Citation Krackhardt",
    "Most Cited Cluster",
    "Most Citing Cluster",
    "Keywords",
    "Description",
    "Focus",
    "Most Similar Cluster",
    "Similarity",
    "Distinguishing Features",
    "Open Questions",
    "Dimensions",
    "Trends",
]

# Three top-level clusters that are referenced by the articles CSV, plus
# one sub-cluster that is NOT referenced. The Stage-15 loader filters
# to the top-level set (per the real release convention).
_CLUSTERS_ROWS = [
    [
        "0",
        "Synthetic Hippocampal Memory",
        "3",
        "2019",
        "5",
        "2",
        "0.3",
        "0.5",
        "1",
        "2",
        json.dumps(["hippocampus", "memory", "place cells"]),
        "Articles on hippocampal memory and place-cell coding.",
        "Spatial memory",
        "1",
        "0.7",
        "Hippocampal anatomy + electrophysiology",
        "How do place cells remap across environments?",
        "memory; spatial",
        "stable",
    ],
    [
        "1",
        "Synthetic Attention And Cortex",
        "2",
        "2022",
        "3",
        "1",
        "0.4",
        "0.6",
        "0",
        "2",
        json.dumps(["attention", "fMRI", "parietal cortex"]),
        "Articles on attentional networks in cortex.",
        "Cortical attention",
        "0",
        "0.7",
        "fMRI-centric methodology",
        "Top-down vs bottom-up attention integration?",
        "attention; cortex",
        "rising",
    ],
    [
        "2",
        "Synthetic Cerebellar Motor Learning",
        "1",
        "2018",
        "8",
        "4",
        "0.5",
        "0.7",
        "0",
        "1",
        json.dumps(["cerebellum", "motor", "learning"]),
        "Articles on cerebellar contributions to motor learning.",
        "Motor learning",
        "0",
        "0.6",
        "Cerebellar electrophysiology",
        "Cerebellar prediction-error signals?",
        "motor; learning",
        "stable",
    ],
    [
        "175",
        "Synthetic Sub-Cluster Filtered",
        "99",
        "2020",
        "1",
        "1",
        "0.1",
        "0.1",
        "0",
        "0",
        json.dumps(["sub"]),
        "Sub-cluster that is NOT referenced by any article — the loader filters it out.",
        "subfocus",
        "0",
        "0.1",
        "sub",
        "sub",
        "sub",
        "sub",
    ],
]

_DIMENSIONS_HEADER = ["Dimension ID", "Title", "Description"]
_DIMENSIONS_ROWS = [
    ["0", "spatial", "Synthetic spatial-cognition dimension"],
    ["1", "attention", "Synthetic attention dimension"],
]


# ---------------------------------------------------------------------------
# HDF5 shard contents
# ---------------------------------------------------------------------------

def _deterministic_vector(pmid: int) -> np.ndarray:
    """Produce a deterministic 64-dim unit-norm vector for *pmid*.

    Uses a per-pmid RNG so vectors are stable across runs. Unit-norm
    so the cosine metric used by the orchestrator's UMAP fit (R-001)
    behaves like the real Stage-2 vectors.
    """

    rng = np.random.default_rng(seed=pmid)
    v = rng.standard_normal(64).astype(np.float32)
    n = float(np.linalg.norm(v))
    if n == 0.0:
        v[0] = 1.0
        return v
    return (v / n).astype(np.float32)


# Maps shard filename → list of (pmid, articles_row_idx) the shard
# contains. articles_row_idx indexes _ARTICLES_ROWS so the per-shard
# HDF5 metadata (title, abstract, journal, year, etc.) matches the
# corresponding CSV row.
_SHARDS: dict[str, list[tuple[int, int]]] = {
    "shard_0000.h5": [(10001, 0), (10002, 1), (10003, 2)],
    "shard_0001.h5": [(10004, 3), (10005, 4), (10006, 5)],
}


def _write_shard(path: Path, contents: list[tuple[int, int]]) -> None:
    """Write one HDF5 shard mirroring the real release's per-shard schema."""

    pmids = np.array([pmid for pmid, _ in contents], dtype=np.int32)
    rows = [_ARTICLES_ROWS[idx] for _, idx in contents]

    def col(name: str) -> list[str]:
        i = _ARTICLES_HEADER.index(name)
        return [r[i] for r in rows]

    titles = np.array(col("Title"), dtype=object)
    abstracts = np.array(col("Abstract"), dtype=object)
    dois = np.array(col("Doi"), dtype=object)
    journals = np.array(col("Journal"), dtype=object)
    types = np.array(col("Type"), dtype=object)
    years = np.array([int(y) for y in col("Year")], dtype=np.int32)
    ages = np.array([float(a) for a in col("Age")], dtype=np.float32)
    citation_counts = np.array([int(c) for c in col("Citations")], dtype=np.int32)
    citation_rates = np.array([float(c) for c in col("Citation Rate")], dtype=np.float32)

    str_dt = h5py.string_dtype(encoding="utf-8")
    with h5py.File(path, "w") as fh:
        fh.create_dataset("pmid", data=pmids)
        fh.create_dataset("title", data=titles.astype(str_dt))
        fh.create_dataset("abstract", data=abstracts.astype(str_dt))
        fh.create_dataset("doi", data=dois.astype(str_dt))
        fh.create_dataset("journal", data=journals.astype(str_dt))
        fh.create_dataset("type", data=types.astype(str_dt))
        fh.create_dataset("year", data=years)
        fh.create_dataset("age", data=ages)
        fh.create_dataset("citation_count", data=citation_counts)
        fh.create_dataset("citation_rate", data=citation_rates)

        emb = fh.create_group("embeddings")
        ilinks = fh.create_group("in_links")
        olinks = fh.create_group("out_links")
        for idx, (pmid, _) in enumerate(contents):
            emb.create_dataset(str(idx), data=_deterministic_vector(pmid))
            # Tiny in/out citation graph — content doesn't matter for
            # Stage 15 (the orchestrator ignores citation graph), but
            # the shape mirrors the real release so the loader's
            # ``visititems``/``rglob`` scans don't trip on missing
            # groups.
            ilinks.create_dataset(str(idx), data=np.array([], dtype=np.int32))
            olinks.create_dataset(str(idx), data=np.array([], dtype=np.int32))


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def write_v101_fixture(root: Path) -> Path:
    """Materialise the synthetic v1.0.1 release under *root*.

    Returns the path to the ``v101`` release root (i.e. the directory
    that the Stage-15 loader expects as its ``--neuroscape-source``
    argument).
    """

    v101 = Path(root) / "v101"
    csv_dir = v101 / "Data" / "CSV"
    hdf5_dir = v101 / "Data" / "HDF5" / "DomainEmbeddings"
    models_dir = v101 / "Data" / "Models"
    for d in (csv_dir, hdf5_dir, models_dir):
        d.mkdir(parents=True, exist_ok=True)

    with (csv_dir / "neuroscience_articles_1999-2023.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_ARTICLES_HEADER)
        w.writerows(_ARTICLES_ROWS)

    with (csv_dir / "neuroscience_clusters_1999-2023.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_CLUSTERS_HEADER)
        w.writerows(_CLUSTERS_ROWS)

    with (csv_dir / "neuroscience_dimensions_1999-2023.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(_DIMENSIONS_HEADER)
        w.writerows(_DIMENSIONS_ROWS)

    for name, contents in _SHARDS.items():
        _write_shard(hdf5_dir / name, contents)

    (models_dir / "domain_embedding_model.pth").write_bytes(MODEL_CHECKPOINT_STUB_BYTES)

    return v101
