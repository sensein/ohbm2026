# Quickstart — Book of Abstracts

> **Note (Stage 11.1, 2026-05-20):** the `--format docx` path was
> retired. Use `--format md` (markdown bundle) or `--format pdf`
> (per-abstract pipeline). PDF builds now use the per-abstract
> pipeline with content-hash caching; first-run ~7 min, warm-cache
> re-run ≤ 60 s. Full delta in `specs/012-stage11-followups/`.

Operator runbook. Takes you from a clean checkout to a printable
PDF book in ten minutes (after one-time system-deps install).

## Prerequisites

- A populated Stage-1 corpus on disk:
  - `data/primary/abstracts.json`
  - `data/primary/abstracts_withdrawn.json`
  - `data/primary/authors.json`
  - `data/inputs/assets/` (high-resolution figure files)
- The repository `.venv` exists (`uv venv --python 3.14 .venv`).
- Stage-2 is **not** required — the book uses only Stage-1
  artefacts.

If any of the Stage-1 artefacts is missing, run the relevant
`ohbmcli` ingest commands first (see top-level `README.md`).

## 1 — Install the optional Python extra

```bash
uv pip install --python .venv/bin/python ".[abstracts_book]"
```

This installs `markdownify`, `beautifulsoup4`, and `python-docx`
(test-time introspection of the docx pandoc emits) into the
project venv. `Pillow` is already a project dependency.

## 2 — Install the two system deps (one-time)

Markdown is the canonical intermediate; pandoc renders it to PDF
(via xelatex) and DOCX. Install both binaries once per machine.

**macOS (Homebrew):**

```bash
brew install pandoc tectonic
```

Tectonic is the recommended LaTeX engine — it auto-fetches LaTeX
packages on demand (no multi-GB up-front install). It provides
`xelatex`-compatible behaviour. If you prefer the full TeX Live
distribution:

```bash
brew install pandoc mactex     # ~4 GB
```

**Ubuntu / Debian:**

```bash
sudo apt-get install -y pandoc texlive-xetex texlive-latex-extra \
                        texlive-fonts-extra texlive-fonts-recommended
```

`texlive-fonts-extra` brings in the ET-Book / Tufte fonts needed
when `--style tufte` is selected.

**CI**: add to the relevant workflow:

```yaml
- name: Install pandoc + xelatex
  run: |
    sudo apt-get update
    sudo apt-get install -y pandoc texlive-xetex texlive-fonts-extra
```

If either binary is missing on `PATH`, `ohbmcli book` raises
`BookBuildError` at startup with a hint pointing at this
quickstart.

## 3 — First run (markdown bundle only — no system deps needed)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format md \
  --sort poster_id
```

Output: `data/outputs/book/book__<state-key>/{book.md,
fig_assets/, provenance.json}`. Total wall time: ~30 seconds.
Useful for verifying the corpus filter + content shape **before**
spending a pandoc cycle.

Sanity check:

```bash
# Count rendered abstracts (matches accepted-corpus count).
grep -c '^## Abstract ' data/outputs/book/book__*/book.md

# Spot-check the anchor-link author index.
sed -n '/^<details>/,$p' data/outputs/book/book__*/book.md \
  | head -30
```

## 4 — PDF (publication-resolution, plain style)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf \
  --sort poster_id
```

This regenerates `book.md` (the canonical intermediate) AND
emits `book.pdf` in the same output directory. pandoc runs
xelatex once with `\makeindex` + `\printindex` for the page-
numbered author index. Wall time: 6–9 minutes for ~3,200
abstracts.

If you see "figure unavailable" blocks in the rendered PDF,
inspect `provenance.json.figures_below_resolution_threshold` and
the build log for the affected poster_ids. Common causes: the
figure was renamed / moved out of `data/inputs/assets/`, or the
upstream submitter uploaded a corrupt file. Re-run
`ohbmcli refresh-assets` to repair.

