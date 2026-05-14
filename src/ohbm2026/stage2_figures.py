"""Stage 2.1 figures-component production runner.

Per-abstract figure batching: one OpenAI Responses API call carries
all of an abstract's figures + the manuscript markdown as
domain context. Each figure is compressed locally to JPEG q85 at
1024 px (in-memory only) and probed for local quality before the
model call. Result includes a `model_quality_estimate` enum and
the four-field `local_quality_estimate` dict.

Drives FR-005, FR-006, FR-007, FR-008.
"""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import io
import json
from pathlib import Path
from typing import Any, Callable, Iterable, Literal

from pydantic import BaseModel, Field

from ohbm2026 import flex_tier
from ohbm2026 import image_quality
from ohbm2026.exceptions import EnrichmentError

__all__ = [
    "FigureInterpretationItem",
    "FigureInterpretationResponse",
    "FigureRunSummary",
    "MODEL_QUALITY_ENUM",
    "DEFAULT_MAX_DIM",
    "DEFAULT_JPEG_QUALITY",
    "run_figure_component",
    "compress_image",
]


MODEL_QUALITY_ENUM = (
    "high",
    "medium",
    "low_resolution",
    "low_contrast",
    "diagram_only",
    "uninterpretable",
)


DEFAULT_MAX_DIM: int = 1024
DEFAULT_JPEG_QUALITY: int = 85


class FigureInterpretationItem(BaseModel):
    """One figure's interpretation, as returned by the model.

    Strict Pydantic schema enforced server-side via the Responses
    API's `text_format=` parameter; off-enum `model_quality_estimate`
    values raise a Pydantic validation error which the runner
    re-raises as `EnrichmentError` (Principle VII / CA-007).
    """

    figure_index: int = Field(..., ge=1, description="1-based; matches request order.")
    interpretation: str = Field(..., min_length=1)
    keywords: list[str] = Field(default_factory=list)
    ocr_text: str | None = None
    model_quality_estimate: Literal[
        "high", "medium", "low_resolution",
        "low_contrast", "diagram_only", "uninterpretable",
    ]


class FigureInterpretationResponse(BaseModel):
    """Top-level structured-output shape: one entry per figure in
    the request, same order."""

    figures: list[FigureInterpretationItem]


@dataclasses.dataclass
class FigureRunSummary:
    """Cost-and-tier telemetry rolled up across all figures of one
    abstract. The orchestrator accumulates these into the
    per-component provenance counters."""

    figure_count: int
    flex_timed_out: bool
    tier_used: Literal["flex", "standard"]
    attempts: int
    latency_ms: float
    prompt_tokens_cached: int = 0
    prompt_tokens_uncached: int = 0
    completion_tokens: int = 0


