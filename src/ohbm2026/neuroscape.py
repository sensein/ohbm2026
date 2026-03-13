from __future__ import annotations

import argparse
import copy
import json
import os
import re
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ohbm2026.graphql_api import chunked, load_dotenv
from ohbm2026.titles import cleaned_abstract_title

DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"
DEFAULT_MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_HF_MODEL = DEFAULT_MINILM_MODEL
DEFAULT_EMBEDDING_FIELDS = ("title", "introduction", "methods", "results", "conclusion")
DEFAULT_STAGE2_OUTPUT_DIMENSION = 64
DEFAULT_STAGE2_HIDDEN_DIMENSIONS = (192, 96, 64)
PUBLISHED_STAGE2_HIDDEN_DIMENSIONS = (512, 256, 128)
PUBLISHED_STAGE2_OUTPUT_DIMENSION = 64
DEFAULT_UMAP_NEIGHBORS = 15
DEFAULT_UMAP_MIN_DIST = 0.1
DEFAULT_TSNE_PERPLEXITY = 30.0
DEFAULT_TSNE_LEARNING_RATE = "auto"
DEFAULT_TSNE_EARLY_EXAGGERATION = 12.0
HUGGINGFACE_TOKEN_ENV_VARS = ("HF_TOKEN", "HUGGINGFACE_HUB_TOKEN")
ALLOWED_EMBEDDING_FIELDS = {
    "title",
    "claims",
    "introduction",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "references",
    "acknowledgement",
}
SECTION_HEADINGS = {
    "claims": "Claims",
    "introduction": "Introduction",
    "methods": "Methods",
    "results": "Results",
    "discussion": "Discussion",
    "conclusion": "Conclusion",
    "references": "References",
    "acknowledgement": "Acknowledgement",
}
SECTION_MARKDOWN_KEYS = {
    "claims": "claims_markdown",
    "introduction": "introduction_markdown",
    "methods": "methods_markdown",
    "results": "results_markdown",
    "discussion": "discussion_markdown",
    "conclusion": "conclusion_markdown",
    "references": "references_markdown",
    "acknowledgement": "acknowledgement_markdown",
}


class NeuroScapeError(RuntimeError):
    """Raised when embedding or relationship generation fails."""


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def parse_string_list_value(raw_value: str | None) -> list[str]:
    if not raw_value:
        return []
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        text = raw_value.strip()
        return [text] if text else []
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    if isinstance(parsed, str):
        text = parsed.strip()
        return [text] if text else []
    return []


def unique_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def configure_huggingface_auth(env_path: Path) -> str | None:
    env_values = load_dotenv(env_path)
    token = None
    for env_var in HUGGINGFACE_TOKEN_ENV_VARS:
        token = os.environ.get(env_var) or env_values.get(env_var)
        if token:
            break
    if not token:
        return None
    os.environ.setdefault("HF_TOKEN", token)
    os.environ.setdefault("HUGGINGFACE_HUB_TOKEN", token)
    return token


def load_title_lookup(path: Path) -> dict[int, str]:
    database = json.loads(path.read_text(encoding="utf-8"))
    return {
        abstract["id"]: cleaned_abstract_title(abstract.get("title", ""))
        for abstract in database.get("abstracts", [])
        if isinstance(abstract.get("id"), int)
    }


def extract_raw_keywords(abstract: dict[str, Any]) -> list[str]:
    for response in abstract.get("responses", []):
        if str(response.get("question_name") or "").strip().lower() == "keywords":
            return parse_string_list_value(response.get("value"))
    return []


def extract_primary_topic(abstract: dict[str, Any]) -> str:
    for response in abstract.get("responses", []):
        if str(response.get("question_name") or "").strip().lower() == "primary parent category & sub-category":
            values = parse_string_list_value(response.get("value"))
            if values:
                return values[0]
    return "Unknown"


def load_annotation_lookup(
    raw_path: Path,
    enriched_path: Path | None = None,
) -> dict[int, dict[str, Any]]:
    raw_database = json.loads(raw_path.read_text(encoding="utf-8"))
    enriched_lookup: dict[int, dict[str, Any]] = {}
    if enriched_path and enriched_path.exists():
        enriched_database = json.loads(enriched_path.read_text(encoding="utf-8"))
        enriched_lookup = {
            abstract["id"]: abstract
            for abstract in enriched_database.get("abstracts", [])
            if isinstance(abstract.get("id"), int)
        }

    annotations: dict[int, dict[str, Any]] = {}
    for abstract in raw_database.get("abstracts", []):
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        enriched = enriched_lookup.get(abstract_id, {})
        keywords = unique_strings(
            extract_raw_keywords(abstract)
            + [str(keyword).strip() for keyword in enriched.get("figure_keywords", []) if str(keyword).strip()]
        )
        annotations[abstract_id] = {
            "id": abstract_id,
            "title": cleaned_abstract_title(abstract.get("title") or ""),
            "accepted_for": abstract.get("accepted_for") or "Unknown",
            "primary_topic": extract_primary_topic(abstract),
            "keywords": keywords,
        }
    return annotations


