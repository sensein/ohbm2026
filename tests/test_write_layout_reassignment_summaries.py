import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


def _load_module():
    module_path = Path(__file__).resolve().parents[1] / "scripts" / "write_layout_reassignment_summaries.py"
    spec = importlib.util.spec_from_file_location("write_layout_reassignment_summaries", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load write_layout_reassignment_summaries module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LayoutReassignmentSummariesTest(unittest.TestCase):
    def test_build_reassignment_summary_crosswalks_old_and_new_labels(self) -> None:
        module = _load_module()
        with tempfile.TemporaryDirectory() as tmpdir:
            proposal_dir = Path(tmpdir) / "proposal"
            proposal_dir.mkdir(parents=True, exist_ok=True)
            (proposal_dir / "proposal.json").write_text(
                json.dumps(
                    {
                        "assignments": [
                            {
                                "abstract_id": 1,
                                "poster_number": 1,
                                "title": "One",
                                "base_layout_label_system": "voyage_stage2_spectral_31",
                                "base_layout_exact_label": "old alpha",
                                "layout_exact_label": "new one",
                            },
                            {
                                "abstract_id": 2,
                                "poster_number": 2,
                                "title": "Two",
                                "base_layout_label_system": "voyage_stage2_spectral_31",
                                "base_layout_exact_label": "old alpha",
                                "layout_exact_label": "new one",
                            },
                            {
                                "abstract_id": 3,
                                "poster_number": 3,
                                "title": "Three",
                                "base_layout_label_system": "voyage_stage2_spectral_31",
                                "base_layout_exact_label": "old beta",
                                "layout_exact_label": "new two",
                            },
                        ],
                        "metadata": {"layout_label_system": "voyage_stage2_olo_contiguous_31"},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )

            summary = module.build_reassignment_summary(proposal_dir)
            markdown = module.build_reassignment_markdown(summary)

        self.assertEqual(summary["old_category_count"], 2)
        self.assertEqual(summary["new_category_count"], 2)
        self.assertEqual(summary["retained_old_category_count"], 2)
        self.assertEqual(summary["split_old_category_count"], 0)
        self.assertEqual(summary["from_old_to_new"][0]["old_label"], "old alpha")
        self.assertEqual(summary["from_new_to_old"][0]["new_label"], "new one")
        self.assertIn("Old taxonomy: `voyage_stage2_spectral_31`.", markdown)
        self.assertIn("New taxonomy: `voyage_stage2_olo_contiguous_31`.", markdown)


if __name__ == "__main__":
    unittest.main()
