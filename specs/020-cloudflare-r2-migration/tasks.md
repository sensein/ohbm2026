---
description: "Task list for Cloudflare R2 Migration & Content-Hashed Data Store"
---

# Tasks: Cloudflare R2 Migration & Content-Hashed Data Store

**Input**: Design documents from `/specs/020-cloudflare-r2-migration/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: INCLUDED. The constitution (Principle IV) mandates verification-first
for behavior/contract/pipeline/UI changes, and the spec's CA-002 + data-model
validation table name the tests per behavior. All Python tests use `unittest`
with `TemporaryDirectory` fixtures and `botocore.stub.Stubber` (no network); the
one site test uses `vitest run`.

**Live endpoint (operator-provided)**: R2 public base URL =
`https://aadata.cirrusscience.org` (custom domain, CORS configured). This is the
value of `R2_PUBLIC_BASE_URL` in `.env`; the S3 *upload* endpoint is still
`https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` (separate from the public
read domain). End-to-end validation is doable locally (upload → build → render).

**Run conventions**:
- Python: `PYTHONPATH=src .venv/bin/python -m unittest tests.<module> -v`
- CLI: `PYTHONPATH=src .venv/bin/python -m ohbm2026.cli <subcommand> …`
- Site test: `cd site && pnpm exec vitest run src/tests/unit/loader_r2_passthrough.test.ts` (NEVER `pnpm test:unit -- --run`)

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1 / US2 / US3 (setup, foundational, polish carry no story label)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Dependencies, ignore rules, and package skeleton before any code.

- [X] T001 [P] Add optional dependency group `r2 = ["boto3>=1.34"]` under `[project.optional-dependencies]` in `pyproject.toml`, then install it into the repo venv: `uv pip install --python .venv/bin/python ".[r2]"`.
- [X] T002 [P] Add Stage-20 ignore lines to `.gitignore` (the `data/` root is already ignored at line 7; these are for convention/clarity and MUST precede any write): `data/provenance/atlas_upload_provenance__*.json` and `data/outputs/data-hosting-comparison__*.json`.
- [X] T003 Create the package skeleton `src/ohbm2026/atlas_hosting/__init__.py` (empty module; submodules added by later tasks).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared building blocks every story depends on (exceptions,
content-hashing, the R2 client). **⚠️ No user story may begin until this phase
is complete.**

- [X] T004 [P] Write FAILING test `tests/test_stage20_exceptions.py` for the `Stage20Error` subtree: each of `R2CredentialsError`, `R2UploadError`, `ContentHashMismatchError`, `ArtifactDiscoveryError`, `HostingComparisonError` subclasses `Stage20Error` → `OhbmStageError`; keyword-only context attributes are stored; all appear in `exceptions.__all__`. Mirror `tests/test_atlas_exceptions.py`.
- [X] T005 Implement the `Stage20Error` subtree in `src/ohbm2026/exceptions.py` (and extend `__all__`) to pass T004, matching the `Stage15Error` style (keyword-only `field`/`key`/`reason`/etc. attrs, docstrings). Per research.md §R-9.
- [X] T006 [P] Write FAILING test `tests/test_atlas_hosting_content_hash.py`: streamed `sha256_file` equals `hashlib.sha256(path.read_bytes())`; `derive_object_key(sha256, filename, prefix)` = `[<prefix>/]<sha256>/<filename>`, stable for identical bytes and distinct for differing bytes; `public_url(base, key)` joins to `https://…`.
- [X] T007 Implement `src/ohbm2026/atlas_hosting/content_hash.py` (`sha256_file` streaming over fixed chunks; `derive_object_key`; `public_url`) to pass T006. Per research.md §R-1.
- [X] T008 [P] Write FAILING test `tests/test_atlas_hosting_r2_client.py`: a missing/blank required `R2_*` var → `R2CredentialsError` (raised before any client call); the S3 endpoint is built as `https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` with `region_name="auto"`; a `botocore` `ClientError` from `head_object`/`upload` surfaces as `R2UploadError` with context (env + boto3 stubbed/mocked).
- [X] T009 Implement `src/ohbm2026/atlas_hosting/r2_client.py` to pass T008: read creds via `get_api_key(env_path, var)` (`fetch/graphql_api.py:201`); build the boto3 S3 client (endpoint from `R2_ACCOUNT_ID`, sigv4, `region="auto"`); `object_exists(key) -> (exists: bool, size: int|None)` via `head_object` catching `ClientError` and inspecting code/status for `404`/`NoSuchKey` precisely (no bare except); `upload(key, path)` via `upload_file` + `TransferConfig` (multipart for large files); other `ClientError` → `R2UploadError`. Per research.md §R-3/§R-4/§R-5.

