# Project Constitution

## Experiments Are Immutable

- Published experiment outputs are append-only.
- A new experiment run must write to a fresh directory and must not overwrite an existing run directory.
- If a method, parameter set, input corpus, or scoring rule changes, create a new run directory even when the parent experiment stays the same.
- Reruns should live under a per-run directory such as `runs/<timestamp-or-run-id>/`.
- Overwriting an existing experiment directory is only allowed for disposable local scratch work that is explicitly labeled as scratch and not treated as a recorded result.

## Reproducibility

- Every experiment directory should include a `README.md` describing the goal, inputs, outputs, and repeat command.
- Every experiment run should include the exact summary artifacts needed to compare it with prior runs.
- Diagnostics files should use generic names like `diagnostics.json` unless the method is specifically diffusion-only.

## Canonical Source And Derived Data

- `data/abstracts.json` is the canonical normalized raw corpus and should remain traceable back to the Oxford Abstracts export.
- Cleanup, title normalization, and other downstream corrections must be recorded in separate audit artifacts instead of silently mutating the raw source record.
- Canonical downstream datasets should prefer append-or-rebuild workflows over in-place ad hoc editing.

## Resumable Long-Running Work

- Long-running API, LLM, or batch jobs should checkpoint incrementally so interrupted work can resume without recomputing completed records.
- New pipeline steps should prefer deterministic local outputs with explicit input and model metadata.
- If a command becomes the default or recommended path, its default inputs and outputs must be documented in the repo.

## Canonical Interfaces And Documentation

- `ohbmcli` is the canonical entrypoint for the main ingest, enrichment, embedding, clustering, and UI-export pipeline.
- Script-only workflows are acceptable for experiments and organizer tooling, but they should write auditable outputs and should be documented close to the workflow.
- When canonical artifact locations, default models, or recommended procedures change, update `README.md` and any affected experiment or plan docs in the same change.

## Organizer-Facing Deliverables Must Be Auditable

- Poster proposal outputs must preserve the JSON or other machine-readable source used to generate review CSVs, HTML, and figures.
- Review surfaces should make it easy to compare alternatives without hiding the underlying metrics or assumptions.
- Human-readable summaries should never be the only record of an organizer-facing decision.
