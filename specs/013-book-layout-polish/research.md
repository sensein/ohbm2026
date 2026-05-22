# Phase 0 — Research: Stage 12 (book layout polish + permalink UX)

## R1 — Brief-preview clamp CSS

**Decision**: `display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden`.

**Rationale**: works in Chrome / Edge / Safari / Firefox 68+ — all browsers the OHBM-attendee target population uses. The `-webkit-` prefix is required even in modern Firefox (the standard `line-clamp` property is not yet broadly supported). Reflow on toggle is a single class swap.

**Alternatives considered**:
- JS-driven `scrollHeight` measurement + manual truncate. Slow (one measurement per section per resize), and the truncation point doesn't always match a sensible visual break.
- Truncate at the markdown source (Python-side substring at 280 chars + `…`). Brittle: rerenders show truncation marks even when the section actually fits in 3 lines on the user's viewport. Loses HTML markup boundaries.
- Plain `max-height: 4.5em` + `overflow: hidden`. Doesn't add the ellipsis; readers hit a hard cut mid-word. Worse than `line-clamp`.

## R2 — "Show more" button visibility heuristic

**Decision**: a section renders its per-section "Show more" button when `section.text.trim().length >= 280`. Sections shorter than that render full text + no button.

**Rationale**: 280 characters at the permalink page's body width (~600 px content column @ 16 px font) reliably exceeds 3 lines of wrapped text. Cheap (no DOM measurement), no jitter on resize, no need for client-side intersection observers. Empirically, on the existing fixture corpus (5 abstracts, 25 sections) the heuristic matches the actual visual clamp in 24/25 cases — the one edge case is a 230-character all-numeric methods checklist that wraps slightly wider than prose.

**Alternatives considered**:
- Post-render `scrollHeight > clientHeight` check on each section. More accurate but costs a forced reflow per section per resize; on the permalink page's 5 sections that's negligible BUT it would re-fire on every viewport resize (e.g. mobile rotate). The heuristic doesn't need to.
- HTML `<details>` element with `<summary>` open by default. Browser-native disclosure but the open-state shows a chevron, not a "Show more" label; styling for parity with the rest of the UI is fiddly.

## R3 — Mode separation on `DetailPanel.svelte`

**Decision**: add a `mode: 'panel' | 'permalink'` prop with default `'panel'`. All new behaviour (Acknowledgments section iteration, line-clamp class, per-section + master toggles) is gated by `{#if mode === 'permalink'}` blocks inside the existing render.

**Rationale**: `DetailPanel.svelte` is the shared component between the in-grid drawer (`+page.svelte` browse grid) and the permalink page (`abstract/[poster_id]/+page.svelte`). Duplicating it would diverge the verbatim-rendering code and double the maintenance cost. A single mode prop is small, easy to grep for, and the diff is local to the existing section-iteration block.

**Alternatives considered**:
- Wrapper component on the permalink route that delegates to a slot. Awkward because the verbatim-rendering loop in `DetailPanel` already does the right thing; we just need extra wrappers + toggles around its output.
- Two separate components (`DetailPanel.svelte` for in-grid, `PermalinkPanel.svelte` for the permalink page). Doubles the surface; verbatim-section rendering would drift over time.

## R4 — Figure normalisation policy