def build_visualization_records(
    ids: list[int],
    annotation_lookup: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for abstract_id in ids:
        annotation = annotation_lookup.get(int(abstract_id), {})
        records.append(
            {
                "id": int(abstract_id),
                "title": annotation.get("title") or "",
                "accepted_for": annotation.get("accepted_for") or "Unknown",
                "primary_topic": annotation.get("primary_topic") or "Unknown",
                "keywords": list(annotation.get("keywords") or []),
            }
        )
    return records


def normalize_embedding_fields(fields: list[str] | tuple[str, ...] | None) -> list[str]:
    raw_fields = list(fields or DEFAULT_EMBEDDING_FIELDS)
    normalized_fields: list[str] = []
    seen: set[str] = set()
    for field in raw_fields:
        normalized = field.strip().lower()
        if normalized not in ALLOWED_EMBEDDING_FIELDS:
            raise NeuroScapeError(f"Unsupported embedding field: {field}")
        if normalized not in seen:
            seen.add(normalized)
            normalized_fields.append(normalized)
    if not normalized_fields:
        raise NeuroScapeError("At least one embedding field is required")
    return normalized_fields


def build_embedding_text(
    abstract: dict[str, Any],
    fields: list[str] | tuple[str, ...] | None = None,
    title_lookup: dict[int, str] | None = None,
) -> str:
    selected_fields = normalize_embedding_fields(fields)
    parts: list[str] = []

    for field in selected_fields:
        if field == "title":
            title = cleaned_abstract_title(abstract.get("title") or "")
            if not title and title_lookup and isinstance(abstract.get("id"), int):
                title = cleaned_abstract_title(title_lookup.get(abstract["id"]) or "")
            if title:
                parts.append(title)
            continue
        if field == "claims":
            claim_text = build_claim_embedding_text(abstract)
            if claim_text:
                parts.append(f"{SECTION_HEADINGS[field]}:\n{claim_text}")
            continue
        section_key = SECTION_MARKDOWN_KEYS[field]
        section_text = (abstract.get(section_key) or "").strip()
        if section_text:
            parts.append(f"{SECTION_HEADINGS[field]}:\n{section_text}")

    return "\n\n".join(parts).strip()


def build_embedding_texts(
    abstracts: list[dict[str, Any]],
    fields: list[str] | tuple[str, ...] | None = None,
    title_lookup: dict[int, str] | None = None,
) -> list[str]:
    selected_fields = normalize_embedding_fields(fields)
    return [build_embedding_text(abstract, selected_fields, title_lookup=title_lookup) for abstract in abstracts]


def build_claim_embedding_text(abstract: dict[str, Any]) -> str:
    claim_extraction = abstract.get("claim_extraction") or {}
    raw_claims = claim_extraction.get("claims") or []
    claim_lines: list[str] = []
    for claim_record in raw_claims:
        if not isinstance(claim_record, dict):
            continue
        claim_text = str(claim_record.get("claim") or "").strip()
        if not claim_text:
            continue
        claim_lines.append(f"- {claim_text}")
    return "\n".join(claim_lines)


def embedding_variant_name(fields: list[str] | tuple[str, ...] | None = None) -> str:
    selected_fields = normalize_embedding_fields(fields)
    if selected_fields == list(DEFAULT_EMBEDDING_FIELDS):
        return "stage1"
    return "-".join(selected_fields)


def model_name_slug(model_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", model_name.strip().lower()).strip("-")
    if not slug:
        raise NeuroScapeError("model_name must not be empty")
    return slug


def build_embedding_output_name(
    model_name: str,
    embedding_fields: list[str] | tuple[str, ...] | None = None,
    output_name: str | None = None,
    prefix: str = "hf",
) -> str:
    if output_name:
        return output_name
    return f"{prefix}_{model_name_slug(model_name)}_{embedding_variant_name(embedding_fields)}"


def voyage_embed(
    texts: list[str],
    api_key: str,
    model: str = DEFAULT_VOYAGE_MODEL,
    batch_size: int = 64,
) -> list[list[float]]:
    endpoint = "https://api.voyageai.com/v1/embeddings"
    vectors: list[list[float]] = []
    for text_batch in chunked(list(range(len(texts))), batch_size):
        batch_inputs = [texts[index] for index in text_batch]
        payload = json.dumps(
            {"input": batch_inputs, "model": model, "input_type": "document"}
        ).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=600) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NeuroScapeError(f"Voyage embeddings failed with HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise NeuroScapeError(f"Voyage embeddings failed: {exc.reason}") from exc
        vectors.extend(item["embedding"] for item in parsed.get("data", []))
    return vectors


def openai_embed(
    texts: list[str],
    api_key: str,
    model: str = "text-embedding-3-small",
    batch_size: int = 128,
    dimensions: int | None = None,
) -> list[list[float]]:
    endpoint = "https://api.openai.com/v1/embeddings"
    vectors: list[list[float]] = []
    for text_batch in chunked(list(range(len(texts))), batch_size):
        batch_inputs = [texts[index] for index in text_batch]
        payload_dict: dict[str, Any] = {
            "input": batch_inputs,
            "model": model,
            "encoding_format": "float",
        }
        if dimensions is not None:
            payload_dict["dimensions"] = dimensions
        payload = json.dumps(payload_dict).encode("utf-8")
        request = Request(
            endpoint,
            data=payload,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=600) as response:
                parsed = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise NeuroScapeError(f"OpenAI embeddings failed with HTTP {exc.code}: {body}") from exc
        except URLError as exc:
            raise NeuroScapeError(f"OpenAI embeddings failed: {exc.reason}") from exc
        vectors.extend(item["embedding"] for item in parsed.get("data", []))
    return vectors


def sentence_transformer_embed(
    texts: list[str],
    model_name: str = DEFAULT_HF_MODEL,
    local_files_only: bool = False,
) -> list[list[float]]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(model_name, local_files_only=local_files_only)
    embeddings = model.encode(
        texts,
        batch_size=64,
        show_progress_bar=True,
        convert_to_numpy=True,
        normalize_embeddings=False,
    )
    return embeddings.tolist()


def minilm_embed(
    texts: list[str],
    model_name: str = DEFAULT_MINILM_MODEL,
    local_files_only: bool = False,
) -> list[list[float]]:
    return sentence_transformer_embed(texts, model_name=model_name, local_files_only=local_files_only)


def write_embedding_bundle(
    output_dir: Path,
    embedding_name: str,
    model_name: str,
    abstracts: list[dict[str, Any]],
    vectors: list[list[float]],
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    import numpy as np

    output_dir.mkdir(parents=True, exist_ok=True)
    matrix = np.asarray(vectors, dtype=np.float32)
    ids = [abstract["id"] for abstract in abstracts]
    metadata = [
        {"id": abstract["id"], "title": abstract.get("title"), "accepted_for": abstract.get("accepted_for")}
        for abstract in abstracts
    ]
    np.save(output_dir / "vectors.npy", matrix)
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": embedding_name,
            "model_name": model_name,
            "embedding_fields": normalize_embedding_fields(embedding_fields),
            "count": len(metadata),
            "metadata": metadata,
            "ids": ids,
        },
    )
    return {"ids": ids, "matrix": matrix, "metadata": metadata}


def compute_neighbors(ids: list[int], matrix: Any, top_k: int = 10) -> dict[str, Any]:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = matrix / norms
    similarities = normalized @ normalized.T
    neighbors: dict[str, list[dict[str, float]]] = {}
    for index, abstract_id in enumerate(ids):
        row = similarities[index].copy()
        row[index] = -1.0
        neighbor_indices = np.argsort(row)[-top_k:][::-1]
        neighbors[str(abstract_id)] = [
            {"id": int(ids[neighbor_index]), "score": float(row[neighbor_index])}
            for neighbor_index in neighbor_indices
        ]
    return {"top_k": top_k, "neighbors": neighbors}


def write_neuroscape_manifest(output_path: Path) -> None:
    write_json(
        output_path,
        {
            "status": "stage1_ready_stage2_pending_validation",
            "base_embedding_model": DEFAULT_VOYAGE_MODEL,
            "local_stage1_model": DEFAULT_MINILM_MODEL,
            "zenodo_record": "https://zenodo.org/records/14865161",
            "repository": "https://github.com/ccnmaastricht/NeuroScape",
            "note": (
                "The published NeuroScape domain model depends on Voyage stage-one embeddings "
                "and still requires the Zenodo artifact download before stage-two projection can run. "
                "A local-retraining path using a local stage-one model should be treated as a separate "
                "track until validated against the NeuroScape training workflow."
            ),
        },
    )


def load_embedding_inputs(path: Path) -> list[dict[str, Any]]:
    database = json.loads(path.read_text(encoding="utf-8"))
    return database.get("abstracts", [])


def normalize_hidden_dimensions(values: list[int] | tuple[int, ...]) -> tuple[int, int, int]:
    dimensions = tuple(int(value) for value in values)
    if len(dimensions) != 3 or any(value <= 0 for value in dimensions):
        raise NeuroScapeError("Stage-2 hidden dimensions must contain exactly three positive integers")
    return dimensions


def choose_torch_device(requested: str | None = None) -> str:
    import torch

    if requested:
        return requested
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def load_stage1_bundle(bundle_dir: Path) -> dict[str, Any]:
    import numpy as np

    metadata_path = bundle_dir / "metadata.json"
    vectors_path = bundle_dir / "vectors.npy"
    if not metadata_path.exists() or not vectors_path.exists():
        raise NeuroScapeError(f"Stage-1 bundle is incomplete: {bundle_dir}")

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    matrix = np.load(vectors_path)
    ids = metadata.get("ids", [])
    rows = metadata.get("metadata", [])
    if len(ids) != len(rows) or len(ids) != int(matrix.shape[0]):
        raise NeuroScapeError("Stage-1 bundle metadata does not match vectors.npy")
    return {"ids": ids, "metadata": rows, "matrix": matrix, "source_metadata": metadata}


def load_embedding_bundle(bundle_dir: Path) -> dict[str, Any]:
    return load_stage1_bundle(bundle_dir)


def build_embedding_visualization_title(
    bundle: dict[str, Any],
    prefix: str,
) -> str:
    source_metadata = bundle.get("source_metadata", {})
    bundle_name = str(source_metadata.get("embedding_name") or "embedding")
    source_name = str(source_metadata.get("source_embedding_name") or bundle_name)
    fields = normalize_embedding_fields(source_metadata.get("embedding_fields"))
    field_text = ", ".join(fields) if fields else "unspecified"
    if source_name == bundle_name:
        name_text = bundle_name
    else:
        name_text = f"{bundle_name} (source: {source_name})"
    return f"{prefix}: {name_text} | fields: {field_text}"


def compute_umap_projection(
    matrix: Any,
    n_neighbors: int = DEFAULT_UMAP_NEIGHBORS,
    min_dist: float = DEFAULT_UMAP_MIN_DIST,
    metric: str = "cosine",
    random_state: int = 42,
) -> Any:
    import numpy as np
    import umap

    matrix = np.asarray(matrix)
    if int(matrix.shape[0]) <= 3:
        # UMAP's spectral initialization is unstable for tiny smoke-test bundles.
        if int(matrix.shape[1]) >= 2:
            return matrix[:, :2].astype(np.float32, copy=True)
        if int(matrix.shape[1]) == 1:
            return np.column_stack([matrix[:, 0], np.zeros(int(matrix.shape[0]), dtype=np.float32)])
        raise NeuroScapeError("UMAP projection requires at least one embedding dimension")

    reducer = umap.UMAP(
        n_components=2,
        n_neighbors=n_neighbors,
        min_dist=min_dist,
        metric=metric,
        random_state=random_state,
    )
    return reducer.fit_transform(matrix)


def compute_tsne_projection(
    matrix: Any,
    perplexity: float = DEFAULT_TSNE_PERPLEXITY,
    learning_rate: str | float = DEFAULT_TSNE_LEARNING_RATE,
    early_exaggeration: float = DEFAULT_TSNE_EARLY_EXAGGERATION,
    metric: str = "cosine",
    random_state: int = 42,
) -> Any:
    import numpy as np
    from sklearn.manifold import TSNE

    matrix = np.asarray(matrix)
    if int(matrix.shape[0]) <= 3:
        if int(matrix.shape[1]) >= 2:
            return matrix[:, :2].astype(np.float32, copy=True)
        if int(matrix.shape[1]) == 1:
            return np.column_stack([matrix[:, 0], np.zeros(int(matrix.shape[0]), dtype=np.float32)])
        raise NeuroScapeError("t-SNE projection requires at least one embedding dimension")

    max_perplexity = max(1.0, float(matrix.shape[0] - 1) / 3.0)
    adjusted_perplexity = min(float(perplexity), max_perplexity)
    reducer = TSNE(
        n_components=2,
        perplexity=adjusted_perplexity,
        learning_rate=learning_rate,
        early_exaggeration=early_exaggeration,
        metric=metric,
        init="pca",
        random_state=random_state,
    )
    return reducer.fit_transform(matrix)


def build_distinct_color_map(values: list[str]) -> dict[str, str]:
    unique_values = sorted({value for value in values if value})
    if not unique_values:
        return {}
    total = len(unique_values)
    return {
        value: f"hsl({int((index * 360) / total)}, 70%, 45%)"
        for index, value in enumerate(unique_values)
    }


def _projection_trace_customdata(records: list[dict[str, Any]], indices: list[int]) -> list[list[Any]]:
    return [
        [
            records[index]["id"],
            records[index]["title"],
            records[index]["accepted_for"],
            records[index]["primary_topic"],
            ", ".join(records[index]["keywords"]),
        ]
        for index in indices
    ]


def _add_projection_panel_traces(
    figure: Any,
    coordinates: Any,
    records: list[dict[str, Any]],
    row: int,
    column: int,
    color_by: str,
    topic_color_map: dict[str, str],
    show_legend: bool = True,
) -> None:
    import numpy as np
    import plotly.graph_objects as go

    coords = np.asarray(coordinates)
    grouped_indices: dict[str, list[int]] = {}
    for index, record in enumerate(records):
        grouped_indices.setdefault(str(record.get(color_by) or "Unknown"), []).append(index)
    for group_name in sorted(grouped_indices):
        indices = grouped_indices[group_name]
        marker: dict[str, Any] = {"size": 7, "opacity": 0.85}
        if color_by == "primary_topic":
            marker["color"] = topic_color_map.get(group_name, "hsl(0, 0%, 50%)")
        figure.add_trace(
            go.Scattergl(
                x=coords[indices, 0],
                y=coords[indices, 1],
                mode="markers",
                name=group_name,
                marker=marker,
                customdata=_projection_trace_customdata(records, indices),
                hovertemplate=(
                    "id=%{customdata[0]}<br>"
                    "title=%{customdata[1]}<br>"
                    "accepted_for=%{customdata[2]}<br>"
                    "primary_topic=%{customdata[3]}<br>"
                    "keywords=%{customdata[4]}<extra></extra>"
                ),
                legendgroup=f"{color_by}:{group_name}",
                legendgrouptitle_text="Accepted For" if color_by == "accepted_for" else "Primary Topic",
                showlegend=show_legend,
                selected={"marker": {"size": 11, "opacity": 1.0, "color": "#111111"}},
                unselected={"marker": {"opacity": 0.22}},
            ),
            row=row,
            col=column,
        )


def _build_linked_highlight_script(div_id: str) -> str:
    return f"""
<script>
(function() {{
  const gd = document.getElementById({json.dumps(div_id)});
  if (!gd) return;
  let highlightedId = null;

  function selectedPointsForTrace(trace, targetId) {{
    if (!trace.customdata || targetId === null || targetId === undefined) return null;
    const selected = [];
    for (let index = 0; index < trace.customdata.length; index += 1) {{
      if (trace.customdata[index] && trace.customdata[index][0] === targetId) {{
        selected.push(index);
      }}
    }}
    return selected.length ? selected : null;
  }}

  function highlightId(targetId) {{
    if (targetId === highlightedId) return;
    highlightedId = targetId;
    for (let traceIndex = 0; traceIndex < gd.data.length; traceIndex += 1) {{
      const selected = selectedPointsForTrace(gd.data[traceIndex], targetId);
      Plotly.restyle(gd, {{selectedpoints: [selected]}}, [traceIndex]);
    }}
  }}

  function clearHighlight() {{
    highlightedId = null;
    for (let traceIndex = 0; traceIndex < gd.data.length; traceIndex += 1) {{
      Plotly.restyle(gd, {{selectedpoints: [null]}}, [traceIndex]);
    }}
  }}

  gd.on('plotly_hover', function(event) {{
    const point = event && event.points && event.points[0];
    if (!point || !point.customdata) return;
    highlightId(point.customdata[0]);
  }});
  gd.on('plotly_click', function(event) {{
    const point = event && event.points && event.points[0];
    if (!point || !point.customdata) return;
    highlightId(point.customdata[0]);
  }});
  gd.on('plotly_unhover', function() {{
    clearHighlight();
  }});
}})();
</script>
""".strip()


def write_umap_outputs(
    output_html: Path,
    output_json: Path,
    coordinates: Any,
    records: list[dict[str, Any]],
    title: str = "OHBM 2026 Abstract Embeddings UMAP",
) -> None:
    import numpy as np
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    coords = np.asarray(coordinates)
    figure = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Accepted For", "Primary Topic"),
        horizontal_spacing=0.08,
    )
    topic_color_map = build_distinct_color_map([str(record.get("primary_topic") or "Unknown") for record in records])

    for column, color_by in ((1, "accepted_for"), (2, "primary_topic")):
        grouped_indices: dict[str, list[int]] = {}
        for index, record in enumerate(records):
            grouped_indices.setdefault(str(record.get(color_by) or "Unknown"), []).append(index)
        for group_name in sorted(grouped_indices):
            indices = grouped_indices[group_name]
            customdata = [
                [
                    records[index]["id"],
                    records[index]["title"],
                    records[index]["accepted_for"],
                    records[index]["primary_topic"],
                    ", ".join(records[index]["keywords"]),
                ]
                for index in indices
            ]
            marker: dict[str, Any] = {"size": 7, "opacity": 0.8}
            if color_by == "primary_topic":
                marker["color"] = topic_color_map.get(group_name, "hsl(0, 0%, 50%)")
            figure.add_trace(
                go.Scattergl(
                    x=coords[indices, 0],
                    y=coords[indices, 1],
                    mode="markers",
                    name=group_name,
                    marker=marker,
                    customdata=customdata,
                    hovertemplate=(
                        "id=%{customdata[0]}<br>"
                        "title=%{customdata[1]}<br>"
                        "accepted_for=%{customdata[2]}<br>"
                        "primary_topic=%{customdata[3]}<br>"
                        "keywords=%{customdata[4]}<extra></extra>"
                    ),
                    legendgroup=f"{color_by}:{group_name}",
                    legendgrouptitle_text="Accepted For" if color_by == "accepted_for" else "Primary Topic",
                    showlegend=True,
                ),
                row=1,
                col=column,
            )
    figure.update_layout(
        title=title,
        template="plotly_white",
    )
    figure.update_xaxes(title_text="UMAP-1", row=1, col=1)
    figure.update_yaxes(title_text="UMAP-2", row=1, col=1)
    figure.update_xaxes(title_text="UMAP-1", row=1, col=2)
    figure.update_yaxes(title_text="UMAP-2", row=1, col=2)
    figure.write_html(str(output_html), include_plotlyjs="cdn")

    write_json(
        output_json,
        {
            "title": title,
            "count": len(records),
            "primary_topic_colors": topic_color_map,
            "points": [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "accepted_for": record["accepted_for"],
                    "primary_topic": record["primary_topic"],
                    "keywords": record["keywords"],
                    "x": float(coords[index, 0]),
                    "y": float(coords[index, 1]),
                }
                for index, record in enumerate(records)
            ],
        },
    )