## 5 — PDF with Tufte styling (optional)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf \
  --sort poster_id \
  --style tufte
```

Selects the `tufte-book` LaTeX document class — ET-Book serif
body type, ragged-right setting, generous outer margin, Tufte
section heading style. Content is unchanged from the plain
PDF; only typography differs. Wall time is similar
(~6–9 minutes).

If you see missing-font warnings for ET-Book on Linux, install
`texlive-fonts-extra`. On macOS Homebrew, Tectonic auto-fetches
the package.

## 6 — DOCX (editorial copy)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format docx \
  --sort poster_id
```

Open `book.docx` in Word, LibreOffice Writer, or Google Docs.
The author index is the anchor-link form (clickable
cross-references). True page-numbered DOCX index is a documented
limitation — see `contracts/cli.md § Known limitations`.

## 7 — All three formats at once

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format all \
  --sort poster_id
```

Produces `book.md` + `book.pdf` + `book.docx` + `fig_assets/` +
`provenance.json` in a single output directory. Wall time:
roughly PDF render time + 90 s (DOCX) + 30 s (MD).

## 8 — Alternate sort orders

```bash
# By case-insensitive title:
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort title

# By first-author surname (then given name, then title for ties):
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort first_author
```

Each invocation produces a separate output directory with its
own state-key suffix; you can keep all three side-by-side.

## 9 — Verify provenance

```bash
.venv/bin/python -m json.tool \
  data/outputs/book/book__<state-key>/provenance.json
```

Confirm:
- `corpus_state_key` matches the Stage-1 state-key on disk.
- `abstract_count` matches the accepted-corpus row count after
  withdrawn / null-poster-id filtering.
- `figures_below_resolution_threshold` is short or empty.
- `no_ai_audit.matches_found` is `0` (SC-006).
- `pandoc_version` + `xelatex_version` are present when the
  format touches PDF/DOCX.

## 10 — Common errors

| You see | What it means | What to do |
|---|---|---|
| `BookBuildError: pandoc not found on PATH` | Step 2 incomplete. | `brew install pandoc` / `apt-get install pandoc`. |
| `BookBuildError: xelatex not found on PATH` | Step 2 incomplete (no LaTeX engine). | `brew install tectonic` / `apt-get install texlive-xetex`. |
| `BookBuildError: corpus path … not found` | Stage 1 hasn't run. | `ohbmcli fetch-abstracts`. |
| `BookBuildError: zero entries after filter` | Every row is withdrawn or null-poster-id. | Inspect the corpus — Stage 1 likely produced a malformed snapshot. |
| `BookBuildError: pandoc returned non-zero (stderr: ...)` | Pandoc failed mid-run. | Read the stderr — usually a LaTeX-package missing, or an HTML→md conversion artefact pandoc choked on. Re-run with `--no-determinism-strip` to keep the intermediate `.tex` for debugging. |
| `figure unavailable: asset missing` blocks in the PDF | Corpus references a file not on disk. | Re-run `ohbmcli refresh-assets`. |
| `figure unavailable: unreadable` blocks | Pillow can't decode the file (truncated upload, unrecognised codec). | Inspect the file manually. |
| Missing-glyph warning during xelatex | A unicode codepoint isn't in the selected font's range. | Usually ET-Book on Linux without `texlive-fonts-extra`. Install it or switch to `--style plain`. |
| LibreOffice opens the docx and the index hyperlinks look broken | LibreOffice's hyperlink-to-internal-anchor support is fiddly. | Open in Word for the most reliable cross-reference behaviour; the underlying file is correct. |

## 11 — Re-running

The default `--state-key` derivation makes re-runs deterministic:
same inputs + same flags → same state-key → same output directory.
Re-running with identical flags **overwrites** the previous build
in place; this is intentional (SC-007).

To keep historical builds, copy the output directory under a new
name before re-running, or override the state-key explicitly
with `--state-key <name>`.
