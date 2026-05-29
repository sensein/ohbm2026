#!/usr/bin/env python
"""Exploration (Track B): evaluate a learned projector MiniLM-384 -> NeuroScape-64.

Motivation
----------
The spec-019 semantic-search lane stores 384-d MiniLM vectors. NeuroScape's
published domain-embedding space is 64-d. If a projector ``f: R^384 -> R^64``
faithfully maps MiniLM into NeuroScape space, the browser (which only has the
cheap Xenova MiniLM encoder) can place a live query into NeuroScape's native
64-d space. That enables:

  * routing queries against the *real* published 64-d centroids, and
  * a 6x smaller search payload (store 64-d instead of 384-d).

This script measures whether such a projector is good enough, under
**option 1** (store the TRUE NeuroScape-64 corpus vectors; project only the
query): the probe is approximated, the corpus is exact.

Data sources (all discovered at runtime; nothing hardcoded beyond roots)
------------------------------------------------------------------------
  * MiniLM-384  : data/cache/atlas-vectors/<state>/cluster_*.npz
                  (keys: pubmed_ids int64[N], vectors_int8 int8[N,384])
  * NeuroScape-64 + year : DomainEmbeddings/*.h5
                  (embeddings/<i> float32[64], pmid int32[200], year int32[200])
  * Cluster ID  : neuroscience_articles_*.csv  (Pmid -> Cluster ID)
  * Centroids   : centroids__*.npy [n_clusters,64] + cluster_table.csv (Cluster ID order)

Caching (Principle III)
-----------------------
The assembled paired matrix and the fitted projectors are cached under
``data/cache/projector-eval/<state>/`` so a second run skips the slow h5 walk
and the fit. Metrics + projected vectors land in
``data/outputs/experiments/projector-eval__<state>/``.
"""

from __future__ import annotations

import argparse
import csv
import glob
import json
import sys
import time
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]

# Temporal split boundaries (inclusive).
TRAIN_MAX_YEAR = 2020
VAL_YEAR = 2021  # everything == VAL_YEAR
# test: year > VAL_YEAR