def default_umap_output_paths(
    embeddings_dir: Path,
    embedding_fields: list[str],
) -> tuple[Path, Path]:
    fieldset = "-".join(embedding_fields)
    basename = f"umap_{fieldset}"
    return embeddings_dir / f"{basename}.html", embeddings_dir / f"{basename}.json"


def default_projection_output_paths(
    embeddings_dir: Path,
    embedding_fields: list[str],
) -> tuple[Path, Path]:
    fieldset = "-".join(embedding_fields)
    basename = f"projection_comparison_{fieldset}"
    return embeddings_dir / f"{basename}.html", embeddings_dir / f"{basename}.json"


def write_projection_comparison_outputs(
    output_html: Path,
    output_json: Path,
    umap_coordinates: Any,
    tsne_coordinates: Any,
    records: list[dict[str, Any]],
    title: str = "OHBM 2026 Projection Comparison",
) -> None:
    import plotly.io as pio
    from plotly.subplots import make_subplots

    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    topic_color_map = build_distinct_color_map([str(record.get("primary_topic") or "Unknown") for record in records])
    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            "UMAP by Accepted For",
            "UMAP by Primary Topic",
            "t-SNE by Accepted For",
            "t-SNE by Primary Topic",
        ),
        horizontal_spacing=0.08,
        vertical_spacing=0.12,
    )

    _add_projection_panel_traces(
        figure,
        umap_coordinates,
        records,
        row=1,
        column=1,
        color_by="accepted_for",
        topic_color_map=topic_color_map,
        show_legend=True,
    )
    _add_projection_panel_traces(
        figure,
        umap_coordinates,
        records,
        row=1,
        column=2,
        color_by="primary_topic",
        topic_color_map=topic_color_map,
        show_legend=True,
    )
    _add_projection_panel_traces(
        figure,
        tsne_coordinates,
        records,
        row=2,
        column=1,
        color_by="accepted_for",
        topic_color_map=topic_color_map,
        show_legend=False,
    )
    _add_projection_panel_traces(
        figure,
        tsne_coordinates,
        records,
        row=2,
        column=2,
        color_by="primary_topic",
        topic_color_map=topic_color_map,
        show_legend=False,
    )
    figure.update_layout(title=title, template="plotly_white")
    figure.update_xaxes(title_text="Axis 1", row=1, col=1)
    figure.update_yaxes(title_text="Axis 2", row=1, col=1)
    figure.update_xaxes(title_text="Axis 1", row=1, col=2)
    figure.update_yaxes(title_text="Axis 2", row=1, col=2)
    figure.update_xaxes(title_text="Axis 1", row=2, col=1)
    figure.update_yaxes(title_text="Axis 2", row=2, col=1)
    figure.update_xaxes(title_text="Axis 1", row=2, col=2)
    figure.update_yaxes(title_text="Axis 2", row=2, col=2)

    div_id = "projection-comparison"
    html = pio.to_html(figure, include_plotlyjs="cdn", full_html=True, div_id=div_id)
    html = html.replace("</body>", f"{_build_linked_highlight_script(div_id)}\n</body>")
    output_html.write_text(html, encoding="utf-8")

    import numpy as np

    umap_coords = np.asarray(umap_coordinates)
    tsne_coords = np.asarray(tsne_coordinates)
    write_json(
        output_json,
        {
            "title": title,
            "count": len(records),
            "primary_topic_colors": topic_color_map,
            "points": [
                {
                    "id": record["id"],
                    "title": record["title"],
                    "accepted_for": record["accepted_for"],
                    "primary_topic": record["primary_topic"],
                    "keywords": record["keywords"],
                    "umap_x": float(umap_coords[index, 0]),
                    "umap_y": float(umap_coords[index, 1]),
                    "tsne_x": float(tsne_coords[index, 0]),
                    "tsne_y": float(tsne_coords[index, 1]),
                }
                for index, record in enumerate(records)
            ],
        },
    )


def build_projection_graph(
    ids: list[int],
    coordinates: Any,
    num_neighbors: int = 15,
) -> Any:
    import networkx as nx
    import numpy as np
    from sklearn.neighbors import NearestNeighbors

    matrix = np.asarray(coordinates, dtype=np.float32)
    if matrix.shape[0] != len(ids):
        raise NeuroScapeError("Projection coordinate count does not match ids")
    if matrix.shape[0] == 0:
        raise NeuroScapeError("Projection graph requires at least one point")

    graph = nx.Graph()
    graph.add_nodes_from(int(abstract_id) for abstract_id in ids)
    if matrix.shape[0] == 1:
        return graph

    effective_neighbors = min(max(1, num_neighbors), int(matrix.shape[0]) - 1)
    nearest = NearestNeighbors(n_neighbors=effective_neighbors + 1, metric="euclidean")
    nearest.fit(matrix)
    distances, neighbor_indices = nearest.kneighbors(matrix)
    for row_index, abstract_id in enumerate(ids):
        for distance, neighbor_index in zip(distances[row_index][1:], neighbor_indices[row_index][1:]):
            neighbor_id = int(ids[int(neighbor_index)])
            if neighbor_id == int(abstract_id):
                continue
            weight = 1.0 / (1.0 + float(distance))
            if graph.has_edge(int(abstract_id), neighbor_id):
                graph[int(abstract_id)][neighbor_id]["weight"] = max(
                    float(graph[int(abstract_id)][neighbor_id]["weight"]),
                    weight,
                )
            else:
                graph.add_edge(int(abstract_id), neighbor_id, weight=weight)
    return graph


def _cluster_distance_metrics(
    ids: list[int],
    coordinates: Any,
    assignments: dict[int, int],
) -> dict[str, float | int | None]:
    import numpy as np

    matrix = np.asarray(coordinates, dtype=np.float32)
    if matrix.shape[0] != len(ids):
        raise NeuroScapeError("Coordinate count does not match ids")

    members: dict[int, list[int]] = {}
    index_by_id = {int(abstract_id): index for index, abstract_id in enumerate(ids)}
    for abstract_id, cluster_id in assignments.items():
        members.setdefault(int(cluster_id), []).append(index_by_id[int(abstract_id)])

    cluster_ids = sorted(members)
    if len(cluster_ids) <= 1:
        return {
            "cluster_count": len(cluster_ids),
            "mean_intercluster_distance": 0.0,
            "mean_intracluster_distance": 0.0,
            "intercluster_distance_ratio": 0.0,
            "silhouette_score": None,
        }

    centroids: dict[int, Any] = {}
    within_distances: list[float] = []
    for cluster_id, member_indices in members.items():
        cluster_points = matrix[member_indices]
        centroid = cluster_points.mean(axis=0)
        centroids[cluster_id] = centroid
        within_distances.extend(np.linalg.norm(cluster_points - centroid, axis=1).tolist())

    centroid_distances: list[float] = []
    for index, cluster_id in enumerate(cluster_ids):
        for other_cluster_id in cluster_ids[index + 1 :]:
            centroid_distances.append(
                float(np.linalg.norm(centroids[cluster_id] - centroids[other_cluster_id]))
            )

    mean_intercluster_distance = float(np.mean(centroid_distances)) if centroid_distances else 0.0
    mean_intracluster_distance = float(np.mean(within_distances)) if within_distances else 0.0
    denominator = mean_intracluster_distance if mean_intracluster_distance > 0 else 1.0
    metrics: dict[str, float | int | None] = {
        "cluster_count": len(cluster_ids),
        "mean_intercluster_distance": mean_intercluster_distance,
        "mean_intracluster_distance": mean_intracluster_distance,
        "intercluster_distance_ratio": mean_intercluster_distance / denominator,
        "silhouette_score": None,
    }

    try:
        from sklearn.metrics import silhouette_score

        labels = np.asarray([assignments[int(abstract_id)] for abstract_id in ids], dtype=np.int32)
        metrics["silhouette_score"] = float(silhouette_score(matrix, labels, metric="euclidean"))
    except Exception:
        metrics["silhouette_score"] = None
    return metrics


def score_projection(
    ids: list[int],
    coordinates: Any,
    graph_neighbors: int = 15,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
) -> dict[str, Any]:
    graph = build_projection_graph(ids, coordinates, num_neighbors=graph_neighbors)
    community_result = detect_semantic_communities(
        graph,
        num_resolution_parameter=num_resolution_parameter,
        max_resolution_parameter=max_resolution_parameter,
    )
    distance_metrics = _cluster_distance_metrics(ids, coordinates, community_result["assignments"])
    return {
        "graph_neighbors": graph_neighbors,
        "cluster_count": distance_metrics["cluster_count"],
        "best_modularity": float(community_result["best_modularity"]),
        "best_resolution": float(community_result["best_resolution"]),
        "mean_intercluster_distance": float(distance_metrics["mean_intercluster_distance"]),
        "mean_intracluster_distance": float(distance_metrics["mean_intracluster_distance"]),
        "intercluster_distance_ratio": float(distance_metrics["intercluster_distance_ratio"]),
        "silhouette_score": (
            None if distance_metrics["silhouette_score"] is None else float(distance_metrics["silhouette_score"])
        ),
    }


