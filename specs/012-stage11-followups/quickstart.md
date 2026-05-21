# Quickstart — Stage 11.1

Operator runbook for the per-abstract PDF pipeline, the standby schema
rework, and the docx retirement.

## Prerequisites

- Stage 11 already shipped (`ohbmcli book` exists; `pandoc` + Tectonic
  on PATH per `specs/011-abstracts-book/quickstart.md` step 2).
- The repository `.venv` exists; `uv pip install --python .venv/bin/python ".[abstracts_book]"`
  has been re-run after the Stage-11.1 PR lands (the optional extra
  drops `python-docx`).

## 1 — First real-corpus PDF build (cold cache)

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort poster_id
```

Expected wall-time on a typical laptop (8 cores): **~7 minutes**.
- Per-abstract pandoc/Tectonic in parallel: ~60 s.
- Pass 1 (concatenate chunks + measure offsets): ~30 s.
- Pass 2 (emit index appendix + concat): ~30 s.
- Total dominated by I/O on the cache writes.

Output lands at `data/outputs/book/book__<state-key>/book.pdf`. The
cache populates `data/cache/book/abstracts/` (~1.5 GB at full
corpus).

## 2 — Re-run with no input change (warm cache)

```bash
# Same command — no flags need to change
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort poster_id
```

Expected wall-time: **under 60 s** (every per-abstract chunk hits
the cache; only the two assembly passes run).

`provenance.json` shows `"cache_hit_count": 3242, "cache_miss_count": 0`.

## 3 — Debugging a single abstract

When the build summary reports a per-abstract failure:

```bash
# Look in provenance.json under `failed_abstracts[]` first to read
# the captured stderr.
.venv/bin/python -m json.tool \
  data/outputs/book/book__*/provenance.json | jq '.failed_abstracts'
```

To re-render one abstract in isolation:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.book.render_per_abstract \
  --corpus data/primary/abstracts.json \
  --poster-id 0042 \
  --style plain
```

Stderr from pandoc/Tectonic prints directly. The resulting chunk
lands in the cache; the next full build will hit the cache.

## 4 — Forcing a cache rebuild

The cache invalidates automatically on toolchain change (R1). To
manually force a full rebuild:

```bash
# Option A: targeted — bypass cache without nuking it
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort poster_id --no-cache

# Option B: nuclear — delete the cache directory
rm -rf data/cache/book/abstracts/
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book \
  --format pdf --sort poster_id
```

## 5 — DOCX migration note

`--format docx` is **retired** in Stage 11.1. The CLI exits non-zero
with a pointer at the surviving formats:

```bash
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli book --format docx
# error: docx export was retired in Stage 11.1 — use --format md
# (markdown bundle) or --format pdf (per-abstract PDF pipeline)
# instead. See docs/abstracts-book-plan.md for the migration note.
```

If your prior workflow piped the docx into Word, switch to either:
- the markdown bundle (`--format md`) for editorial work (open in any
  Markdown editor; figures live in `fig_assets/`), or
- the assembled PDF (`--format pdf`) for print or PDF-viewer use.

## 6 — Standby schema migration (UI data package)

The Stage-6 `scripts/build_ui_data.py` rebuild now emits
`schema_version: parquet-single.v2` with the new `standby_slots`
table + INT8 indices. After the rebuild:

```bash
# Rebuild the parquet (unchanged invocation)
PYTHONPATH=src .venv/bin/python scripts/build_ui_data.py \
  --corpus data/primary/abstracts.json \
  --withdrawn data/primary/abstracts_withdrawn.json \
  --authors data/primary/authors.json \
  --enriched data/primary/abstracts_enriched.sqlite \
  --analysis-root data/outputs/analysis \
  --discover-rollup \
  --minilm-root data/outputs/embeddings/minilm \
  --output site/static/data \
  --output-format parquet-single

# Verify the new schema version + standby_slots table
.venv/bin/python -c "
import pyarrow.parquet as pq, io, json
t = pq.read_table('site/static/data/data.parquet')
names = t.column('table_name').to_pylist()
assert 'standby_slots' in names, 'v2 schema not emitted'
for i in range(t.num_rows):
    if names[i] == 'manifest':
        mj = json.loads(t.column('table_bytes')[i].as_py().decode())
        # Look for schema_version field
print('OK: v2 schema present')
"
```

Drag-replace the file on Dropbox at the existing share URL. The
in-browser decoder accepts both v1 and v2 for one deploy cycle —
no flag-day required.

After the next prod deploy is green for ≥ 24 hours, the v1 acceptance
branch in `site/src/lib/data_package/loader.ts` can be deleted in a
follow-up cleanup commit.

## 7 — Stage 1 state-key rename

Stage 1's emitted `state_key` field is renamed to `fetch_state_key`
in new provenance + checkpoint files. Existing on-disk artefacts
with the legacy `state_key` name keep working — readers accept both
via the shared `read_fetch_state_key` helper. A `DeprecationWarning`
fires every time the legacy field is read.

To migrate an existing operator's local state to the new name in
one go:

```bash
# Re-run Stage 1 — the new state-key field name is written into the
# new provenance file. Old provenance files on disk are untouched.
PYTHONPATH=src .venv/bin/python -m ohbm2026.cli fetch-abstracts
```

`grep -r 'state_key' src/` should return ZERO matches after the
rename PR lands; `grep -r 'fetch_state_key' src/` shows the new
usages.

## 8 — CI label-aware deploy verification

The next merge of a `deploy-production`-labelled PR will exercise the
retry-loop telemetry added in this stage. The workflow log's
`Resolve deploy target` step contains a new line of the form:

```text
PR-association lookup: attempt 1/6 succeeded on first call (XXX ms)
```

(or `attempt N/6 succeeded after retry (XXX ms total)`). If the
attempt count is > 1 the retry loop saved the deploy from
demoting to sandbox. If you see `attempt 6/6 EXHAUSTED — falling
through to sandbox`, the retry budget was insufficient; bump the
loop count in `.github/workflows/deploy-ui.yml`.

## 9 — Common errors

| You see | What it means | What to do |
|---|---|---|
| `BookBuildError: zero abstracts survived` | Every per-abstract pandoc call failed. | Look at `provenance.failed_abstracts[]` — likely a global LaTeX preamble issue (header-includes.tex broke) or pandoc upgrade incompatibility. |
| `BookBuildError: docx export was retired` | `--format docx` was requested. | Switch to `--format md` or `--format pdf`. See § 5. |
| `DeprecationWarning: Stage 1 provenance uses 'state_key'` | Reader hit a legacy artefact still using the old field name. | Acceptable for now (legacy compat is in place); to clean up, re-run `ohbmcli fetch-abstracts` so the new provenance uses `fetch_state_key`. |
| `Stage6BuildError: standby_slots reference invalid` | The parquet emitter found an abstract whose `standby_first_index` doesn't reference an existing row in `standby_slots`. | Bug — file a report. The builder should never emit dangling indices. |
| `pdftotext output differs on re-run` | Determinism regression. | Check `pikepdf` strip-metadata step; ensure the deterministic-strip flag wasn't disabled. |
