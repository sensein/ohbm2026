"""T047 — Stage-10 shard LinkML schema validation.

Smoke-tests the canonical schema at
`specs/010-export-redesign/contracts/shards.linkml.yaml`:

1. Parses as YAML.
2. Declares every per-table class the parquet emitter writes.
3. Each class declares the required slots / attributes used by the
   browser-side decoder (loader.ts → shards.ts type definitions).
4. The lint script (`scripts/lint_schema.py`) exits 0 against the schema.

Does not run the full LinkML validator against actual parquet data —
that's an integration-level check the bench harness would own when a
larger end-to-end test landed. The class/slot presence assertions here
catch the regressions that matter for the UI contract.
"""

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path

import yaml


_ROOT = Path(__file__).resolve().parents[1]
SCHEMA = _ROOT / "specs" / "010-export-redesign" / "contracts" / "shards.linkml.yaml"
LINT = _ROOT / "scripts" / "lint_schema.py"


class TestShardsSchema(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with SCHEMA.open() as f:
            cls.schema = yaml.safe_load(f)

    def test_parses_as_yaml(self) -> None:
        self.assertIsInstance(self.schema, dict)
        self.assertEqual(self.schema.get("name"), "ohbm_shards")

    def test_has_every_per_table_class(self) -> None:
        classes = self.schema.get("classes", {})
        expected = {
            "Abstract",
            "Author",
            "CellRow",
            "TopicRecord",
            "NeighborRow",
            "EnrichmentClaim",
            "EnrichmentFigure",
            "Manifest",
        }
        missing = expected - set(classes)
        self.assertFalse(missing, msg=f"Missing classes: {sorted(missing)}")

    def test_abstract_has_required_attrs(self) -> None:
        attrs = self.schema["classes"]["Abstract"]["attributes"]
        expected = {
            "poster_id",
            "title",
            "accepted_for",
            "sections",
            "topics",
            "methods_checklist",
            "facets",
            "author_ids",
            "reference_dois",
            "reference_urls",
            "reference_titles",
            "poster_standby",
        }
        self.assertFalse(
            expected - set(attrs),
            msg=f"Abstract missing attrs: {sorted(expected - set(attrs))}",
        )
        # poster_id is the int identifier — explicit range check.
        self.assertEqual(attrs["poster_id"]["range"], "integer")
        self.assertTrue(attrs["poster_id"].get("required"))

    def test_author_lists_poster_ids(self) -> None:
        attrs = self.schema["classes"]["Author"]["attributes"]
        self.assertEqual(attrs["poster_ids"]["range"], "integer")
        self.assertTrue(attrs["poster_ids"].get("multivalued"))
        self.assertGreaterEqual(int(attrs["poster_ids"].get("minimum_cardinality", 0)), 1)

    def test_cell_row_has_umap_arrays(self) -> None:
        attrs = self.schema["classes"]["CellRow"]["attributes"]
        self.assertEqual(attrs["umap2d"]["minimum_cardinality"], 2)
        self.assertEqual(attrs["umap2d"]["maximum_cardinality"], 2)
        self.assertEqual(attrs["umap3d"]["minimum_cardinality"], 3)
        self.assertEqual(attrs["umap3d"]["maximum_cardinality"], 3)

    def test_no_range_any_anywhere(self) -> None:
        """SC-203: no `range: Any` slots in the redesigned schema."""
        raw = SCHEMA.read_text()
        offending = [
            (i + 1, ln) for i, ln in enumerate(raw.splitlines())
            if ln.lstrip().startswith("range:") and ln.split(":", 1)[1].strip() == "Any"
        ]
        self.assertEqual(
            offending,
            [],
            msg=f"Found {len(offending)} `range: Any` slot(s): {offending}",
        )

    def test_lint_script_passes(self) -> None:
        """`scripts/lint_schema.py` exits 0 against the canonical schema."""
        result = subprocess.run(
            [sys.executable, str(LINT), str(SCHEMA)],
            capture_output=True,
            text=True,
            cwd=_ROOT,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"lint failed:\nstdout: {result.stdout}\nstderr: {result.stderr}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
