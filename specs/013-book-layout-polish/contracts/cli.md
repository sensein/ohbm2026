# Contract — `ohbmcli book` (Stage 12 delta)

This contract amends `specs/011-abstracts-book/contracts/cli.md` and the Stage 11.1 addendum at `specs/012-stage11-followups/contracts/cli.md`. Only the deltas are listed here.

## New flag — `--margins {tight,loose}`

```text
[--margins {tight,loose}]
```

| Default | Description |
|---|---|
| `tight` | New default for Stage 12. Loads `header-includes.tex` which carries `\usepackage[margin=0.65in]{geometry}`. Targets ≥ 15% page-count reduction vs the LaTeX `book` class default. |
| `loose` | Loads `header-includes-loose.tex` which omits the `geometry` import and falls back to the LaTeX `book` class default (~1 in margins). Available for an operator who needs the pre-Stage-12 layout (e.g., to compare against an archived Stage 11.1 build). |

The flag value is part of the cache key (indirectly — the per-abstract cache key already hashes the loaded header-includes file's bytes, so a different file → different bytes → different key → automatic re-render). No additional cache invalidation logic is needed.

## Updated provenance fields

`provenance.json` for any run that produces a PDF gains three fields:

```json
{
  "figures_normalised_count": 4625,
  "figures_normalised_with_fallback": [
    {"poster_id": 1234, "filename": "1234567-0123-results.png", "error_reason": "cannot identify image file (truncated bytes)"}
  ],
  "toc_page_count": 78
}
```

- `figures_normalised_count`: the number of figures that the normaliser successfully re-encoded to JPEG q=90 at the 150 DPI dimension cap during this build.
- `figures_normalised_with_fallback[]`: list of figures that Pillow couldn't open; each entry carries the poster_id, the source filename, and the Pillow error message. The build proceeds with byte-copied originals for those figures (CA-006).
- `toc_page_count`: the number of pages the new 3-column TOC consumed. Useful for SC-003 verification.

The existing `xelatex_version` / `pdf_engine_version` / `pdf_pipeline_version` / `cache_hit_count` / `cache_miss_count` / `failed_abstracts[]` / `assembly_time_seconds` / `index_pages` / `front_matter_pages` / `included_poster_ids[]` fields are unchanged.

## Behavioural changes (no CLI surface change)

These behaviours change WITHOUT a new flag — they are always-on after Stage 12 lands:

1. **Figure assets normalisation**: every figure is re-encoded to `.jpg` at q=90 with the 150 DPI dimension cap. Source-format extensions (`.png`, `.gif`, `.webp`, `.tif`) are no longer preserved.
2. **TOC**: the 3-column `longtable` (`Poster | Title | Page`) replaces pandoc's default flat-section TOC.
3. **Author index**: each non-empty letter bucket (`A`, `B`, …, `Z`, `Other`) is preceded by a `## <letter>` heading in the back-of-book index.

These three changes are "always-on because the user asked for them" — no opt-out flag is provided in v1. If a future operator needs the old behaviour, the v1 source format can be recovered by reverting the relevant module-level changes; this contract does not promise a configurable surface for them.

## Exit codes

Unchanged from Stage 11.1 (`0` on success, `2` on `BookBuildError`).

## Backward compatibility

- Operators with existing scripts that DO NOT pass `--margins` get the new `tight` preset automatically. Pre-Stage-12 layouts can be recovered with `--margins=loose`.
- Operators reading old `provenance.json` files MUST tolerate absent `figures_normalised_*` / `toc_page_count` keys; the recommended pattern is `prov.get("figures_normalised_count", 0)`.
- The data-package consumer (the SvelteKit site's `shards.ts`) MUST tolerate absent `sections.acknowledgments` (older parquet shards don't carry the field). The `sections.acknowledgments?` optional type captures this.