def _normalize_rows(matrix: Any) -> Any:
    import numpy as np

    normalized = np.asarray(matrix, dtype=np.float32).copy()
    norms = np.linalg.norm(normalized, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return normalized / norms


def prepare_clustering_matrix(
    matrix: Any,
    normalize_rows: bool = True,
    pca_components: int | None = 50,
    random_state: int = 42,
) -> dict[str, Any]:
    import numpy as np

    prepared = np.asarray(matrix, dtype=np.float32)
    metadata: dict[str, Any] = {
        "input_dimension": int(prepared.shape[1]) if prepared.ndim == 2 else 0,
        "row_normalized": bool(normalize_rows),
        "pca_components": None,
    }
    if normalize_rows:
        prepared = _normalize_rows(prepared)
    requested_components = None if pca_components is None else int(pca_components)
    if requested_components and requested_components > 0:
        max_components = min(int(prepared.shape[0]), int(prepared.shape[1]))
        effective_components = min(requested_components, max_components)
        if effective_components >= 2 and effective_components < int(prepared.shape[1]):
            from sklearn.decomposition import PCA

            reducer = PCA(n_components=effective_components, random_state=random_state)
            prepared = reducer.fit_transform(prepared).astype(np.float32, copy=False)
            metadata["pca_components"] = int(effective_components)
            metadata["explained_variance_ratio"] = float(reducer.explained_variance_ratio_.sum())
    metadata["output_dimension"] = int(prepared.shape[1]) if prepared.ndim == 2 else 0
    return {"matrix": prepared, "metadata": metadata}


def _agglomerative_kwargs(metric: str, linkage: str) -> dict[str, Any]:
    kwargs: dict[str, Any] = {"n_clusters": None, "distance_threshold": None, "linkage": linkage}
    try:
        from sklearn.cluster import AgglomerativeClustering

        AgglomerativeClustering(metric=metric, **kwargs)
        kwargs["metric"] = metric
    except TypeError:
        kwargs["affinity"] = metric
    return kwargs


def cluster_with_method(
    matrix: Any,
    method: str,
    cluster_count: int,
    random_state: int = 42,
) -> list[int]:
    import numpy as np
    from sklearn.cluster import AgglomerativeClustering, Birch, KMeans
    from sklearn.mixture import GaussianMixture

    method_name = str(method).strip().lower()
    if cluster_count < 2:
        raise NeuroScapeError("cluster_count must be at least 2")

    if method_name == "kmeans":
        estimator = KMeans(n_clusters=cluster_count, random_state=random_state, n_init=10)
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "agglomerative-ward":
        estimator = AgglomerativeClustering(n_clusters=cluster_count, linkage="ward")
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "agglomerative-average":
        kwargs = _agglomerative_kwargs("cosine", "average")
        kwargs["n_clusters"] = cluster_count
        kwargs.pop("distance_threshold", None)
        estimator = AgglomerativeClustering(**kwargs)
        try:
            return estimator.fit_predict(matrix).astype(np.int32).tolist()
        except ValueError as exc:
            if "zero vectors" not in str(exc).lower():
                raise
            fallback_kwargs = _agglomerative_kwargs("euclidean", "average")
            fallback_kwargs["n_clusters"] = cluster_count
            fallback_kwargs.pop("distance_threshold", None)
            fallback_estimator = AgglomerativeClustering(**fallback_kwargs)
            return fallback_estimator.fit_predict(matrix).astype(np.int32).tolist()
    if method_name == "gaussian-mixture":
        estimator = GaussianMixture(n_components=cluster_count, covariance_type="diag", random_state=random_state)
        return estimator.fit(matrix).predict(matrix).astype(np.int32).tolist()
    if method_name == "birch":
        estimator = Birch(n_clusters=cluster_count)
        return estimator.fit_predict(matrix).astype(np.int32).tolist()
    raise NeuroScapeError(f"Unsupported clustering method: {method}")


def _normalized_cluster_entropy(counts: list[int]) -> float:
    import math

    total = sum(counts)
    if total <= 0 or len(counts) <= 1:
        return 0.0
    probabilities = [count / total for count in counts if count > 0]
    entropy = -sum(probability * math.log(probability) for probability in probabilities)
    return float(entropy / math.log(len(probabilities))) if len(probabilities) > 1 else 0.0


def compute_clustering_metrics(
    ids: list[int],
    matrix: Any,
    labels: list[int] | tuple[int, ...],
) -> dict[str, Any]:
    import numpy as np
    from sklearn.metrics import calinski_harabasz_score, davies_bouldin_score, silhouette_score

    if len(ids) != len(labels):
        raise NeuroScapeError("ID and label counts do not match")
    numeric_labels = np.asarray(labels, dtype=np.int32)
    cluster_ids = sorted({int(value) for value in numeric_labels.tolist()})
    cluster_sizes = [int(np.sum(numeric_labels == cluster_id)) for cluster_id in cluster_ids]
    total = max(1, len(labels))
    assignments = {int(abstract_id): int(cluster_id) for abstract_id, cluster_id in zip(ids, numeric_labels.tolist())}
    distance_metrics = _cluster_distance_metrics(ids, matrix, assignments)

    metrics: dict[str, Any] = {
        "cluster_count": len(cluster_ids),
        "cluster_sizes": cluster_sizes,
        "largest_cluster_fraction": (max(cluster_sizes) / total) if cluster_sizes else 1.0,
        "smallest_cluster_size": min(cluster_sizes) if cluster_sizes else 0,
        "cluster_size_std_fraction": (
            float(np.std(cluster_sizes) / np.mean(cluster_sizes)) if len(cluster_sizes) > 1 else 0.0
        ),
        "cluster_size_entropy": _normalized_cluster_entropy(cluster_sizes),
        "mean_intercluster_distance": float(distance_metrics["mean_intercluster_distance"]),
        "mean_intracluster_distance": float(distance_metrics["mean_intracluster_distance"]),
        "intercluster_distance_ratio": float(distance_metrics["intercluster_distance_ratio"]),
        "silhouette_score": None,
        "calinski_harabasz_score": None,
        "davies_bouldin_score": None,
        "valid": len(cluster_ids) > 1,
    }
    if len(cluster_ids) <= 1:
        return metrics

    try:
        metrics["silhouette_score"] = float(silhouette_score(matrix, numeric_labels, metric="euclidean"))
    except Exception:
        metrics["silhouette_score"] = None
    try:
        metrics["calinski_harabasz_score"] = float(calinski_harabasz_score(matrix, numeric_labels))
    except Exception:
        metrics["calinski_harabasz_score"] = None
    try:
        metrics["davies_bouldin_score"] = float(davies_bouldin_score(matrix, numeric_labels))
    except Exception:
        metrics["davies_bouldin_score"] = None
    return metrics


def _valid_benchmark_run(result: dict[str, Any]) -> bool:
    cluster_count = int(result.get("cluster_count") or 0)
    smallest_cluster_size = int(result.get("smallest_cluster_size") or 0)
    largest_cluster_fraction = float(result.get("largest_cluster_fraction") or 1.0)
    return (
        bool(result.get("valid"))
        and cluster_count >= 2
        and smallest_cluster_size > 0
        and largest_cluster_fraction < 0.98
    )


def _normalized_metric_value(
    results: list[dict[str, Any]],
    result: dict[str, Any],
    key: str,
    higher_is_better: bool,
) -> float:
    numeric_values = [
        float(candidate[key])
        for candidate in results
        if _valid_benchmark_run(candidate) and candidate.get(key) is not None
    ]
    if not numeric_values or result.get(key) is None:
        return 0.0
    value = float(result[key])
    minimum = min(numeric_values)
    maximum = max(numeric_values)
    if maximum <= minimum:
        return 1.0
    normalized = (value - minimum) / (maximum - minimum)
    return normalized if higher_is_better else 1.0 - normalized


def rank_clustering_benchmark_results(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for result in results:
        normalized_metrics = {
            "silhouette": _normalized_metric_value(results, result, "silhouette_score", higher_is_better=True),
            "intercluster_ratio": _normalized_metric_value(
                results,
                result,
                "intercluster_distance_ratio",
                higher_is_better=True,
            ),
            "calinski_harabasz": _normalized_metric_value(
                results,
                result,
                "calinski_harabasz_score",
                higher_is_better=True,
            ),
            "davies_bouldin": _normalized_metric_value(
                results,
                result,
                "davies_bouldin_score",
                higher_is_better=False,
            ),
            "cluster_entropy": _normalized_metric_value(
                results,
                result,
                "cluster_size_entropy",
                higher_is_better=True,
            ),
            "cluster_balance": _normalized_metric_value(
                results,
                result,
                "largest_cluster_fraction",
                higher_is_better=False,
            ),
        }
        weights = {
            "silhouette": 0.30,
            "intercluster_ratio": 0.20,
            "calinski_harabasz": 0.15,
            "davies_bouldin": 0.15,
            "cluster_entropy": 0.10,
            "cluster_balance": 0.10,
        }
        composite_score = sum(normalized_metrics[key] * weights[key] for key in weights)
        if not _valid_benchmark_run(result):
            composite_score = -1.0
        ranked_result = dict(result)
        ranked_result["normalized_metrics"] = normalized_metrics
        ranked_result["composite_score"] = float(composite_score)
        ranked.append(ranked_result)

    return sorted(
        ranked,
        key=lambda item: (
            float(item.get("composite_score") or -1.0),
            float(item.get("silhouette_score") if item.get("silhouette_score") is not None else -1.0),
            float(item.get("intercluster_distance_ratio") or 0.0),
            -float(item.get("davies_bouldin_score") or 999999.0),
        ),
        reverse=True,
    )


def run_clustering_benchmark(
    ids: list[int],
    matrix: Any,
    methods: list[str],
    k_values: list[int],
    random_state: int = 42,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    best_labels_by_signature: dict[tuple[str, int], list[int]] = {}
    for method in methods:
        for cluster_count in k_values:
            try:
                labels = cluster_with_method(matrix, method, cluster_count=cluster_count, random_state=random_state)
                metrics = compute_clustering_metrics(ids, matrix, labels)
                result = {
                    "method": method,
                    "requested_cluster_count": int(cluster_count),
                    **metrics,
                }
                results.append(result)
                best_labels_by_signature[(method, int(cluster_count))] = labels
            except Exception as exc:
                results.append(
                    {
                        "method": method,
                        "requested_cluster_count": int(cluster_count),
                        "cluster_count": 0,
                        "valid": False,
                        "error": str(exc),
                    }
                )
    ranked_results = rank_clustering_benchmark_results(results)
    best_result = ranked_results[0] if ranked_results else None
    best_labels = None
    if best_result and _valid_benchmark_run(best_result):
        best_labels = best_labels_by_signature.get(
            (str(best_result["method"]), int(best_result["requested_cluster_count"]))
        )
    return {
        "results": ranked_results,
        "best_result": best_result,
        "best_labels": best_labels,
    }


def write_clustering_benchmark(
    output_dir: Path,
    benchmark: dict[str, Any],
    ids: list[int],
    records: list[dict[str, Any]],
    matrix: Any,
    config: dict[str, Any],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(
        output_dir / "benchmark.json",
        {
            "config": config,
            "best_result": benchmark["best_result"],
            "results": benchmark["results"],
        },
    )
    best_result = benchmark.get("best_result")
    best_labels = benchmark.get("best_labels")
    if not best_result or not best_labels or not _valid_benchmark_run(best_result):
        return
    assignments = {
        int(abstract_id): int(cluster_id)
        for abstract_id, cluster_id in zip(ids, best_labels)
    }
    cluster_summaries = summarize_semantic_clusters(
        ids,
        matrix,
        records,
        assignments,
        max_keywords=max_keywords,
        max_representatives=max_representatives,
    )
    write_json(output_dir / "best_run.json", {"result": best_result})
    write_json(
        output_dir / "cluster_assignments.json",
        {
            "assignments": {
                str(abstract_id): cluster_id
                for abstract_id, cluster_id in sorted(assignments.items())
            }
        },
    )
    write_json(output_dir / "cluster_summaries.json", {"clusters": cluster_summaries})


def _projection_rank_key(result: dict[str, Any]) -> tuple[float, float, float, float]:
    cluster_count = int(result.get("cluster_count") or 0)
    silhouette_score = result.get("silhouette_score")
    return (
        1.0 if cluster_count > 1 else 0.0,
        float(result.get("best_modularity") or 0.0),
        float(result.get("intercluster_distance_ratio") or 0.0),
        float(silhouette_score) if silhouette_score is not None else -1.0,
    )


def optimize_projection_parameters(
    ids: list[int],
    matrix: Any,
    umap_neighbors: list[int],
    umap_min_dists: list[float],
    tsne_perplexities: list[float],
    tsne_early_exaggerations: list[float],
    tsne_learning_rates: list[str],
    metric: str = "cosine",
    random_state: int = 42,
    graph_neighbors: int = 15,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []

    for n_neighbors in umap_neighbors:
        for min_dist in umap_min_dists:
            coordinates = compute_umap_projection(
                matrix,
                n_neighbors=int(n_neighbors),
                min_dist=float(min_dist),
                metric=metric,
                random_state=random_state,
            )
            metrics = score_projection(
                ids,
                coordinates,
                graph_neighbors=graph_neighbors,
                num_resolution_parameter=num_resolution_parameter,
                max_resolution_parameter=max_resolution_parameter,
            )
            results.append(
                {
                    "method": "umap",
                    "params": {"n_neighbors": int(n_neighbors), "min_dist": float(min_dist), "metric": metric},
                    **metrics,
                }
            )

    for perplexity in tsne_perplexities:
        for early_exaggeration in tsne_early_exaggerations:
            for learning_rate in tsne_learning_rates:
                coordinates = compute_tsne_projection(
                    matrix,
                    perplexity=float(perplexity),
                    learning_rate=learning_rate,
                    early_exaggeration=float(early_exaggeration),
                    metric=metric,
                    random_state=random_state,
                )
                metrics = score_projection(
                    ids,
                    coordinates,
                    graph_neighbors=graph_neighbors,
                    num_resolution_parameter=num_resolution_parameter,
                    max_resolution_parameter=max_resolution_parameter,
                )
                results.append(
                    {
                        "method": "tsne",
                        "params": {
                            "perplexity": float(perplexity),
                            "early_exaggeration": float(early_exaggeration),
                            "learning_rate": learning_rate,
                            "metric": metric,
                        },
                        **metrics,
                    }
                )

    ordered_results = sorted(results, key=_projection_rank_key, reverse=True)
    best_by_method: dict[str, dict[str, Any]] = {}
    for result in ordered_results:
        method = str(result["method"])
        best_by_method.setdefault(method, result)
    return {"results": ordered_results, "best_by_method": best_by_method, "best_overall": ordered_results[0]}


def split_stage2_matrix(
    matrix: Any, validation_size: float = 0.05, seed: int = 42
) -> tuple[Any, Any]:
    import numpy as np

    if not 0 < validation_size < 1:
        raise NeuroScapeError("validation_size must be between 0 and 1")
    if matrix.shape[0] < 20:
        raise NeuroScapeError("Stage-2 training requires at least 20 stage-1 vectors")

    indices = np.arange(matrix.shape[0])
    rng = np.random.default_rng(seed)
    rng.shuffle(indices)

    validation_count = max(1, int(round(matrix.shape[0] * validation_size)))
    train_indices = indices[validation_count:]
    validation_indices = indices[:validation_count]
    return matrix[train_indices].copy(), matrix[validation_indices].copy()


def build_stage2_network(
    input_dimension: int,
    hidden_dimensions: tuple[int, int, int] = DEFAULT_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = DEFAULT_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.1,
) -> Any:
    import torch.nn as nn
    import torch.nn.functional as F

    class Network(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.first_stage = nn.Sequential(
                nn.Linear(input_dimension, hidden_dimensions[0]),
                nn.BatchNorm1d(hidden_dimensions[0]),
                nn.ELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dimensions[0], hidden_dimensions[1]),
                nn.ELU(),
            )
            self.second_stage = nn.Sequential(
                nn.Linear(hidden_dimensions[1], hidden_dimensions[2]),
                nn.BatchNorm1d(hidden_dimensions[2]),
                nn.ELU(),
                nn.Dropout(dropout),
                nn.Linear(hidden_dimensions[2], output_dimension),
            )

        def forward(self, x: Any) -> Any:
            first_state = self.first_stage(x)
            second_state = self.second_stage(first_state)
            return F.normalize(second_state, p=2, dim=1)

    return Network()


def dimension_correlation(projected: Any) -> Any:
    import torch

    if projected.shape[0] < 2 or projected.shape[1] < 2:
        return torch.zeros((), dtype=projected.dtype, device=projected.device)
    corr_matrix = torch.corrcoef(projected.T)
    return torch.mean(torch.abs(torch.triu(corr_matrix, diagonal=1)))


def compute_stage2_losses(
    model: Any,
    batch: Any,
    temperature: float,
    cutoff_values: tuple[float, float],
    correlation_weight: float = 0.0,
) -> tuple[Any, Any, Any]:
    import torch

    positive_cutoff, negative_cutoff = cutoff_values
    projected = model(batch)
    source_similarity = torch.matmul(batch, batch.T)
    target_similarity = torch.matmul(projected, projected.T)
    positives_mask = source_similarity >= positive_cutoff
    positives_mask = positives_mask & ~torch.eye(batch.shape[0], dtype=torch.bool, device=batch.device)
    negatives_mask = source_similarity <= negative_cutoff

    positive_logsum = torch.logsumexp(target_similarity * positives_mask.float() / temperature, dim=1)
    negative_logsum = torch.logsumexp(target_similarity * negatives_mask.float() / temperature, dim=1)
    info_nce_loss = (-positive_logsum + negative_logsum).mean()
    correlation_loss = correlation_weight * dimension_correlation(projected)
    return info_nce_loss + correlation_loss, info_nce_loss, correlation_loss


def evaluate_stage2_model(
    model: Any,
    validation_tensor: Any,
    temperature: float,
    cutoff_values: tuple[float, float],
) -> float:
    import torch

    with torch.no_grad():
        _, info_nce_loss, _ = compute_stage2_losses(
            model,
            validation_tensor,
            temperature=temperature,
            cutoff_values=cutoff_values,
            correlation_weight=0.0,
        )
    return float(info_nce_loss.item())


def train_stage2_model(
    matrix: Any,
    hidden_dimensions: tuple[int, int, int] = DEFAULT_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = DEFAULT_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.1,
    epochs: int = 120,
    batch_size: int = 256,
    validation_size: float = 0.05,
    initial_learning_rate: float = 1e-4,
    minimum_learning_rate: float = 1e-5,
    temperature: float = 0.1,
    cutoff_values: tuple[float, float] = (0.85, 0.75),
    correlation_weight: float = 0.1,
    seed: int = 42,
    device: str | None = None,
    report_every: int = 10,
) -> tuple[Any, dict[str, Any]]:
    import numpy as np
    import torch

    if epochs <= 0:
        raise NeuroScapeError("epochs must be positive")
    if batch_size <= 1:
        raise NeuroScapeError("batch_size must be greater than 1")

    torch.manual_seed(seed)
    np.random.seed(seed)

    train_matrix, validation_matrix = split_stage2_matrix(matrix, validation_size=validation_size, seed=seed)
    torch_device = choose_torch_device(device)
    model = build_stage2_network(
        int(matrix.shape[1]),
        hidden_dimensions=hidden_dimensions,
        output_dimension=output_dimension,
        dropout=dropout,
    ).to(torch_device)

    optimizer = torch.optim.Adam(model.parameters(), lr=initial_learning_rate, weight_decay=0.01)
    gamma = (minimum_learning_rate / initial_learning_rate) ** (1 / max(epochs, 1))
    scheduler = torch.optim.lr_scheduler.StepLR(optimizer, step_size=1, gamma=gamma)

    validation_tensor = torch.tensor(validation_matrix, dtype=torch.float32, device=torch_device)
    best_validation_loss = float("inf")
    best_state = copy.deepcopy(model.state_dict())
    train_history: list[dict[str, float]] = []

    for epoch in range(epochs):
        model.train()
        permutation = np.random.permutation(train_matrix.shape[0])
        shuffled = train_matrix[permutation]
        batch_losses: list[float] = []
        batch_info_losses: list[float] = []
        batch_correlation_losses: list[float] = []

        for start in range(0, shuffled.shape[0], batch_size):
            stop = min(start + batch_size, shuffled.shape[0])
            current_batch = shuffled[start:stop]
            if current_batch.shape[0] < 2:
                continue
            batch_tensor = torch.tensor(current_batch, dtype=torch.float32, device=torch_device)
            optimizer.zero_grad()
            total_loss, info_nce_loss, correlation_loss = compute_stage2_losses(
                model,
                batch_tensor,
                temperature=temperature,
                cutoff_values=cutoff_values,
                correlation_weight=correlation_weight,
            )
            total_loss.backward()
            optimizer.step()
            batch_losses.append(float(total_loss.item()))
            batch_info_losses.append(float(info_nce_loss.item()))
            batch_correlation_losses.append(float(correlation_loss.item()))

        scheduler.step()
        validation_loss = evaluate_stage2_model(
            model,
            validation_tensor,
            temperature=temperature,
            cutoff_values=cutoff_values,
        )
        if validation_loss < best_validation_loss:
            best_validation_loss = validation_loss
            best_state = copy.deepcopy(model.state_dict())

        epoch_record = {
            "epoch": float(epoch + 1),
            "training_loss": float(sum(batch_losses) / max(len(batch_losses), 1)),
            "training_info_nce_loss": float(sum(batch_info_losses) / max(len(batch_info_losses), 1)),
            "training_correlation_loss": float(sum(batch_correlation_losses) / max(len(batch_correlation_losses), 1)),
            "validation_loss": float(validation_loss),
        }
        train_history.append(epoch_record)
        if epoch == 0 or (epoch + 1) % report_every == 0 or epoch + 1 == epochs:
            print(json.dumps(epoch_record, sort_keys=True))

    model.load_state_dict(best_state)
    return model, {
        "device": torch_device,
        "epochs": epochs,
        "batch_size": batch_size,
        "validation_size": validation_size,
        "temperature": temperature,
        "cutoff_values": list(cutoff_values),
        "correlation_weight": correlation_weight,
        "best_validation_loss": best_validation_loss,
        "history": train_history,
    }


def apply_stage2_model(model: Any, matrix: Any, batch_size: int = 256, device: str | None = None) -> Any:
    import numpy as np
    import torch

    torch_device = choose_torch_device(device)
    model = model.to(torch_device)
    model.eval()
    projected_batches: list[Any] = []
    with torch.no_grad():
        for start in range(0, matrix.shape[0], batch_size):
            stop = min(start + batch_size, matrix.shape[0])
            batch_tensor = torch.tensor(matrix[start:stop], dtype=torch.float32, device=torch_device)
            projected_batches.append(model(batch_tensor).cpu().numpy())
    return np.concatenate(projected_batches, axis=0)


def load_pretrained_stage2_model(
    model_path: Path,
    input_dimension: int,
    hidden_dimensions: tuple[int, int, int] = PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
    output_dimension: int = PUBLISHED_STAGE2_OUTPUT_DIMENSION,
    dropout: float = 0.05,
    device: str | None = None,
) -> tuple[Any, str]:
    import torch

    torch_device = choose_torch_device(device)
    model = build_stage2_network(
        input_dimension,
        hidden_dimensions=hidden_dimensions,
        output_dimension=output_dimension,
        dropout=dropout,
    ).to(torch_device)
    state = torch.load(model_path, map_location=torch_device)
    model.load_state_dict(state)
    model.eval()
    return model, torch_device


def write_stage2_bundle(
    output_dir: Path,
    stage1_bundle: dict[str, Any],
    projected_matrix: Any,
    model: Any,
    training_summary: dict[str, Any],
    hidden_dimensions: tuple[int, int, int],
    output_dimension: int,
    dropout: float,
) -> None:
    import numpy as np
    import torch

    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "vectors.npy", np.asarray(projected_matrix, dtype=np.float32))
    torch.save(model.state_dict(), output_dir / "domain_embedding_model_best.pth")
    write_json(output_dir / "neighbors.json", compute_neighbors(stage1_bundle["ids"], projected_matrix))
    write_json(output_dir / "training.json", training_summary)
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": output_dir.name,
            "model_name": "neuroscape-stage2-local",
            "count": len(stage1_bundle["ids"]),
            "ids": stage1_bundle["ids"],
            "metadata": stage1_bundle["metadata"],
            "source_embedding_name": stage1_bundle["source_metadata"].get("embedding_name"),
            "source_model_name": stage1_bundle["source_metadata"].get("model_name"),
            "embedding_fields": stage1_bundle["source_metadata"].get("embedding_fields"),
            "stage2_config": {
                "hidden_dimensions": list(hidden_dimensions),
                "output_dimension": output_dimension,
                "dropout": dropout,
            },
            "training_summary": {
                "device": training_summary["device"],
                "epochs": training_summary["epochs"],
                "batch_size": training_summary["batch_size"],
                "best_validation_loss": training_summary["best_validation_loss"],
            },
        },
    )


def write_pretrained_stage2_bundle(
    output_dir: Path,
    stage1_bundle: dict[str, Any],
    projected_matrix: Any,
    model_path: Path,
    model_name: str,
    hidden_dimensions: tuple[int, int, int],
    output_dimension: int,
    dropout: float,
) -> None:
    import numpy as np
    import shutil

    output_dir.mkdir(parents=True, exist_ok=True)
    np.save(output_dir / "vectors.npy", np.asarray(projected_matrix, dtype=np.float32))
    shutil.copy2(model_path, output_dir / model_path.name)
    write_json(output_dir / "neighbors.json", compute_neighbors(stage1_bundle["ids"], projected_matrix))
    write_json(
        output_dir / "metadata.json",
        {
            "embedding_name": output_dir.name,
            "model_name": model_name,
            "count": len(stage1_bundle["ids"]),
            "ids": stage1_bundle["ids"],
            "metadata": stage1_bundle["metadata"],
            "source_embedding_name": stage1_bundle["source_metadata"].get("embedding_name"),
            "source_model_name": stage1_bundle["source_metadata"].get("model_name"),
            "embedding_fields": stage1_bundle["source_metadata"].get("embedding_fields"),
            "stage2_config": {
                "hidden_dimensions": list(hidden_dimensions),
                "output_dimension": output_dimension,
                "dropout": dropout,
                "pretrained_model_path": str(model_path),
            },
        },
    )


def load_enriched_lookup(path: Path) -> dict[int, dict[str, Any]]:
    return {
        abstract["id"]: abstract
        for abstract in load_embedding_inputs(path)
        if isinstance(abstract.get("id"), int)
    }


def align_semantic_records(
    ids: list[int],
    enriched_lookup: dict[int, dict[str, Any]],
    title_lookup: dict[int, str] | None = None,
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    selected_fields = normalize_embedding_fields(embedding_fields)
    for abstract_id in ids:
        abstract = enriched_lookup.get(abstract_id, {"id": abstract_id})
        record = dict(abstract)
        record["id"] = abstract_id
        record["title"] = (
            (title_lookup or {}).get(abstract_id)
            or abstract.get("title")
            or ""
        )
        record["cluster_document"] = build_embedding_text(
            record,
            selected_fields,
            title_lookup=title_lookup,
        )
        records.append(record)
    return records


def align_cluster_records(
    ids: list[int],
    enriched_lookup: dict[int, dict[str, Any]],
    title_lookup: dict[int, str] | None = None,
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    return align_semantic_records(
        ids,
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )


def build_knn_graph(ids: list[int], matrix: Any, num_neighbors: int = 50) -> Any:
    import networkx as nx
    from sklearn.neighbors import NearestNeighbors

    if num_neighbors <= 0:
        raise NeuroScapeError("num_neighbors must be positive")
    if len(ids) != int(matrix.shape[0]):
        raise NeuroScapeError("IDs and matrix row count do not match")

    graph = nx.Graph()
    graph.add_nodes_from(int(abstract_id) for abstract_id in ids)
    neighbor_count = min(num_neighbors + 1, int(matrix.shape[0]))
    search = NearestNeighbors(n_neighbors=neighbor_count, metric="cosine", algorithm="brute")
    search.fit(matrix)
    distances, indices = search.kneighbors(matrix)

    for row_index, abstract_id in enumerate(ids):
        for neighbor_index, distance in zip(indices[row_index][1:], distances[row_index][1:]):
            neighbor_id = int(ids[int(neighbor_index)])
            similarity = max(0.0, 1.0 - float(distance))
            if similarity <= 0.0:
                continue
            if graph.has_edge(int(abstract_id), neighbor_id):
                graph[int(abstract_id)][neighbor_id]["weight"] = max(
                    float(graph[int(abstract_id)][neighbor_id]["weight"]),
                    similarity,
                )
            else:
                graph.add_edge(int(abstract_id), neighbor_id, weight=similarity)
    return graph


def detect_semantic_communities(
    graph: Any,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
    min_community_count: int = 1,
) -> dict[str, Any]:
    import numpy as np
    from networkx.algorithms.community import greedy_modularity_communities, modularity

    if num_resolution_parameter <= 0:
        raise NeuroScapeError("num_resolution_parameter must be positive")
    if min_community_count <= 0:
        raise NeuroScapeError("min_community_count must be positive")
    resolution_values = np.linspace(
        max_resolution_parameter / num_resolution_parameter,
        max_resolution_parameter,
        num_resolution_parameter,
    )
    history: list[dict[str, Any]] = []
    best_modularity = float("-inf")
    best_resolution = float(resolution_values[0])
    best_communities: list[set[int]] = []
    best_nontrivial_modularity = float("-inf")
    best_nontrivial_resolution = float(resolution_values[0])
    best_nontrivial_communities: list[set[int]] = []

    for resolution in resolution_values:
        try:
            communities = list(
                greedy_modularity_communities(
                    graph,
                    weight="weight",
                    resolution=float(resolution),
                )
            )
            modularity_value = float(
                modularity(graph, communities, weight="weight", resolution=float(resolution))
            )
        except TypeError:
            communities = list(greedy_modularity_communities(graph, weight="weight"))
            modularity_value = float(modularity(graph, communities, weight="weight"))
        history.append(
            {
                "resolution": float(resolution),
                "modularity": modularity_value,
                "community_count": len(communities),
            }
        )
        if modularity_value > best_modularity:
            best_modularity = modularity_value
            best_resolution = float(resolution)
            best_communities = [set(community) for community in communities]
        if len(communities) >= min_community_count and modularity_value > best_nontrivial_modularity:
            best_nontrivial_modularity = modularity_value
            best_nontrivial_resolution = float(resolution)
            best_nontrivial_communities = [set(community) for community in communities]

    selected_communities = best_nontrivial_communities or best_communities
    selected_modularity = best_nontrivial_modularity if best_nontrivial_communities else best_modularity
    selected_resolution = best_nontrivial_resolution if best_nontrivial_communities else best_resolution

    ordered_communities = sorted(selected_communities, key=lambda community: (-len(community), min(community)))
    assignments: dict[int, int] = {}
    for cluster_id, community in enumerate(ordered_communities):
        for abstract_id in community:
            assignments[int(abstract_id)] = cluster_id

    return {
        "best_resolution": selected_resolution,
        "best_modularity": selected_modularity,
        "history": history,
        "communities": ordered_communities,
        "assignments": assignments,
    }


def detect_semantic_communities_at_resolution(
    graph: Any,
    resolution: float,
) -> dict[str, Any]:
    from networkx.algorithms.community import greedy_modularity_communities, modularity

    if resolution <= 0:
        raise NeuroScapeError("resolution must be positive")
    try:
        communities = list(
            greedy_modularity_communities(
                graph,
                weight="weight",
                resolution=float(resolution),
            )
        )
        modularity_value = float(
            modularity(graph, communities, weight="weight", resolution=float(resolution))
        )
    except TypeError:
        communities = list(greedy_modularity_communities(graph, weight="weight"))
        modularity_value = float(modularity(graph, communities, weight="weight"))

    ordered_communities = sorted(communities, key=lambda community: (-len(community), min(community)))
    assignments: dict[int, int] = {}
    for cluster_id, community in enumerate(ordered_communities):
        for abstract_id in community:
            assignments[int(abstract_id)] = cluster_id

    return {
        "best_resolution": float(resolution),
        "best_modularity": modularity_value,
        "history": [
            {
                "resolution": float(resolution),
                "modularity": modularity_value,
                "community_count": len(ordered_communities),
            }
        ],
        "communities": [set(community) for community in ordered_communities],
        "assignments": assignments,
    }


def detect_stage2_communities(
    graph: Any,
    num_resolution_parameter: int = 20,
    max_resolution_parameter: float = 1.0,
    min_community_count: int = 1,
) -> dict[str, Any]:
    return detect_semantic_communities(
        graph,
        num_resolution_parameter=num_resolution_parameter,
        max_resolution_parameter=max_resolution_parameter,
        min_community_count=min_community_count,
    )


def extract_cluster_keywords(documents: list[str], max_keywords: int = 8) -> list[str]:
    from sklearn.feature_extraction.text import TfidfVectorizer

    filtered_documents = [document for document in documents if document.strip()]
    if not filtered_documents:
        return []
    try:
        vectorizer = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), max_features=5000)
        matrix = vectorizer.fit_transform(filtered_documents)
    except ValueError:
        return []
    scores = matrix.sum(axis=0).A1
    feature_names = vectorizer.get_feature_names_out()
    ranked_indices = scores.argsort()[::-1]
    keywords = [feature_names[index] for index in ranked_indices if scores[index] > 0]
    return keywords[:max_keywords]


def summarize_semantic_clusters(
    ids: list[int],
    matrix: Any,
    records: list[dict[str, Any]],
    assignments: dict[int, int],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> list[dict[str, Any]]:
    import numpy as np

    index_by_id = {int(abstract_id): position for position, abstract_id in enumerate(ids)}
    cluster_members: dict[int, list[int]] = {}
    for abstract_id, cluster_id in assignments.items():
        cluster_members.setdefault(int(cluster_id), []).append(int(abstract_id))

    centroids: dict[int, Any] = {}
    for cluster_id, member_ids in cluster_members.items():
        cluster_matrix = matrix[[index_by_id[member_id] for member_id in member_ids]]
        centroid = cluster_matrix.mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        if centroid_norm:
            centroid = centroid / centroid_norm
        centroids[cluster_id] = centroid

    cluster_ids = sorted(cluster_members)
    centroid_matrix = np.vstack([centroids[cluster_id] for cluster_id in cluster_ids])
    centroid_similarities = centroid_matrix @ centroid_matrix.T
    record_by_id = {int(record["id"]): record for record in records}

    summaries: list[dict[str, Any]] = []
    for cluster_position, cluster_id in enumerate(cluster_ids):
        member_ids = sorted(cluster_members[cluster_id])
        member_indices = [index_by_id[member_id] for member_id in member_ids]
        member_matrix = matrix[member_indices]
        centroid = centroids[cluster_id]
        scores = member_matrix @ centroid
        representative_order = np.argsort(scores)[::-1][:max_representatives]
        representative_ids = [member_ids[index] for index in representative_order]
        documents = [record_by_id[member_id].get("cluster_document", "") for member_id in member_ids]
        keywords = extract_cluster_keywords(documents, max_keywords=max_keywords)
        accepted_for_counts: dict[str, int] = {}
        for member_id in member_ids:
            accepted_for = record_by_id[member_id].get("accepted_for") or "Unknown"
            accepted_for_counts[str(accepted_for)] = accepted_for_counts.get(str(accepted_for), 0) + 1
        similarity_row = centroid_similarities[cluster_position].copy()
        similarity_row[cluster_position] = -1.0
        nearest_cluster_position = int(np.argmax(similarity_row))
        nearest_cluster_id = cluster_ids[nearest_cluster_position]

        summaries.append(
            {
                "cluster_id": cluster_id,
                "size": len(member_ids),
                "label": ", ".join(keywords[:3]) if keywords else f"Cluster {cluster_id}",
                "keywords": keywords,
                "accepted_for_counts": accepted_for_counts,
                "representative_abstracts": [
                    {
                        "id": member_id,
                        "title": record_by_id[member_id].get("title") or "",
                    }
                    for member_id in representative_ids
                ],
                "most_similar_cluster_id": nearest_cluster_id,
                "most_similar_cluster_score": float(similarity_row[nearest_cluster_position]),
            }
        )
    return summaries


def summarize_stage2_clusters(
    ids: list[int],
    matrix: Any,
    records: list[dict[str, Any]],
    assignments: dict[int, int],
    max_keywords: int = 8,
    max_representatives: int = 5,
) -> list[dict[str, Any]]:
    return summarize_semantic_clusters(
        ids,
        matrix,
        records,
        assignments,
        max_keywords=max_keywords,
        max_representatives=max_representatives,
    )


def write_semantic_analysis(
    output_dir: Path,
    graph: Any,
    community_result: dict[str, Any],
    cluster_summaries: list[dict[str, Any]],
) -> None:
    import networkx as nx

    output_dir.mkdir(parents=True, exist_ok=True)
    graphml_graph = nx.relabel_nodes(graph, lambda node: str(node))
    nx.write_graphml(graphml_graph, output_dir / "article_similarity.graphml")
    write_json(
        output_dir / "community_detection.json",
        {
            "best_resolution": community_result["best_resolution"],
            "best_modularity": community_result["best_modularity"],
            "history": community_result["history"],
        },
    )
    write_json(
        output_dir / "cluster_assignments.json",
        {
            "assignments": {
                str(abstract_id): cluster_id
                for abstract_id, cluster_id in sorted(community_result["assignments"].items())
            }
        },
    )
    write_json(output_dir / "cluster_summaries.json", {"clusters": cluster_summaries})


def write_stage2_analysis(
    output_dir: Path,
    graph: Any,
    community_result: dict[str, Any],
    cluster_summaries: list[dict[str, Any]],
) -> None:
    write_semantic_analysis(output_dir, graph, community_result, cluster_summaries)


def build_sentence_transformer_parser(
    description: str,
    default_model: str,
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--title-input", default="data/abstracts.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--output-name")
    parser.add_argument("--fields", nargs="+", default=list(DEFAULT_EMBEDDING_FIELDS))
    parser.add_argument("--local-files-only", action="store_true")
    parser.add_argument("--model", default=default_model)
    return parser


def run_sentence_transformer_embedding(args: argparse.Namespace, output_prefix: str) -> int:
    configure_huggingface_auth(Path(args.env_file))
    abstracts = load_embedding_inputs(Path(args.input))
    embedding_fields = normalize_embedding_fields(args.fields)
    title_lookup = load_title_lookup(Path(args.title_input)) if "title" in embedding_fields else None
    embedding_texts = build_embedding_texts(abstracts, embedding_fields, title_lookup=title_lookup)
    output_name = build_embedding_output_name(
        args.model,
        embedding_fields,
        output_name=args.output_name,
        prefix=output_prefix,
    )
    output_dir = Path(args.embeddings_dir) / output_name
    vectors = sentence_transformer_embed(
        embedding_texts,
        model_name=args.model,
        local_files_only=args.local_files_only,
    )
    bundle = write_embedding_bundle(
        output_dir,
        output_dir.name,
        args.model,
        abstracts,
        vectors,
        embedding_fields=embedding_fields,
    )
    write_json(output_dir / "neighbors.json", compute_neighbors(bundle["ids"], bundle["matrix"]))
    print(
        json.dumps(
            {
                "input": args.input,
                "title_input": args.title_input,
                "embeddings_dir": str(output_dir),
                "model_name": args.model,
                "embedding_fields": embedding_fields,
                "abstract_count": len(abstracts),
                "env_file": args.env_file,
                "local_files_only": args.local_files_only,
            },
            indent=2,
        )
    )
    return 0


def build_minilm_parser() -> argparse.ArgumentParser:
    parser = build_sentence_transformer_parser(
        "Generate local MiniLM embeddings for OHBM 2026 abstracts",
        DEFAULT_MINILM_MODEL,
    )
    parser.add_argument("--minilm-model", dest="model", help=argparse.SUPPRESS)
    return parser


def minilm_main(argv: list[str] | None = None) -> int:
    args = build_minilm_parser().parse_args(argv)
    if args.output_name is None:
        args.output_name = f"minilm_{embedding_variant_name(args.fields)}"
    return run_sentence_transformer_embedding(args, output_prefix="minilm")


def build_hf_parser() -> argparse.ArgumentParser:
    return build_sentence_transformer_parser(
        "Generate local Hugging Face sentence-transformer embeddings for OHBM 2026 abstracts",
        DEFAULT_HF_MODEL,
    )


def hf_main(argv: list[str] | None = None) -> int:
    args = build_hf_parser().parse_args(argv)
    return run_sentence_transformer_embedding(args, output_prefix="hf")


def build_voyage_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate Voyage embeddings for OHBM 2026 abstracts")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--title-input", default="data/abstracts.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--voyage-api-var", default="VOYAGE_API")
    parser.add_argument("--voyage-model", default=DEFAULT_VOYAGE_MODEL)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--fields", nargs="+", default=list(DEFAULT_EMBEDDING_FIELDS))
    return parser


def voyage_main(argv: list[str] | None = None) -> int:
    from ohbm2026.graphql_api import get_api_key

    args = build_voyage_parser().parse_args(argv)
    abstracts = load_embedding_inputs(Path(args.input))
    embedding_fields = normalize_embedding_fields(args.fields)
    title_lookup = load_title_lookup(Path(args.title_input)) if "title" in embedding_fields else None
    embedding_texts = build_embedding_texts(abstracts, embedding_fields, title_lookup=title_lookup)
    output_dir = Path(args.embeddings_dir) / f"voyage_{embedding_variant_name(embedding_fields)}"
    vectors = voyage_embed(
        embedding_texts,
        get_api_key(Path(args.env_file), args.voyage_api_var),
        model=args.voyage_model,
        batch_size=args.batch_size,
    )
    bundle = write_embedding_bundle(
        output_dir,
        output_dir.name,
        args.voyage_model,
        abstracts,
        vectors,
        embedding_fields=embedding_fields,
    )
    write_json(output_dir / "neighbors.json", compute_neighbors(bundle["ids"], bundle["matrix"]))
    print(
        json.dumps(
            {
                "input": args.input,
                "title_input": args.title_input,
                "embeddings_dir": str(output_dir),
                "model_name": args.voyage_model,
                "batch_size": args.batch_size,
                "embedding_fields": embedding_fields,
                "abstract_count": len(abstracts),
            },
            indent=2,
        )
    )
    return 0


def build_openai_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate OpenAI embeddings for OHBM 2026 abstracts")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--title-input", default="data/abstracts.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings")
    parser.add_argument("--env-file", default=".env")
    parser.add_argument("--openai-api-var", default="OPENAI_API_KEY")
    parser.add_argument("--openai-model", default="text-embedding-3-small")
    parser.add_argument("--output-name")
    parser.add_argument("--fields", nargs="+", default=list(DEFAULT_EMBEDDING_FIELDS))
    parser.add_argument("--dimensions", type=int)
    return parser


def openai_main(argv: list[str] | None = None) -> int:
    from ohbm2026.graphql_api import get_api_key

    args = build_openai_parser().parse_args(argv)
    abstracts = load_embedding_inputs(Path(args.input))
    embedding_fields = normalize_embedding_fields(args.fields)
    title_lookup = load_title_lookup(Path(args.title_input)) if "title" in embedding_fields else None
    embedding_texts = build_embedding_texts(abstracts, embedding_fields, title_lookup=title_lookup)
    output_name = build_embedding_output_name(
        args.openai_model,
        embedding_fields,
        output_name=args.output_name,
        prefix="openai",
    )
    output_dir = Path(args.embeddings_dir) / output_name
    vectors = openai_embed(
        embedding_texts,
        get_api_key(Path(args.env_file), args.openai_api_var),
        model=args.openai_model,
        dimensions=args.dimensions,
    )
    bundle = write_embedding_bundle(
        output_dir,
        output_dir.name,
        args.openai_model,
        abstracts,
        vectors,
        embedding_fields=embedding_fields,
    )
    write_json(output_dir / "neighbors.json", compute_neighbors(bundle["ids"], bundle["matrix"]))
    print(
        json.dumps(
            {
                "input": args.input,
                "title_input": args.title_input,
                "embeddings_dir": str(output_dir),
                "model_name": args.openai_model,
                "embedding_fields": embedding_fields,
                "abstract_count": len(abstracts),
                "dimensions": args.dimensions,
            },
            indent=2,
        )
    )
    return 0


def build_stage2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Train and apply a local NeuroScape stage-2 model from an existing stage-1 embedding bundle"
    )
    parser.add_argument("--stage1-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--output-dir", default="data/embeddings/neuroscape_stage2_local")
    parser.add_argument("--device")
    parser.add_argument("--hidden-dimensions", nargs="+", type=int, default=list(DEFAULT_STAGE2_HIDDEN_DIMENSIONS))
    parser.add_argument("--output-dimension", type=int, default=DEFAULT_STAGE2_OUTPUT_DIMENSION)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--validation-size", type=float, default=0.05)
    parser.add_argument("--initial-learning-rate", type=float, default=1e-4)
    parser.add_argument("--minimum-learning-rate", type=float, default=1e-5)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--positive-cutoff", type=float, default=0.85)
    parser.add_argument("--negative-cutoff", type=float, default=0.75)
    parser.add_argument("--correlation-weight", type=float, default=0.1)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--report-every", type=int, default=10)
    return parser


def build_apply_pretrained_stage2_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Apply the published NeuroScape stage-2 model to a compatible stage-1 embedding bundle"
    )
    parser.add_argument("--stage1-dir", default="data/embeddings/voyage_stage1")
    parser.add_argument(
        "--model-path",
        default="/Users/satra/software/repronim/abcd-repronim/data/NeuroScape/Data/Models/domain_embedding_model.pth",
    )
    parser.add_argument("--output-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument("--device")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--dropout", type=float, default=0.05)
    return parser


