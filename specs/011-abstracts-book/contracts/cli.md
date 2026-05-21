# Contract — `ohbmcli book`

> **Note (Stage 11.1, 2026-05-20):** the PDF path was rewired to a
> per-abstract pipeline + two-pass assembly. Three new flags
> (`--workers`, `--no-cache`, `--cache-dir`) are added; provenance
> gains `pdf_pipeline_version`, `pdf_engine_version`,
> `cache_hit_count`, `cache_miss_count`, `assembly_time_seconds`,
> `index_pages`, `front_matter_pages`, `included_poster_ids[]`,
> `failed_abstracts[]`. The legacy `xelatex_version` field is still
> emitted (alongside the new `pdf_engine_version`) for one deploy
> cycle. DOCX retirement is in scope of Stage 11.1 US3 — see
> `specs/012-stage11-followups/contracts/cli.md` for the full delta.

Command surface this feature exposes. Single CLI entry point; no
network endpoints.

## Synopsis

```text
ohbmcli book \
  [--sort {poster_id,title,first_author}] \
  [--format {md,pdf,docx,all}] \
  [--style {plain,tufte}] \
  [--corpus PATH] \
  [--authors PATH] \
  [--withdrawn PATH] \
  [--assets-root PATH] \
  [--output-root PATH] \
  [--include-section NAME ...] \
  [--no-determinism-strip] \
  [--state-key STR]
```

## Flags

| Flag | Default | Description |
|---|---|---|
| `--sort` | `poster_id` | Sort order — `poster_id`, `title`, `first_author`. |
| `--format` | `md` | Output format — `md`, `pdf`, `docx`, or `all` (emits all three side-by-side). |
| `--style` | `plain` | PDF document-class style. `plain` uses the LaTeX `book` class; `tufte` uses `tufte-book` with ET-Book typography + ragged-right + Tufte-spec margin. Ignored for `md` / `docx`. |
| `--corpus` | `data/primary/abstracts.json` | Accepted-corpus JSON. |
| `--authors` | `data/primary/authors.json` | Authors lookup. |
| `--withdrawn` | `data/primary/abstracts_withdrawn.json` | Withdrawn-id source. |
| `--assets-root` | `data/inputs/assets/` | Directory holding the high-resolution figure files. |
| `--output-root` | `data/outputs/book/` | Root for the produced book directory. |
| `--include-section` | (none) | Additional response question_names to include in the body, beyond the default six (research R4). Repeatable. |
| `--no-determinism-strip` | `false` | Skip the PDF/DOCX metadata strip (debug only — output then includes real build timestamps in file metadata; provenance.json still carries the canonical run timestamp). |
| `--state-key` | discovered | Override the state-key suffix on the output directory. Default: hash of `(corpus_path, authors_path, withdrawn_path, sort_order, format, style, include_sections)`. |

## System-dependency preflight

`ohbmcli book` runs a startup preflight when `--format` touches
PDF or DOCX:

- `pandoc --version` must succeed for any of `pdf`, `docx`, `all`.
  Captured into `provenance.pandoc_version`.
- `xelatex --version` must succeed for any of `pdf`, `all`.
  Captured into `provenance.xelatex_version`.

A missing system dep raises `BookBuildError` exit-code 2 with a
one-line install hint pointing at `quickstart.md`'s system-deps
step. The preflight runs **before** any expensive composition
work — it's the second line of `main()` after CLI-parse.

## Inputs (discovered, not configured)

- The figure-asset paths are read from
  `Abstract.local_assets[].local_path` for each abstract. The
  book does not assume any naming convention; it follows the
  absolute paths the Stage-1 fetch wrote.
- The set of body-section question_names is `BODY_SECTION_NAMES`
  in `src/ohbm2026/book/sections.py`, extensible per-run via
  `--include-section`.

## Outputs

```text
<output-root>/book__<state-key>/
├── book.md               # always (canonical intermediate)
├── book.pdf              # if --format pdf|all
├── book.docx             # if --format docx|all
├── fig_assets/           # always — book.md references these
│   └── <submission_id>-<poster_id>-<type>[-<index>].<ext>
└── provenance.json       # always
```

Note: `book.md` and `fig_assets/` are **always** written —
they're the canonical intermediate. PDF / DOCX are derived from
that markdown via pandoc. This means `--format pdf` produces both
`book.md` AND `book.pdf` in the same output directory; the
markdown bundle is the source-of-truth artefact.

**Figure filename pattern** (see `data-model.md § Layer 3` for the
full rules): flat directory, names of the form
`<submission_id>-<poster_id>-<type>[-<index>].<ext>`. `<type>` is
`methods`/`results` (from the Oxford question_name minus the
" Figure" suffix, lower-cased); `<index>` is 1-based and only
present when an abstract supplies more than one figure of the
same type. Examples: `1196698-0503-results.png`,
`1196701-0505-results-1.png`, `1196701-0505-results-2.png`.

