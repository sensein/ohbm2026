"""Tests for ``ohbm2026.atlas_package.provenance.normalise_path``.

Spec: ``specs/015-neuroscape-context/`` — CA-008 + research R-009
``AtlasProvenanceError`` contract. Every Stage 15 provenance field
that names a filesystem path MUST be repo-relative; absolute paths,
``$HOME``-prefixed paths, and parent-relative escapes are rejected
loudly (Principle VIII).

The helper accepts either a ``str`` or a ``pathlib.Path``; it returns
a repo-relative ``str`` on the happy path and raises
``AtlasProvenanceError`` with structured kwargs on violation. Paths
that are already repo-relative pass through unchanged.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ohbm2026 import exceptions
from ohbm2026.atlas_package import provenance


class NormalisePathHappyPathTests(unittest.TestCase):
    def test_repo_relative_str_passes_through(self) -> None:
        self.assertEqual(
            provenance.normalise_path("data/outputs/parquets/abcd1234/ohbm2026.parquet"),
            "data/outputs/parquets/abcd1234/ohbm2026.parquet",
        )

    def test_repo_relative_path_object_is_converted_to_str(self) -> None:
        p = Path("data/inputs/neuroscape-source/v101/Data/Models/domain_embedding_model.pth")
        out = provenance.normalise_path(p)
        self.assertIsInstance(out, str)
        self.assertEqual(out, str(p))

    def test_repo_relative_with_dotdot_inside_is_resolved(self) -> None:
        # A `data/cache/../outputs/foo` is repo-rooted and resolvable;
        # normalise it to the canonical form rather than rejecting.
        self.assertEqual(
            provenance.normalise_path("data/cache/../outputs/parquets/x.parquet"),
            "data/outputs/parquets/x.parquet",
        )


class NormalisePathRejectionTests(unittest.TestCase):
    def test_absolute_unix_path_raises(self) -> None:
        with self.assertRaises(exceptions.AtlasProvenanceError) as ctx:
            provenance.normalise_path("/Users/op/data/outputs/parquets/x.parquet")
        self.assertEqual(ctx.exception.expected, "<repo-relative>")
        self.assertTrue(ctx.exception.actual.startswith("/Users/"))

    def test_tilde_prefix_raises(self) -> None:
        with self.assertRaises(exceptions.AtlasProvenanceError) as ctx:
            provenance.normalise_path("~/work/data/outputs/parquets/x.parquet")
        self.assertEqual(ctx.exception.expected, "<repo-relative>")
        self.assertTrue(ctx.exception.actual.startswith("~"))

    def test_parent_escape_raises(self) -> None:
        # `..` that escapes the repo root is rejected. `data/cache/../outputs/`
        # stays inside the repo so it is accepted (see happy-path test);
        # `../../etc/passwd` does not.
        with self.assertRaises(exceptions.AtlasProvenanceError) as ctx:
            provenance.normalise_path("../../etc/passwd")
        self.assertEqual(ctx.exception.expected, "<repo-relative>")
        self.assertTrue("..", ctx.exception.actual)

    def test_path_object_with_absolute_root_raises(self) -> None:
        with self.assertRaises(exceptions.AtlasProvenanceError):
            provenance.normalise_path(Path("/tmp/x.parquet"))

    def test_empty_string_raises(self) -> None:
        with self.assertRaises(exceptions.AtlasProvenanceError):
            provenance.normalise_path("")


class NormalisePathFieldKwargTests(unittest.TestCase):
    def test_field_kwarg_is_propagated_into_the_raised_error(self) -> None:
        with self.assertRaises(exceptions.AtlasProvenanceError) as ctx:
            provenance.normalise_path("/abs/path", field="inputs.ohbm2026_parquet")
        self.assertEqual(ctx.exception.field, "inputs.ohbm2026_parquet")


if __name__ == "__main__":
    unittest.main()
