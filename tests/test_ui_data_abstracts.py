"""T009 — abstracts builder accepted-only invariant tests."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from ohbm2026.ui_data.abstracts import build_abstracts, build_abstracts_records

from tests._ui_data_fixtures import BUILD_INFO, write_fixtures


class TestAcceptedOnlyInvariant(unittest.TestCase):
    def test_no_withdrawn_records_leak(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            records = build_abstracts_records(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
            )
        self.assertEqual(len(records), 2)
        self.assertTrue(all(r["accepted_for"] != "Withdrawn" for r in records))
        # Stage 10: poster_id is the user-facing id; submission 1002 maps
        # to poster 102 in the fixture and must not appear.
        self.assertNotIn(102, {r["poster_id"] for r in records})

    def test_envelope_carries_build_info(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            envelope = build_abstracts(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
                build_info=BUILD_INFO,
            )
        self.assertEqual(envelope["schema_version"], "abstracts.v1")
        self.assertEqual(envelope["build_info"], BUILD_INFO)
        self.assertIsInstance(envelope["abstracts"], list)

    def test_poster_id_emitted_not_submission_id(self) -> None:
        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            records = build_abstracts_records(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
            )
        # Stage 10: poster_id is int16; "0101" from the fixture parses to
        # 101 (leading zeros are display-only — `String(id).padStart(4)`
        # in the UI).
        poster_ids = {r["poster_id"] for r in records}
        self.assertIn(101, poster_ids)
        for r in records:
            self.assertNotIn("submission_id", r)


class TestResearchDimensionsJoin(unittest.TestCase):
    """Stage 23 — the four dimensions are left-joined into each exported
    record's `facets` block, keyed by Oxford submission id."""

    def _records(self, tmp, research_dimensions):
        paths = write_fixtures(Path(tmp))
        return build_abstracts_records(
            corpus_path=paths["corpus"],
            enriched_path=None,
            references_path=None,
            withdrawn_path=paths["withdrawn"],
            research_dimensions=research_dimensions,
        )

    def test_dimensions_injected_into_facets(self) -> None:
        from ohbm2026.ui_data.dimensions import load_research_dimensions

        with TemporaryDirectory() as tmp:
            paths = write_fixtures(Path(tmp))
            dims = load_research_dimensions(paths["dimensions"])
            records = build_abstracts_records(
                corpus_path=paths["corpus"],
                enriched_path=None,
                references_path=None,
                withdrawn_path=paths["withdrawn"],
                research_dimensions=dims,
            )
        by_poster = {r["poster_id"]: r for r in records}
        # 1001 → poster 101: all four present.
        self.assertEqual(by_poster[101]["facets"]["focus"], ["Translational", "Clinical"])
        self.assertEqual(by_poster[101]["facets"]["epistemic_basis"], ["Data-driven"])
        # 1003 → poster 103: theory_scope empty, focus present.
        self.assertEqual(by_poster[103]["facets"]["theory_scope"], [])
        self.assertEqual(by_poster[103]["facets"]["focus"], ["Fundamental"])

    def test_abstract_absent_from_map_gets_empty_lists(self) -> None:
        # Map only has 1001; 1003 must come back with empty dimension lists.
        with TemporaryDirectory() as tmp:
            records = self._records(tmp, {1001: {"focus": ["Clinical"]}})
        by_poster = {r["poster_id"]: r for r in records}
        for key in ("focus", "research_modality", "theory_scope", "epistemic_basis"):
            self.assertEqual(by_poster[103]["facets"][key], [])

    def test_no_map_means_all_four_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            records = self._records(tmp, None)
        for r in records:
            for key in ("focus", "research_modality", "theory_scope", "epistemic_basis"):
                self.assertEqual(r["facets"][key], [])


class TestHtmlToTextSupSub(unittest.TestCase):
    """Stage 12.2 — `<sup>` / `<sub>` survive `_html_to_text` as
    Unicode super/subscript glyphs instead of being flattened to
    ambiguous adjacent digits ("ref1,2" reads as numeric).
    """

    def test_sup_digits_become_unicode_superscript(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        out = _html_to_text("<p>reference<sup>1,2</sup>.</p>")
        self.assertIn("¹,²", out)
        self.assertNotIn("<sup>", out)
        self.assertNotIn("reference1,2", out)

    def test_sup_single_digit(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        self.assertIn("mm³", _html_to_text("4 mm<sup>3</sup>"))

    def test_sub_digits(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        self.assertIn("H₂O", _html_to_text("H<sub>2</sub>O"))

    def test_math_delimiters_pass_through(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        # KaTeX picks these up client-side; the stripper leaves them
        # intact.
        out = _html_to_text(r"<p>The value $\alpha=0.05$ holds.</p>")
        self.assertIn("$\\alpha=0.05$", out)

    def test_bare_math_autowrapped_for_katex(self) -> None:
        """Stage 12.2 — author-pasted raw LaTeX without `$...$` wrapping
        gets wrapped server-side so KaTeX can render it client-side.
        Poster 2094 in the real corpus was the canary."""
        from ohbm2026.ui_data.abstracts import _html_to_text

        out = _html_to_text(
            r"<p>similarity was defined as \rho\left(s,j\right)=corr(z,j). next sentence</p>"
        )
        # The bare `\rho\left(...)` cluster lands inside `$...$` so KaTeX
        # recognises it as a math span.
        self.assertIn(r"$\rho\left(s,j\right)=corr(z,j)$", out)

    def test_bare_matrix_wrapped_for_katex(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        out = _html_to_text(
            r"<p>encoder inputs are \begin{matrix}a&b\\c&d\end{matrix} done.</p>"
        )
        self.assertIn(r"$$\begin{matrix}", out)
        self.assertIn(r"\end{matrix}$$", out)

    def test_thinsp_alias_normalised(self) -> None:
        from ohbm2026.ui_data.abstracts import _html_to_text

        out = _html_to_text(
            r"<p>yields \mathrm{out}\mathrm{\thinsp} more text</p>"
        )
        self.assertIn(r"\thinspace", out)
        self.assertNotIn(r"\thinsp ", out)
        self.assertNotIn(r"\thinsp}", out)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
