<!--
Sync Impact Report
Version change: 1.1.0 -> 1.2.0
Modified principles:
- None renamed
Added sections:
- VII. Discover External State, Don't Hardcode It (new core principle)
- VIII. Provenance For Organizer-Facing Outputs (promoted from an Operational
  Constraints bullet to a full core principle)
- Governance subsection: Application Without Spec Kit
Removed sections:
- Operational Constraints bullet about machine-readable provenance for
  organizer-facing outputs (relocated to Principle VIII)
Templates requiring updates:
- ✅ .specify/templates/plan-template.md (Constitution Check expanded for VII, VIII)
- ✅ .specify/templates/spec-template.md (CA-007, CA-008 added)
- ✅ .specify/templates/tasks-template.md (Polish phase expanded)
- ✅ CLAUDE.md (canonical path updated; "Constitution applies to every turn"
  checklist added; hook install instructions added)
- ✅ CONSTITUTION.md (root replaced with pointer to this file)
- ✅ .specify/scripts/bash/constitution-check.sh (new automatable lint)
- ✅ .githooks/pre-commit (new opt-in pre-commit hook)
- ✅ tests/test_constitution_check.py (new behavioral verification)
Follow-up TODOs:
- None
-->
# OHBM 2026 Pipeline Constitution

This file is the single source of truth for the project's non-negotiable rules.
The root `CONSTITUTION.md` is a pointer to this file. Amendments are made
through `/speckit-constitution`, which rewrites this file, propagates changes
to dependent templates, and bumps the version below.

## Core Principles

### I. Reproducible Venv Execution
All Python actions in this repository MUST run through the repository-local
`.venv/bin/python` interpreter or a `uv` command explicitly targeting that
interpreter. System Python MUST NOT be used for tests, scripts, CLI entrypoints,
dependency installation, or one-off validation commands. New docs, plans, and
automation MUST show `.venv`-scoped Python commands only.

Rationale: the pipeline depends on reproducible local execution, and host-level
Python drift is an avoidable source of breakage.

### II. Immutable Evidence And Canonical Data
Recorded experiment outputs are append-only. New runs MUST write to fresh
directories and MUST NOT overwrite prior recorded results. `data/abstracts.json`
is the canonical normalized raw corpus; cleanup, normalization, or corrective
transformations MUST be captured in explicit derivative artifacts instead of
silently rewriting the raw record. Canonical derived datasets SHOULD prefer
append-or-rebuild workflows over ad hoc in-place mutation.

Data products are local-only. Raw ingest snapshots, derived datasets, caches,
downloaded assets, exported UI bundles, screenshots, and other generated
artifacts MUST NOT be committed to the repository. The gitignored roots
(currently `data/`, `export/`, `tmp/`, `archive/`, `memory/archive/`, and
`.claude/`) are the operative boundary; new artifact roots MUST be gitignored
before any file is written there, and accidental tracking MUST be reverted,
not normalized. Commits MUST include only source code, plans, specs,
templates, docs, and the small fixtures/seed files that those need to
function.

Rationale: the project serves as both evidence base and delivery pipeline, so
operators need to distinguish raw inputs, derived artifacts, and experiments,
and the repository must not become a transport for large or shifting data.

### III. Resumable, Auditable Pipelines
Long-running API, LLM, enrichment, or batch jobs MUST checkpoint incrementally
and remain resumable without recomputing completed records. New pipeline steps
MUST emit deterministic local outputs with enough metadata to explain their
inputs, model choices, and defaults. `ohbmcli` remains the canonical interface
for the main corpus pipeline; script-only workflows are acceptable for
experiments and organizer tooling only when they write auditable outputs and
are documented close to the workflow.

Rationale: resumability keeps expensive work practical, and auditability keeps
current defaults explainable to future operators.

### IV. Plan-First, Test-Driven Delivery
Behavior-changing work MUST begin with the closest relevant plan, spec, or
design note being created or updated before implementation. Tests or other
explicit verification steps MUST be identified first and MUST fail, or be shown
to be missing, before code changes land for behavior, contract, pipeline, or UI
changes. When canonical defaults, interfaces, inputs, or outputs change, the
code and the docs users rely on MUST be updated in the same change.

