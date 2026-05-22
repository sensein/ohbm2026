# Phase 1 — Data Model: Stage 12 (book layout polish + permalink UX)

Three areas: (1) `sections.acknowledgments` field on the data-package abstracts envelope, (2) client-side permalink-page state for the brief-preview toggles, (3) book-side entities for normalised figures, the 3-column TOC, and the bucketed author index.

## Area 1 — `sections.acknowledgments` field

### Per-record shape (Python + on-the-wire parquet STRUCT field)

```python
{
    "sections": {
        "introduction": str,    # existing
        "methods": str,         # existing
        "results": str,         # existing
        "conclusion": str,      # existing
        "references": str,      # existing
        "acknowledgments": str, # NEW. Trimmed `Acknowledgement` response or "".
    },
    ...
}
```

### TypeScript (`shards.ts`)

```ts
interface AbstractRecord {
    sections: {
        introduction?: string;
        methods?: string;
        results?: string;
        conclusion?: string;
        references?: string;
        acknowledgments?: string;   // NEW
    };
    // ...
}
```

### Validation rules

- The value is the corpus's `Acknowledgement` response (Oxford Abstracts field name; the corpus normaliser already lower-cases the question key to `acknowledgement` in the per-record `questions` dict), trimmed of leading/trailing whitespace, HTML-to-markdown converted via the existing `_section` helper.
- Empty string when the question is absent OR the trimmed value is empty.
- No schema-version bump: the parquet's `sections` STRUCT is an open dict (pyarrow's `pa.struct` field-add is backward compatible; older readers ignore the new field).

## Area 2 — Permalink-page brief-preview state (client-side only)

### `PermalinkSectionState`

```ts
// Lives inside DetailPanel.svelte when mode === 'permalink'.
type SectionKey = 'introduction' | 'methods' | 'results' | 'conclusion' | 'acknowledgments';

let expanded: Map<SectionKey, boolean> = new Map([
    ['introduction',   false],
    ['methods',        false],
    ['results',        false],
    ['conclusion',     false],
    ['acknowledgments', false],
]);

// Derived (reactive):
$: allExpanded = Array.from(expanded.values()).every(Boolean);
// Master toggle label: 'Show all' when !allExpanded, 'Collapse all' when allExpanded.
```

### State transitions

- Initial: every section `false` (clamped to 3 lines).
- Per-section "Show more" click: `expanded.set(skey, true)` → that section unwraps to full text + button relabels to "Show less".
- Per-section "Show less" click: `expanded.set(skey, false)` → clamp + label flips back.
- Master "Show all" click (when `!allExpanded`): set every key to `true`. Master relabels to "Collapse all".
- Master "Collapse all" click (when `allExpanded`): set every key to `false`. Master relabels to "Show all".

### Non-persistence

State is local to the component instance. No `localStorage` / `sessionStorage`. Navigating to a different permalink page → fresh component instance → state resets to all-clamped. Refreshing the page → same reset.

### Visibility heuristic (per R2)

```ts
function isClampable(text: string | undefined): boolean {
    return (text ?? '').trim().length >= 280;
}
```

A section renders its per-section "Show more" button only when `isClampable(sections[skey])` is true. Sections whose full text fits in 3 lines (text length < 280 chars) just render full text and no button.

## Area 3 — Book-side entities

### `NormalisedFigureAsset`

```python
@dataclass(frozen=True, slots=True)
class NormalisedFigureAsset:
    """One re-encoded figure on disk under fig_assets/."""
    src_path: pathlib.Path           # absolute source path
    dest_path: pathlib.Path          # absolute dest path with .jpg extension
    src_width: int                   # source pixel width
    src_height: int                  # source pixel height
    dest_width: int                  # final pixel width (≤ 975)
    dest_height: int                 # final pixel height (preserves aspect)
    dest_quality: int                # always 90 for v1
    dest_bytes: int                  # output file size in bytes
    used_byte_copy_fallback: bool    # True when Pillow couldn't open src
    fallback_error_reason: str | None  # set iff used_byte_copy_fallback
```

`NormalisedFigureAsset` instances are NOT serialised individually. The orchestrator aggregates:

- `provenance.figures_normalised_count`: count of `not used_byte_copy_fallback`.
- `provenance.figures_normalised_with_fallback`: list of `{poster_id, filename, error_reason}` per failed re-encode.

### `TocRow`

```python
@dataclass(frozen=True, slots=True)
class TocRow:
    poster_id: int       # int16 — sole user-facing identifier
    title: str           # already cleaned / normalised
    page: int            # global page number from chunk_offsets
```

Source of `page`: `assemble_pdf.chunk_offsets` (1-based pages from pass-1 measurement). The TOC reads each accepted abstract's `chunk_offsets[(poster_id, start_page)]` lookup; failure-isolated abstracts are absent from `chunk_offsets` and skipped.

### `AuthorIndexBucket`

```python
@dataclass(frozen=True, slots=True)
class AuthorIndexBucket:
    letter: str                              # 'A'-'Z' or 'Other'
    entries: tuple[AuthorIndexEntry, ...]    # already sorted by (last_name, first_name)
```

Buckets ordered `A, B, …, Z, Other`. Empty buckets are NOT emitted (no `## D` header if no D-surnames exist). The `_build_index_markdown` helper iterates `(letter, entries)` pairs and prepends `## <letter>` before each bucket's entries.

## Provenance schema delta

`provenance.json` adds three fields when the per-abstract pipeline path produced this run:

```json
{
  ...existing Stage 11.1 fields...,
  "figures_normalised_count": 4625,
  "figures_normalised_with_fallback": [
    {"poster_id": 1234, "filename": "1234567-0123-results.png", "error_reason": "cannot identify image file (truncated bytes)"}
  ],
  "toc_page_count": 78
}
```

`toc_page_count` is measured at front-matter pandoc time (the front-matter chunk's `page_count` minus the title-page + abstract-count + corpus-state-key lines' page contribution; in practice the TOC IS the dominant content of the front-matter chunk after stage 12 lands, so this is effectively `front_matter_pages` for most builds).

## Validation rules across data layers

- **Acknowledgments**: empty string in the data-package shard MUST be valid (= absent on the wire); the UI guards against rendering an empty section header.
- **NormalisedFigureAsset**: `dest_width <= 975` always; `dest_quality == 90` always (no operator override in v1).
- **TocRow**: `page >= front_matter_pages + 1` for every surviving abstract; `page` is strictly increasing with `chunk_offsets` order.
- **AuthorIndexBucket**: `letter` is one of `A`-`Z` or exactly `'Other'`; `entries` is non-empty for every emitted bucket.
