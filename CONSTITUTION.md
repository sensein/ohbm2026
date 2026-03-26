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
