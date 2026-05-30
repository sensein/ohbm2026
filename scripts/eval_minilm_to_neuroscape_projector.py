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


def build_relrep(x: np.ndarray, anchors: np.ndarray, batch: int = 50000) -> np.ndarray:
    """Relative-representation featurisation (Moschella et al., ICLR 2023).

    Re-express each (L2-normed) row of ``x`` as its cosine similarities to a
    fixed set of ``anchors`` (also L2-normed), then L2-norm the resulting
    K-vector. Because every coordinate is an inner product between unit
    vectors, the representation is invariant to any rotation/reflection of the
    source space — the survey's biggest-bang lever for aligning two
    independently-trained embedding spaces before a projector even sees them.

    Batched over rows to keep the [N,K] matmul off a single huge allocation."""
    out = np.empty((x.shape[0], anchors.shape[0]), dtype=np.float32)
    for s in range(0, x.shape[0], batch):
        e = min(s + batch, x.shape[0])
        out[s:e] = x[s:e] @ anchors.T
    return _l2norm(out)


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


def _make_projector(in_dim, out_dim, device):
    """384 -> 512 -> 256 -> 64 with LayerNorm + GELU + dropout; L2-normed output.

    Wider, normed, regularised vs the plain MLP — the retrieval loss below is
    what matters, but the architecture follows the survey recommendation.
    """
    import torch.nn as nn

    class Projector(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(in_dim, 512),
                nn.LayerNorm(512),
                nn.GELU(),
                nn.Dropout(0.1),
                nn.Linear(512, 256),
                nn.LayerNorm(256),
                nn.GELU(),
                nn.Dropout(0.1),
                nn.Linear(256, out_dim),
            )

        def forward(self, x):
            p = self.net(x)
            return p / p.norm(dim=1, keepdim=True).clamp_min(1e-8)

    return Projector().to(device)


def _val_recall20(model, xval_probe, yval_probe, ref_true, device):
    """recall@20 on a FIXED val probe vs a FIXED reference — the early-stop signal.

    This is the metric we actually report, so we stop on it directly rather than
    on cosine/MSE (which the survey flags as the reason naive regression plateaus:
    low MSE can still scramble local rank order).

    Reviewer fix: the probe + reference are sampled ONCE by the caller and the
    reference size matches the test reference, so early-stop is on the same
    metric we report (no per-epoch resampling jitter; no 50k-vs-100k mismatch
    that mechanically inflated val recall@20 over test)."""
    pv = mlp_predict(model, xval_probe, device)
    return recall_at_k(pv, yval_probe, ref_true, 20)


