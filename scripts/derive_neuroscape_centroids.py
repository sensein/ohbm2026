#!/usr/bin/env python
"""One-off setup: derive NeuroScape centroids from the published table.

Reads:
- `<input-root>/DomainEmbeddings/*.h5` — Stage-2 projected vectors
  (multi-shard; one HDF5 file per shard).
- `<input-root>/neuroscience_articles_1999-2023.csv` — article id →
  Cluster ID.
- `<input-root>/neuroscience_clusters_1999-2023.csv` — Cluster ID →
  Title / Description / Keywords / Focus.

Groups vectors by Cluster ID, applies the spherical-mean recipe
(`analyze.centroids.spherical_mean`), and writes:
- `<output-root>/centroids__<table_version>.npy` — shape
  `(n_clusters, 64)`, float32, unit-norm rows.
- `<output-root>/cluster_table.csv` — Cluster ID + Title +
  Description + Keywords (JSON-encoded list) + Focus +
  centroid_table_version (repeated in every row for runtime discovery
  per Principle VII).

`<table_version>` is `sha256(grouped_vectors_bytes)[:12]` so any
change to the upstream NeuroScape data produces a fresh, distinct
centroid file.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sys
from hashlib import sha256
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def _resolve_articles_csv(input_root: Path) -> Path:
    candidates = sorted(input_root.rglob("neuroscience_articles_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No neuroscience_articles_*.csv under {input_root}. "
            f"Download the NeuroScape data first."
        )
    return candidates[-1]


def _resolve_clusters_csv(input_root: Path) -> Path:
    candidates = sorted(input_root.rglob("neuroscience_clusters_*.csv"))
    if not candidates:
        raise FileNotFoundError(
            f"No neuroscience_clusters_*.csv under {input_root}. "
            f"Download the NeuroScape data first."
        )
    return candidates[-1]


def _resolve_domain_embeddings_dir(input_root: Path) -> Path:
    candidates = [
        input_root / "DomainEmbeddings",
        input_root / "HDF5" / "DomainEmbeddings",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    discovered = sorted(
        p for p in input_root.rglob("DomainEmbeddings") if p.is_dir()
    )
    if discovered:
        return discovered[-1]
    raise FileNotFoundError(
        f"No DomainEmbeddings directory under {input_root}. "
        f"Download the NeuroScape HDF5 data first."
    )


def _resolve_stage2_model(input_root: Path) -> Path | None:
    candidates = [
        input_root / "Models" / "domain_embedding_model.pth",
        input_root / "domain_embedding_model.pth",
        input_root / "stage2_model.pth",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    discovered = sorted(input_root.rglob("domain_embedding_model*.pth"))
    return discovered[-1] if discovered else None


def _hash_grouped_vectors(vectors_by_cluster: dict[int, list["np.ndarray"]]) -> str:
    """Return the sha-12 version for the grouped source vectors."""
    import numpy as np

    hasher = sha256()
    for cid in sorted(vectors_by_cluster):
        stack = np.stack(vectors_by_cluster[cid], axis=0).astype(np.float32, copy=False)
        hasher.update(str(cid).encode("utf-8"))
        hasher.update(str(stack.shape).encode("utf-8"))
        hasher.update(stack.tobytes())
    return hasher.hexdigest()[:12]


def _decode_scalar(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8")
    if hasattr(value, "item"):
        try:
            value = value.item()
        except ValueError:
            pass
    return str(value)


def _row_identifier(row: dict[str, str], preferred: str) -> str | None:
    for column in (
        preferred,
        "ArticleID",
        "article_id",
        "Pmid",
        "PMID",
        "pmid",
        "Doi",
        "DOI",
        "doi",
    ):
        value = row.get(column)
        if value not in (None, ""):
            return str(value)
    return None


def _iter_h5_vectors(shard: Path) -> "Iterable[tuple[str, np.ndarray]]":
    """Yield `(article_id, vector)` from supported NeuroScape H5 layouts."""
    import h5py
    import numpy as np

    with h5py.File(shard, "r") as fh:
        if "embeddings" in fh:
            embeddings = fh["embeddings"]
            id_dataset = next(
                (
                    fh[name]
                    for name in ("pmid", "Pmid", "PMID", "doi", "Doi", "DOI", "ArticleID")
                    if name in fh
                ),
                None,
            )
            if id_dataset is None:
                raise SystemExit(
                    f"{shard} has an embeddings dataset/group but no pmid/doi/id dataset."
                )
            if hasattr(embeddings, "keys"):
                # Group-keyed H5 layout: `embeddings` is a group; each key
                # maps to one vector dataset. The corresponding article id
                # comes from `id_dataset` at the same *positional* index in
                # the sorted-key order. Mapping by `int(key)` would be wrong
                # when keys are digits but not a contiguous 0-based range
                # (e.g. {"3","7","42"}) — use the enumeration index, which is
                # always positional.
                keys = sorted(
                    embeddings.keys(),
                    key=lambda k: int(k) if str(k).isdigit() else str(k),
                )
                if len(id_dataset) != len(keys):
                    raise SystemExit(
                        f"{shard}: id_dataset has {len(id_dataset)} rows but "
                        f"embeddings group has {len(keys)} keys; cannot align."
                    )
                for index, key in enumerate(keys):
                    yield (
                        _decode_scalar(id_dataset[index]),
                        np.asarray(embeddings[key][()], dtype=np.float32),
                    )
                return
            for index in range(int(embeddings.shape[0])):
                yield (
                    _decode_scalar(id_dataset[index]),
                    np.asarray(embeddings[index], dtype=np.float32),
                )
            return

        # Fallback for compact synthetic fixtures: each H5 dataset is
        # keyed directly by article id and stores one vector.
        for key in sorted(fh.keys()):
            obj = fh[key]
            if not hasattr(obj, "shape") or tuple(obj.shape) != (64,):
                continue
            yield key, np.asarray(obj[()], dtype=np.float32)


def main(argv: list[str] | None = None) -> int:
    import numpy as np

    from ohbm2026.analyze.centroids import spherical_mean

    parser = argparse.ArgumentParser(
        prog="derive_neuroscape_centroids",
        description="Derive NeuroScape centroids from the published Stage-2 data.",
    )
    parser.add_argument(
        "--input-root", type=Path, required=True,
        help="Directory containing DomainEmbeddings/*.h5 + the two articles/clusters CSVs.",
    )
    parser.add_argument(
        "--output-root", type=Path, required=True,
        help="Directory to write centroids__<version>.npy + cluster_table.csv.",
    )
    parser.add_argument(
        "--id-column", default="ArticleID",
        help="Article-id column name in articles CSV (default: ArticleID).",
    )
    parser.add_argument(
        "--cluster-column", default="Cluster ID",
        help="Cluster-id column name in articles CSV (default: 'Cluster ID').",
    )
    args = parser.parse_args(argv)

    input_root = args.input_root
    output_root = args.output_root
    output_root.mkdir(parents=True, exist_ok=True)

    # 1. Load article → Cluster ID map
    articles_csv = _resolve_articles_csv(input_root)
    article_to_cluster: dict[str, int] = {}
    with articles_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            aid = _row_identifier(row, args.id_column)
            cid_raw = row.get(args.cluster_column) or row.get("Cluster ID")
            if aid in (None, "") or cid_raw in (None, ""):
                continue
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            article_to_cluster[str(aid)] = cid

    # 2. Stream H5 shards, gather vectors by Cluster ID
    try:
        import h5py
    except ImportError as exc:
        raise SystemExit(
            "h5py is required. Install via: uv pip install --python .venv/bin/python '.[analysis]'"
        ) from exc

    domain_embeddings_dir = _resolve_domain_embeddings_dir(input_root)
    h5_paths = sorted(domain_embeddings_dir.glob("*.h5"))
    if not h5_paths:
        raise SystemExit(
            f"No *.h5 shards under {domain_embeddings_dir}. "
            f"Download the NeuroScape data first."
        )

    vectors_by_cluster: dict[int, list[np.ndarray]] = {}
    for shard in h5_paths:
        for article_id, vec in _iter_h5_vectors(shard):
            cid = article_to_cluster.get(article_id)
            if cid is None:
                continue
            vectors_by_cluster.setdefault(cid, []).append(vec)

    if not vectors_by_cluster:
        raise SystemExit(
            "No vectors mapped to clusters. Check --id-column / --cluster-column "
            f"against the headers of {articles_csv}."
        )

    # 3. Derive table_version from the grouped source vectors' bytes.
    digest = _hash_grouped_vectors(vectors_by_cluster)

    # 4. Apply spherical_mean per Cluster ID
    cluster_ids_sorted = sorted(vectors_by_cluster.keys())
    centroids = np.zeros((len(cluster_ids_sorted), 64), dtype=np.float32)
    for i, cid in enumerate(cluster_ids_sorted):
        stack = np.stack(vectors_by_cluster[cid], axis=0)
        centroids[i] = spherical_mean(stack)

    matrix_path = output_root / f"centroids__{digest}.npy"

    # 5. Load cluster labels (including the extended columns from the
    # published NeuroScape table: Size, Most Citing/Cited Cluster,
    # Reference/Citation Krackhardt).
    clusters_csv = _resolve_clusters_csv(input_root)
    labels: dict[int, dict[str, str]] = {}
    with clusters_csv.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            cid_raw = row.get("Cluster ID") or row.get("cluster_id")
            if cid_raw in (None, ""):
                continue
            try:
                cid = int(cid_raw)
            except (TypeError, ValueError):
                continue
            labels[cid] = {
                "Title": row.get("Title", "") or "",
                "Description": row.get("Description", "") or "",
                "Keywords": row.get("Keywords", "") or "",
                "Focus": row.get("Focus", "") or "",
                "Size": row.get("Size", "") or "",
                "Most Citing Cluster": row.get("Most Citing Cluster", "") or "",
                "Most Cited Cluster": row.get("Most Cited Cluster", "") or "",
                "Reference Krackhardt": row.get("Reference Krackhardt", "") or "",
                "Citation Krackhardt": row.get("Citation Krackhardt", "") or "",
            }

    # 6. Write outputs atomically
    sidecar_path = output_root / "cluster_table.csv"
    # np.save appends `.npy` if not present, so build the temp path with
    # a `.tmp.npy` suffix to keep the extension intact.
    tmp_matrix = matrix_path.with_name(matrix_path.stem + ".tmp.npy")
    np.save(tmp_matrix, centroids)
    tmp_matrix.replace(matrix_path)

    tmp_sidecar = sidecar_path.with_suffix(sidecar_path.suffix + ".tmp")
    with tmp_sidecar.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "Cluster ID",
                "Title",
                "Description",
                "Keywords",
                "Focus",
                "Size",
                "Most Citing Cluster",
                "Most Cited Cluster",
                "Reference Krackhardt",
                "Citation Krackhardt",
                "centroid_table_version",
            ]
        )
        for cid in cluster_ids_sorted:
            lab = labels.get(cid, {})
            # If the upstream Keywords column wasn't JSON-encoded, wrap it.
            kw_raw = lab.get("Keywords", "")
            try:
                json.loads(kw_raw)
                kw_str = kw_raw
            except (json.JSONDecodeError, TypeError):
                # Split on common delimiters if present; else treat as single phrase.
                if isinstance(kw_raw, str) and ("," in kw_raw or ";" in kw_raw):
                    parts = [p.strip() for p in kw_raw.replace(";", ",").split(",") if p.strip()]
                    kw_str = json.dumps(parts)
                elif kw_raw:
                    kw_str = json.dumps([kw_raw])
                else:
                    kw_str = "[]"
            writer.writerow(
                [
                    cid,
                    lab.get("Title", ""),
                    lab.get("Description", ""),
                    kw_str,
                    lab.get("Focus", ""),
                    lab.get("Size", ""),
                    lab.get("Most Citing Cluster", ""),
                    lab.get("Most Cited Cluster", ""),
                    lab.get("Reference Krackhardt", ""),
                    lab.get("Citation Krackhardt", ""),
                    digest,
                ]
            )
    tmp_sidecar.replace(sidecar_path)

    source_model_path = _resolve_stage2_model(input_root)
    copied_model_path = None
    if source_model_path is not None:
        copied_model_path = output_root / "stage2_model.pth"
        if source_model_path.resolve() != copied_model_path.resolve():
            tmp_model = copied_model_path.with_suffix(copied_model_path.suffix + ".tmp")
            shutil.copy2(source_model_path, tmp_model)
            tmp_model.replace(copied_model_path)

    # 7. Compute file hashes for runtime discovery (FR-008 + CA-007).
    def _file_sha256(p: Path) -> str:
        h = sha256()
        with p.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    csv_shas = {
        articles_csv.name: _file_sha256(articles_csv),
        clusters_csv.name: _file_sha256(clusters_csv),
    }

    # HDF5 shard manifest hash: deterministic over sorted (relative-name,
    # size, sha256-of-bytes) tuples. Stable across machines, sensitive to
    # any shard change.
    manifest_h = sha256()
    for shard in h5_paths:
        rel = shard.name
        sz = shard.stat().st_size
        manifest_h.update(rel.encode("utf-8"))
        manifest_h.update(str(sz).encode("utf-8"))
        manifest_h.update(_file_sha256(shard).encode("utf-8"))
    hdf5_manifest_sha = manifest_h.hexdigest()

    domain_model_checkpoint_sha = (
        _file_sha256(source_model_path) if source_model_path is not None else None
    )

    metadata = {
        "centroid_table_version": digest,
        "n_centroids": len(cluster_ids_sorted),
        "cluster_count": len(cluster_ids_sorted),
        "cluster_ids": [int(c) for c in cluster_ids_sorted],
        "source_csv_sha256s": csv_shas,
        "hdf5_shard_manifest_sha256": hdf5_manifest_sha,
        "domain_model_checkpoint_sha256": domain_model_checkpoint_sha,
        "domain_model_checkpoint_source": str(source_model_path) if source_model_path else None,
        "domain_model_checkpoint_copy": str(copied_model_path) if copied_model_path else None,
        "articles_csv": articles_csv.name,
        "clusters_csv": clusters_csv.name,
        "h5_shard_count": len(h5_paths),
    }
    metadata_path = output_root / "centroid_metadata.json"
    tmp_meta = metadata_path.with_suffix(metadata_path.suffix + ".tmp")
    tmp_meta.write_text(json.dumps(metadata, indent=2, sort_keys=True), encoding="utf-8")
    tmp_meta.replace(metadata_path)

    print(
        json.dumps(
            {
                "event": "centroids_derived",
                "matrix_path": str(matrix_path),
                "sidecar_path": str(sidecar_path),
                "metadata_path": str(metadata_path),
                "stage2_model_path": str(copied_model_path) if copied_model_path else None,
                "table_version": digest,
                "n_centroids": len(cluster_ids_sorted),
                "domain_model_checkpoint_sha256": domain_model_checkpoint_sha,
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