def compress_image(
    image_bytes: bytes,
    *,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[bytes, dict]:
    """In-memory JPEG compression + local quality probe.

    Reads `image_bytes` (the canonical PNG bytes from disk; the
    file itself is NEVER written back). Returns `(jpeg_bytes,
    local_quality_estimate_dict)`.

    The caller transmits `jpeg_bytes` to the model and stores the
    dict on the figure-interpretation record.

    Raises `EnrichmentError` for inputs Pillow refuses to decode
    (corrupt PNG, exceeded decompression-bomb safety limit, etc.)
    — the per-figure threshold logic counts these as failures
    instead of crashing the whole run.
    """
    from PIL import Image
    # Pillow's default `MAX_IMAGE_PIXELS = 178956970` flags any
    # image above ~179M pixels as a potential decompression bomb.
    # OHBM poster scans regularly exceed this (e.g., a 16384x16384
    # PNG = 268M pixels). Raise the cap to a generous bound (1B
    # pixels) — still bounded enough to refuse genuinely malicious
    # gigapixel inputs.
    Image.MAX_IMAGE_PIXELS = 1_000_000_000

    original_bytes = len(image_bytes)
    try:
        src_cm = Image.open(io.BytesIO(image_bytes))
    except (Image.UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise EnrichmentError(
            f"figures: Pillow refused to decode image ({type(exc).__name__}: {exc})"
        ) from exc
    with src_cm as src:
        # Force RGB so JPEG encode never fails on palette / RGBA.
        img = src.convert("RGB")
        native_max = image_quality.native_max_dim(img)
        # Probe BEFORE resize so the brightness/blur estimates
        # reflect the original input, not the compressed copy.
        laplacian = image_quality.laplacian_variance(img)
        brightness = image_quality.mean_brightness(img)

        # Resize so max(width, height) <= max_dim.
        w, h = img.size
        long_side = max(w, h)
        if long_side > max_dim:
            scale = max_dim / float(long_side)
            new_size = (int(round(w * scale)), int(round(h * scale)))
            img = img.resize(new_size, Image.LANCZOS)

        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        jpeg_bytes = buf.getvalue()

    estimate = {
        "laplacian_variance": laplacian,
        "mean_brightness": brightness,
        "native_max_dim": native_max,
        "compression_ratio": image_quality.compression_ratio(original_bytes, len(jpeg_bytes)),
    }
    return jpeg_bytes, estimate


def _build_input_payload(
    abstract: dict,
    *,
    manuscript_markdown: str,
    figures: list[tuple[str, bytes, dict]],
) -> list[dict]:
    """Assemble the Responses API `input` list.

    Format: a single user message containing instructions, the
    manuscript context, and the N figures attached in order.
    The model is told that all N images are from the SAME
    abstract and to interpret each in that context.
    """
    content_blocks: list[dict] = [
        {
            "type": "input_text",
            "text": (
                "You will analyze a set of figures from one scientific "
                "abstract. Interpret each figure in the context of the "
                "abstract's manuscript text below. Return a JSON object "
                "with key 'figures', a list of one entry per figure in "
                "the SAME ORDER they appear below. Each entry MUST "
                "contain: figure_index (1-based), interpretation "
                "(prose), keywords (array of short strings), ocr_text "
                "(or null), model_quality_estimate (one of: high, "
                "medium, low_resolution, low_contrast, diagram_only, "
                "uninterpretable).\n\n"
                f"=== MANUSCRIPT CONTEXT ===\n{manuscript_markdown}\n\n"
                f"=== FIGURES (n={len(figures)}) ==="
            ),
        }
    ]
    for index, (figure_url, jpeg_bytes, _local_estimate) in enumerate(figures, start=1):
        data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg_bytes).decode("ascii")
        content_blocks.append({
            "type": "input_text",
            "text": f"Figure {index} (source URL: {figure_url}):",
        })
        content_blocks.append({
            "type": "input_image",
            "image_url": data_url,
            "detail": "high",
        })

    return [{"role": "user", "content": content_blocks}]


def _build_manuscript_markdown(abstract: dict) -> str:
    """Concatenate title + intro + methods + results + conclusion.

    Mirrors the existing claim-manuscript builder in `enrichment.py`
    but with a tighter section list — for the figures component the
    references and acknowledgements add no figure-interpretation
    value.
    """
    parts: list[str] = []
    title = (abstract.get("title") or "").strip()
    if title:
        parts.append(f"# {title}")
    wanted = {"introduction", "methods", "results", "conclusion"}
    for response in abstract.get("responses", []) or []:
        name = (response.get("question_name") or "").strip().lower()
        if name in wanted:
            value = (response.get("value") or "").strip()
            if value:
                parts.append(f"## {response['question_name']}\n\n{value}")
    return "\n\n".join(parts)


def _hash_for_cache(jpeg_bytes: bytes, model_id: str) -> str:
    h = hashlib.sha256()
    h.update(jpeg_bytes)
    h.update(b"||")
    h.update(model_id.encode("utf-8"))
    return h.hexdigest()


def _read_image_bytes(local_path: str | None, *, cwd: Path) -> bytes | None:
    """Read canonical PNG bytes. Returns None if the asset is
    missing (caller treats as per-figure failure)."""
    if not local_path:
        return None
    p = cwd / local_path if not Path(local_path).is_absolute() else Path(local_path)
    if not p.exists():
        return None
    return p.read_bytes()


def run_figure_component(
    abstract: dict,
    *,
    model_id: str,
    flex_enabled: bool,
    client: Any,
    cwd: Path,
    timeout_seconds: float = flex_tier.DEFAULT_FIGURES_TIMEOUT_SECONDS,
    max_dim: int = DEFAULT_MAX_DIM,
    jpeg_quality: int = DEFAULT_JPEG_QUALITY,
) -> tuple[list[dict], FigureRunSummary]:
    """Run the figures component for one abstract.

    Returns `(figure_interpretation_list, FigureRunSummary)`.

    Raises `EnrichmentError` on any failure (missing canonical
    asset on disk, model schema drift, retry-budget exhaustion).
    The caller (orchestrator) catches and counts these against the
    figure-failure threshold.
    """
    figure_urls = abstract.get("figure_urls") or []
    if not figure_urls:
        return [], FigureRunSummary(
            figure_count=0, flex_timed_out=False, tier_used="flex" if flex_enabled else "standard",
            attempts=0, latency_ms=0.0,
        )

    # Stage 1 corpus uses `source_url` as the figure-URL key in both
    # figure_urls and local_assets. Older test fixtures used `url` /
    # `figure_url`. Tolerate all three.
    local_assets_by_url = {
        (a.get("source_url") or a.get("figure_url") or ""): a.get("local_path")
        for a in (abstract.get("local_assets") or [])
    }
    primary_assets_root = cwd / "data" / "primary" / "assets"

    figures: list[tuple[str, bytes, dict]] = []
    cache_keys: list[str] = []
    local_estimates: list[dict] = []
    local_paths: list[str | None] = []
    question_names: list[str] = []

    for entry in figure_urls:
        url = entry.get("source_url") or entry.get("url") or entry.get("figure_url") or ""
        question_name = entry.get("question_name", "")
        stored_local_path = local_assets_by_url.get(url)
        # Try stored path first; if missing (Stage 1 FR-008 relocated
        # assets to data/primary/assets/), fall back to basename lookup.
        png_bytes = None
        resolved_local_path = stored_local_path
        if stored_local_path:
            stored = Path(stored_local_path)
            candidates = [stored if stored.is_absolute() else (cwd / stored)]
            candidates.append(primary_assets_root / stored.name)
            for cand in candidates:
                if cand.exists():
                    png_bytes = cand.read_bytes()
                    resolved_local_path = (
                        str(cand.relative_to(cwd)) if cand.is_relative_to(cwd) else str(cand)
                    )
                    break
        if png_bytes is None:
            raise EnrichmentError(
                f"figures: local asset missing for abstract {abstract.get('id')} "
                f"figure {url!r} (expected at {stored_local_path!r})"
            )
        local_path = resolved_local_path
        jpeg_bytes, local_estimate = compress_image(
            png_bytes, max_dim=max_dim, quality=jpeg_quality,
        )
        figures.append((url, jpeg_bytes, local_estimate))
        cache_keys.append(_hash_for_cache(jpeg_bytes, model_id))
        local_estimates.append(local_estimate)
        local_paths.append(local_path)
        question_names.append(question_name)

    manuscript_markdown = _build_manuscript_markdown(abstract)
    input_payload = _build_input_payload(
        abstract,
        manuscript_markdown=manuscript_markdown,
        figures=figures,
    )

    def call(*, service_tier: str, timeout: float) -> Any:
        return client.responses.parse(
            model=model_id,
            input=input_payload,
            text_format=FigureInterpretationResponse,
            service_tier=service_tier,
            timeout=timeout,
            prompt_cache_key=f"stage2.figures.{model_id}",
        )

    result = flex_tier.call_with_flex_fallback(
        call,
        flex_enabled=flex_enabled,
        timeout_seconds=timeout_seconds,
        component="figures",
    )

    parsed: FigureInterpretationResponse = result.response.output_parsed
    if parsed is None or len(parsed.figures) != len(figures):
        raise EnrichmentError(
            f"figures: response shape mismatch — expected {len(figures)} figures, "
            f"got {0 if parsed is None else len(parsed.figures)}"
        )

    usage = getattr(result.response, "usage", None)
    summary = FigureRunSummary(
        figure_count=len(figures),
        flex_timed_out=result.flex_timed_out,
        tier_used=result.tier_used,
        attempts=result.attempts,
        latency_ms=result.latency_ms,
        prompt_tokens_cached=_get_usage_field(usage, "cached_tokens"),
        prompt_tokens_uncached=_get_usage_field(usage, "input_tokens") - _get_usage_field(usage, "cached_tokens"),
        completion_tokens=_get_usage_field(usage, "output_tokens"),
    )
    # Defensive: usage can underflow if cached_tokens > input_tokens in edge cases.
    if summary.prompt_tokens_uncached < 0:
        summary.prompt_tokens_uncached = 0

    out: list[dict] = []
    for index, item in enumerate(parsed.figures):
        out.append({
            "figure_url": figures[index][0],
            "local_path": local_paths[index],
            "question_name": question_names[index],
            "interpretation": item.interpretation,
            "keywords": list(item.keywords),
            "ocr_text": item.ocr_text,
            "model_quality_estimate": item.model_quality_estimate,
            "local_quality_estimate": local_estimates[index],
            "model_id": model_id,
            "cache_key": cache_keys[index],
        })
    return out, summary


def _get_usage_field(usage: Any, name: str) -> int:
    """Tolerantly read a token-count field off the SDK's usage
    object. The Responses API exposes the same usage shape as
    Chat Completions; field names can differ across versions."""
    if usage is None:
        return 0
    # Direct attr access.
    value = getattr(usage, name, None)
    if isinstance(value, (int, float)):
        return int(value)
    # Some shapes nest cached_tokens under input_tokens_details.
    if name == "cached_tokens":
        details = getattr(usage, "input_tokens_details", None)
        if details is not None:
            value = getattr(details, "cached_tokens", None)
            if isinstance(value, (int, float)):
                return int(value)
    return 0
