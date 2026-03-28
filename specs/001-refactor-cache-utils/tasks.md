---

description: "Task list for refactor shared utils and cache governance"
---

# Tasks: Refactor Shared Utils And Cache Governance

**Input**: Design documents from `/specs/001-refactor-cache-utils/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Test and verification tasks are required for this feature because it
changes repository behavior, artifact paths, cache lookup, and regeneration
rules.

**Organization**: Tasks are grouped by user story to enable independent
implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `src/`, `tests/` at repository root
- This feature adds a shared artifact utility in `src/ohbm2026/artifacts.py`
- Local artifacts remain under ignored `data/`, `data/inputs/`, `data/cache/`,
  `data/outputs/`, and `export/`

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish the shared artifact-governance scaffolding and local path
rules before workflow-specific changes begin.

- [ ] T001 Update ignore rules for `data/inputs/`, `data/cache/`, and `data/outputs/` in `.gitignore`
- [ ] T002 Create the shared artifact governance module scaffold in `src/ohbm2026/artifacts.py`
- [ ] T003 [P] Create the shared artifact test module scaffold in `tests/test_artifacts.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the shared path, metadata, and dependency-basis primitives
that all workflow migrations will depend on.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Implement deterministic state-key and direct path builders in `src/ohbm2026/artifacts.py`
- [ ] T005 Implement artifact metadata, dependency-basis, and regeneration policy helpers in `src/ohbm2026/artifacts.py`
- [ ] T006 [P] Add unit coverage for path resolution, metadata normalization, and git-ignore expectations in `tests/test_artifacts.py`
- [ ] T007 Wire shared artifact constants/imports into `src/ohbm2026/cli.py`, `src/ohbm2026/enrichment.py`, `src/ohbm2026/openalex.py`, `src/ohbm2026/neuroscape.py`, and `src/ohbm2026/ui.py`
- [ ] T008 [P] Add representative ignore-path verification coverage for `data/inputs/`, `data/cache/`, and `data/outputs/` in `tests/test_artifacts.py`

**Checkpoint**: Shared artifact layer, metadata contract, and ignore-path rules
are ready for workflow-specific implementation.

---

## Phase 3: User Story 1 - Clean Up Repeated Maintenance Work (Priority: P1) 🎯 MVP

**Goal**: Replace repeated path and metadata behavior with a shared artifact
utility layer that maintainers can reuse across expensive workflows.

**Independent Test**: Update one in-scope expensive workflow and confirm that
shared path and metadata behavior is defined once in
`src/ohbm2026/artifacts.py`, with regression coverage proving the workflow no
longer depends on duplicated local helper logic.

### Tests for User Story 1 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [ ] T009 [P] [US1] Add shared-helper regression tests for cache path and metadata resolution in `tests/test_enrichment.py`
- [ ] T010 [P] [US1] Add shared-helper regression tests for checkpoint/cache path and metadata resolution in `tests/test_openalex.py`

### Implementation for User Story 1

- [ ] T011 [US1] Refactor `src/ohbm2026/enrichment.py` to use `src/ohbm2026/artifacts.py` for cache naming, metadata writes, and direct lookup
- [ ] T012 [US1] Refactor `src/ohbm2026/openalex.py` to use `src/ohbm2026/artifacts.py` for checkpoint naming, metadata writes, and direct lookup
- [ ] T013 [US1] Refactor shared JSON/path helper usage in `src/ohbm2026/neuroscape.py` and `src/ohbm2026/ui.py` toward `src/ohbm2026/artifacts.py`

**Checkpoint**: The shared artifact utility is the single source of truth for
path and metadata behavior in the first migrated workflows.

---

## Phase 4: User Story 2 - Distinguish Canonical Data From Regenerable Caches (Priority: P1)

**Goal**: Make fetched inputs, resumable caches, and output families visibly and
consistently separate under `data/inputs/`, `data/cache/`, and
`data/outputs/`.

**Independent Test**: Run representative ingest, cache-producing, and
output-producing flows and confirm that GraphQL-fetched inputs land under
`data/inputs/`, caches land under `data/cache/`, and outputs land under the
correct output family (`experiments`, `exported-sites`, or `proposals`).

### Tests for User Story 2 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [ ] T014 [P] [US2] Add input snapshot and asset refresh coverage for `data/inputs/` in `tests/test_assets.py`
- [ ] T015 [P] [US2] Add output-family path coverage for exported sites and experiments in `tests/test_neuroscape.py` and `tests/test_ui.py`
- [ ] T016 [P] [US2] Add proposal output-family path coverage in `tests/test_poster_layout.py` and `tests/test_poster_sequencing.py`

### Implementation for User Story 2

- [ ] T017 [US2] Update `src/ohbm2026/assets.py` to store GraphQL-fetched source snapshots under `data/inputs/` while preserving canonical normalized outputs
- [ ] T018 [US2] Update default cache paths in `src/ohbm2026/enrichment.py` and `src/ohbm2026/openalex.py` to resolve under `data/cache/`
- [ ] T019 [US2] Update exported-site and experiment output paths in `src/ohbm2026/neuroscape.py` and `src/ohbm2026/ui.py` to resolve under `data/outputs/exported-sites/` and `data/outputs/experiments/`
- [ ] T020 [US2] Update proposal output writers in `src/ohbm2026/poster_layout.py` and `src/ohbm2026/poster_sequencing.py` to resolve under `data/outputs/proposals/`

**Checkpoint**: Operators can distinguish fetched inputs, caches, and each
output family by location alone, with tests confirming the contract.

---

## Phase 5: User Story 3 - Recover From Stale Or Interrupted Expensive Work (Priority: P2)

**Goal**: Give operators explicit invalidation and regeneration routes based on
dependency-basis metadata rather than ad hoc file deletion.

