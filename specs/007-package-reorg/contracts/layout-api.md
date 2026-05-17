# Contract: `ohbm2026.layout` package (post-US2) — parked

This package is **parked**. Code is preserved verbatim from the pre-Stage-5 surface; no scheduled enhancements. The contract is the same as it was before the move — the only change is the qualified-name prefix.

## Stable public imports

```python
from ohbm2026.layout.poster_layout import (
    # whatever symbols poster_layout.py exposed pre-stage
)
from ohbm2026.layout.poster_sequencing import (
    # whatever symbols poster_sequencing.py exposed pre-stage
)
from ohbm2026.layout.nocd_experiments import (
    # whatever symbols nocd_experiments.py exposed pre-stage
)
```

The three modules' public surfaces are **not enumerated here** because nothing about them changes in this stage; the contract is "whatever they exported before, now under the `ohbm2026.layout.` prefix."

## Banned imports (post-stage)

```python
from ohbm2026 import poster_layout                # module relocated
from ohbm2026.poster_layout import …              # module relocated
from ohbm2026 import poster_sequencing            # module relocated
from ohbm2026.poster_sequencing import …          # module relocated
from ohbm2026 import nocd_experiments             # module relocated
from ohbm2026.nocd_experiments import …           # module relocated
```

Grep-based assertion (part of US2 verification):

```bash
grep -rE "from ohbm2026 import (poster_layout|poster_sequencing|nocd_experiments)|from ohbm2026\.(poster_layout|poster_sequencing|nocd_experiments)" src/ tests/ scripts/ && exit 1 || true
```

## Re-export policy

`layout/__init__.py` is a single docstring naming the package as parked. No re-exports. No `__all__`. No runtime warning.

## Script-relocation contract

Each of the 15 scripts under `scripts/layout/` retains its CLI surface (argparse, flags) verbatim. The only changes are:

1. `REPO_ROOT = Path(__file__).resolve().parents[1]` → `parents[2]` (one extra directory).
2. Any `from ohbm2026.poster_layout import …` becomes `from ohbm2026.layout.poster_layout import …`.

A smoke check is part of US2 verification:

```bash
PYTHONPATH=src .venv/bin/python scripts/layout/optimize_poster_layout.py --help >/dev/null
PYTHONPATH=src .venv/bin/python scripts/layout/benchmark_poster_sequencing.py --help >/dev/null
PYTHONPATH=src .venv/bin/python scripts/layout/run_nocd_classic_predict_experiment.py --help >/dev/null
```

All three exit 0.

## Parking note (docs surface)

CLAUDE.md, README.md, and `docs/reproducibility-vision.md` each gain one sentence explicitly naming `ohbm2026.layout` as parked. SC-007 verifies via a single `grep -l "layout.*parked\|parked.*layout"`.
