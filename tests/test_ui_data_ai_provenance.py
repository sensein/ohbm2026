"""Stage 15.4 follow-up — ``enrichment.ai_provenance`` survives the parquet round-trip.

Spec 008 FR-023 wires a ``✨ AI`` pill in the OHBM 2026 detail panel that
reads ``enrichment_shard.ai_provenance.{claims_model_id, figures_model_id}``.
The Stage-10 parquet redesign (spec 010) flattens the enrichment envelope
into two per-row tables (``enrichment_claims``, ``enrichment_figures``);
the envelope-level ``ai_provenance`` block has no natural home in that
shape and was silently dropped, so the loader served ``ai_provenance: {}``
and the pill never displayed in production.

The follow-up persists ``ai_provenance`` inside the parquet manifest JSON
(``manifest_with_format["enrichment_ai_provenance"]``) so the browser-side
loader can recover it. These tests pin the round-trip Python-side: write
a real parquet with a populated enrichment envelope, decode the manifest,
and assert the model ids survive.
"""

from __future__ import annotations

import io
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pyarrow.parquet as pq

from ohbm2026.ui_data.formats import parquet_single


def _empty_envelope() -> dict:
    return {"schema_version": "v", "build_info": {}, "records": []}


def _abstracts_envelope() -> dict:
    # Minimal abstracts envelope. ``sections`` + ``topics`` need at
    # least one key so pyarrow can infer a non-empty STRUCT schema
    # (parquet cannot serialise an empty-child struct).
    return {
        "abstracts": [
            {
                "poster_id": 101,
                "title": "t",
                "accepted_for": "Poster",
                "sections": {"abstract_text": "body"},
                "topics": {"keywords": ["k"]},
                "facets": {},
                "methods_checklist": [],
                "author_ids": [5000],
                "reference_dois": [],
                "reference_urls": [],
                "reference_titles": [],
            }
        ]
    }


def _authors_envelope() -> dict:
    return {"authors": [{"id": 5000, "name": "Author One", "poster_ids": [101]}]}


def _decode_manifest_json(parquet_path: Path) -> dict:
    """Open the outer parquet, find the manifest blob, parse it."""

    table = pq.read_table(parquet_path)
    names = table.column("table_name").to_pylist()
    blobs = table.column("table_bytes").to_pylist()
    midx = names.index("manifest")
    inner = pq.read_table(io.BytesIO(blobs[midx]))
    manifest_json = inner.column("manifest_json").to_pylist()[0]
    return json.loads(manifest_json)


def _shared_write_kwargs(
    output_dir: Path, enrichment_envelope: dict
) -> dict:
    return dict(
        output_dir=output_dir,
        build_info={"corpus_state_key": "abc", "rollup_state_key": "def"},
        conference_id="ohbm2026",
        manifest={
            "schema_version": "abstracts.v2",
            "conference_id": "ohbm2026",
            "build_info": {"corpus_state_key": "abc"},
        },
        abstracts_envelope=_abstracts_envelope(),
        authors_envelope=_authors_envelope(),
        cells_envelopes={},
        topics_envelopes={},
        neighbors_envelopes={},
        enrichment_envelope=enrichment_envelope,
        minilm_bin=None,
        minilm_sidecar={"schema_version": "search.minilm_vectors.v1"},
    )


class EnrichmentAiProvenanceManifestTests(unittest.TestCase):
    def test_ai_provenance_lands_in_manifest_when_populated(self) -> None:
        envelope = {
            "schema_version": "enrichment.v1",
            "build_info": {},
            "ai_provenance": {
                "claims_model_id": "gpt-5.4-mini",
                "figures_model_id": "gpt-5.4-mini",
            },
            "records": {},
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            parquet_single.write(**_shared_write_kwargs(out, envelope))
            manifest = _decode_manifest_json(out / parquet_single.DEFAULT_OUTPUT_FILENAME)
        self.assertIn("enrichment_ai_provenance", manifest)
        self.assertEqual(
            manifest["enrichment_ai_provenance"],
            {
                "claims_model_id": "gpt-5.4-mini",
                "figures_model_id": "gpt-5.4-mini",
            },
        )

    def test_ai_provenance_omitted_when_envelope_is_empty(self) -> None:
        """A corpus with no enrichment must not carry a stale, half-
        populated ai_provenance block — the loader treats absence as
        'no pill' which is the correct UX."""
        envelope = {
            "schema_version": "enrichment.v1",
            "build_info": {},
            "ai_provenance": {"claims_model_id": None, "figures_model_id": None},
            "records": {},
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            parquet_single.write(**_shared_write_kwargs(out, envelope))
            manifest = _decode_manifest_json(out / parquet_single.DEFAULT_OUTPUT_FILENAME)
        self.assertNotIn("enrichment_ai_provenance", manifest)

    def test_partial_provenance_partial_keys_only(self) -> None:
        """Mid-cycle corpus that only has claim model attribution (no
        figures yet) must still surface the available id."""
        envelope = {
            "schema_version": "enrichment.v1",
            "build_info": {},
            "ai_provenance": {
                "claims_model_id": "gpt-5.4-mini",
                "figures_model_id": None,
            },
            "records": {},
        }
        with TemporaryDirectory() as tmp:
            out = Path(tmp)
            parquet_single.write(**_shared_write_kwargs(out, envelope))
            manifest = _decode_manifest_json(out / parquet_single.DEFAULT_OUTPUT_FILENAME)
        self.assertEqual(
            manifest["enrichment_ai_provenance"],
            {"claims_model_id": "gpt-5.4-mini", "figures_model_id": None},
        )


if __name__ == "__main__":
    unittest.main()
