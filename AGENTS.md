# ohbm2026 Development Guidelines

Auto-generated from all feature plans. Last updated: 2026-03-28

## Active Technologies

- Python 3.11+ + Python standard library (`argparse`, `pathlib`, `json`,
  `hashlib`, `datetime`), existing `ohbm2026` pipeline modules, and NumPy-backed
  downstream consumers already present in the repo
- Local JSON/filesystem artifacts under ignored `data/inputs/`,
  `data/cache/`, `data/outputs/`, `archive/`, `export/`, `tmp/`, and experiment
  directories

## Project Structure

```text
src/
tests/
docs/
specs/
```

## Commands

- `UV_CACHE_DIR=.uv-cache uv venv --python 3.11 .venv`
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`

## Code Style

Python 3.11+: Follow standard conventions

## Recent Changes

- `001-refactor-cache-utils`: planning for shared artifact governance across
  `data/inputs/`, `data/cache/`, and `data/outputs/`

## Delivery Guardrails

- Keep credentials in environment variables or `.env`, never in committed files
  or pasted logs.
- Update the nearest plan/spec docs when canonical defaults or workflow
  expectations change.
- Commit verified work with a descriptive message and push it unless the
  requester explicitly asks to keep it local.

<!-- MANUAL ADDITIONS START -->
<!-- MANUAL ADDITIONS END -->