**Checkpoint**: exceptions + content-hashing + R2 client exist and are unit-tested; stories can begin.

---

## Phase 3: User Story 1 - The live site serves the current bundle from R2 (Priority: P1) 🎯 MVP

**Goal**: Publish the current atlas-package parquets to R2 under content-addressed
keys via `ohbmcli upload-atlas-package`, register a new R2 channel, and confirm
all three site surfaces render identically from the R2 URLs.

**Independent Test**: Run a local upload against the built package, point the
site at the emitted R2 URLs, build/serve locally, and confirm `/ohbm2026/`,
`/neuroscape/`, and atlas-root render with no console fetch/CORS/Range errors
(atlas-root exercises a sibling Range fetch). (SC-001)

### Tests for User Story 1 (write FIRST, ensure they FAIL)

- [X] T010 [P] [US1] Write test `site/src/tests/unit/loader_r2_passthrough.test.ts` asserting `normaliseDropboxUrl('https://aadata.cirrusscience.org/<sha>/atlas.parquet')` returns the URL unchanged (only Dropbox hosts are rewritten), using the `vi.mock('hyparquet')` + `vi.stubEnv` style of `loader_dispatch.test.ts`. Locks FR-005 (this verifies existing behavior — it must pass against the current loader and guard against future regressions).
- [X] T011 [P] [US1] Write FAILING test `tests/test_atlas_hosting_uploader.py::test_happy_path` (fake client double): given `ohbm2026.parquet` (separate) + a package dir with `neuroscape`/`atlas`/`neuroscape_vectors` (all four required), the uploader discovers them, derives content-addressed keys, sees `object_exists` → absent, issues one `upload` per artifact, writes a manifest, and returns/emits a registry-shaped `channel_entry` with `{url, sha256}` per artifact.
- [X] T012 [P] [US1] Write FAILING test `tests/test_atlas_hosting_manifest.py`: `UploadManifest` round-trips to/from dict; `upload_state_key` is the deterministic `_stable_hash` of `{bucket, key_prefix, sorted (logical_name, sha256)}`; path fields pass through `normalise_path`; serialized dict validates against `contracts/upload-manifest.schema.json`.

### Implementation for User Story 1

- [X] T013 [US1] Implement `src/ohbm2026/atlas_hosting/manifest.py` to pass T012: `UploadManifest` dataclass (fields per data-model.md), `to_dict`/`from_dict`, `write(out_dir)` → `data/provenance/atlas_upload_provenance__<upload_state_key>.json` using `atlas_package.provenance.normalise_path` for path fields and `artifacts._stable_hash` for the key.
- [X] T014 [US1] Implement `src/ohbm2026/atlas_hosting/uploader.py` happy path to pass T011: discover the bundle — `ohbm2026.parquet` from `--ohbm2026-parquet` + `neuroscape`/`atlas`/`neuroscape_vectors` from `--package-dir` (all four required); read each parquet's `build_info.state_key` (best-effort, via `manifest_json` predicate pushdown) for `source_build_state_key`; for each artifact hash → key → `object_exists` → upload-if-absent / basic skip-if-present (the size-guard + explicit skip logging land in T024); assemble `ContentAddressedObject`s, write the manifest, and build the `channel_entry`. Depends on T007, T009, T013.
- [X] T015 [US1] Implement `src/ohbm2026/atlas_hosting/cli.py` `build_parser()` + `main()` for `upload-atlas-package` (args per `contracts/cli-upload-atlas-package.md`: `--package-dir` required, `--ohbm2026-parquet` required, `--env-file` default `.env`, `--manifest-out` default `data/provenance/`, `--dry-run` — registered here as a parse-only flag whose no-write behavior lands in T024), print the `channel_entry` JSON + summary to stdout; then register + dispatch it in `src/ohbm2026/cli.py` (mirror the `build-atlas-package` `_copy_actions` + dispatch pattern at `cli.py:58-62,255`).
- [X] T016 [P] [US1] Write FAILING test `tests/test_atlas_hosting_cli.py::test_upload_parser_and_dispatch`: the top-level `ohbmcli upload-atlas-package --help` resolves; argv routes to `atlas_hosting.cli.main`; required `--package-dir` enforced. (Pairs with T015.)
- [X] T017 [US1] **Live validation** (SC-001). **CORS precondition check (UN2)**: before building, confirm the bucket CORS allowlist includes the origin you'll validate from — a preflight `curl -sI -X OPTIONS -H 'Origin: <origin>' -H 'Access-Control-Request-Method: GET' https://aadata.cirrusscience.org/<an-uploaded-key>` must return an `Access-Control-Allow-Origin` matching `<origin>` (use `http://localhost:5173` for `pnpm dev`, or the deployed origin for preview). If it does not, validate via the pushed PR-preview origin instead (see T031), since the operator-added CORS rule may cover only the production origin. Then: set `.env` (`R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL=https://aadata.cirrusscience.org`); run `upload-atlas-package --package-dir data/outputs/atlas-package__<state-key> --ohbm2026-parquet data/outputs/parquets/<corpus-key>/ohbm2026.parquet`; copy the emitted R2 URLs into `site/.env.local` (`VITE_DATA_PACKAGE_URL_OHBM2026`/`_NEUROSCAPE`/`_ATLAS`/`_NEUROSCAPE_VECTORS` — all four); for each mode run `cd site && VITE_SITE_MODE=<ohbm2026|neuroscape|atlas-root> pnpm dev` (or `pnpm build && pnpm preview`); confirm every surface renders with no console CORS/Range/fetch errors. (If the local origin isn't in the bucket CORS allowlist, validate via a pushed PR preview instead — see T031 wiring.)