def _log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _l2norm(x: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(x, axis=1, keepdims=True)
    n[n == 0.0] = 1.0
    return (x / n).astype(np.float32)


# ── data assembly ────────────────────────────────────────────────────


def _load_minilm(atlas_vectors_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Concatenate all per-cluster npz shards -> (pmid int64[N], x384 float32[N,384] L2-normed)."""
    files = sorted(atlas_vectors_dir.glob("cluster_*.npz"))
    if not files:
        raise FileNotFoundError(f"no cluster_*.npz under {atlas_vectors_dir}")
    pmids: list[np.ndarray] = []
    vecs: list[np.ndarray] = []
    for f in files:
        d = np.load(f)
        pmids.append(d["pubmed_ids"].astype(np.int64))
        vecs.append(d["vectors_int8"].astype(np.float32))
    pmid = np.concatenate(pmids)
    x = np.concatenate(vecs, axis=0)
    _log(f"minilm: {x.shape[0]} rows x {x.shape[1]} dims")
    return pmid, _l2norm(x)


def _load_neuroscape64(h5_dir: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Walk DomainEmbeddings shards -> (pmid int64[M], y64 float32[M,64], year int32[M])."""
    import h5py

    shards = sorted(h5_dir.glob("*.h5"))
    if not shards:
        raise FileNotFoundError(f"no *.h5 under {h5_dir}")
    pmids: list[np.ndarray] = []
    years: list[np.ndarray] = []
    vecs: list[np.ndarray] = []
    for si, shard in enumerate(shards):
        with h5py.File(shard, "r") as fh:
            if "embeddings" not in fh or "pmid" not in fh:
                raise KeyError(f"{shard}: expected 'embeddings' + 'pmid' datasets")
            emb = fh["embeddings"]
            pmid = np.asarray(fh["pmid"][()], dtype=np.int64)
            year = np.asarray(fh["year"][()], dtype=np.int32)
            n = pmid.shape[0]
            block = np.empty((n, 64), dtype=np.float32)
            for i in range(n):
                row = np.asarray(emb[str(i)][()], dtype=np.float32)
                if row.shape != (64,):
                    raise ValueError(f"{shard}: embeddings/{i} shape {row.shape} != (64,)")
                block[i] = row
            pmids.append(pmid)
            years.append(year)
            vecs.append(block)
        if (si + 1) % 200 == 0:
            _log(f"  h5 shards {si + 1}/{len(shards)}")
    pmid = np.concatenate(pmids)
    year = np.concatenate(years)
    y = np.concatenate(vecs, axis=0)
    _log(f"neuroscape64: {y.shape[0]} rows x {y.shape[1]} dims")
    return pmid, _l2norm(y), year


def _load_clusters_csv(csv_path: Path) -> dict[int, int]:
    out: dict[int, int] = {}
    with csv_path.open(newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            pm = row.get("Pmid")
            cid = row.get("Cluster ID")
            if not pm or not cid:
                continue
            out[int(pm)] = int(cid)
    _log(f"clusters csv: {len(out)} pmid->cluster")
    return out


def assemble_pairs(cache_dir: Path, atlas_vectors_dir: Path, h5_dir: Path, csv_path: Path) -> dict:
    pairs_path = cache_dir / "pairs.npz"
    if pairs_path.exists():
        _log(f"pairs cache hit: {pairs_path}")
        d = np.load(pairs_path)
        return {k: d[k] for k in d.files}

    _log("assembling paired dataset (cache miss)")
    pm_x, x384 = _load_minilm(atlas_vectors_dir)
    pm_y, y64, year_y = _load_neuroscape64(h5_dir)
    clusters = _load_clusters_csv(csv_path)

    # Join on pmid (intersection of all three).
    y_index = {int(p): i for i, p in enumerate(pm_y)}
    sel_x: list[int] = []
    sel_y: list[int] = []
    sel_cluster: list[int] = []
    for xi, p in enumerate(pm_x):
        pi = int(p)
        yi = y_index.get(pi)
        if yi is None:
            continue
        cid = clusters.get(pi)
        if cid is None:
            continue
        sel_x.append(xi)
        sel_y.append(yi)
        sel_cluster.append(cid)

    sel_x_arr = np.asarray(sel_x, dtype=np.int64)
    sel_y_arr = np.asarray(sel_y, dtype=np.int64)
    out = {
        "pmid": pm_x[sel_x_arr].astype(np.int64),
        "x384": x384[sel_x_arr],
        "y64": y64[sel_y_arr],
        "year": year_y[sel_y_arr].astype(np.int32),
        "cluster": np.asarray(sel_cluster, dtype=np.int32),
    }
    _log(f"joined pairs: {out['pmid'].shape[0]} articles")
    cache_dir.mkdir(parents=True, exist_ok=True)
    np.savez(pairs_path, **out)
    return out


def load_centroids(centroids_npy: Path, cluster_table_csv: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (cluster_ids int32[C], centroids float32[C,64] L2-normed) aligned to the npy rows."""
    cent = np.load(centroids_npy).astype(np.float32)
    cluster_ids: list[int] = []
    with cluster_table_csv.open(newline="") as f:
        reader = csv.DictReader(f)
        key = "Cluster ID" if "Cluster ID" in (reader.fieldnames or []) else (reader.fieldnames or [None])[0]
        for row in reader:
            cluster_ids.append(int(row[key]))
    ids = np.asarray(cluster_ids, dtype=np.int32)
    if ids.shape[0] != cent.shape[0]:
        raise ValueError(
            f"centroid count {cent.shape[0]} != cluster_table rows {ids.shape[0]}"
        )
    return ids, _l2norm(cent)


# ── models ───────────────────────────────────────────────────────────


def fit_ridge(xtr, ytr, xval, yval, alphas):
    from sklearn.linear_model import Ridge

    best = None
    for a in alphas:
        m = Ridge(alpha=a)
        m.fit(xtr, ytr)
        pred = _l2norm(m.predict(xval).astype(np.float32))
        cos = float(np.mean(np.sum(pred * yval, axis=1)))
        _log(f"  ridge alpha={a:<8} val cos={cos:.4f}")
        if best is None or cos > best[0]:
            best = (cos, a, m)
    return best[2], best[1]


def fit_mlp(xtr, ytr, xval, yval, epochs, hidden, lr, device):
    import torch
    import torch.nn as nn

    torch.manual_seed(0)
    Xtr = torch.from_numpy(xtr).to(device)
    Ytr = torch.from_numpy(ytr).to(device)
    Xval = torch.from_numpy(xval).to(device)
    Yval = torch.from_numpy(yval).to(device)

    model = nn.Sequential(
        nn.Linear(xtr.shape[1], hidden),
        nn.GELU(),
        nn.Linear(hidden, hidden),
        nn.GELU(),
        nn.Linear(hidden, ytr.shape[1]),
    ).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=lr)

    def cosine_loss(pred, tgt):
        pred = pred / pred.norm(dim=1, keepdim=True).clamp_min(1e-8)
        return (1.0 - (pred * tgt).sum(dim=1)).mean()

    n = Xtr.shape[0]
    bs = 8192
    best_state = None
    best_val = -1.0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, device=device)
        for s in range(0, n, bs):
            idx = perm[s : s + bs]
            opt.zero_grad()
            pred = model(Xtr[idx])
            loss = cosine_loss(pred, Ytr[idx]) + 0.1 * nn.functional.mse_loss(
                pred / pred.norm(dim=1, keepdim=True).clamp_min(1e-8), Ytr[idx]
            )
            loss.backward()
            opt.step()
        model.eval()
        with torch.no_grad():
            pv = model(Xval)
            pv = pv / pv.norm(dim=1, keepdim=True).clamp_min(1e-8)
            vcos = float((pv * Yval).sum(dim=1).mean())
        _log(f"  mlp epoch {ep + 1}/{epochs} val cos={vcos:.4f}")
        if vcos > best_val:
            best_val = vcos
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    return model


def mlp_predict(model, x, device):
    import torch

    model.eval()
    with torch.no_grad():
        p = model(torch.from_numpy(x).to(device)).cpu().numpy()
    return _l2norm(p.astype(np.float32))


# ── metrics ──────────────────────────────────────────────────────────


def centroid_agreement(pred64, true_cluster, cluster_ids, centroids):
    """top-1 / top-3 agreement of nearest centroid(pred) vs the article's true cluster."""
    sims = pred64 @ centroids.T  # [Ntest, C]
    order = np.argsort(-sims, axis=1)
    top1_ids = cluster_ids[order[:, 0]]
    top1 = float(np.mean(top1_ids == true_cluster))
    top3_ids = cluster_ids[order[:, :3]]
    top3 = float(np.mean(np.any(top3_ids == true_cluster[:, None], axis=1)))
    return top1, top3


def recall_at_k(probe, ideal_probe, reference, k, batch=512):
    """recall@k: overlap of top-k neighbours in `reference` retrieved by
    `probe` (approx) vs `ideal_probe` (true-64), averaged over rows."""
    n = probe.shape[0]
    accs = np.empty(n, dtype=np.float32)
    for s in range(0, n, batch):
        e = min(s + batch, n)
        ap = probe[s:e] @ reference.T
        ip = ideal_probe[s:e] @ reference.T
        ak = np.argpartition(-ap, k, axis=1)[:, :k]
        ik = np.argpartition(-ip, k, axis=1)[:, :k]
        for r in range(e - s):
            accs[s + r] = len(set(ak[r].tolist()) & set(ik[r].tolist())) / k
    return float(np.mean(accs))


# ── orchestration ────────────────────────────────────────────────────


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--state-key", default="eaae0a30b85e")
    ap.add_argument(
        "--atlas-vectors-root", default=str(REPO_ROOT / "data/cache/atlas-vectors")
    )
    ap.add_argument(
        "--neuroscape-source",
        default=str(REPO_ROOT / "data/inputs/neuroscape-source/v101"),
    )
    ap.add_argument(
        "--centroids-npy",
        default=None,
        help="defaults to the latest data/inputs/neuroscape/centroids__*.npy",
    )
    ap.add_argument("--models", default="both", choices=["ridge", "mlp", "both"])
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--recall-k", type=int, default=20)
    ap.add_argument("--recall-test", type=int, default=5000, help="sampled test probes for recall@k")
    ap.add_argument("--recall-ref", type=int, default=100000, help="sampled reference corpus size")
    ap.add_argument("--device", default="auto")
    args = ap.parse_args()

    cache_dir = REPO_ROOT / "data/cache/projector-eval" / args.state_key
    out_dir = REPO_ROOT / "data/outputs/experiments" / f"projector-eval__{args.state_key}"
    out_dir.mkdir(parents=True, exist_ok=True)

    src = Path(args.neuroscape_source)
    h5_dir = next(iter(sorted(src.rglob("DomainEmbeddings"))), None)
    if h5_dir is None:
        raise FileNotFoundError(f"no DomainEmbeddings dir under {src}")
    csv_path = next(iter(sorted(src.rglob("neuroscience_articles_*.csv"))), None)
    if csv_path is None:
        raise FileNotFoundError(f"no neuroscience_articles_*.csv under {src}")
    atlas_dir = Path(args.atlas_vectors_root) / args.state_key

    if args.centroids_npy:
        cent_npy = Path(args.centroids_npy)
    else:
        cands = sorted((REPO_ROOT / "data/inputs/neuroscape").glob("centroids__*.npy"))
        if not cands:
            raise FileNotFoundError("no centroids__*.npy under data/inputs/neuroscape")
        cent_npy = cands[-1]
    cluster_table = cent_npy.parent / "cluster_table.csv"

    pairs = assemble_pairs(cache_dir, atlas_dir, h5_dir, csv_path)
    cluster_ids, centroids = load_centroids(cent_npy, cluster_table)

    x = pairs["x384"]
    y = pairs["y64"]
    year = pairs["year"]
    cluster = pairs["cluster"]

    tr = year <= TRAIN_MAX_YEAR
    va = year == VAL_YEAR
    te = year > VAL_YEAR
    _log(f"split: train={int(tr.sum())} val={int(va.sum())} test={int(te.sum())}")

    # Sanity ceiling: how well does the TRUE 64-d land on its own cluster?
    ceil_top1, ceil_top3 = centroid_agreement(y[te], cluster[te], cluster_ids, centroids)
    _log(f"CEILING (true-64): centroid top1={ceil_top1:.4f} top3={ceil_top3:.4f}")

    device = args.device
    if device == "auto":
        try:
            import torch

            device = "mps" if torch.backends.mps.is_available() else "cpu"
        except Exception:
            device = "cpu"

    # recall@k sampling (option 1: reference is TRUE-64 corpus).
    rng = np.random.default_rng(0)
    te_idx = np.flatnonzero(te)
    probe_idx = rng.choice(te_idx, size=min(args.recall_test, te_idx.size), replace=False)
    ref_pool = np.flatnonzero(tr | va)
    ref_idx = rng.choice(ref_pool, size=min(args.recall_ref, ref_pool.size), replace=False)
    ref_true = y[ref_idx]
    ideal_probe = y[probe_idx]

    results: dict[str, dict] = {
        "ceiling_true64": {"centroid_top1": ceil_top1, "centroid_top3": ceil_top3}
    }

    def evaluate(name, pred_test_full, pred_probe):
        top1, top3 = centroid_agreement(pred_test_full, cluster[te], cluster_ids, centroids)
        cos = float(np.mean(np.sum(pred_test_full * y[te], axis=1)))
        rec = recall_at_k(pred_probe, ideal_probe, ref_true, args.recall_k)
        _log(
            f"== {name}: cos={cos:.4f} centroid top1={top1:.4f} top3={top3:.4f} "
            f"recall@{args.recall_k}={rec:.4f}"
        )
        results[name] = {
            "cos_to_true64": cos,
            "centroid_top1": top1,
            "centroid_top3": top3,
            f"recall@{args.recall_k}": rec,
        }

    if args.models in ("ridge", "both"):
        _log("fitting ridge")
        model, alpha = fit_ridge(x[tr], y[tr], x[va], y[va], [1.0, 10.0, 100.0, 300.0, 1000.0])
        pred_test = _l2norm(model.predict(x[te]).astype(np.float32))
        pred_probe = _l2norm(model.predict(x[probe_idx]).astype(np.float32))
        evaluate(f"ridge(alpha={alpha})", pred_test, pred_probe)
        np.savez(
            cache_dir / "ridge.npz",
            coef=model.coef_.astype(np.float32),
            intercept=model.intercept_.astype(np.float32),
            alpha=np.float32(alpha),
        )

    if args.models in ("mlp", "both"):
        _log(f"fitting mlp on {device}")
        model = fit_mlp(x[tr], y[tr], x[va], y[va], args.epochs, args.hidden, args.lr, device)
        pred_test = mlp_predict(model, x[te], device)
        pred_probe = mlp_predict(model, x[probe_idx], device)
        evaluate("mlp", pred_test, pred_probe)
        import torch

        torch.save(model.state_dict(), cache_dir / "mlp.pt")
        np.save(out_dir / "mlp_pred_test.npy", pred_test)

    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2))
    _log(f"wrote {out_dir / 'metrics.json'}")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
