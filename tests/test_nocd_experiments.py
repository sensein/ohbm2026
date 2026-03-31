import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from ohbm2026 import nocd_experiments


def _load_script_module(name: str):
    module_path = Path(__file__).resolve().parents[1] / "scripts" / name
    spec = importlib.util.spec_from_file_location(name.replace(".py", ""), module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NOCDExperimentsTest(unittest.TestCase):
    def test_discover_checkpoint_configs_uses_available_portable_checkpoints_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_dir = Path(tmpdir)
            (checkpoint_dir / "nocd-gcn-structural-mag_med.pt").write_bytes(b"pt")
            (checkpoint_dir / "nocd-gcn-structural-mag_med.json").write_text(
                json.dumps(
                    {
                        "name": "nocd-gcn-structural-mag_med",
                        "distribution": [{"name": "nocd-gcn-structural-mag_med.pt"}],
                        "cr:modelArchitecture": "gcn",
                        "cr:featureType": "structural",
                        "cr:hiddenDims": [64, 32],
                        "cr:nComponents": None,
                    }
                ),
                encoding="utf-8",
            )
            (checkpoint_dir / "nocd-gcn-spectral-k32-mag_med.pt").write_bytes(b"pt")
            (checkpoint_dir / "nocd-gcn-spectral-k32-mag_med.json").write_text(
                json.dumps(
                    {
                        "name": "nocd-gcn-spectral-k32-mag_med",
                        "distribution": [{"name": "nocd-gcn-spectral-k32-mag_med.pt"}],
                        "cr:modelArchitecture": "gcn",
                        "cr:featureType": "spectral",
                        "cr:hiddenDims": [64, 32],
                        "cr:nComponents": 32,
                    }
                ),
                encoding="utf-8",
            )
            (checkpoint_dir / "nocd-gcn-X.pt").write_bytes(b"pt")
            (checkpoint_dir / "nocd-gcn-X.json").write_text(
                json.dumps(
                    {
                        "name": "nocd-gcn-X",
                        "distribution": [{"name": "nocd-gcn-X.pt"}],
                        "cr:modelArchitecture": "gcn",
                        "cr:featureType": "X",
                        "cr:hiddenDims": [64, 32],
                        "cr:nComponents": None,
                    }
                ),
                encoding="utf-8",
            )

            configs, compatibility = nocd_experiments.discover_checkpoint_configs(checkpoint_dir)

            self.assertEqual(
                [config["checkpoint_name"] for config in configs],
                [
                    "nocd-gcn-spectral-k32-mag_med.pt",
                    "nocd-gcn-structural-mag_med.pt",
                ],
            )
            self.assertEqual(
                [config["model_key"] for config in configs],
                [
                    "nocd_gcn_spectral_k32_mag_med_pretrained",
                    "nocd_gcn_structural_mag_med_pretrained",
                ],
            )
            self.assertEqual(len(compatibility), 1)
            self.assertEqual(compatibility[0]["checkpoint_name"], "nocd-gcn-X.pt")
            classic = nocd_experiments.select_classic_checkpoint_config(configs)
            self.assertEqual(classic["checkpoint_name"], "nocd-gcn-structural-mag_med.pt")
            self.assertEqual(classic["model_key"], "classic_nocd_gcn_structural_mag_med_pretrained")

    def test_discover_load_and_prepare_embedding_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            bundle = root / "demo_embeddings"
            bundle.mkdir(parents=True, exist_ok=True)
            np.save(
                bundle / "vectors.npy",
                np.asarray(
                    [
                        [1.0, 0.0],
                        [0.9, 0.1],
                        [0.0, 1.0],
                    ],
                    dtype=np.float32,
                ),
            )
            (bundle / "metadata.json").write_text(
                json.dumps({"ids": [101, 102, 103]}, indent=2),
                encoding="utf-8",
            )

            discovered = nocd_experiments.discover_embedding_sources(root)
            self.assertEqual(discovered, [bundle])

            source = nocd_experiments.load_embedding_source(bundle)
            self.assertEqual(source.name, "demo_embeddings")
            self.assertEqual(source.ids, [101, 102, 103])
            self.assertEqual(source.matrix.shape, (3, 2))

            prepared = nocd_experiments.prepare_source_artifacts(source, root / "prepared", neighbor_count=2)
            self.assertTrue((root / "prepared" / "graph.npz").exists())
            self.assertTrue((root / "prepared" / "features.npz").exists())
            self.assertTrue((root / "prepared" / "graph_info.json").exists())
            self.assertEqual(prepared["adjacency"].shape, (3, 3))
            self.assertEqual(prepared["features"].shape, (3, 2))

            filtered = nocd_experiments.filter_embedding_sources(discovered, ["demo_embeddings"])
            self.assertEqual(filtered, [bundle])

    def test_summary_markdown_helpers_include_requested_metrics(self) -> None:
        classic_rows = nocd_experiments.annotate_community_structure_scores(
            [
                {
                    "embedding_source": "voyage_stage2_published",
                    "coverage": 0.4,
                    "density": 0.05,
                    "conductance": 0.6,
                    "clustering_coefficient": 0.42,
                    "assigned_node_fraction": 0.7,
                    "multi_membership_fraction": 0.1,
                    "nonempty_community_count": 12,
                }
            ]
        )
        classic = nocd_experiments.classic_summary_markdown(classic_rows, "nocd-gcn-structural.pt")
        sweep_rows = nocd_experiments.annotate_community_structure_scores(
            [
                {
                    "model_key": "gcn_structural_pretrained",
                    "embedding_source": "voyage_stage2_published",
                    "coverage": 0.4,
                    "density": 0.05,
                    "conductance": 0.6,
                    "clustering_coefficient": 0.42,
                    "assigned_node_fraction": 0.7,
                    "multi_membership_fraction": 0.1,
                    "nonempty_community_count": 12,
                }
            ]
        )
        sweep = nocd_experiments.checkpoint_sweep_summary_markdown(sweep_rows)

        self.assertIn("Coverage", classic)
        self.assertIn("Conductance", classic)
        self.assertIn("gcn_structural_pretrained", sweep)
        self.assertIn("Clustering coeff.", sweep)
        self.assertIn("Score", classic)
        self.assertIn("Rank", sweep)

    def test_annotate_community_structure_scores_demotes_degenerate_rows(self) -> None:
        rows = nocd_experiments.annotate_community_structure_scores(
            [
                {
                    "model_key": "good",
                    "embedding_source": "voyage_stage2_published",
                    "coverage": 0.6,
                    "density": 0.08,
                    "conductance": 0.3,
                    "clustering_coefficient": 0.02,
                    "assigned_node_fraction": 0.8,
                    "multi_membership_fraction": 0.2,
                    "nonempty_community_count": 8,
                    "degenerate_single_community": False,
                },
                {
                    "model_key": "degenerate",
                    "embedding_source": "voyage_stage2_published",
                    "coverage": 1.0,
                    "density": 0.01,
                    "conductance": 0.0,
                    "clustering_coefficient": 0.0,
                    "assigned_node_fraction": 1.0,
                    "multi_membership_fraction": 0.0,
                    "nonempty_community_count": 1,
                    "degenerate_single_community": True,
                },
            ]
        )

        self.assertEqual(rows[0]["model_key"], "good")
        self.assertEqual(rows[0]["community_structure_rank"], 1)
        self.assertEqual(rows[1]["model_key"], "degenerate")

    def test_new_nocd_scripts_reject_non_empty_output_directory(self) -> None:
        classic_runner = _load_script_module("run_nocd_classic_predict_experiment.py")
        sweep_runner = _load_script_module("run_nocd_checkpoint_sweep_experiment.py")
        with tempfile.TemporaryDirectory() as tmpdir:
            output_root = Path(tmpdir) / "outputs"
            output_root.mkdir(parents=True, exist_ok=True)
            (output_root / "summary.json").write_text("{}", encoding="utf-8")

            with self.assertRaises(FileExistsError):
                classic_runner.validate_output_root(output_root, allow_existing_output=False)
            with self.assertRaises(FileExistsError):
                sweep_runner.validate_output_root(output_root, allow_existing_output=False)

    def test_nocd_scripts_default_to_artifact_embedding_root(self) -> None:
        classic_runner = _load_script_module("run_nocd_classic_predict_experiment.py")
        sweep_runner = _load_script_module("run_nocd_checkpoint_sweep_experiment.py")

        self.assertEqual(
            classic_runner.build_parser().parse_args([]).embeddings_root,
            "data/outputs/experiments/embeddings",
        )
        self.assertEqual(
            sweep_runner.build_parser().parse_args([]).embeddings_root,
            "data/outputs/experiments/embeddings",
        )
        self.assertEqual(classic_runner.build_parser().parse_args([]).embedding_source, [])
        self.assertEqual(sweep_runner.build_parser().parse_args([]).embedding_source, [])


if __name__ == "__main__":
    unittest.main()
