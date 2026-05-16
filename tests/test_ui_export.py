"""Tests for the Stage 4 UI export path (SC-004 / T097a).

Per spec FR-018 + SC-004 (Session 2026-05-15 clarification):
`ohbmcli export-ui --analysis-rollup PATH` consumes the canonical
Stage 4 rollup sqlite + per-bundle topics.json and produces a UI
payload that surfaces UMAP coordinates + community labels + NeuroScape
cluster labels + topic keywords.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

import numpy as np


@contextmanager
def _isolated_cwd():
    original = Path.cwd()
    tmp = tempfile.mkdtemp()
    try:
        os.chdir(tmp)
        yield Path(tmp)
    finally:
        os.chdir(original)
        shutil.rmtree(tmp, ignore_errors=True)


def _write_synthetic_rollup(
    sqlite_path: Path, n_abstracts: int = 3
) -> None:
    """Synthesize an `annotations.sqlite` + `cluster_topics` table for testing."""
    sqlite_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(sqlite_path))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE annotations (
                abstract_id INTEGER PRIMARY KEY,
                umap2d_voyage_x REAL,
                umap2d_voyage_y REAL,
                umap3d_voyage_x REAL,
                umap3d_voyage_y REAL,
                umap3d_voyage_z REAL,
                community_voyage_abstract INTEGER,
                neuroscape_cluster_neuroscape_claims INTEGER,
                neuroscape_cluster_distance_neuroscape_claims REAL,
                topic_cluster_voyage_abstract INTEGER
            )
            """
        )
        for aid in range(1, n_abstracts + 1):
            cur.execute(
                "INSERT INTO annotations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid,
                    0.1 * aid, 0.2 * aid,
                    0.3 * aid, 0.4 * aid, 0.5 * aid,
                    aid % 2,  # community
                    5,  # neuroscape cluster
                    0.2,  # angular distance
                    aid % 3,  # topic cluster
                ),
            )
        cur.execute(
            """
            CREATE TABLE cluster_topics (
                clustering_method TEXT NOT NULL,
                model_key TEXT NOT NULL,
                input_source TEXT NOT NULL,
                cluster_id INTEGER NOT NULL,
                topic_keywords TEXT,
                topic_title TEXT,
                topic_description TEXT,
                topic_focus TEXT,
                PRIMARY KEY (clustering_method, model_key, input_source, cluster_id)
            )
            """
        )
        for cid in (0, 1):
            cur.execute(
                "INSERT INTO cluster_topics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "communities", "voyage", "abstract", cid,
                    json.dumps([f"kw_voyage_abstract_{cid}_a", f"kw_voyage_abstract_{cid}_b"]),
                    f"Voyage Abstract Community {cid}",
                    f"Community {cid} description.",
                    "themes",
                ),
            )
        cur.execute(
            "INSERT INTO cluster_topics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "neuroscape_clusters", "neuroscape", "claims", 5,
                json.dumps(["DMN", "resting-state"]),
                "Default Mode Network",
                "DMN-related abstracts (published NeuroScape label).",
                "",
            ),
        )
        for cid in (0, 1, 2):
            cur.execute(
                "INSERT INTO cluster_topics VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "topic_clusters", "voyage", "abstract", cid,
                    json.dumps([f"topic_kw_{cid}_a", f"topic_kw_{cid}_b"]),
                    f"Topic {cid}",
                    f"Topic-cluster {cid} description.",
                    "methodologies",
                ),
            )
        conn.commit()
    finally:
        conn.close()


def _write_synthetic_raw_corpus(path: Path, n_abstracts: int = 3) -> None:
    abstracts = [
        {"id": aid, "title": f"Abstract {aid}", "accepted_for": "Poster"}
        for aid in range(1, n_abstracts + 1)
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"abstracts": abstracts}), encoding="utf-8")