**Independent Test**: Simulate stale inputs, changed defaults, and interrupted
runs for representative workflows and confirm the code chooses documented
resume, selective rebuild, or full rebuild behavior without deleting unaffected
inputs or outputs.

### Tests for User Story 3 (REQUIRED FOR BEHAVIOR CHANGES) ⚠️

- [ ] T021 [P] [US3] Add invalidation and state-key regeneration tests in `tests/test_artifacts.py`
- [ ] T022 [P] [US3] Add resume and regeneration regression tests in `tests/test_enrichment.py` and `tests/test_openalex.py`
- [ ] T023 [P] [US3] Add output regeneration regression tests in `tests/test_ui.py` and `tests/test_neuroscape.py`

### Implementation for User Story 3

- [ ] T024 [US3] Implement dependency-basis invalidation and resume policy helpers in `src/ohbm2026/artifacts.py`
- [ ] T025 [US3] Wire regeneration metadata and stale-detection behavior through `src/ohbm2026/enrichment.py` and `src/ohbm2026/openalex.py`
- [ ] T026 [US3] Wire regeneration metadata and stale-detection behavior through `src/ohbm2026/neuroscape.py`, `src/ohbm2026/ui.py`, `src/ohbm2026/poster_layout.py`, and `src/ohbm2026/poster_sequencing.py`

**Checkpoint**: Stale or interrupted expensive workflows can be resumed or
rebuilt predictably from explicit metadata and regeneration rules.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Sync operator docs, review secret safety, and validate the planned
workflow end to end.

- [ ] T027 [P] Update operator docs for `data/inputs/`, `data/cache/`, and `data/outputs/` in `README.md`, `docs/README.md`, and `docs/reproducibility-vision.md`
- [ ] T028 [P] Update workflow guidance for output families and git-ignore expectations in `experiments/README.md` and `AGENTS.md`
- [ ] T029 Review secret exposure and metadata redaction behavior in `src/ohbm2026/artifacts.py`, `src/ohbm2026/enrichment.py`, `src/ohbm2026/openalex.py`, `src/ohbm2026/neuroscape.py`, and `src/ohbm2026/ui.py`
- [ ] T030 Run the verification flow documented in `specs/001-refactor-cache-utils/quickstart.md`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational completion
- **User Story 2 (Phase 4)**: Depends on Foundational completion and is safest after User Story 1 because it reuses the shared artifact layer heavily
- **User Story 3 (Phase 5)**: Depends on User Stories 1 and 2 so regeneration rules are applied to the final input/cache/output structure
- **Polish (Phase 6)**: Depends on all desired user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational - establishes the shared utility layer and is the recommended MVP slice
- **User Story 2 (P1)**: Can start after Foundational, but should follow User Story 1 to minimize overlapping edits in shared workflow modules
- **User Story 3 (P2)**: Depends on User Stories 1 and 2 because invalidation and regeneration behavior needs the final path and metadata model

### Within Each User Story

- Tests MUST be written and shown failing before implementation
- Shared path/metadata primitives must exist before workflow migrations
- Input/cache/output path migration must land before regeneration rules
- Story-specific code and tests should be completed before moving to the next story

### Parallel Opportunities

- T003, T006, and T008 can run in parallel once Phase 1 scaffolding exists
- T009 and T010 can run in parallel for User Story 1
- T014, T015, and T016 can run in parallel for User Story 2 because they target different test files
- T021, T022, and T023 can run in parallel for User Story 3
- T027 and T028 can run in parallel during polish

---

## Parallel Example: User Story 2

```bash
# Launch the path-contract tests for User Story 2 together:
Task: "Add input snapshot and asset refresh coverage for data/inputs in tests/test_assets.py"
Task: "Add output-family path coverage for exported sites and experiments in tests/test_neuroscape.py and tests/test_ui.py"
Task: "Add proposal output-family path coverage in tests/test_poster_layout.py and tests/test_poster_sequencing.py"

# Then implement output families in parallel where file ownership does not overlap:
Task: "Update src/ohbm2026/assets.py to store GraphQL-fetched source snapshots under data/inputs while preserving canonical normalized outputs"
Task: "Update proposal output writers in src/ohbm2026/poster_layout.py and src/ohbm2026/poster_sequencing.py to resolve under data/outputs/proposals/"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: Run `tests/test_artifacts.py`, `tests/test_enrichment.py`, and `tests/test_openalex.py`
5. Review the shared utility API before broadening the migration surface

### Incremental Delivery

1. Build the shared artifact layer and its tests
2. Migrate the first cache-heavy workflows (User Story 1)
3. Move fetched inputs, caches, and output families to their new locations (User Story 2)
4. Add explicit invalidation/regeneration behavior (User Story 3)
5. Finish with docs, secret review, and quickstart validation

### Parallel Team Strategy

With multiple developers:

1. One developer owns `src/ohbm2026/artifacts.py` and `tests/test_artifacts.py`
2. One developer owns cache-heavy workflow migrations in `src/ohbm2026/enrichment.py` and `src/ohbm2026/openalex.py`
3. One developer owns output-family migrations in `src/ohbm2026/neuroscape.py`, `src/ohbm2026/ui.py`, `src/ohbm2026/poster_layout.py`, and `src/ohbm2026/poster_sequencing.py`
4. Converge for regeneration rules and final docs sync after the path contract is stable

---

## Notes

- Total tasks: 30
- User Story task counts:
  - US1: 5 tasks
  - US2: 7 tasks
  - US3: 6 tasks
- Setup/foundational/polish tasks: 12 tasks
- Suggested MVP scope: Phase 1 + Phase 2 + User Story 1
- All tasks follow the required checklist format with checkbox, task ID, story label where required, and exact file paths
