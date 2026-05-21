# Book of Abstracts — operator summary

Compose a publication-quality book of every accepted abstract —
title, authors with affiliations, full body text, embedded figures,
and the author-supplied references — sorted by `poster_id` (default),
`title`, or `first_author` surname, with a page-numbered author
index at the back.

**Markdown is the canonical intermediate.** `book.md` is always
emitted (the source-of-truth artefact). PDF derives from it via
the per-abstract pipeline introduced in Stage 11.1 — each abstract
pandoc-renders in parallel with content+toolchain caching, then a
two-pass assembly attaches a page-numbered author index.

DOCX export was **retired in Stage 11.1 US3** (`ohbmcli book --format docx`
exits 2 with a pointer at `--format md` and `--format pdf`). The
real-corpus DOCX hit 2.8 GB even after figure resizing — too large
for Word to open — and the markdown bundle + PDF cover every use
case it served.

**No AI-generated content reaches the book.** Content sourced
exclusively from Stage-1 artefacts (`data/primary/abstracts.json` +
`authors.json` + `data/inputs/assets/`); never from Stage-2
enrichments. Verified by an SC-006 audit logged in
`provenance.json.no_ai_audit` and by a static import-graph check
that ensures no Stage-2 / enrich module appears in the book
package's source.

## Spec + design

Full spec, plan, research, data-model, CLI contract, and quickstart
live under `specs/011-abstracts-book/`:

- `spec.md` — FR-001..011, SC-001..007, CA-001..008.
- `plan.md` — pandoc subprocess pipeline; system-dep contract.
- `research.md` — seven decisions (no-captions reality,
  HTML→markdown once at load, pandoc-only rendering, body-section
  policy, figure-DPI handling, determinism via pikepdf+zipfile,
  optional Tufte styling).
- `data-model.md` — three layers (Stage-1 inputs → markdown-bearing
  in-memory model → outputs with figure-filename contract).
- `contracts/cli.md` — `ohbmcli book` flags, error path table,
  known limitations.
- `quickstart.md` — operator runbook for install + first run.

## Quick reference

```bash
# One-time install of the optional extra:
uv pip install --python .venv/bin/python ".[abstracts_book]"

# One-time install of system deps (macOS):
brew install pandoc tectonic

# Markdown-only first run (no system deps needed):
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format md

# Full PDF run:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format pdf --sort poster_id

# All three formats + Tufte typography for the PDF:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format all --sort poster_id --style tufte
```

Outputs land at `data/outputs/book/book__<state-key>/`. Figure
assets carry the filename pattern
`<submission_id>-<poster_id>-<type>[-<index>].<ext>` (flat
directory; index suffix only for multi-of-type).

## Stage 11.1 — per-abstract PDF pipeline

Stage 11's monolithic `book.md` → pandoc → `book.pdf` invocation
never produced a real-corpus PDF: a single broken abstract aborted
the whole 8-15 minute compile, leaving no usable artefact and no
way to diagnose which entry was the culprit. Stage 11.1 replaces
that with a per-abstract pipeline:

1. Each abstract pandoc-renders independently to its own small PDF
   chunk under `data/cache/book/abstracts/<cache-key>.pdf` + a
   sidecar `<cache-key>.json` (page_count, index_entries).
2. Cache keys are `sha256(md_body || pandoc_version ||
   engine_version || header_includes_hash || style)` truncated to
   16 hex (CA-007 — content-driven, no version allow-list). An
   upstream pandoc / Tectonic upgrade invalidates every entry
   automatically.
3. joblib's loky backend parallelises the chunks across all cores.
4. A **two-pass assembly** gives the book a real page-numbered
   author index: pass 1 concatenates chunks via `pikepdf` and
   records each chunk's global page offset; pass 2 emits a hand-
   rolled appendix markdown using those offsets (no LaTeX
   `\printindex` machinery — that would bind page numbers to the
   appendix's pages, not to each abstract's actual page).
5. Per-abstract failures isolate cleanly: the offending entry
   drops out, the build still succeeds (exit 0), and the diagnostic
   capture lands in `provenance.failed_abstracts[]`. The CLI prints
   a stderr warning naming the failure count.

Performance targets (real-corpus, ~3,242 abstracts on a typical
laptop):
- First build (cold cache): ~7 min.
- Re-run with no input change (warm cache): ≤ 60 s.

Operator flags:
- `--workers N` (default `-1`) — joblib n_jobs.
- `--no-cache` — bypass the per-abstract cache.
- `--cache-dir PATH` — override the cache root.

Single-abstract debug (re-render one chunk in isolation, populating
the cache):
```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.book.render_per_abstract \
    --poster-id 0042 --style plain
```

Provenance fields added when the per-abstract path runs:
- `pdf_pipeline_version: "stage-11.1"`
- `pdf_engine_version` (mirrors the legacy `xelatex_version` value)
- `cache_hit_count`, `cache_miss_count`, `assembly_time_seconds`
- `index_pages`, `front_matter_pages`
- `included_poster_ids[]`, `failed_abstracts[]`

Full spec / plan / contracts at `specs/012-stage11-followups/`.

DOCX retirement: `--format docx` exits non-zero with the message
"docx export was retired in Stage 11.1 — use --format md (markdown
bundle) or --format pdf (per-abstract PDF pipeline) instead". The
`to_docx` implementation, the docx-only test module, and the
`python-docx` optional dep are removed.