def fit_infonce(
    xtr, ytr, xval_probe, yval_probe, val_ref, epochs, lr, device,
    tau=0.05, nbr_thresh=0.8, batch=8192, weight_decay=1e-4,
    loss_kind="cosine", verbose=True,
):
    """InfoNCE projector: pull pred(x_i) toward its OWN true-64 AND its in-batch
    true-64 neighbours (cos >= nbr_thresh), push away the rest.

    Directly optimises retrieval geometry instead of point-wise distance, which
    is the survey's top recommendation for a UMAP-like (locally-warped) target.
    In-batch similarities supply the neighbour-graph positives cheaply — no
    global kNN precompute.

    Optimisations / reviewer fixes over the first pass:
      * symmetric loss (pred->true AND true->pred directions),
      * larger batch (more in-batch negatives + neighbours),
      * AdamW + cosine LR decay + weight decay,
      * nbr_thresh raised 0.6 -> 0.8 so positives are true near-duplicates,
        not the whole cluster blob (the loose threshold reproduced the
        centroid-shrinkage failure mode it was meant to avoid),
      * loss_kind="geodesic": Riemannian anchor on S^63 — minimise the
        squared geodesic (arc-length) distance arccos(<p,y>)^2 instead of
        the chordal 1-cos. arccos is the intrinsic metric of the unit
        sphere, so it weights near-orthogonal (hard) pairs more than cosine,
        which saturates. Logits stay cosine/tau (standard contrastive).
    Early-stops on val recall@20 (fixed probe+ref). Returns (model, best_val_recall)."""
    import torch

    torch.manual_seed(0)
    Xtr = torch.from_numpy(xtr).to(device)
    Ytr = torch.from_numpy(ytr).to(device)

    model = _make_projector(xtr.shape[1], ytr.shape[1], device)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=epochs)

    def anchor_term(pb, yb):
        cos = (pb * yb).sum(dim=1).clamp(-1.0 + 1e-6, 1.0 - 1e-6)
        if loss_kind == "geodesic":
            # squared arc-length on S^63; arccos in [0, pi].
            return (torch.arccos(cos) ** 2).mean()
        return (1.0 - cos).mean()

    n = Xtr.shape[0]
    best_state = None
    best_rec = -1.0
    for ep in range(epochs):
        model.train()
        perm = torch.randperm(n, device=device)
        for s in range(0, n, batch):
            idx = perm[s : s + batch]
            xb = Xtr[idx]
            yb = Ytr[idx]  # already L2-normed at assembly time
            opt.zero_grad()
            pb = model(xb)  # [B,64] normed
            # Positive set per row: self + in-batch true-64 neighbours.
            with torch.no_grad():
                ysim = yb @ yb.T
                pos = (ysim >= nbr_thresh).float()
                pos.fill_diagonal_(1.0)
                pos_row = pos / pos.sum(dim=1, keepdim=True).clamp_min(1.0)
                pos_col = pos / pos.sum(dim=0, keepdim=True).clamp_min(1.0)
            logits = (pb @ yb.T) / tau  # [B,B] — pred_i vs true_j
            # Symmetric: rows = pred retrieves true; cols = true retrieves pred.
            logp_row = torch.log_softmax(logits, dim=1)
            logp_col = torch.log_softmax(logits, dim=0)
            nce = -(pos_row * logp_row).sum(dim=1).mean() \
                  - (pos_col * logp_col).sum(dim=0).mean()
            loss = 0.5 * nce + 0.1 * anchor_term(pb, yb)
            loss.backward()
            opt.step()
        sched.step()
        rec = _val_recall20(model, xval_probe, yval_probe, val_ref, device)
        if verbose:
            _log(f"  infonce[{loss_kind}] epoch {ep + 1}/{epochs} val recall@20={rec:.4f}")
        if rec > best_rec:
            best_rec = rec
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    _log(f"  infonce[{loss_kind}] best val recall@20={best_rec:.4f}")
    return model, best_rec


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


