"""Stage 4 storage helpers and embedding-bundle I/O.

Owns the I/O surface that the rest of the `analyze/` package — and
downstream consumers in `ui.py`, `poster_layout.py`,
`category_evaluation.py`, and the `scripts/` directory — rely on:

- JSON readers/writers (`write_json`, `parse_string_list_value`,
  `unique_strings`).
- Embedding-text shaping helpers (`build_embedding_text`,
  `build_claim_embedding_text`, `normalize_embedding_fields`,
  `embedding_variant_name`, `model_name_slug`,
  `build_embedding_output_name`).
- Per-record bundle writers (`write_embedding_bundle`,
  `write_analysis_bundle`) and atomic-rename iter helper
  (`iter_analysis_bundles`).
- Bundle loaders (`load_embedding_bundle`, `load_stage1_bundle`,
  `load_embedding_inputs`, `load_title_lookup`,
  `load_annotation_lookup`).
- Misc helpers (`compute_neighbors`, `build_visualization_records`,
  `build_distinct_color_map`, `build_embedding_visualization_title`,
  `extract_primary_topic`, `extract_raw_keywords`,
  `configure_huggingface_auth`).

All function bodies were lifted verbatim from the old monolithic
`analyze.py` to keep the SC-007 invariant intact (test suite stays
green; only import-path rewrites change).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

from ohbm2026.fetch.graphql_api import chunked, load_dotenv
from ohbm2026.titles import cleaned_abstract_title

DEFAULT_VOYAGE_MODEL = "voyage-large-2-instruct"
DEFAULT_MINILM_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_HF_MODEL = DEFAULT_MINILM_MODEL
DEFAULT_EMBEDDING_FIELDS = ("title", "introduction", "methods", "results", "conclusion")
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


def extract_primary_topic(abstract: dict[str, Any]) -> str:
    for response in abstract.get("responses", []):
        if str(response.get("question_name") or "").strip().lower() == "primary parent category & sub-category":
            values = parse_string_list_value(response.get("value"))
            if values:
                return values[0]
    return "Unknown"


def load_embedding_inputs(path: Path) -> list[dict[str, Any]]:
    database = json.loads(path.read_text(encoding="utf-8"))
    return database.get("abstracts", [])


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


def write_embedding_bundle(
    output_dir: Path,
    embedding_name: str,
    model_name: str,
    abstracts: list[dict[str, Any]],
    vectors: list[list[float]],
    embedding_fields: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
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


def compute_neighbors(ids: list[int], matrix: Any, top_k: int = 10, bottom_k: int = 5) -> dict[str, Any]:
    import numpy as np

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    normalized = matrix / norms
    similarities = normalized @ normalized.T
    neighbors: dict[str, list[dict[str, float]]] = {}
    distant: dict[str, list[dict[str, float]]] = {}
    for index, abstract_id in enumerate(ids):
        row = similarities[index].copy()
        row[index] = -1.0
        neighbor_indices = np.argsort(row)[-top_k:][::-1]
        neighbors[str(abstract_id)] = [
            {"id": int(ids[ni]), "score": float(row[ni])}
            for ni in neighbor_indices
        ]
        if bottom_k > 0:
            row[index] = 2.0  # exclude self from bottom-k (cosine sim max is 1.0)
            distant_indices = np.argsort(row)[:bottom_k]
            distant[str(abstract_id)] = [
                {"id": int(ids[di]), "score": float(row[di])}
                for di in distant_indices
            ]
    result: dict[str, Any] = {"top_k": top_k, "neighbors": neighbors}
    if bottom_k > 0:
        result["bottom_k"] = bottom_k
        result["distant"] = distant
    return result


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


def build_distinct_color_map(values: list[str]) -> dict[str, str]:
    unique_values = sorted({value for value in values if value})
    if not unique_values:
        return {}
    total = len(unique_values)
    return {
        value: f"hsl({int((index * 360) / total)}, 70%, 45%)"
        for index, value in enumerate(unique_values)
    }



# ---------------------------------------------------------------------------
# Stage 4 — new bundle + cache I/O surface
# ---------------------------------------------------------------------------


def write_analysis_bundle(
    bundle_dir: Path,
    *,
    ids: np.ndarray,
    payload: dict[str, np.ndarray],
    metadata: dict[str, Any],
    provenance: dict[str, Any],
    topics: dict[int, dict[str, Any]] | None = None,
) -> Path:
    """Write a Stage 4 analysis bundle atomically.

    Layout:
        <bundle_dir>/
            ids.npy
            <payload key>.npy   (one per entry in `payload`)
            topics.json         (only when `topics is not None`)
            metadata.json
            provenance.json

    The bundle is materialized inside a sibling temp directory and
    renamed into place once every file lands successfully, so
    concurrent readers never observe a partially-written bundle.
    """
    bundle_dir = Path(bundle_dir)
    parent = bundle_dir.parent
    parent.mkdir(parents=True, exist_ok=True)

    if not isinstance(ids, np.ndarray):
        raise TypeError(f"ids must be np.ndarray, got {type(ids).__name__}")
    for key, arr in payload.items():
        if not isinstance(arr, np.ndarray):
            raise TypeError(
                f"payload[{key!r}] must be np.ndarray, got {type(arr).__name__}"
            )
        if arr.shape[0] != ids.shape[0]:
            raise ValueError(
                f"payload[{key!r}] has shape {arr.shape}; expected leading dim {ids.shape[0]}"
            )

    with tempfile.TemporaryDirectory(
        prefix=f".{bundle_dir.name}__tmp_", dir=parent
    ) as tmp_root_str:
        tmp_root = Path(tmp_root_str)
        np.save(tmp_root / "ids.npy", ids)
        for key, arr in payload.items():
            np.save(tmp_root / f"{key}.npy", arr)
        if topics is not None:
            (tmp_root / "topics.json").write_text(
                json.dumps(
                    {str(k): v for k, v in topics.items()},
                    indent=2,
                    sort_keys=True,
                ),
                encoding="utf-8",
            )
        (tmp_root / "metadata.json").write_text(
            json.dumps(metadata, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        (tmp_root / "provenance.json").write_text(
            json.dumps(provenance, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        if bundle_dir.exists():
            shutil.rmtree(bundle_dir)
        tmp_root.replace(bundle_dir)
    return bundle_dir


def iter_analysis_bundles(
    output_root: Path,
    *,
    kinds: Iterable[str] | None = None,
) -> Iterable[Path]:
    """Yield every analysis bundle directory under `output_root`.

    Walks the canonical layout
    `data/outputs/analysis/<input_key>/<kind>__<state-key>/`. When
    `kinds` is provided, restricts to bundles whose directory name
    starts with one of the requested kinds. Skips dotfiles and
    `.prev` rollback directories.
    """
    if not output_root.exists():
        return
    kind_set: set[str] | None = set(kinds) if kinds else None
    for input_dir in sorted(output_root.iterdir()):
        if not input_dir.is_dir() or input_dir.name.startswith("."):
            continue
        for bundle_dir in sorted(input_dir.iterdir()):
            if not bundle_dir.is_dir() or bundle_dir.name.startswith("."):
                continue
            if bundle_dir.name.endswith(".prev"):
                continue
            if kind_set is not None:
                kind_prefix = bundle_dir.name.split("__", 1)[0]
                if kind_prefix not in kind_set:
                    continue
            yield bundle_dir
