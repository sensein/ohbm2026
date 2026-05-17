"""T008 — manifest builder tests (incl. CA-007 no-hardcoded-facets check)."""

from __future__ import annotations

import ast
import inspect
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data import manifest as manifest_module
from ohbm2026.ui_data.manifest import build_manifest, discover_cells, discover_topic_kinds

from tests._ui_data_fixtures import BUILD_INFO, CORPUS_PAYLOAD, write_fixtures


class TestManifestShape(unittest.TestCase):
    def test_manifest_shape(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            abstracts = [a for a in CORPUS_PAYLOAD["abstracts"] if a["accepted_for"] != "Withdrawn"]
            # Massage to the post-build_abstracts shape (the manifest reads
            # the per-abstract `facets` and `topics` blocks).
            normalized = [
                {
                    "abstract_id": a["id"],
                    "accepted_for": a["accepted_for"],
                    "topics": {"primary": next((r["value"].split("|")[0] for r in a["responses"] if r["question_name"].startswith("Primary")), ""),
                                 "secondary": next((r["value"].split("|")[0] for r in a["responses"] if r["question_name"].startswith("Secondary")), "")},
                    "facets": {"keywords": ["Aging"], "methods": ["Functional MRI"]},
                }
                for a in abstracts
            ]
            m = build_manifest(
                abstracts=normalized,
                rollup_db=paths["rollup"],
                build_info=BUILD_INFO,
            )
        # Shape contract
        self.assertEqual(m["schema_version"], "ui.v1")
        self.assertEqual(m["build_info"], BUILD_INFO)
        self.assertEqual(m["corpus_count"], len(normalized))
        self.assertEqual(m["default_cell"], {"model": "neuroscape", "input": "abstract"})
        self.assertIn("neuroscape", m["models"])
        self.assertIn("minilm", m["models"])
        self.assertIn("abstract", m["inputs"])
        self.assertIn("methods", m["inputs"])
        self.assertGreaterEqual(len(m["cells"]), 1)
        cell_keys = {c["cell_key"] for c in m["cells"]}
        self.assertIn("neuroscape_abstract", cell_keys)
        # Each cell has shard_url + topic_shards
        for cell in m["cells"]:
            self.assertTrue(cell["shard_url"].startswith("data/cells/"))
            self.assertIsInstance(cell["topic_shards"], dict)
        # Facets are present, alphabetical, derived from data
        facet_keys = [f["key"] for f in m["facets"]]
        self.assertIn("primary_topic", facet_keys)
        self.assertIn("species", facet_keys)
        # search block
        self.assertEqual(m["search"]["minilm_dim"], 384)
        self.assertEqual(m["search"]["minilm_dtype"], "int8")
        self.assertEqual(m["search"]["minilm_vectors_build_info_url"], "data/search/minilm_vectors.build_info.json")

    def test_discover_cells_returns_distinct_pairs(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            cells = discover_cells(paths["rollup"])
        # The fixture has neuroscape × {abstract, methods} + minilm × {abstract, methods}.
        self.assertIn(("neuroscape", "abstract"), cells)
        self.assertIn(("minilm", "methods"), cells)

    def test_discover_topic_kinds_returns_triples(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            kinds = discover_topic_kinds(paths["rollup"])
        # Includes communities, topic_clusters, neuroscape_clusters.
        triples = {(k, m, i) for k, m, i in kinds}
        self.assertIn(("communities", "neuroscape", "abstract"), triples)
        self.assertIn(("neuroscape_clusters", "neuroscape", "abstract"), triples)


class TestNoHardcodedFacets(unittest.TestCase):
    """CA-007 — the facet *options* in the manifest are discovered, not hardcoded.

    The KEYS are documented constants (FACET_KEYS) — those are intentional and
    serve as the schema. What's forbidden is hardcoded option *lists* inside
    a function body — e.g. ``return ["Human", "Mouse", ...]``. Scan the
    manifest source AST for any function that returns a non-empty list literal
    of strings; flag if found.
    """

    def test_no_function_returns_hardcoded_string_lists(self) -> None:
        source = inspect.getsource(manifest_module)
        tree = ast.parse(source)
        offenders: list[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Return) and isinstance(child.value, ast.List):
                    items = child.value.elts
                    if items and all(isinstance(e, ast.Constant) and isinstance(e.value, str) for e in items):
                        offenders.append(node.name)
                        break
        self.assertEqual(
            offenders,
            [],
            f"Hardcoded string-list returns in manifest.py functions: {offenders}",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