def same_cluster_purity(probe, probe_cluster, reference, ref_cluster, k, batch=512):
    """purity@k: fraction of a probe's top-k neighbours in `reference` that
    share the probe's true cluster.

    Reviewer's recommended headline metric: it measures "does the query land in
    the right neighbourhood" without penalising the projector for failing to
    reproduce true-64's idiosyncratic exact neighbour order (true-64 is itself a
    lossy UMAP-like projection, so matching its neighbour list is not the
    deployment goal — landing in the right cluster is)."""
    n = probe.shape[0]
    accs = np.empty(n, dtype=np.float32)
    for s in range(0, n, batch):
        e = min(s + batch, n)
        ap = probe[s:e] @ reference.T
        ak = np.argpartition(-ap, k, axis=1)[:, :k]
        for r in range(e - s):
            accs[s + r] = float(np.mean(ref_cluster[ak[r]] == probe_cluster[s + r]))
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
    ap.add_argument(
        "--models", default="both", choices=["ridge", "mlp", "infonce", "both", "all"]
    )
    ap.add_argument("--epochs", type=int, default=40)
    ap.add_argument("--hidden", type=int, default=512)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--tau", type=float, default=0.05, help="InfoNCE temperature")
    ap.add_argument(
        "--nbr-thresh",
        type=float,
        default=0.8,
        help="true-64 cosine above which an in-batch row is an InfoNCE positive",
    )
    ap.add_argument(
        "--loss",
        default="cosine",
        choices=["cosine", "geodesic"],
        help="InfoNCE anchor metric: chordal 1-cos or Riemannian arccos^2 on S^63",
    )
    ap.add_argument(
        "--features",
        default="raw",
        choices=["raw", "relrep"],
        help="projector input: raw MiniLM-384 or relative-representation "
        "cosine-sims to --n-anchors fixed training anchors",
    )
    ap.add_argument(
        "--n-anchors",
        type=int,
        default=512,
        help="number of fixed training anchors for --features relrep",
    )
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

    if args.features == "relrep":
        # Anchors are a fixed random subset of TRAIN rows (no val/test leakage).
        anchor_rng = np.random.default_rng(0)
        tr_pool = np.flatnonzero(tr)
        n_anchors = min(args.n_anchors, tr_pool.size)
        anchor_idx = anchor_rng.choice(tr_pool, size=n_anchors, replace=False)
        anchors = x[anchor_idx]
        x = build_relrep(x, anchors)
        _log(f"relrep: featurised x -> {x.shape[1]}-d (cosine-sims to {n_anchors} train anchors)")

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
    ref_cluster = cluster[ref_idx]
    ideal_probe = y[probe_idx]
    probe_cluster = cluster[probe_idx]

    # Fixed val probe + reference for the InfoNCE early-stop signal. Reviewer
    # fix: reference size matches the TEST reference (args.recall_ref), and the
    # probe/ref are sampled ONCE, so early-stop tracks the same metric we report
    # (the old 50k-vs-100k mismatch mechanically inflated val over test).
    va_idx = np.flatnonzero(va)
    val_probe_idx = rng.choice(va_idx, size=min(2000, va_idx.size), replace=False)
    val_ref_pool = np.flatnonzero(tr)
    val_ref_idx = rng.choice(
        val_ref_pool, size=min(args.recall_ref, val_ref_pool.size), replace=False
    )
    xval_probe, yval_probe = x[val_probe_idx], y[val_probe_idx]
    val_ref = y[val_ref_idx]

    # purity@k ceiling (true-64 itself).
    ceil_purity = same_cluster_purity(
        ideal_probe, probe_cluster, ref_true, ref_cluster, args.recall_k
    )
    _log(f"CEILING (true-64): purity@{args.recall_k}={ceil_purity:.4f}")

    results: dict[str, dict] = {
        "ceiling_true64": {
            "centroid_top1": ceil_top1,
            "centroid_top3": ceil_top3,
            f"purity@{args.recall_k}": ceil_purity,
        }
    }

    def evaluate(name, pred_test_full, pred_probe):
        top1, top3 = centroid_agreement(pred_test_full, cluster[te], cluster_ids, centroids)
        cos = float(np.mean(np.sum(pred_test_full * y[te], axis=1)))
        rec = recall_at_k(pred_probe, ideal_probe, ref_true, args.recall_k)
        purity = same_cluster_purity(
            pred_probe, probe_cluster, ref_true, ref_cluster, args.recall_k
        )
        _log(
            f"== {name}: cos={cos:.4f} centroid top1={top1:.4f} top3={top3:.4f} "
            f"recall@{args.recall_k}={rec:.4f} purity@{args.recall_k}={purity:.4f}"
        )
        results[name] = {
            "cos_to_true64": cos,
            "centroid_top1": top1,
            "centroid_top3": top3,
            f"recall@{args.recall_k}": rec,
            f"purity@{args.recall_k}": purity,
        }

    if args.models in ("ridge", "both", "all"):
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

    if args.models in ("mlp", "both", "all"):
        _log(f"fitting mlp on {device}")
        model = fit_mlp(x[tr], y[tr], x[va], y[va], args.epochs, args.hidden, args.lr, device)
        pred_test = mlp_predict(model, x[te], device)
        pred_probe = mlp_predict(model, x[probe_idx], device)
        evaluate("mlp", pred_test, pred_probe)
        import torch

        torch.save(model.state_dict(), cache_dir / "mlp.pt")
        np.save(out_dir / "mlp_pred_test.npy", pred_test)

    if args.models in ("infonce", "all"):
        name = f"infonce_{args.loss}"
        _log(
            f"fitting {name} projector on {device} "
            f"(tau={args.tau} nbr_thresh={args.nbr_thresh})"
        )
        model, _ = fit_infonce(
            x[tr], y[tr], xval_probe, yval_probe, val_ref, args.epochs, args.lr, device,
            tau=args.tau, nbr_thresh=args.nbr_thresh, loss_kind=args.loss,
        )
        pred_test = mlp_predict(model, x[te], device)
        pred_probe = mlp_predict(model, x[probe_idx], device)
        evaluate(name, pred_test, pred_probe)
        import torch

        torch.save(model.state_dict(), cache_dir / f"{name}.pt")
        np.save(out_dir / f"{name}_pred_test.npy", pred_test)

    (out_dir / "metrics.json").write_text(json.dumps(results, indent=2))
    _log(f"wrote {out_dir / 'metrics.json'}")
    print(json.dumps(results, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