**Checkpoint**: the current bundle is served from R2 and the site renders from it — MVP complete and independently demonstrable.

---

## Phase 4: User Story 2 - Publish a new atlas version without overwriting the old (Priority: P2)

**Goal**: Harden the uploader into a content-hashed *system*: idempotent
(zero-byte re-upload), immutable/non-destructive across versions, fail-loud on
bad inputs, with a dry-run mode — so future atlas updates are a safe re-run.

**Independent Test**: Upload a package, re-run unchanged (zero bytes uploaded),
then change one artifact and upload again (only that artifact gets a new key;
all prior keys/URLs remain). (SC-003, SC-004)

### Tests for User Story 2 (write FIRST, ensure they FAIL)

- [X] T018 [P] [US2] Add `tests/test_atlas_hosting_uploader.py::test_idempotent_skip` (Stubber): every `head_object` → 200 with matching size ⇒ zero `upload` calls; every artifact `action == "skipped"`.
- [X] T019 [P] [US2] Add `tests/test_atlas_hosting_uploader.py::test_immutable_multi_version` (Stubber): with one artifact's bytes changed, only the changed artifact's new content key is `upload`ed; no `delete_object`/overwrite of any prior key occurs.
- [X] T020 [P] [US2] Add `tests/test_atlas_hosting_uploader.py` discovery tests (fake client): a missing required parquet (`atlas` / `neuroscape_vectors`) → `ArtifactDiscoveryError`; a missing `--ohbm2026-parquet` file → `ArtifactDiscoveryError`; an unexpected `*.parquet` in `--package-dir` (incl. a stray `ohbm2026.parquet`) → `ArtifactDiscoveryError`. (`neuroscape_vectors` is REQUIRED — no longer optional.)
- [X] T021 [P] [US2] Add `tests/test_atlas_hosting_uploader.py::test_hash_mismatch_guard` (Stubber): `head_object` → 200 but `ContentLength` ≠ local file size ⇒ `ContentHashMismatchError` (no overwrite).
- [X] T022 [P] [US2] Add `tests/test_atlas_hosting_uploader.py::test_dry_run` (Stubber): `--dry-run` performs discovery + hashing + existence checks, prints the would-be `channel_entry`, but issues NO `upload` and writes NO manifest.
- [X] T023 [P] [US2] Add `tests/test_atlas_hosting_uploader.py::test_manifest_safe`: the written manifest contains no absolute/`~` path (any such path → the manifest write raises via `normalise_path`) and no R2 secret value (only bucket, public base, hashes, URLs).

### Implementation for User Story 2

