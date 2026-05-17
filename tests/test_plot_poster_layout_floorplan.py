import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_floorplan_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "layout" / "plot_poster_layout_floorplan.py"
    spec = importlib.util.spec_from_file_location("plot_poster_layout_floorplan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load plot_poster_layout_floorplan module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PosterLayoutFloorplanPlotTest(unittest.TestCase):
    def test_main_writes_combined_layout_review_with_legacy_aliases(self) -> None:
        module = _load_floorplan_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            proposal_dir = Path(tmpdir) / "proposal"
            proposal_dir.mkdir(parents=True, exist_ok=True)
            umap_path = Path(tmpdir) / "projection.umap.json"
            umap_path.write_text(
                json.dumps(
                    {
                        "umap": {
                            "points": [
                                {"id": 1, "title": "One", "primary_topic": "Parent A", "x": 0.1, "y": 0.2},
                                {"id": 2, "title": "Two", "primary_topic": "Parent B", "x": 0.4, "y": 0.5},
                                {"id": 3, "title": "Other", "primary_topic": "Parent C", "x": 0.8, "y": 0.9},
                            ]
                        }
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            proposal = {
                "metadata": {
                    "layout_label_system": "voyage_stage2_kmeans_25",
                },
                "assignments": [
                    {
                        "abstract_id": 1,
                        "title": "One",
                        "standby_session": 1,
                        "standby_session_label": "June 15 standby",
                        "block_id": 1,
                        "block_label": "June 15-16 block",
                        "block_position": 1,
                        "poster_number": 1,
                        "primary_parent_category": "Parent A",
                        "primary_category": "Parent A :: Sub A",
                        "layout_exact_label": "voyage alpha",
                    },
                    {
                        "abstract_id": 2,
                        "title": "Two",
                        "standby_session": 3,
                        "standby_session_label": "June 17 standby",
                        "block_id": 2,
                        "block_label": "June 17-18 block",
                        "block_position": 1,
                        "poster_number": 1611,
                        "primary_parent_category": "Parent B",
                        "primary_category": "Parent B :: Sub B",
                        "layout_exact_label": "voyage beta",
                    },
                ]
            }
            (proposal_dir / "proposal.json").write_text(json.dumps(proposal, indent=2), encoding="utf-8")

            result = module.main(["--proposal-dir", str(proposal_dir), "--ui-umap-input", str(umap_path)])
            review_html = (proposal_dir / "layout_review.html").read_text(encoding="utf-8")
            primary_html = (proposal_dir / "layout_primary_category.html").read_text(encoding="utf-8")
            semantic_html = (proposal_dir / "layout_semantic_category.html").read_text(encoding="utf-8")

        self.assertEqual(result, 0)
        self.assertIn("Poster layout review: proposal", review_html)
        self.assertIn("June 15-16 block", review_html)
        self.assertIn("UI UMAP", review_html)
        self.assertIn("block-1-plot", review_html)
        self.assertIn("block-2-plot", review_html)
        self.assertIn("umap-plot", review_html)
        self.assertIn("Lasso or click in any plot", review_html)
        self.assertIn("linked-selection-status", review_html)
        self.assertIn("data-filter-group=\"categorical_primary_label\"", review_html)
        self.assertIn("data-filter-group=\"voyage25_label\"", review_html)
        self.assertIn("data-filter-group=\"voyage31_label\"", review_html)
        self.assertIn("data-filter-group=\"claims28_label\"", review_html)
        self.assertIn("layout-filter-state", review_html)
        self.assertIn("poster-detail-card", review_html)
        self.assertIn("category-correspondence", review_html)
        self.assertIn("Categorical primary", review_html)
        self.assertIn("Voyage 25", review_html)
        self.assertIn("Voyage 31", review_html)
        self.assertIn("Claims 28", review_html)
        self.assertIn("Unknown", review_html)
        self.assertNotIn("Category Selectors</h2>", review_html)
        self.assertNotIn('"scaleanchor":"x"', review_html)
        self.assertEqual(primary_html, review_html)
        self.assertEqual(semantic_html, review_html)


if __name__ == "__main__":
    unittest.main()