## Exit codes

- `0` — book generated successfully; provenance written.
- `1` — generic error (bad CLI args, unwritable output path).
- `2` — `BookBuildError` (typed): corpus missing, empty result
  set, malformed authors lookup, system dep missing, pandoc
  non-zero exit. Detail printed to `stderr`.
- `3` — figure-resolution check failed catastrophically (Pillow
  raised on > 5% of figures — distinct from individual figures
  being below the 300 DPI threshold, which is logged not fatal).

## State-key derivation

Output directory carries a `<state-key>` suffix so historical
builds coexist. State-key = first 12 hex chars of
`sha256(corpus_mtime || authors_mtime || withdrawn_mtime ||
sort_order || format || style || include_sections_tuple)`. Same
inputs + flags → same state-key → same output directory (re-runs
overwrite — intentional per SC-007).

## Provenance contract

Every produced book carries `provenance.json` per the schema in
`data-model.md § Layer 3`. Fixed at `version: 1`. Adds
`pandoc_version` (always for PDF/DOCX outputs) and
`xelatex_version` (PDF only) compared to the pre-clarification
HTML-pipeline schema.

## Idempotence guarantee

- Re-running `ohbmcli book --format md --sort poster_id` twice
  with the same inputs MUST produce byte-identical `book.md` and
  `fig_assets/<...>` outputs (SC-007a).
- Re-running `--format pdf` twice with the same inputs MUST
  produce content-identical PDFs — same abstracts, same order,
  same figures, same index. PDF `/CreationDate` + `/ModDate`
  stripped to `D:19700101000000Z`; pandoc-generated body content
  is deterministic. `pdftotext book.pdf` is byte-identical
  re-run to re-run (SC-007b).
- Same applies to DOCX: `docProps/core.xml` `dcterms:created` /
  `dcterms:modified` overwritten to fixed values; zip entries
  rebuilt with sorted order + zeroed mtimes + deterministic
  compression level. `pandoc -t plain book.docx` byte-identical
  re-run to re-run.

## Determinism escape hatch

`--no-determinism-strip` keeps pandoc's emitted timestamps in
place. Default behaviour (strip ON) is the contract.

## Error path summary (CA-006)

| Condition | Behaviour |
|---|---|
| Corpus path missing | `BookBuildError`, exit 2. |
| Authors path missing or empty | `BookBuildError`, exit 2. |
| Zero entries after filter | `BookBuildError`, exit 2. |
| Output root unwritable | `BookBuildError`, exit 2, *before* any expensive work. |
| `pandoc` not on PATH (when format touches PDF/DOCX) | `BookBuildError`, exit 2, with install hint. |
| `xelatex` not on PATH (when format touches PDF) | `BookBuildError`, exit 2, with install hint. |
| Pandoc non-zero exit | `BookBuildError`, exit 2, stderr captured. |
| Single figure asset missing | "figure unavailable" block rendered at that position. No exit. |
| Single figure below 300 DPI | Logged in `provenance.figures_below_resolution_threshold`. No exit. |
| Body section absent for an abstract | Section heading skipped silently. |
| `--include-section` names an unseen question_name | WARN logged once, run continues. |
| Pillow cannot read figure file | FigureBlock.error set; "figure unavailable: unreadable" block rendered. |
| Stage 2 cache opened anywhere in the run | IMPOSSIBLE by design — the book code imports nothing under `stage2_*.py` or `data/cache/{figure,claim,reference}_*/`. Enforced by an import-graph walk in `tests/test_book_no_ai_audit.py`. |

## Known limitations (documented, not bugs)

- **DOCX author index is anchor-link only, not page-numbered.**
  Pandoc's docx writer doesn't emit PAGEREF field codes. The index
  is clickable and navigates correctly inside Word / LibreOffice;
  it just shows author names + abstract titles, not page numbers.
  PDF is the format for true paginated author index. (R3
  alternatives — post-process XML injection is feasible but
  deferred to a future enhancement if the editor asks.)
- **Tufte styling is typography-only.** Citation superscripts
  remain as `^N^` inline; they are NOT auto-converted to true
  Tufte margin-sidenotes. Full sidenote conversion requires
  parsing the references block and matching every superscript
  numeral, which is non-trivial; deferred per the user's
  "optional styling" signal. (R7 alternatives.)
- **Math content.** The corpus carries the occasional inline math
  expression as raw HTML or LaTeX inside body sections. Those
  pass through HTML → markdown unchanged (raw LaTeX in markdown
  is a pandoc-supported island), then pandoc renders them
  correctly in PDF. DOCX rendering of inline math is pandoc-best-
  effort.