class BuildUIPayloadFromStage4Tests(unittest.TestCase):
    def test_consumes_stage4_rollup(self) -> None:
        """End-to-end SC-004: the new payload surfaces UMAP coords +
        community labels + NeuroScape cluster labels + topic keywords."""
        from ohbm2026.ui import build_ui_payload_from_stage4

        with _isolated_cwd() as tmp:
            sqlite_path = tmp / "data/outputs/analysis/annotations__test.sqlite"
            raw_path = tmp / "data/primary/abstracts.json"
            _write_synthetic_rollup(sqlite_path)
            _write_synthetic_raw_corpus(raw_path)

            payload = build_ui_payload_from_stage4(
                raw_input=raw_path,
                enriched_input=tmp / "nonexistent_enriched.sqlite",
                rollup_sqlite=sqlite_path,
                analysis_root=tmp / "data/outputs/analysis",
            )

            # Manifest signals Stage 4 source
            self.assertEqual(payload["manifest"]["source"], "stage4")
            self.assertEqual(payload["manifest"]["abstract_count"], 3)

            # Search records present and aligned with the raw corpus
            search = payload["search"]
            self.assertEqual(len(search), 3)
            self.assertEqual(search[0]["title"], "Abstract 1")

            # UMAP coordinates surfaced per model
            projection = payload["projection"]["stage4"]
            self.assertIn("voyage", projection)
            self.assertEqual(len(projection["voyage"]["umap2d"]), 3)
            self.assertEqual(len(projection["voyage"]["umap3d"][0]), 3)
            self.assertAlmostEqual(projection["voyage"]["umap2d"][0][0], 0.1)

            # Cluster cells present for each kind
            clusters = payload["clusters"]["stage4"]
            self.assertEqual(len(clusters["communities"]), 1)
            self.assertEqual(len(clusters["neuroscape_clusters"]), 1)
            self.assertEqual(len(clusters["topic_clusters"]), 1)

            # Community metadata has the LLM-grouped Keywords + Title
            community_cell = clusters["communities"][0]
            self.assertEqual(community_cell["model"], "voyage")
            self.assertEqual(community_cell["input"], "abstract")
            cluster0 = next(
                m for m in community_cell["cluster_metadata"] if m["cluster_id"] == 0
            )
            self.assertEqual(cluster0["Title"], "Voyage Abstract Community 0")
            self.assertIn("kw_voyage_abstract_0_a", cluster0["Keywords"])

            # NeuroScape cluster label sourced from published cluster_table
            neuroscape_cell = clusters["neuroscape_clusters"][0]
            self.assertEqual(neuroscape_cell["model"], "neuroscape")
            self.assertEqual(neuroscape_cell["input"], "claims")
            ns_cluster = neuroscape_cell["cluster_metadata"][0]
            self.assertEqual(ns_cluster["Title"], "Default Mode Network")

            # Per-abstract cluster assignment surface
            community_assignments = community_cell["assignments"]
            self.assertEqual(len(community_assignments), 3)
            self.assertEqual(community_assignments[0]["id"], 1)

    def test_missing_rollup_raises_uibuilderror(self) -> None:
        from ohbm2026.ui import UIBuildError, build_ui_payload_from_stage4

        with _isolated_cwd() as tmp:
            raw_path = tmp / "data/primary/abstracts.json"
            _write_synthetic_raw_corpus(raw_path)
            with self.assertRaises(UIBuildError):
                build_ui_payload_from_stage4(
                    raw_input=raw_path,
                    enriched_input=tmp / "enriched.sqlite",
                    rollup_sqlite=tmp / "nonexistent.sqlite",
                    analysis_root=tmp / "data/outputs/analysis",
                )

    def test_cli_export_ui_with_analysis_rollup_flag(self) -> None:
        """`ohbmcli export-ui --analysis-rollup ...` writes the Stage 4 payload."""
        import io
        from contextlib import redirect_stdout
        from ohbm2026.ui import export_ui_main

        with _isolated_cwd() as tmp:
            sqlite_path = tmp / "data/outputs/analysis/annotations__test.sqlite"
            raw_path = tmp / "data/primary/abstracts.json"
            output_dir = tmp / "export-out"
            _write_synthetic_rollup(sqlite_path)
            _write_synthetic_raw_corpus(raw_path)

            stdout = io.StringIO()
            with redirect_stdout(stdout):
                rc = export_ui_main([
                    "--raw-input", str(raw_path),
                    "--enriched-input", str(tmp / "nonexistent.sqlite"),
                    "--analysis-rollup", str(sqlite_path),
                    "--analysis-root", str(tmp / "data/outputs/analysis"),
                    "--output-dir", str(output_dir),
                ])
            self.assertEqual(rc, 0)
            self.assertTrue((output_dir / "manifest.json").exists())
            self.assertTrue((output_dir / "clusters.json").exists())
            self.assertTrue((output_dir / "projection.umap.json").exists())
            manifest = json.loads((output_dir / "manifest.json").read_text())
            self.assertEqual(manifest["source"], "stage4")


if __name__ == "__main__":
    unittest.main()
