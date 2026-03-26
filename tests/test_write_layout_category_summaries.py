import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "write_layout_category_summaries.py"
    spec = importlib.util.spec_from_file_location("write_layout_category_summaries", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load write_layout_category_summaries module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WriteLayoutCategorySummariesTest(unittest.TestCase):
    def test_build_layout_category_summary_uses_cluster_keywords_when_available(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            clusters_dir = root / "clusters"
            clusters_dir.mkdir(parents=True, exist_ok=True)
            (clusters_dir / "cluster_assignments.json").write_text("{}", encoding="utf-8")
            (clusters_dir / "cluster_summaries.json").write_text(
                json.dumps(
                    {
                        "clusters": [
                            {
                                "cluster_id": 7,
                                "label": "voyage alpha",
                                "keywords": ["alpha", "beta"],
                                "representative_abstracts": [{"id": 1, "title": "Representative title"}],
                                "size": 12,
                            }
                        ]
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            proposal_dir = root / "proposal"
            proposal_dir.mkdir(parents=True, exist_ok=True)
            (proposal_dir / "proposal.json").write_text(
                json.dumps(
                    {
                        "metadata": {
                            "layout_label_system": "voyage_stage2_spectral_31",
                            "layout_label_source": str(clusters_dir / "cluster_assignments.json"),
                        },
                        "assignments": [
                            {
                                "abstract_id": 1,
                                "accepted_for": "Poster",
                                "block_id": 1,
                                "poster_number": 1,
                                "title": "One",
                                "layout_exact_label": "voyage alpha",
                                "layout_parent_label": "voyage alpha",
                                "primary_category": "Topic A :: Sub 1",
                            },
                            {
                                "abstract_id": 2,
                                "accepted_for": "Oral",
                                "block_id": 2,
                                "poster_number": 2,
                                "title": "Two",
                                "layout_exact_label": "voyage alpha",
                                "layout_parent_label": "voyage alpha",
                                "primary_category": "Topic A :: Sub 1",
                            },
                        ],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            summary = module.build_layout_category_summary(proposal_dir)
            markdown = module.build_layout_category_markdown(summary)

        self.assertEqual(summary["category_count"], 1)
        self.assertEqual(summary["categories"][0]["keywords"], ["alpha", "beta"])
        self.assertEqual(summary["categories"][0]["block_counts"], {"1": 1, "2": 1})
        self.assertIn("Keywords: alpha, beta", markdown)
        self.assertIn("Block split: June 15-16=`1`, June 17-18=`1`", markdown)


if __name__ == "__main__":
    unittest.main()
