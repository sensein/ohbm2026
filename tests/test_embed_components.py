"""Golden tests for `src/ohbm2026/embed_components.py`.

Covers the six default components + the partial-coverage
`inference_claims`. Verifies whitespace normalization, HTML→markdown
conversion, claims concatenation order, and the empty-component
contract (empty string means "abstract absent for this component").
"""

from __future__ import annotations

import unittest

from ohbm2026.embed import components as embed_components


def _record(
    *,
    abstract_id: int = 1,
    title: str = "Cortical processing of auditory motion",
    intro: str = "<p>We studied <b>auditory motion</b> in fMRI.</p>",
    methods: str = "Subjects listened to moving tones in a 7T scanner.",
    results: str = "We observed a 23 percent decrease in BOLD signal.",
    conclusion: str = "Auditory motion suppresses auditory cortex.",
    claims: list[dict] | None = None,
) -> dict:
    return {
        "id": abstract_id,
        "title": title,
        "responses": [
            {"question_name": "Introduction", "value": intro},
            {"question_name": "Methods", "value": methods},
            {"question_name": "Results", "value": results},
            {"question_name": "Conclusion", "value": conclusion},
        ],
        "claims": claims if claims is not None else [
            {"claim": "BOLD decreased 23 percent.", "claim_type": "EXPLICIT"},
            {"claim": "Auditory cortex is suppressed.", "claim_type": "IMPLICIT"},
            {"claim": "Subjects were attending.", "claim_type": "EXPLICIT"},
        ],
    }


class AssembleComponentTests(unittest.TestCase):
    def test_title_returns_normalized_string(self) -> None:
        record = _record(title="   Cortical    processing   ")
        self.assertEqual(
            embed_components.assemble_component(record, "title"),
            "Cortical processing",
        )

    def test_introduction_strips_html(self) -> None:
        out = embed_components.assemble_component(_record(), "introduction")
        # html_to_markdown collapses tags; we then collapse whitespace.
        self.assertIn("auditory motion", out)
        self.assertNotIn("<b>", out)
        self.assertNotIn("</b>", out)

    def test_methods_results_conclusion_each_resolve(self) -> None:
        record = _record()
        for comp, expected_substring in [
            ("methods", "7T scanner"),
            ("results", "23 percent decrease"),
            ("conclusion", "suppresses auditory cortex"),
        ]:
            with self.subTest(comp=comp):
                self.assertIn(
                    expected_substring,
                    embed_components.assemble_component(record, comp),
                )

    def test_section_case_insensitive(self) -> None:
        record = _record()
        record["responses"][0]["question_name"] = "INTRODUCTION"
        self.assertIn(
            "auditory motion",
            embed_components.assemble_component(record, "introduction"),
        )

    def test_claims_concatenates_in_order(self) -> None:
        out = embed_components.assemble_component(_record(), "claims")
        chunks = out.split("\n\n")
        self.assertEqual(chunks[0], "BOLD decreased 23 percent.")
        self.assertEqual(chunks[1], "Auditory cortex is suppressed.")
        self.assertEqual(chunks[2], "Subjects were attending.")

    def test_inference_claims_filters_to_implicit_only(self) -> None:
        out = embed_components.assemble_component(_record(), "inference_claims")
        self.assertEqual(out, "Auditory cortex is suppressed.")

    def test_empty_component_returns_empty_string(self) -> None:
        record = _record(intro="", methods="   ", results="<p></p>")
        for comp in ("introduction", "methods", "results"):
            with self.subTest(comp=comp):
                self.assertEqual(
                    embed_components.assemble_component(record, comp),
                    "",
                )

    def test_no_implicit_claims_yields_empty_inference_claims(self) -> None:
        record = _record(claims=[
            {"claim": "Only explicit.", "claim_type": "EXPLICIT"},
        ])
        self.assertEqual(
            embed_components.assemble_component(record, "inference_claims"),
            "",
        )

    def test_unknown_component_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            embed_components.assemble_component(_record(), "abstract")

    def test_assemble_all_components_returns_dict(self) -> None:
        out = embed_components.assemble_all_components(
            _record(), embed_components.DEFAULT_COMPONENTS,
        )
        self.assertEqual(set(out.keys()), set(embed_components.DEFAULT_COMPONENTS))
        self.assertTrue(out["title"])
        self.assertTrue(out["claims"])

    def test_abstract_has_component_probe(self) -> None:
        record = _record()
        self.assertTrue(embed_components.abstract_has_component(record, "title"))
        empty_record = _record(claims=[])
        self.assertFalse(
            embed_components.abstract_has_component(empty_record, "claims")
        )


if __name__ == "__main__":
    unittest.main()