- [X] T024 [US2] Extend `src/ohbm2026/atlas_hosting/uploader.py` (and `cli.py` `--dry-run` wiring) to pass T018–T023: explicit skip-if-present branch with size guard (`ContentHashMismatchError`), `ArtifactDiscoveryError` for missing/unexpected artifacts, optional-vectors handling, and the `--dry-run` no-write path (completing the parse-only flag declared in T015). Logs each skip explicitly (no silent no-op). Depends on T014, T015.
- [X] T025 [US2] **Live multi-version proof** (SC-003/SC-004): re-run `upload-atlas-package` on the unchanged package → confirm `summary.uploaded == 0`; then alter one input and rebuild (or hand-modify a copy), upload again → confirm only the changed artifact occupies a new key and every previously published URL still resolves (HTTP 200 + byte-identical). Record outcome in the run notes.

**Checkpoint**: the upload system is idempotent, immutable, and fail-loud — future updates are a safe re-run.

---

## Phase 5: User Story 3 - Compare R2 against Dropbox (Priority: P3)

**Goal**: Produce machine-readable Dropbox↔R2 evidence (byte-parity, CORS, Range)
that the deferred production-cutover decision will rest on.

**Independent Test**: Run `compare-data-hosting` over the Dropbox and R2 channels
and confirm the report records a byte-parity / CORS / Range verdict per artifact,
fails loudly on any probe failure, and exits 0 only when all pass. (SC-005)

### Tests for User Story 3 (write FIRST, ensure they FAIL)

- [X] T026 [P] [US3] Write FAILING test `tests/test_atlas_hosting_compare.py` (`requests` mocked): a `206` + valid `Content-Range` ⇒ `range_supported=true` (the verdict that satisfies SC-002 — a `206` means only the requested bytes cross the wire, not the full file); a `200` to a ranged GET ⇒ `range_supported=false`; an echoed `Access-Control-Allow-Origin` (origin or `*`) ⇒ `cors_allowed=true`; equal sha256 ⇒ `byte_parity=true`; `overall_pass` is the AND across artifacts; a failed probe is RECORDED with `error` set (never omitted) and forces `pass=false`; an un-attemptable probe (malformed URL / missing artifact in a channel) ⇒ `HostingComparisonError`.
- [X] T027 [P] [US3] Write FAILING test `tests/test_atlas_hosting_cli.py::test_compare_parser_and_exit_codes`: `compare-data-hosting --help` resolves and routes to `atlas_hosting.cli.main`; exit 0 when `overall_pass`, exit 1 when not, exit >1 on `HostingComparisonError`.

### Implementation for User Story 3

- [X] T028 [US3] Implement `src/ohbm2026/atlas_hosting/compare.py` to pass T026: `EndpointProbe`/`ArtifactComparison`/`ComparisonReport` dataclasses (data-model.md); the Range/CORS/byte-parity probes via `requests` (with `--trust-recorded-sha256` to skip downloads); fail-loud aggregation; serialize to a dict validating against `contracts/comparison-report.schema.json`.
- [X] T029 [US3] Implement `compare-data-hosting` `build_parser()` + `main()` in `src/ohbm2026/atlas_hosting/cli.py` (args per `contracts/cli-compare-data-hosting.md`), write the report to `data/outputs/data-hosting-comparison__<ts>.json`, print the per-artifact ✓/✗ table, and set exit codes; register + dispatch in `src/ohbm2026/cli.py`. Depends on T028.
- [X] T030 [US3] **Live comparison** (SC-005): export the registry locally (`gh variable get OHBM2026_UI_DATA_PACKAGE_URLS > /tmp/registry.json`); run `compare-data-hosting --registry /tmp/registry.json --dropbox-channel <current-prod-key> --r2-channel <new-r2-key> --origin https://abstractatlas.brainkb.org`; confirm `overall_pass` and that the report is written. (Delete `/tmp/registry.json` after — it is not committed.)