def apply_pretrained_stage2_main(argv: list[str] | None = None) -> int:
    args = build_apply_pretrained_stage2_parser().parse_args(argv)
    stage1_bundle = load_stage1_bundle(Path(args.stage1_dir))
    matrix = stage1_bundle["matrix"]
    if int(matrix.shape[1]) != 1024:
        raise NeuroScapeError(
            f"Published NeuroScape stage-2 model expects 1024-dimensional stage-1 embeddings; got {int(matrix.shape[1])}"
        )
    model_path = Path(args.model_path)
    model, torch_device = load_pretrained_stage2_model(
        model_path,
        input_dimension=int(matrix.shape[1]),
        hidden_dimensions=PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
        output_dimension=PUBLISHED_STAGE2_OUTPUT_DIMENSION,
        dropout=args.dropout,
        device=args.device,
    )
    projected_matrix = apply_stage2_model(
        model,
        matrix,
        batch_size=args.batch_size,
        device=torch_device,
    )
    write_pretrained_stage2_bundle(
        Path(args.output_dir),
        stage1_bundle,
        projected_matrix,
        model_path=model_path,
        model_name="neuroscape-stage2-published",
        hidden_dimensions=PUBLISHED_STAGE2_HIDDEN_DIMENSIONS,
        output_dimension=PUBLISHED_STAGE2_OUTPUT_DIMENSION,
        dropout=args.dropout,
    )
    print(
        json.dumps(
            {
                "stage1_dir": args.stage1_dir,
                "model_path": str(model_path),
                "output_dir": args.output_dir,
                "count": len(stage1_bundle["ids"]),
                "input_dimension": int(matrix.shape[1]),
                "output_dimension": int(projected_matrix.shape[1]),
                "device": torch_device,
            },
            indent=2,
        )
    )
    return 0