Rationale: this repository is large enough that unplanned local edits create
hidden regressions and documentation debt quickly.

### V. Secret-Safe, Reviewable Delivery
API keys, access tokens, and similar credentials MUST remain in `.env`, local
environment variables, or secret stores and MUST NOT be committed, echoed into
logs, pasted into docs, embedded in generated artifacts, or pasted into chat
transcripts, issue threads, or screenshots. Reviews and automation MUST assume
redaction by default; before each commit the diff MUST be scanned for token-
shaped strings, `.env` contents, and credential filenames, and any hit MUST be
removed and rotated rather than ignored.

Delivery MUST happen in small, frequent commits with descriptive messages,
made as soon as a logical slice of work is locally verified. Operators MUST
NOT accumulate hours of uncommitted state, MUST NOT batch unrelated changes
into a single commit, and MUST push to the configured remote once the
requested change is complete unless the requester explicitly asks not to
publish it.

Rationale: the repo handles live external services and collaborative work,
so credential hygiene and an auditable, granular commit trail are both
mandatory.

### VI. Fail Loudly, No Shortcuts
Code in this repository MUST surface failures, not hide them. Bare `except`,
catch-all `except Exception: pass`, silent fallbacks that mask broken
behavior, and "log and continue" handlers around operations whose failure
would corrupt downstream artifacts are PROHIBITED. Exception handlers MUST
narrow to the expected error type, MUST either repair, requeue, or re-raise,
and MUST log enough context (record id, model, inputs) to diagnose the
failure from artifacts alone.

Verification gates MUST NOT be bypassed. Skipping tests, disabling pre-commit
or commit-message hooks (e.g. `--no-verify`), commenting out assertions,
weakening type checks, hard-coding "expected" outputs, or marking real
failures as `xfail`/`skip` to make CI green are all PROHIBITED unless the
bypass is explicitly approved in the same change and accompanied by a
follow-up task to remove it. Temporary workarounds MUST be labeled in code
with the root cause and the follow-up reference; expedient fixes MUST be
replaced with real fixes, not left in place.

Rationale: this is a multi-stage pipeline with expensive external API calls
and immutable evidence artifacts; a single silenced failure can poison
downstream outputs for days before anyone notices, and bypassed gates erase
the guarantees the rest of this constitution depends on.

### VII. Discover External State, Don't Hardcode It
Code that depends on artifacts the project does not own — upstream model
zoos, third-party checkpoint sets, vendor enumerations, API response
schemas, external file layouts — MUST detect what is actually present at
runtime (e.g., reading checkpoint metadata, listing files, querying the
service) rather than matching against a hardcoded list. When the discovered
state has no compatible match, the code MUST fail with a precise error
naming what was searched and what was found; it MUST NOT silently fall back
to a stale assumption or skip records. Compatibility tables (e.g.
"feature_type X is not zero-shot transferable") MUST be derived from the
discovered metadata, not from a baked-in allow-list.

Rationale: external dependencies change shape — checkpoints are deprecated,
schemas evolve, vendors rename fields. Hardcoded lists turn an upstream
update into a silent regression weeks later; runtime discovery turns it
into an immediate, diagnosable failure.

### VIII. Provenance For Organizer-Facing Outputs
Every artifact that leaves the developer loop and reaches organizers,
reviewers, or downstream consumers (poster layouts, proposal bundles, UI
exports, cluster lenses, sequencing outputs, organizer memos, comparison
HTML pages) MUST be accompanied by machine-readable provenance: the input
artifacts, embedding bundle, clustering or layout configuration, code
revision, command line, and random seed if any. Human-readable summaries,
HTML pages, screenshots, and spreadsheet exports MUST NOT be the only
record of how an output was produced. Provenance MUST live alongside the
artifact (same directory or referenced manifest) and MUST survive moving
the bundle to another machine; absolute paths, user-home paths, and
machine-local IDs MUST NOT appear in the provenance record.