**Checkpoint**: all three stories independently functional; cutover evidence in hand.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [X] T031 [P] Update `README.md`: the R2 publish runbook (build → `upload-atlas-package` → register channel via `gh variable set` → set `site/data-channel.json` → PR preview), the new subcommands, and the `R2_*` env vars (names only, never values).
- [X] T032 [P] Add the operational data-hosting note to the body of `CLAUDE.md` (R2 channel alongside Dropbox; the SPECKIT plan pointer is already updated): content-addressed keys, `aadata.cirrusscience.org` public base, `.env` var names, and that `resolve-data-channel.sh`/the loader are unchanged.
- [X] T033 [P] Update the explanatory comments in `.github/scripts/resolve-data-channel.sh` and `site/data-channel.json` to note the registry channels may now hold R2 URLs (no resolver/site code change).
- [X] T034 [P] Add a schema-validation check (small test or `scripts` step) that a produced upload manifest validates against `contracts/upload-manifest.schema.json` and a produced comparison report against `contracts/comparison-report.schema.json`.
- [X] T035 Secret-exposure review: confirm no `R2_*` value appears in stdout, the manifest, the report, the emitted channel snippet, or logs; confirm `git status` shows no `data/` artifact staged and the new ignore lines (T002) are present.
- [X] T036 Error-handling + external-state audit: no bare `except` (precise `ClientError` code/status handling only); existence/Range/CORS discovered at runtime (`head_object`/live probes), not hardcoded; missing-artifact/credential/mismatch paths raise precise typed errors; provenance manifest carries inputs/hashes/revision/command/timestamp with no absolute/`~` paths.
- [X] T037 Run `.specify/scripts/bash/constitution-check.sh --full` and resolve any reported violation; run the full Python suite `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests` + the site test `cd site && pnpm exec vitest run`.
- [ ] T038 Run `quickstart.md` end-to-end (steps 0–6) as the acceptance pass.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies.
- **Foundational (Phase 2)**: depends on Setup; BLOCKS all stories.
- **US1 (Phase 3)**: depends on Foundational. The MVP.
- **US2 (Phase 4)**: depends on US1 (extends `uploader.py`/`cli.py` from T014/T015). Independently *testable* (its guarantees), but not a fresh code path.
- **US3 (Phase 5)**: depends only on Foundational (uses `content_hash` + `exceptions`, not the uploader); can run in parallel with US1/US2 once Phase 2 is done.
- **Polish (Phase 6)**: after the desired stories land.

### Within each story

- Tests written first and FAIL before implementation.
- content_hash/r2_client/manifest (modules) before uploader; uploader before CLI wiring; core before the live-validation task.

### Parallel opportunities

- Setup: T001, T002 in parallel (T003 trivial).
- Foundational: the three test-writes T004/T006/T008 are [P] (different files); each impl follows its test.
- US1 tests T010/T011/T012 (+T016) are [P] (different files).
- US2 guarantee tests T018–T023 are [P] (sibling test methods authored independently; they share one impl task T024).
- US3 can proceed concurrently with US1/US2 after Phase 2 (separate files: `compare.py`, `test_atlas_hosting_compare.py`).
- Polish T031–T034 are [P] (different files).

---

## Parallel Example: Foundational + US1

```bash
# Foundational test-writes (parallel — different files):
Task: "T004 tests/test_stage20_exceptions.py"
Task: "T006 tests/test_atlas_hosting_content_hash.py"
Task: "T008 tests/test_atlas_hosting_r2_client.py"

# US1 test-writes (parallel — different files):
Task: "T010 site/src/tests/unit/loader_r2_passthrough.test.ts"
Task: "T011 tests/test_atlas_hosting_uploader.py::test_happy_path"
Task: "T012 tests/test_atlas_hosting_manifest.py"
```

---

## Implementation Strategy

### MVP First (US1)

1. Phase 1 Setup → 2. Phase 2 Foundational → 3. Phase 3 US1 →
4. **STOP & VALIDATE**: run T017 (local upload + build) against
`aadata.cirrusscience.org` and confirm all three surfaces render from R2.

### Incremental delivery

- US1 → demo (site loads from R2). 
- US2 → demo (re-upload zero-byte + change-one safe). 
- US3 → produce the Dropbox-vs-R2 report. 
- Each commits as its own verified slice; push when the change is complete
  (Dropbox stays the production default — cutover deferred per spec).

---

## Notes

- [P] = different files, no incomplete-task dependency. US2's guarantee tests
  share impl task T024 (same `uploader.py`), so author them in parallel but land
  T024 once.
- Secrets stay in `.env`; never commit data/caches/exports/manifests/reports —
  they live under the gitignored `data/` root.
- No silenced failures or bypassed gates; `head_object` 404 is caught by
  inspecting the error code, never a bare `except`.
- The atlas-package *build* is unchanged — this feature only publishes its
  output and validates the result.
