# Feature Specification: Data export redesign — LinkML-tight schema + compact storage + cross-conference foundation

**Feature Branch**: `010-export-redesign`
**Created**: 2026-05-18
**Status**: Draft
**Input**: User description: "i'd like a software and database architect agents to focus on the export to ensure it can fit into a proper linkml schema model without the use of range: any everywhere. we will also use this to make the export as compact as possible through optimized storage and compression methods/formats. this will require running some agents to do proper review of the codebase and what has been done, and to understand the ui. it should also keep in mind that in the future we may want to add other conference abstracts and also the neuroscape pubmed analysis projection as the full landscape of neuroscience abstracts, and we may need to cross connect across these conferences without having to regenerate all the data."

## Overview

The Atlas's exported data package — the gzipped tarball the SvelteKit site fetches at first paint — is currently a 26 MB on-the-wire payload (96 MB uncompressed) modelled by a 633-line LinkML schema. The schema works but carries three `range: Any` slots and a handful of secondary looseness (untyped UMAP coordinate arrays, missing enum constraints, parallel-array fields without cross-validation). The shape also implicitly assumes a single conference — every field, every record, every URL is OHBM-2026.

This rework does three coupled things:

1. **Tighten the LinkML schema** so every shard validates against a precise type (every `range: Any` either eliminated by an inner class or explicitly justified with a documented limitation of LinkML's expressivity).
2. **Shrink the export** through better compression and format choices on the bytes that dominate (long text in `enrichment.json`, dense numeric arrays in `neighbors/*`, full sections in `abstracts.json`). Target: at minimum **a 30 % reduction in tarball size** without losing any UI-visible information.
3. **Add a cross-conference foundation** so a future deploy can host OHBM 2026 + ISMRM 2027 + a NeuroScape PubMed landscape projection side-by-side AND let users cross-link across conferences (e.g., "show me other abstracts/papers whose claims overlap this one") without regenerating the existing conferences' shards.

The work is intentionally architectural: we want a software + database architect agent pass to review the codebase + UI first and then ratify (or push back on) the schema and storage choices. We are NOT rebuilding the SvelteKit UI surface in this rework — every URL, every testid, every user-visible feature stays the same.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Visitor on a slow link gets to the Atlas faster (Priority: P1)

A reviewer on a slow café Wi-Fi opens `abstractatlas.brainkb.org/ohbm2026/`. The redesigned data package downloads in noticeably less time than today's; the first interactive paint stays inside the SC-001 budget (≤ 3 s on a desktop network); on a 1 Mbps mobile link the home page reaches "search-ready" perceptibly faster than the pre-rework deploy.

**Why this priority**: This is the payoff for the entire rework — every other change underpins it. Without a measurable shrink, nothing the rework introduces is justified.

**Independent Test**: Compare the tarball size and first-interactive-paint timing before and after the rework on a fixed throttled link (1 Mbps, 100 ms RTT). Both the tarball byte size and the WebPageTest "search-input visible" time MUST decrease by at least 30 % and 20 % respectively.

**Acceptance Scenarios**:

1. **Given** the redesigned tarball is published to the production URL, **When** a fresh-cache visitor opens `<cname>/ohbm2026/` on a throttled 1 Mbps link, **Then** the data-package download completes in ≥ 30 % less wall-clock time than the pre-rework baseline measured on the same throttling profile.
2. **Given** the redesigned tarball, **When** Lighthouse-CI runs the next PR-preview audit, **Then** the audit's First Contentful Paint and Largest Contentful Paint metrics each improve by ≥ 10 % versus the pre-rework baseline run.

---

### User Story 2 — Schema validator confirms every shard is precisely typed (Priority: P1)

A reviewer or downstream consumer runs `scripts/validate_ui_data.sh` against the redesigned shards. The LinkML validator reports 68 / 68 pass — same as today — but the schema itself now resolves every shard down to concrete types: numeric ranges have explicit dimensions, parallel arrays are cross-validated, enum-coded fields carry the enum, and every previously-`range: Any` slot is either replaced by an inner class or accompanied by a one-paragraph rationale that names the LinkML feature whose absence forces the looseness.

**Why this priority**: The constitution (Principle VIII) makes machine-readable provenance non-negotiable for organizer-facing outputs. A loose schema lets downstream consumers build incorrect mental models of the data; tightening it is the highest-leverage improvement we can make to the contract.

**Independent Test**: Diff the pre- and post-rework `ui_data.linkml.yaml`: the count of `range: Any` MUST drop to zero OR every remaining instance MUST carry an inline `# LIMITATION: …` comment explaining the LinkML feature that's missing. `pyright` / `linkml-validate` runs return zero "missing schema" warnings.

**Acceptance Scenarios**:

1. **Given** the redesigned schema, **When** `scripts/validate_ui_data.sh` runs against the freshly-built data package, **Then** 68 / 68 shards validate AND `grep -c "range: Any" ui_data.linkml.yaml` returns 0 (or every remaining occurrence is annotated with a LIMITATION comment).
2. **Given** a downstream consumer (e.g., a Python tool generated from the LinkML), **When** it deserializes any shard, **Then** every field resolves to a concrete typed value — no `dict[str, Any]` and no `JSON-encoded string that needs a second parse`.

---

### User Story 3 — Adding a second conference does NOT regenerate the first conference's shards (Priority: P2)

A maintainer prepares to host a second conference (e.g., ISMRM 2027 or a NeuroScape PubMed projection) on the same Atlas. They run the data-build pipeline for the new conference; the build emits only the new conference's shards under a separate namespace. The existing OHBM 2026 shards are not touched, not re-hashed, and not re-uploaded. The deployed site serves both conferences side-by-side, and a cross-conference query ("show me PubMed papers that overlap this OHBM abstract's claims") works without a corpus-wide rebuild.

**Why this priority**: Important for the long-term architecture but not on the critical path for the current OHBM deployment. P2 because the cross-conference feature itself isn't shipped here; only the data-model affordances are.

**Independent Test**: Build the data package twice with mock corpora — once with just OHBM, once with OHBM + a stub second conference. The OHBM shards from run 1 and run 2 MUST be byte-identical (sha256 match) for every shard the OHBM data alone determines. The second-conference shards MUST live under a separate URL prefix or filename namespace so neither overwrites the other.

**Acceptance Scenarios**:

1. **Given** the export builder is run with `--conference ohbm2026 …`, **When** a maintainer subsequently runs the same builder with `--conference second-conf …` against an independent corpus, **Then** every OHBM 2026 shard file in the manifest is byte-identical to the run-1 output (verified by sha256).
2. **Given** both conferences are deployed, **When** the SvelteKit site loads a cross-conference neighbour list for an OHBM abstract, **Then** the list returns entries pointing at the second-conference's URL space (with per-entry `conference_id` metadata) without the OHBM shards needing to know about the second conference at build time.
3. **Given** a NeuroScape PubMed projection is added as a third conference, **When** an OHBM abstract is opened, **Then** its "related papers in the PubMed landscape" affordance surfaces — driven by a cross-conference embedding-space neighbour table that lives in a per-conference shard, NOT in the OHBM shards themselves.

---

## Functional Requirements *(mandatory)*

- **FR-201 (Schema tightness)**: Every `range: Any` slot in `specs/008-ui-rewrite/contracts/ui_data.linkml.yaml` MUST be either (a) replaced by a concrete inner class or typed-pair-array, or (b) retained with an inline `# LIMITATION:` comment naming the LinkML construct whose absence forces the looseness AND citing the issue tracker / RFC where the limitation is being addressed. The post-rework count of un-justified `range: Any` MUST be zero.

- **FR-202 (No silent type widening)**: Secondary looseness identified during the architectural review (untyped UMAP coordinate arrays, missing enum on `evidence_eco_codes`, parallel-array fields like `reference_dois`/`reference_urls`/`reference_titles` without cross-validation, multi-valued fields without `minimum_cardinality`) MUST EACH be tightened OR flagged with an inline rationale. The schema review pass MUST be exhaustive — no silent gaps.

- **FR-203 (Tarball size budget)**: The redesigned, gzipped data package MUST be at least 30 % smaller on disk than the pre-rework `26 MB` baseline (`≤ 18 MB`). The improvement MUST come from real reductions (drop-unused fields, denser numeric formats, better compression) — not from removing UI-visible content.

- **FR-204 (Zero UI feature regression)**: Every existing Playwright e2e spec (the eight currently-tracked specs under `site/src/tests/e2e/`) MUST pass against the redesigned data package without any change to test assertions. Any change to a testid, route, or visible affordance is out of scope for this rework.

- **FR-205 (First-paint independence from heavy shards)**: The home page MUST become interactive (search bar visible AND the result grid populated with at least 60 cards) before the heaviest data on disk (currently `enrichment.json` at 34 MB raw, ~7 MB compressed) has finished downloading and parsing. The mechanism — lazy per-shard fetch, range-request seek-into-container, critical/deferred split, or a query-engine lazy materialisation — is intentionally not pinned here; FR-212 decides empirically.

- **FR-206 (Cross-conference identifier)**: The data-model MUST introduce a stable `conference_id` (string, e.g. `"ohbm2026"`, `"ismrm2027"`, `"pubmed-neuroscape"`) somewhere in the export. The Atlas UI MUST be able to determine from a given record which conference produced it WITHOUT consulting the URL path. The exact placement (envelope-only, per-record column, separate manifest field) is empirically optimised in FR-212.

- **FR-207 (No-regenerate guarantee)**: The data-builder pipeline MUST be able to emit a single conference's data independently of all other conferences. Adding a second conference to the deployed tree MUST NOT require rebuilding, re-hashing, or re-uploading any pre-existing conference's data. The `build_info` envelope (state-keys, code revision, timestamps) MUST remain per-conference.

- **FR-208 (Cross-conference linking shape)**: The data-model MUST provide a place for cross-conference linking (neighbour pairs, citation overlap, claim-text overlap — at least one of these). Whether the linking lives as a pre-computed table, a SQL JOIN over base tables, or a runtime vector-search over a shared embedding space is empirically chosen in FR-212. The hard constraint: cross-conference linking MUST be generatable AFTER both conferences' base data exists, without rebuilding either.

- **FR-212 (Empirical format selection — experiments before commitment)**: The design phase MUST run a documented experiment matrix across at least the following candidate storage formats, each producing the same OHBM-2026 corpus in its native shape:
    1. **Status quo, tightened**: gzipped tarball of JSON shards with unused fields dropped, dense numeric arrays moved to binary sidecars, brotli or zstd as alternate compressors.
    2. **Single-file Parquet, multi-table**: one `*.parquet` per table (abstracts, authors, enrichment, …) bundled OR as a single multi-table Parquet file. Range-request fetch via HTTP `Range:` headers on row-group boundaries; no in-browser query engine.
    3. **Single-file Parquet + DuckDB-WASM**: same Parquet files PLUS the DuckDB-WASM query engine in the browser; SQL queries over `httpfs`-fetched ranges.
    4. **Single-file SQLite**: one `.sqlite` blob loaded into the browser via `@sqlite.org/sqlite-wasm` (or `sql.js`). FTS5 for the lexical search index. Optionally a custom range-request VFS so the whole file doesn't load on first paint.
    5. **Single-file DuckDB**: a `.duckdb` database file loaded by DuckDB-WASM. Distinct from candidate 3 in that it's ONE file, not a directory of `.parquet`s.
    6. **Arrow IPC** with record-batch-level range requests.

    For each candidate, the experiment MUST measure: (a) total on-disk size, (b) cold-start time to "search-ready" on a throttled 1 Mbps / 100 ms RTT link, (c) the wire bytes the browser actually downloads in a typical session (home → search → open one abstract → open About), (d) the in-browser engine / decoder bundle cost in bytes, (e) feasibility of cross-conference JOIN / lookup (qualitative, with a short rationale), and (f) the LinkML-schema-equivalent fidelity (can the format admit per-column types or does it degrade to opaque blobs).

    The experiment outputs MUST land in `specs/010-export-redesign/research.md` as a single decision table. The architect-agent pass (FR-209) reviews this table and recommends; the human commits to a format AFTER reviewing the numbers, NOT before.

    **The format choice MUST NOT be made without these numbers in front of the reviewer.**

- **FR-209 (Architect-agent review trail)**: The design phase of this rework MUST run at least one architecture review by an LLM agent against the empirical results from FR-212, with the agent's findings + the human responses captured in `specs/010-export-redesign/research.md`. The review MUST cover: schema fidelity vs the candidate format's expressivity, storage efficiency at the measured numbers, forward-compatibility for the cross-conference scenario, and any cross-cutting risks the bench didn't measure (browser memory ceilings, mobile-Safari WASM caveats, etc.).

- **FR-209 (Architect-agent review trail)**: The design phase of this rework MUST run at least one architecture review by an LLM agent against the proposed schema + storage choices, with the agent's findings + the human responses captured in `specs/010-export-redesign/research.md`. The review MUST cover: schema fidelity, storage efficiency, and forward-compatibility for the cross-conference scenario.

- **FR-210 (Deterministic output preserved)**: The Stage-6 deterministic-build contract (fixed `mtime` 2026-01-01, byte-identical tarballs across rebuilds with the same inputs, Dropbox share-link inode preservation) MUST be preserved end-to-end. New compression / encoding choices MUST be deterministic; new field orders MUST be canonical.

- **FR-211 (Migration path for the current deploy)**: The redesigned data package MUST be servable from the existing Dropbox URL (or a sibling URL behind the same env var) WITHOUT a hard cutover that breaks the production `/ohbm2026/` deploy mid-rollout. A staging tarball MUST be testable on a PR-preview deploy before the production URL flips.

## Assumptions

- The current Stage-6 data package (`site/static/data/*` + `data-package.tar.gz`) is the baseline — its 26 MB gzipped / 96 MB uncompressed / 633-line LinkML schema is what the rework starts from.
- The SvelteKit UI is treated as a stable consumer in this rework. Schema / storage changes that require UI edits are in scope (e.g., the `dataPackage` loader gains a lazy-per-shard mode), but UI-feature changes (new affordances, new routes, new testids) are NOT.
- The "architect agents" the user requested are LLM agents spawned during `/speckit-plan` and `/speckit-implement` (Explore for codebase review, an architect-style review pass in research.md, code-reviewer agents on the PR). They are an implementation tactic, not a hard runtime dependency. Their primary deliverable is the bench-matrix review in FR-212 / SC-211 — empirical analysis, not a paper design.
- The empirical experiment phase (FR-212) is the single biggest scoping risk. A reasonable budget is one focused session: build each candidate format from the same source corpus, measure six numbers per candidate, and write up the comparison. The actual format choice MUST follow the table; if no candidate clears a hard threshold (e.g., everyone misses the ≥ 30 % shrink target), we keep the status quo and re-scope.
- "NeuroScape PubMed analysis projection as the full landscape of neuroscience abstracts" is treated as a future, separate conference (`pubmed-neuroscape` or similar) with its own corpus and its own shards. This rework does NOT generate or ingest a PubMed corpus — it only ensures the data-model can accommodate one when it lands.
- Cross-conference linking is foreseen via the **embedding space**: every conference's abstracts get projected into the published NeuroScape 64-D space (already used for OHBM), making cross-conference neighbour computation a vector-search problem with a shared coordinate system. The spec does not pin this — it allows other linking strategies (citation overlap, claim-text overlap, etc.) too.

## Out of Scope

- Re-architecting the SvelteKit site itself (routes, components, stores, tests). This rework only touches the data-package builder and the runtime `loadDataPackage` / `loadShard` callers; the rendered UI stays identical.
- Adding a real second conference's data, or ingesting PubMed abstracts. This rework only creates the affordances; populating them is a future stage.
- Re-running Stage 1–4 (corpus fetch, enrichment, embedding, analysis). Those pipelines stay as-is; only the Stage 5 / UI-data builder is touched.
- Changing the LinkML version or vendor (still `linkml-validate` from the `linkml-runtime` project). Tooling stays put.
- Adding a database. The export remains a static-file tarball served over HTTPS; introducing a query backend is explicitly future work.

## Success Criteria *(mandatory)*

- **SC-201 (Tarball shrink)**: Production tarball size drops from `≤ 26 MB` (pre-rework baseline) to `≤ 18 MB` (≥ 30 % reduction). Measured by `du -b` on the published `data-package.tar.gz`.

- **SC-202 (Uncompressed shrink)**: Sum of `du -b` across `site/static/data/**/*.json` plus binary sidecars drops by ≥ 20 % from the `96 MB` pre-rework baseline (`≤ 77 MB`).

- **SC-203 (Schema zero-Any)**: `grep -c "range: Any" ui_data.linkml.yaml` returns either `0` OR a number where every match has an immediately-preceding `# LIMITATION:` comment line explaining what LinkML construct is missing. Verified by a script.

- **SC-204 (Validator pass)**: `scripts/validate_ui_data.sh` reports `passed: 68  failed: 0` against the redesigned shards.

- **SC-205 (Lazy-load home)**: On the PR-preview deploy, the `[data-testid="search-input"]` becomes visible within `≤ 3 s` of first paint on a throttled 1 Mbps link, even when `enrichment.json` is the largest shard and has NOT finished downloading. Verified by a Playwright trace at the throttled profile.

- **SC-206 (Existing e2e stays green)**: All 26 currently-passing Playwright e2e cases (across the eight tracked specs) pass against the redesigned data package without per-spec source edits.

- **SC-207 (No-regenerate proof)**: Building the data package twice — first with `[ohbm2026]` only, then with `[ohbm2026, mock-second-conf]` — produces byte-identical OHBM shards across both runs (verified by per-file sha256 diff).

- **SC-208 (Cross-conference shard isolation)**: A second-conference's shards live under a distinct namespace (e.g., `data/<conference_id>/...` or `data/<conference_id>__abstracts.json`) so neither conference's filename ever collides with the other.

- **SC-209 (Lighthouse delta)**: The next PR-preview Lighthouse-CI run shows FCP and LCP each improved by `≥ 10 %` versus the pre-rework baseline run.

- **SC-210 (Architect review captured)**: `specs/010-export-redesign/research.md` contains an "Architect review" section with at least one LLM agent's findings + the human responses, dated.

- **SC-211 (Format-selection bench matrix)**: `specs/010-export-redesign/research.md` contains a "Format selection — empirical results" table with one row per candidate format from FR-212, populated with the six measured metrics (on-disk size, cold-start TTI, session wire bytes, decoder bundle, cross-conference feasibility, schema fidelity). The committed format choice MUST cite this table.

## Key Entities

The rework introduces no new corpus-level entities. The data-model affordances added are:

- **`conference_id`** (string): Stable identifier per conference. First value: `"ohbm2026"`. Values for future conferences are TBD; the constraint is "URL-safe, lower-snake-case, no slashes". Lives in the data-model as either an envelope field, per-record column, or per-file header — the placement that's cheapest under the chosen storage format is decided by FR-212's bench matrix.
- **Cross-conference linking surface**: A way for the deployed site to relate a record in one conference to one or more records in another. Could be a pre-computed pairs table, a SQL JOIN over base tables, or a runtime nearest-neighbour search in a shared embedding space. The concrete shape is decided by FR-212 based on what the chosen format makes natural.
- **Storage container** (TBD per FR-212): One of {gzipped-JSON tarball, Parquet directory, Parquet+DuckDB-WASM, single SQLite file, single DuckDB file, Arrow IPC}. The choice is the single most consequential design output of this rework.

## Dependencies

- The Stage-6 data package builder (`src/ohbm2026/ui_data/`) and the runtime fetcher (`site/src/lib/data_package.ts`, `site/src/lib/shards.ts`) — both are being modified.
- The Stage-6 LinkML schema (`specs/008-ui-rewrite/contracts/ui_data.linkml.yaml`) — under significant edit.
- The Stage-9 conference-subpath rework (`specs/009-conference-subpath/`) — already on `main`. This rework builds on top of the subpath structure (every URL stays under `/ohbm2026/`) and re-uses the deploy workflows that stage `site/publish/ohbm2026/`.
- The published NeuroScape Stage-2 model on Zenodo (`https://zenodo.org/records/14865161`) — unchanged; we keep using it as the cross-conference embedding space.