Rationale: organizer-facing outputs are negotiated, compared, and sometimes
regenerated months later. Without provenance, a chosen proposal cannot be
reproduced or audited, and disagreements about "which version" become
unresolvable.

## Operational Constraints

- Use `uv` to create and manage the repository-local virtual environment before
  any Python work.
- Keep experiment and proposal outputs auditable, with README files or nearby
  docs that state purpose, inputs, outputs, and repeat commands.
- Treat `memory/` as working context rather than canon, and keep local-only
  notes untracked unless someone explicitly requests otherwise.
- Confirm a candidate file or directory is gitignored before writing any
  generated artifact into it; never add data, caches, or exports to the
  index, even temporarily.

## Delivery Workflow

1. Start from the nearest plan, spec, or experiment doc and update it if the
   requested change affects behavior, defaults, or intended workflow.
2. Refresh or create `.venv` with `uv`, then run Python commands only through
   `.venv/bin/python` or `uv` targeting that interpreter.
3. Add or update verification first for code, pipeline, contract, or UI
   changes, then implement the smallest auditable slice.
4. Update README, plan docs, and experiment docs in the same change whenever
   the code changes canonical defaults, paths, commands, or review surfaces.
5. Commit each verified slice as it lands with a descriptive message; do not
   accumulate hours of unrecorded work. Each commit MUST contain only source,
   docs, plans, and small fixtures — never data, caches, exports, or
   downloaded assets.
6. Before each commit, run `.specify/scripts/bash/constitution-check.sh
   --staged` (also wired as `.githooks/pre-commit`) to catch the
   pattern-detectable subset of principle violations: tracked files under
   gitignored roots, bare `except:` in `src/`, `--no-verify` usage, and
   token-shaped strings in the staged diff.
7. Push to the configured remote once the requested change is complete unless
   the requester explicitly asks to keep it unpublished.

## Governance

This constitution supersedes conflicting local habits and outdated docs. Amend
it by updating this file together with any affected templates and operator
documentation in the same reviewable change.

Versioning policy:

- MAJOR: removes or materially redefines a core principle or governance rule
- MINOR: adds a new principle or materially expands required workflow
- PATCH: clarifies wording without changing operative requirements

Compliance review expectations:

- Every implementation plan MUST pass the constitution check before work begins
  and again after design is updated.
- Every task list MUST reflect required verification, documentation sync,
  secret-safe execution, no-data-commit hygiene, no-shortcut error handling,
  runtime discovery of external state, and provenance for organizer-facing
  outputs where relevant.
- Every merge-ready or handoff-ready change MUST confirm venv-only Python
  execution, auditable outputs, docs sync for changed defaults, secret
  hygiene, no committed data artifacts, no silenced failures or bypassed
  verification gates, no hardcoded external-state assumptions, and
  machine-readable provenance for any organizer-facing artifact it touches.

### Application Without Spec Kit

Spec Kit slash commands (`/speckit-plan`, `/speckit-tasks`,
`/speckit-analyze`, etc.) run an automatic Constitution Check, but the
constitution applies on every turn, not only when those commands fire.
Direct edits, ad-hoc prompts, bash-only work, debugging sessions, and
unattended jobs all MUST self-apply these principles. Before reporting work
complete in any mode, Claude (and any human contributor) MUST self-check
against the short-name checklist:

- I. venv-only Python execution
- II. no committed data, caches, exports, or downloaded assets
- III. resumable, auditable pipeline outputs
- IV. plan + verification recorded before behavior change
- V. secrets stayed in `.env`; commits made early and often
- VI. no swallowed failures or bypassed verification gates
- VII. external state discovered at runtime, not hardcoded
- VIII. machine-readable provenance for organizer-facing outputs

If any self-check fails, the change is not complete. The local lint at
`.specify/scripts/bash/constitution-check.sh` automates the subset of these
checks that can be done by pattern (II partial, V partial, VI partial);
passing the lint is necessary but not sufficient — the remaining principles
require judgment and MUST be applied even when no tool flags them.

**Version**: 1.2.0 | **Ratified**: 2026-03-26 | **Last Amended**: 2026-05-12