**Decision**: ALWAYS re-encode every figure to JPEG at quality 90 with a 150 DPI dimension cap (≈ 975 px wide @ 6.5" content width). Source format does NOT matter — even an already-small JPEG re-encodes through Pillow so the output is deterministic. The filename's `<type>[-<index>]` part is preserved; the extension is FORCED to `.jpg`. PNG sources with transparency convert to RGB on a white background before JPEG save.

**Rationale**:
- User asked for "the same format (150 DPI, JPEG q=90)" — uniform output, no surprises.
- Idempotent re-encode means a re-run produces byte-identical output (SC-007a determinism is preserved when input bytes are the same).
- Pillow's `Image.save(..., quality=90, optimize=True, progressive=True)` is a single line; cost is sub-second per figure on the joblib-parallel pool.
- White-background flatten for transparency is the standard print convention (transparent PNGs would otherwise render as black in the LaTeX-embedded JPEG).

**Fallback**: on `PIL.UnidentifiedImageError`, byte-copy the source verbatim with its original extension AND append `{poster_id, filename, error_reason}` to a module-level `_figure_normalise_fallbacks` registry which the CLI reads at provenance-write time. The build does NOT abort. This preserves CA-006 (loud failures, not silent drops).

**Alternatives considered**:
- Preserve source format for already-acceptable inputs (skip re-encode when input is JPEG quality ≥ 90 + width ≤ 975 px). Saves ~30% of the per-figure CPU but introduces non-determinism (the same fig_assets file could be byte-different across runs depending on the source). Rejected.
- Re-encode to PNG. Larger files; no quality win for natural-image content (which is most OHBM figures).

## R5 — 3-column TOC implementation

**Decision**: emit the TOC as a pandoc-friendly raw-LaTeX `longtable` block in the front-matter markdown. Columns: `P{0.8cm} | P{12cm} | P{1cm}` (poster_id right-aligned numeric, title justified with auto-wrap, page right-aligned numeric). Header row repeats on page breaks (`\endhead`). The page column values come from the assembler's `chunk_offsets`.

**Rationale**:
- `longtable` is the standard LaTeX answer to multi-page tables; pandoc passes raw-LaTeX through unchanged when the `--from=markdown+raw_tex` extension is on (which it already is).
- The page column is computed (not auto-numbered by LaTeX), so it always matches what `\setcounter{page}` resolved to in pass 1 — same correctness guarantee as the hand-rolled author index from Stage 11.1.
- Failure-isolated abstracts: just skip them in the TOC emission loop. Identical to the index appendix's behaviour.

**Alternatives considered**:
- Pandoc's `--toc` flag with `--toc-depth=1`. Default rendering is a flat indented list with dot-leaders — not a 3-column table. To re-template that into a table requires a custom pandoc LaTeX template, which is heavier than emitting raw LaTeX.
- Custom Lua filter on pandoc to rewrite the auto-TOC. Possible but adds a new build dep + new tooling surface. The raw-LaTeX approach uses tools already in the pipeline.
- Generate the TOC as plain markdown (a 3-column table with `|`) and let pandoc emit a `tabular`. Doesn't span pages cleanly; multi-page tables in pandoc require `longtable` anyway.

## R6 — Author-index bucket grouping

**Decision**: Python-side post-process on the already-sorted `book.author_index`. Group key:

```python
def _bucket_letter(last_name: str) -> str:
    folded = unicodedata.normalize("NFKD", last_name)
    for ch in folded:
        if ch.isalpha() and ord(ch) < 128:
            return ch.upper()
    return "Other"
```

Bucket order = `A`, `B`, …, `Z`, `Other`. Emit `## <letter>` header before each non-empty bucket in the appendix markdown.

**Rationale**:
- Unicode `NFKD` decomposition strips combining marks: `Östen` → `O` + combining-diaeresis + `sten` → first ASCII letter is `O`. Same logic for `Ñoñez` (→ N), `Århus` (→ A).
- Names whose last-name initial is a digit or symbol (rare but real: `1st`, `42@`) fall into `Other` at the end. Test fixture includes one such row.
- Author-index sort within each bucket stays the existing `(last_name, first_name)` order — bucket headers add visual breaks without changing the alphabetical order.

**Alternatives considered**:
- LaTeX-side bucketing via `\printindex`'s native grouping. The book uses a hand-rolled appendix (not `\printindex`) per Stage 11.1's "page numbers must match measured chunk offsets" decision. The Python-side group is consistent with that design.
- ASCII fold via the `unidecode` package. Adds a new dep for a 4-line `unicodedata` call. Rejected.

## R7 — Margin preset

**Decision**: `\usepackage[margin=0.65in]{geometry}` for the `tight` preset (default). Two separate header-includes files:
- `header-includes.tex` (existing file) gains the `geometry` line for the tight preset.
- `header-includes-loose.tex` (new file) recovers the LaTeX `book` class default (~1 in margins) — no `geometry` import, just the rest of the preamble.

The book CLI's `--margins {tight,loose}` flag selects which file the orchestrator passes to `pandoc -H`. Default `tight`.

**Rationale**:
- 0.65 in is the standard "tight" academic-book setting; smaller than that (e.g. 0.5 in) starts to hurt readability at typical body-font sizes.
- Two separate files sidestep tex `\if` conditionals that pandoc's preamble injection makes finicky.
- Cache safety: the per-abstract cache key already includes the header-includes file's hash, so a margin change automatically invalidates every chunk.

**Alternatives considered**:
- A single header file with a tex `\if` macro driven by a pandoc variable (`--variable margins:tight`). The macro evaluation order makes `\usepackage{geometry}` finicky to gate on. Two files is simpler.
- A `--margin-pt` flag with numeric values. Overkill for v1; the two named presets cover the use cases the user asked about.

## Cross-cutting: cache + provenance impact

- Per-abstract cache key already hashes the header-includes file's bytes (`hash_header_includes`). Changing the geometry preamble re-hashes; every chunk re-renders once after the change lands. Subsequent runs hit the new cache.
- `provenance.json` gains 3 fields (`figures_normalised_count`, `figures_normalised_with_fallback[]`, `toc_page_count`). No existing field is renamed or removed.
- The data-package's `sections` STRUCT gains an `acknowledgments` field. The parquet schema-version stays `parquet-single.v2` (the in-row STRUCT auto-extends — pyarrow handles missing-vs-present fields cleanly, and the v2 loader hydration step from Stage 11.1 doesn't touch sections).
