# Contract: `ohbm2026.enrich` package public-import surface (post-US1)

The Stage 2 / 2.1 surface lives in `ohbm2026.enrich`. Every consumer imports from the explicit submodule that owns the symbol; `__init__.py` carries no package-level re-export shell.

## Stable public imports

```python
# Cache paths + JSON I/O
from ohbm2026.enrich.cache_paths import (
    default_image_analysis_cache_path,
    default_claim_analysis_cache_path,
    load_image_analysis_cache,
    load_claim_analysis_cache,
    refresh_analysis_cache_stats,
    load_json,
    write_json,
)

# HTML ↔ Markdown text helpers
from ohbm2026.enrich.text import (
    html_to_markdown,
    HTMLToMarkdownParser,
)

# Manuscript / section / claim markdown rendering
from ohbm2026.enrich.markdown_render import (
    build_sections_markdown,
    build_claim_manuscript_markdown,
    render_abstract_markdown,
    filter_content_questions_markdown,
    is_content_question,
    question_to_section,
    normalize_question_name,
    parse_list_value,
)

# Legacy OpenAI / multimodal compatibility helpers
from ohbm2026.enrich.openai_compat import (
    openai_chat_multimodal,
    openai_chat_multimodal_batch,
    resolve_openai_api_key,
    parse_jsonish_content,
    image_to_data_url,
)

# Stage 2.1 production runners (unchanged by this stage)
from ohbm2026.enrich.figures import run_figure_analysis
from ohbm2026.enrich.claims import run_claim_extraction
from ohbm2026.enrich.references import run_reference_resolution
from ohbm2026.enrich.storage import EnrichedCorpusWriter, iter_enriched, read_one_by_id, corpus_metadata
from ohbm2026.enrich.stage import EnrichmentStage, run_stage   # actual symbol names per stage.py

# Cross-stage exception
from ohbm2026.exceptions import EnrichmentError
```

## Banned imports (post-stage)

Any of these MUST cause `ModuleNotFoundError` after the cleanup:

```python
from ohbm2026 import enrichment                  # module gone
from ohbm2026.enrichment import …                # module gone
from ohbm2026.enrich import enrich_main          # symbol gone
from ohbm2026.enrich import analyze_figures      # symbol gone
from ohbm2026.enrich import build_cllm_environment   # symbol gone
```

A grep-based assertion runs as part of US1 verification:

```bash
grep -rE "from ohbm2026 import enrichment|from ohbm2026\.enrichment" src/ tests/ scripts/ && exit 1 || true
```

## Re-export policy

`enrich/__init__.py` contains only the package docstring (≤ 5 lines) and at most one warmup import to break a circular cycle if one is discovered during implementation. No `from .module import *`. No `__all__` listing every public symbol.

## EnrichmentError

The exception class lives at exactly one location: `ohbm2026.exceptions.EnrichmentError`. The pre-stage redundant declaration at `enrichment.py:72` is removed. All 28 callers that currently use either path settle on the canonical one.