def stage2_main(argv: list[str] | None = None) -> int:
    args = build_stage2_parser().parse_args(argv)
    stage1_bundle = load_stage1_bundle(Path(args.stage1_dir))
    hidden_dimensions = normalize_hidden_dimensions(args.hidden_dimensions)
    model, training_summary = train_stage2_model(
        stage1_bundle["matrix"],
        hidden_dimensions=hidden_dimensions,
        output_dimension=args.output_dimension,
        dropout=args.dropout,
        epochs=args.epochs,
        batch_size=args.batch_size,
        validation_size=args.validation_size,
        initial_learning_rate=args.initial_learning_rate,
        minimum_learning_rate=args.minimum_learning_rate,
        temperature=args.temperature,
        cutoff_values=(args.positive_cutoff, args.negative_cutoff),
        correlation_weight=args.correlation_weight,
        seed=args.seed,
        device=args.device,
        report_every=args.report_every,
    )
    projected_matrix = apply_stage2_model(
        model,
        stage1_bundle["matrix"],
        batch_size=args.batch_size,
        device=training_summary["device"],
    )
    write_stage2_bundle(
        Path(args.output_dir),
        stage1_bundle,
        projected_matrix,
        model,
        training_summary,
        hidden_dimensions=hidden_dimensions,
        output_dimension=args.output_dimension,
        dropout=args.dropout,
    )
    print(
        json.dumps(
            {
                "stage1_dir": args.stage1_dir,
                "output_dir": args.output_dir,
                "count": len(stage1_bundle["ids"]),
                "device": training_summary["device"],
                "best_validation_loss": training_summary["best_validation_loss"],
                "epochs": args.epochs,
            },
            indent=2,
        )
    )
    return 0


