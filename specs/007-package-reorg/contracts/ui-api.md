# Contract: `ohbm2026.ui` package public-import surface (post-US3)

The static-UI export surface lives in `ohbm2026.ui`. Every consumer imports from the explicit submodule that owns the symbol; `__init__.py` carries no package-level re-export shell.

## Stable public imports

```python
# CLI front-ends
from ohbm2026.ui.cli import export_ui_main, build_ui_main

# Payload builders
from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4
from ohbm2026.ui.payload_legacy import build_ui_payload   # legacy embedding-bundle-driven

# Lower-level helpers (rarely imported from outside the package, but exported)
from ohbm2026.ui.text import (
    markdown_to_plain_text,
    markdown_to_html,
    render_additional_content_markdown,
    question_lookup,
    primary_topic_from_questions,
    secondary_topic_from_questions,
    topic_subcategories_from_questions,
)
from ohbm2026.ui.figures import (
    simplify_image_analysis,
    figure_note_sort_key,
    order_figure_notes,
    build_figure_text_blob,
    load_image_analysis_lookup,
)
from ohbm2026.ui.references import (
    load_reference_lookup,
    load_neighbors,
    load_distant,
)
from ohbm2026.ui.manifest import (
    default_site_output_dir,
    default_export_output_dir,
    ClusterLayerSpec,
)

# Exception
from ohbm2026.exceptions import UIBuildError   # moved out of ui.py
```

## Banned imports (post-stage)

```python
from ohbm2026 import ui                          # ui.py is gone
from ohbm2026.ui import …                        # MUST resolve via explicit submodule, not the package
import ohbm2026.ui                               # works (the package exists) but exposes only the docstring
```

The key contract: there must be **no top-level symbol on `ohbm2026.ui`** after this stage. Tests asserting `from ohbm2026.ui import build_ui_payload_from_stage4` MUST be rewired to `from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4`. The grep-based assertion below catches any consumer still relying on the legacy package-level re-export:

```bash
grep -rE "from ohbm2026\.ui import [A-Z_]" src/ tests/ scripts/   # all matches MUST resolve to submodules
```

(The non-submodule import like `from ohbm2026.ui import build_ui_payload_from_stage4` would surface as a `from ohbm2026.ui import build_ui_payload_from_stage4` line — these MUST be replaced with `from ohbm2026.ui.payload_stage4 import build_ui_payload_from_stage4` etc.)

## Re-export policy

`ui/__init__.py` is a docstring only (≤ 5 lines). No `__all__`, no `from .submodule import …`. The same rule the Stage 4 reorganization established for `analyze/__init__.py` (per spec 006 clarification Q2 + T108b).

## Dependency direction (avoids circular imports per research.md R5)

- **Leaves**: `ui/text.py`, `ui/figures.py`, `ui/references.py`, `ui/manifest.py` — no intra-package imports.
- **Mid**: `ui/payload_legacy.py`, `ui/payload_stage4.py` — import from leaves only.
- **Trunk**: `ui/cli.py` — imports `ui/payload_legacy`, `ui/payload_stage4`, `ui/manifest`.

Any new submodule introduced during implementation MUST honor this order or be added as a new leaf.

## CLI dispatch contract

`src/ohbm2026/cli.py` dispatches the `export-ui` and `build-ui` subcommands by importing from `ohbm2026.ui.cli`:

```python
from ohbm2026.ui.cli import export_ui_main, build_ui_main
```

After Stage 5, `ohbmcli export-ui --help` and `ohbmcli build-ui --help` both succeed (FR-006).

## Shape-equivalence contract

A full `ohbmcli build-ui --analysis-rollup data/outputs/analysis/annotations__f0c51e80dc0e.sqlite …` invocation MUST produce a bundle whose top-level file list matches the pre-stage build:

```
abstracts.detail.json
abstracts.search.json
clusters.json
facets.json
manifest.json
projection.umap.json
relations.json
```

`manifest.json["source"] == "stage4"` and `manifest.json["abstract_count"] == 3244` for the live corpus. Per-file SHAs are NOT required to match (timestamps + the new file-write order may shift them); only file-list + manifest-key equivalence is enforced.
