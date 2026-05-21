"""T038 — Stage 11.1 US4 — Stage 1 ``state_key`` field rename.

The Stage-1 emitter writes ``fetch_state_key`` (new) instead of
``state_key`` (legacy). Readers accept both names via the
``read_fetch_state_key`` helper landed in Phase 2 — a
DeprecationWarning fires when the legacy field is encountered so
operators can grep for stale provenance files.

Only the JSON FIELD NAME emitted by Stage 1's provenance + checkpoint
writers is renamed. The Python ``state_key`` variable name, the
``build_state_key`` helper, and the generic ``state_key`` field inside
``artifact_metadata`` (which every stage emits) are intentionally
unchanged — Stage 1's field collided VERBALLY with Stage 6's
``corpus_state_key``; the cross-stage helper is uncontroversial.
"""

from __future__ import annotations

import unittest
import warnings


class TestReadFetchStateKey(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            from ohbm2026.artifacts import read_fetch_state_key
        except ImportError as exc:
            raise unittest.SkipTest(
                f"read_fetch_state_key not yet implemented: {exc}"
            )
        cls.read = staticmethod(read_fetch_state_key)

    def test_reads_new_field_name(self) -> None:
        value = self.read({"fetch_state_key": "abc123"})
        self.assertEqual(value, "abc123")

    def test_reads_legacy_field_with_deprecation_warning(self) -> None:
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            value = self.read({"state_key": "legacy456"})
            self.assertEqual(value, "legacy456")
            self.assertEqual(len(caught), 1)
            self.assertTrue(issubclass(caught[0].category, DeprecationWarning))

    def test_raises_when_neither_field_present(self) -> None:
        with self.assertRaises(KeyError):
            self.read({})


class TestFetchStageEmitsNewFieldName(unittest.TestCase):
    """The fetch-stage provenance/checkpoint writers MUST emit
    ``fetch_state_key``. Verified by reading the module source — the
    full Stage-1 integration test would require a live GraphQL
    endpoint which is out of scope here.
    """

    def test_fetch_stage_writes_fetch_state_key(self) -> None:
        import pathlib

        src = pathlib.Path(__file__).resolve().parents[1]
        stage_py = (src / "src" / "ohbm2026" / "fetch" / "stage.py").read_text()
        # The new field name must appear in the provenance + checkpoint
        # emission paths. Legacy `"state_key": state_key` MUST be gone
        # from the EMISSION sites; the local Python variable still uses
        # `state_key =` which is fine.
        self.assertIn('"fetch_state_key": state_key', stage_py)
        self.assertNotIn('"state_key": state_key', stage_py)


class TestDeployWorkflowTelemetry(unittest.TestCase):
    """The deploy-ui workflow's PR-association retry loop MUST log
    every attempt explicitly so the operator can verify the loop
    actually saved a deploy (SC-006). Static check on the YAML body.
    """

    def setUp(self) -> None:
        import pathlib

        self.workflow = (
            pathlib.Path(__file__).resolve().parents[1]
            / ".github"
            / "workflows"
            / "deploy-ui.yml"
        )

    def test_workflow_file_exists(self) -> None:
        self.assertTrue(self.workflow.exists())

    def test_telemetry_pattern_present(self) -> None:
        body = self.workflow.read_text()
        # Either "attempt N/6" or "PR-association lookup: attempt"
        # must appear in the retry-loop body, AND the success-on-
        # first-try branch must also log so silent success isn't
        # mistaken for a missing retry-loop.
        body_lower = body.lower()
        self.assertIn("attempt", body_lower)
        self.assertTrue(
            "1/6" in body or "first call" in body_lower,
            "first-attempt telemetry missing from deploy-ui.yml",
        )


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