def build_cluster_benchmark_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Benchmark label-independent clustering methods over a local embedding bundle"
    )
    parser.add_argument("--embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--title-input", default="data/abstracts.json")
    parser.add_argument("--output-dir", default="data/embeddings/minilm_stage1/clustering_benchmark")
    parser.add_argument(
        "--methods",
        nargs="+",
        default=["kmeans", "agglomerative-ward", "agglomerative-average", "gaussian-mixture", "birch"],
    )
    parser.add_argument("--k-min", type=int, default=2)
    parser.add_argument("--k-max", type=int, default=30)
    parser.set_defaults(row_normalize=True)
    parser.add_argument("--row-normalize", action="store_true", dest="row_normalize")
    parser.add_argument("--no-row-normalize", action="store_false", dest="row_normalize")
    parser.add_argument("--pca-components", type=int, default=50)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--max-keywords", type=int, default=8)
    parser.add_argument("--max-representatives", type=int, default=5)
    return parser


def cluster_benchmark_main(argv: list[str] | None = None) -> int:
    args = build_cluster_benchmark_parser().parse_args(argv)
    if args.k_min < 2:
        raise NeuroScapeError("k-min must be at least 2")
    if args.k_max < args.k_min:
        raise NeuroScapeError("k-max must be greater than or equal to k-min")
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    prepared = prepare_clustering_matrix(
        bundle["matrix"],
        normalize_rows=bool(args.row_normalize),
        pca_components=args.pca_components,
        random_state=args.random_state,
    )
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    title_lookup = load_title_lookup(Path(args.title_input))
    enriched_lookup = load_enriched_lookup(Path(args.input))
    records = align_cluster_records(
        bundle["ids"],
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )
    methods = [str(method).strip().lower() for method in args.methods if str(method).strip()]
    k_values = list(range(int(args.k_min), int(args.k_max) + 1))
    benchmark = run_clustering_benchmark(
        bundle["ids"],
        prepared["matrix"],
        methods=methods,
        k_values=k_values,
        random_state=args.random_state,
    )
    config = {
        "embeddings_dir": args.embeddings_dir,
        "input": args.input,
        "title_input": args.title_input,
        "methods": methods,
        "k_values": k_values,
        "random_state": args.random_state,
        **prepared["metadata"],
    }
    write_clustering_benchmark(
        Path(args.output_dir),
        benchmark,
        bundle["ids"],
        records,
        prepared["matrix"],
        config,
        max_keywords=args.max_keywords,
        max_representatives=args.max_representatives,
    )
    valid_results = [result for result in benchmark["results"] if _valid_benchmark_run(result)]
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "output_dir": args.output_dir,
                "count": len(bundle["ids"]),
                "tested_runs": len(benchmark["results"]),
                "valid_runs": len(valid_results),
                "best_result": benchmark["best_result"],
                "preprocessing": prepared["metadata"],
            },
            indent=2,
        )
    )
    return 0


def build_semantic_analysis_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build a semantic graph, detect communities, and summarize clusters from a local embedding bundle"
    )
    parser.add_argument("--embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--input", default="data/abstracts_enriched.json")
    parser.add_argument("--title-input", default="data/abstracts.json")
    parser.add_argument("--output-dir", default="data/embeddings/minilm_stage1/semantic_analysis")
    parser.add_argument("--num-neighbors", type=int, default=50)
    parser.add_argument("--resolution", type=float)
    parser.add_argument("--num-resolution-parameter", type=int, default=20)
    parser.add_argument("--max-resolution-parameter", type=float, default=1.0)
    parser.add_argument("--min-community-count", type=int, default=1)
    parser.add_argument("--max-keywords", type=int, default=8)
    parser.add_argument("--max-representatives", type=int, default=5)
    return parser


def semantic_analysis_main(argv: list[str] | None = None) -> int:
    args = build_semantic_analysis_parser().parse_args(argv)
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    title_lookup = load_title_lookup(Path(args.title_input))
    enriched_lookup = load_enriched_lookup(Path(args.input))
    records = align_semantic_records(
        bundle["ids"],
        enriched_lookup,
        title_lookup=title_lookup,
        embedding_fields=embedding_fields,
    )
    graph = build_knn_graph(bundle["ids"], bundle["matrix"], num_neighbors=args.num_neighbors)
    if args.resolution is not None:
        community_result = detect_semantic_communities_at_resolution(graph, args.resolution)
    else:
        community_result = detect_semantic_communities(
            graph,
            num_resolution_parameter=args.num_resolution_parameter,
            max_resolution_parameter=args.max_resolution_parameter,
            min_community_count=args.min_community_count,
        )
    cluster_summaries = summarize_semantic_clusters(
        bundle["ids"],
        bundle["matrix"],
        records,
        community_result["assignments"],
        max_keywords=args.max_keywords,
        max_representatives=args.max_representatives,
    )
    write_semantic_analysis(Path(args.output_dir), graph, community_result, cluster_summaries)
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "output_dir": args.output_dir,
                "node_count": len(bundle["ids"]),
                "edge_count": int(graph.number_of_edges()),
                "cluster_count": len(cluster_summaries),
                "best_resolution": community_result["best_resolution"],
                "best_modularity": community_result["best_modularity"],
                "resolution": args.resolution,
                "min_community_count": args.min_community_count,
            },
            indent=2,
        )
    )
    return 0


def build_stage2_analysis_parser() -> argparse.ArgumentParser:
    parser = build_semantic_analysis_parser()
    parser.description = (
        "Compatibility alias for semantic analysis from a local embedding bundle"
    )
    return parser


def stage2_analysis_main(argv: list[str] | None = None) -> int:
    argv = list(argv or [])
    translated_argv: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token == "--stage2-dir":
            translated_argv.append("--embeddings-dir")
        else:
            translated_argv.append(token)
        index += 1
    return semantic_analysis_main(translated_argv)


def _normalize_tsne_learning_rates(values: list[str]) -> list[str | float]:
    normalized: list[str | float] = []
    for value in values:
        text = str(value).strip()
        if not text:
            continue
        if text == "auto":
            normalized.append("auto")
            continue
        try:
            normalized.append(float(text))
        except ValueError as exc:
            raise NeuroScapeError(f"Invalid t-SNE learning rate: {value}") from exc
    if not normalized:
        raise NeuroScapeError("At least one t-SNE learning rate must be provided")
    return normalized


def build_projection_compare_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Write a linked interactive UMAP/t-SNE comparison for a local embedding bundle"
    )
    parser.add_argument("--embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--enriched-input", default="data/abstracts_enriched.json")
    parser.add_argument("--output-html")
    parser.add_argument("--output-json")
    parser.add_argument("--umap-n-neighbors", type=int, default=DEFAULT_UMAP_NEIGHBORS)
    parser.add_argument("--umap-min-dist", type=float, default=DEFAULT_UMAP_MIN_DIST)
    parser.add_argument("--tsne-perplexity", type=float, default=DEFAULT_TSNE_PERPLEXITY)
    parser.add_argument("--tsne-learning-rate", default=str(DEFAULT_TSNE_LEARNING_RATE))
    parser.add_argument("--tsne-early-exaggeration", type=float, default=DEFAULT_TSNE_EARLY_EXAGGERATION)
    parser.add_argument("--metric", default="cosine")
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def projection_compare_main(argv: list[str] | None = None) -> int:
    args = build_projection_compare_parser().parse_args(argv)
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    default_output_html, default_output_json = default_projection_output_paths(
        Path(args.embeddings_dir),
        embedding_fields,
    )
    output_html = Path(args.output_html) if args.output_html else default_output_html
    output_json = Path(args.output_json) if args.output_json else default_output_json
    annotations = load_annotation_lookup(Path(args.raw_input), Path(args.enriched_input))
    records = build_visualization_records(bundle["ids"], annotations)
    umap_coordinates = compute_umap_projection(
        bundle["matrix"],
        n_neighbors=args.umap_n_neighbors,
        min_dist=args.umap_min_dist,
        metric=args.metric,
        random_state=args.random_state,
    )
    tsne_coordinates = compute_tsne_projection(
        bundle["matrix"],
        perplexity=args.tsne_perplexity,
        learning_rate=_normalize_tsne_learning_rates([args.tsne_learning_rate])[0],
        early_exaggeration=args.tsne_early_exaggeration,
        metric=args.metric,
        random_state=args.random_state,
    )
    write_projection_comparison_outputs(
        output_html,
        output_json,
        umap_coordinates,
        tsne_coordinates,
        records,
        title=build_embedding_visualization_title(bundle, "OHBM 2026 Projection Comparison"),
    )
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "raw_input": args.raw_input,
                "enriched_input": args.enriched_input,
                "output_html": str(output_html),
                "output_json": str(output_json),
                "count": len(records),
                "umap_n_neighbors": args.umap_n_neighbors,
                "umap_min_dist": args.umap_min_dist,
                "tsne_perplexity": args.tsne_perplexity,
                "tsne_learning_rate": args.tsne_learning_rate,
                "tsne_early_exaggeration": args.tsne_early_exaggeration,
                "metric": args.metric,
            },
            indent=2,
        )
    )
    return 0


def build_projection_optimize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Search UMAP and t-SNE parameter sets for more separable projection clusters"
    )
    parser.add_argument("--embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--output", help="Optional JSON output path for scored parameter sets")
    parser.add_argument("--umap-neighbors", nargs="+", type=int, default=[10, 30])
    parser.add_argument("--umap-min-dists", nargs="+", type=float, default=[0.0, 0.25])
    parser.add_argument("--tsne-perplexities", nargs="+", type=float, default=[20.0, 40.0])
    parser.add_argument("--tsne-early-exaggerations", nargs="+", type=float, default=[8.0, 12.0])
    parser.add_argument("--tsne-learning-rates", nargs="+", default=["auto"])
    parser.add_argument("--metric", default="cosine")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--graph-neighbors", type=int, default=15)
    parser.add_argument("--num-resolution-parameter", type=int, default=20)
    parser.add_argument("--max-resolution-parameter", type=float, default=1.0)
    parser.add_argument("--top-k", type=int, default=5)
    return parser


def projection_optimize_main(argv: list[str] | None = None) -> int:
    args = build_projection_optimize_parser().parse_args(argv)
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    optimization = optimize_projection_parameters(
        bundle["ids"],
        bundle["matrix"],
        umap_neighbors=[int(value) for value in args.umap_neighbors],
        umap_min_dists=[float(value) for value in args.umap_min_dists],
        tsne_perplexities=[float(value) for value in args.tsne_perplexities],
        tsne_early_exaggerations=[float(value) for value in args.tsne_early_exaggerations],
        tsne_learning_rates=_normalize_tsne_learning_rates(list(args.tsne_learning_rates)),
        metric=args.metric,
        random_state=args.random_state,
        graph_neighbors=args.graph_neighbors,
        num_resolution_parameter=args.num_resolution_parameter,
        max_resolution_parameter=args.max_resolution_parameter,
    )
    if args.output:
        write_json(Path(args.output), optimization)
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "best_overall": optimization["best_overall"],
                "best_by_method": optimization["best_by_method"],
                "top_results": optimization["results"][: max(1, int(args.top_k))],
                "output": args.output,
            },
            indent=2,
        )
    )
    return 0


def build_umap_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Project a local embedding bundle to 2D with UMAP and write an interactive Plotly HTML"
    )
    parser.add_argument("--embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--raw-input", default="data/abstracts.json")
    parser.add_argument("--enriched-input", default="data/abstracts_enriched.json")
    parser.add_argument("--output-html")
    parser.add_argument("--output-json")
    parser.add_argument("--n-neighbors", type=int, default=DEFAULT_UMAP_NEIGHBORS)
    parser.add_argument("--min-dist", type=float, default=DEFAULT_UMAP_MIN_DIST)
    parser.add_argument("--metric", default="cosine")
    parser.add_argument("--random-state", type=int, default=42)
    return parser


def umap_main(argv: list[str] | None = None) -> int:
    args = build_umap_parser().parse_args(argv)
    bundle = load_embedding_bundle(Path(args.embeddings_dir))
    embedding_fields = normalize_embedding_fields(bundle["source_metadata"].get("embedding_fields"))
    default_output_html, default_output_json = default_umap_output_paths(
        Path(args.embeddings_dir),
        embedding_fields,
    )
    output_html = Path(args.output_html) if args.output_html else default_output_html
    output_json = Path(args.output_json) if args.output_json else default_output_json
    annotations = load_annotation_lookup(Path(args.raw_input), Path(args.enriched_input))
    records = build_visualization_records(bundle["ids"], annotations)
    coordinates = compute_umap_projection(
        bundle["matrix"],
        n_neighbors=args.n_neighbors,
        min_dist=args.min_dist,
        metric=args.metric,
        random_state=args.random_state,
    )
    write_umap_outputs(
        output_html,
        output_json,
        coordinates,
        records,
        title=build_embedding_visualization_title(bundle, "OHBM 2026 Abstract Embeddings UMAP"),
    )
    print(
        json.dumps(
            {
                "embeddings_dir": args.embeddings_dir,
                "raw_input": args.raw_input,
                "enriched_input": args.enriched_input,
                "output_html": str(output_html),
                "output_json": str(output_json),
                "count": len(records),
                "n_neighbors": args.n_neighbors,
                "min_dist": args.min_dist,
                "metric": args.metric,
            },
            indent=2,
        )
    )
    return 0


def build_manifest_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Write the NeuroScape handoff manifest for OHBM 2026 embeddings")
    parser.add_argument("--output", default="data/embeddings/neuroscape_stage2_manifest.json")
    return parser


def manifest_main(argv: list[str] | None = None) -> int:
    args = build_manifest_parser().parse_args(argv)
    write_neuroscape_manifest(Path(args.output))
    print(json.dumps({"output": args.output}, indent=2))
    return 0
