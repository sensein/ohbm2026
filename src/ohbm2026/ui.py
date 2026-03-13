from __future__ import annotations

import argparse
import json
import re
import shutil
from collections import Counter
from datetime import UTC, datetime
from html import escape
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026.neuroscape import parse_string_list_value
from ohbm2026.titles import cleaned_abstract_title

DEFAULT_RAW_INPUT = "data/abstracts.json"
DEFAULT_ENRICHED_INPUT = "data/abstracts_enriched.json"
DEFAULT_REFERENCES_INPUT = "data/reference_metadata.json"
DEFAULT_IMAGE_ANALYSES_INPUT = "data/image_analyses_openai.json"
DEFAULT_NEIGHBORS_INPUT = "data/embeddings/voyage_stage2_published/neighbors.json"
DEFAULT_CLUSTER_15_DIR = "data/embeddings/voyage_stage2_published/semantic_analysis_15-communities"
DEFAULT_CLUSTER_21_DIR = "data/embeddings/voyage_stage2_published/semantic_analysis_21-communities"
DEFAULT_CLUSTER_25_DIR = "data/embeddings/voyage_stage2_published/clustering_benchmark"
DEFAULT_CLAIMS_CLUSTER_DIR = "data/embeddings/minilm_claims/clustering_benchmark_25_30"
DEFAULT_SEMANTIC_VECTORS_INPUT = "data/embeddings/minilm_stage1/vectors.npy"
DEFAULT_SEMANTIC_METADATA_INPUT = "data/embeddings/minilm_stage1/metadata.json"
DEFAULT_UMAP_INPUT = "data/embeddings/minilm_stage1/umap_title-introduction-methods-results-conclusion.json"
DEFAULT_EXPORT_OUTPUT = "export/ui-site/data"
DEFAULT_SITE_SOURCE = "ui"
DEFAULT_SITE_OUTPUT = "export/ui-site"

SECTION_FIELDS = (
    ("introduction_markdown", "Introduction"),
    ("methods_markdown", "Methods"),
    ("results_markdown", "Results"),
    ("conclusion_markdown", "Conclusion"),
    ("references_markdown", "References"),
    ("acknowledgement_markdown", "Acknowledgement"),
    ("additional_content_questions_markdown", "Additional Content"),
)
FACET_GROUPS = (
    "accepted_for",
    "semantic_25",
    "claims_28",
    "primary_topic",
    "secondary_topic",
    "keywords",
    "methods",
    "study_type",
    "population",
    "field_strength",
    "processing_packages",
    "species",
    "recording_technology",
    "brain_regions",
    "brain_networks",
)
QUESTION_MAP = {
    "methods": "Please indicate which methods were used in your research:",
    "study_type": 'Please indicate below if your study was a "resting state" or "task-activation” study.',
    "population": "Healthy subjects only or patients (note that patient studies may also involve healthy subjects).",
    "field_strength": "For human MRI, what field strength scanner do you use?",
    "processing_packages": "Which processing packages did you use for your study?",
}
PRIMARY_TOPIC_QUESTION = "Primary Parent Category & Sub-Category"
SECONDARY_TOPIC_QUESTION = "Secondary Parent Category & Sub-Category"
BROWSER_SEMANTIC_MODEL = "Xenova/all-MiniLM-L6-v2"
SEMANTIC_VECTOR_FILENAME = "semantic.vectors.f32"
SPECIES_PATTERNS = {
    "Human": (r"\bhuman(s)?\b", r"\bparticipant(s)?\b", r"\bpatient(s)?\b", r"\bhealthy subject(s)?\b"),
    "Mouse": (r"\bmouse\b", r"\bmice\b", r"\bmus musculus\b"),
    "Rat": (r"\brat(s)?\b", r"\brattus\b"),
    "Macaque": (r"\bmacaque(s)?\b", r"\bmonkey\b", r"\bnon-?human primate(s)?\b"),
    "Marmoset": (r"\bmarmoset(s)?\b",),
    "Zebrafish": (r"\bzebrafish\b",),
}
RECORDING_TECH_PATTERNS = {
    "fMRI": (r"\bfmri\b", r"\bbold\b"),
    "Structural MRI": (r"\bstructural mri\b", r"\bt1w?\b", r"\bt2w?\b"),
    "Diffusion MRI": (r"\bdiffusion mri\b", r"\bdti\b", r"\bdwi\b"),
    "EEG": (r"\beeg\b", r"\belectroencephalograph", r"\bscalp eeg\b"),
    "MEG": (r"\bmeg\b", r"\bmagnetoencephalograph"),
    "ECoG": (r"\becog\b", r"\belectrocorticograph"),
    "PET": (r"\bpet\b", r"\bpositron emission tomography\b"),
    "fNIRS": (r"\bfnirs\b", r"\bfunctional near infrared spectroscopy\b"),
    "MRS": (r"\bmrs\b", r"\bmagnetic resonance spectroscopy\b"),
    "TMS": (r"\btms\b", r"\btranscranial magnetic stimulation\b", r"\btheta burst stimulation\b", r"\btbs\b"),
    "tDCS/tES": (r"\btdcs\b", r"\btes\b", r"\btranscranial electrical stimulation\b"),
    "DBS": (r"\bdbs\b", r"\bdeep brain stimulation\b"),
    "Calcium Imaging": (r"\bcalcium imaging\b", r"\bgcamp\b"),
    "Electrophysiology": (r"\belectrophysiolog", r"\bspike(s)?\b", r"\blfp\b", r"\bsingle-unit\b", r"\bmulti-unit\b"),
}
BRAIN_REGION_PATTERNS = {
    "Amygdala": (r"\bamygdala\b",),
    "Hippocampus": (r"\bhippocamp",),
    "Thalamus": (r"\bthalam",),
    "Cerebellum": (r"\bcerebell",),
    "Striatum": (r"\bstriat", r"\bcaudate\b", r"\bputamen\b", r"\bnucleus accumbens\b"),
    "Basal Ganglia": (r"\bbasal ganglia\b", r"\bglobus pallidus\b", r"\bsubthalamic nucleus\b"),
    "Prefrontal Cortex": (r"\bprefrontal cortex\b", r"\bpfc\b", r"\bdlpfc\b", r"\bvm?pfc\b", r"\bfrontopolar\b", r"\bofc\b"),
    "Anterior Cingulate Cortex": (r"\banterior cingulate\b", r"\bacc\b"),
    "Posterior Cingulate Cortex": (r"\bposterior cingulate\b", r"\bpcc\b"),
    "Insula": (r"\binsula\b", r"\binsular\b"),
    "Motor Cortex": (r"\bmotor cortex\b", r"\bm1\b", r"\bpremotor\b", r"\bsma\b", r"\bsupplementary motor area\b"),
    "Visual Cortex": (r"\bvisual cortex\b", r"\bv1\b", r"\boccipital cortex\b"),
    "Somatosensory Cortex": (r"\bsomatosensory cortex\b", r"\bs1\b"),
    "Temporal Cortex": (r"\btemporal cortex\b", r"\btemporal lobe\b", r"\bsuperior temporal\b"),
    "Parietal Cortex": (r"\bparietal cortex\b", r"\bparietal lobe\b", r"\bintraparietal\b"),
    "Occipital Cortex": (r"\boccipital cortex\b", r"\boccipital lobe\b"),
    "Brainstem": (r"\bbrainstem\b", r"\bmidbrain\b", r"\bpons\b", r"\bmedulla\b"),
}
BRAIN_NETWORK_PATTERNS = {
    "Default Mode Network": (r"\bdefault mode network\b", r"\bdmn\b"),
    "Salience Network": (r"\bsalience network\b"),
    "Frontoparietal Network": (r"\bfrontoparietal network\b", r"\bexecutive control network\b", r"\bcontrol network\b"),
    "Dorsal Attention Network": (r"\bdorsal attention network\b", r"\bdan\b"),
    "Ventral Attention Network": (r"\bventral attention network\b", r"\bvan\b"),
    "Visual Network": (r"\bvisual network\b"),
    "Sensorimotor Network": (r"\bsensorimotor network\b", r"\bmotor network\b"),
    "Limbic Network": (r"\blimbic network\b"),
}


class UIBuildError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def question_lookup(abstract: dict[str, Any]) -> dict[str, Any]:
    return {
        str(response.get("question_name") or ""): response.get("value")
        for response in abstract.get("responses", [])
    }


def topic_pair_from_questions(questions: dict[str, Any], question_name: str) -> list[str]:
    return parse_string_list_value(questions.get(question_name))


def topic_parent(topic_values: list[str]) -> str:
    return topic_values[0] if topic_values else "Unknown"


def topic_subcategory(topic_values: list[str]) -> str:
    if len(topic_values) >= 2:
        return topic_values[1]
    if topic_values:
        return topic_values[0]
    return "Unknown"


def primary_topic_from_questions(questions: dict[str, Any]) -> str:
    return topic_parent(topic_pair_from_questions(questions, PRIMARY_TOPIC_QUESTION))


def secondary_topic_from_questions(questions: dict[str, Any]) -> str:
    primary_values = topic_pair_from_questions(questions, PRIMARY_TOPIC_QUESTION)
    if primary_values:
        return topic_subcategory(primary_values)
    return topic_subcategory(topic_pair_from_questions(questions, SECONDARY_TOPIC_QUESTION))


def topic_subcategories_from_questions(questions: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for question_name in (PRIMARY_TOPIC_QUESTION, SECONDARY_TOPIC_QUESTION):
        topic_values = topic_pair_from_questions(questions, question_name)
        subcategory = topic_subcategory(topic_values)
        if subcategory == "Unknown" or subcategory in values:
            continue
        values.append(subcategory)
    return values


def markdown_to_plain_text(text: str | None) -> str:
    value = str(text or "")
    value = re.sub(r"`([^`]+)`", r"\1", value)
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", value)
    value = value.replace("**", "").replace("*", "").replace("_", "")
    value = re.sub(r"^#+\s*", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*[-*]\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"^\s*\d+\.\s+", "", value, flags=re.MULTILINE)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def markdown_to_html(text: str | None) -> str:
    value = escape(str(text or "").strip())
    if not value:
        return ""
    value = re.sub(r"\[(.*?)\]\((.*?)\)", r'<a href="\2" target="_blank" rel="noreferrer">\1</a>', value)
    value = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", value)
    value = re.sub(r"\*(.*?)\*", r"<em>\1</em>", value)
    lines = value.splitlines()
    blocks: list[str] = []
    list_buffer: list[str] = []

    def flush_list() -> None:
        nonlocal list_buffer
        if list_buffer:
            blocks.append("<ul>" + "".join(f"<li>{item}</li>" for item in list_buffer) + "</ul>")
            list_buffer = []

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            flush_list()
            continue
        if line.startswith("#### "):
            flush_list()
            blocks.append(f"<h5>{line[5:]}</h5>")
            continue
        if line.startswith("### "):
            flush_list()
            blocks.append(f"<h4>{line[4:]}</h4>")
            continue
        if line.startswith("## "):
            flush_list()
            blocks.append(f"<h3>{line[3:]}</h3>")
            continue
        if line.startswith("- "):
            list_buffer.append(line[2:])
            continue
        if re.match(r"^\d+\.\s+", line):
            list_buffer.append(re.sub(r"^\d+\.\s+", "", line))
            continue
        flush_list()
        blocks.append(f"<p>{line}</p>")
    flush_list()
    return "\n".join(blocks)


def render_additional_content_markdown(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            question_name = str(item.get("question_name") or "").strip()
            markdown = str(item.get("markdown") or "").strip()
            if not markdown:
                continue
            if question_name:
                parts.append(f"### {question_name}\n\n{markdown}")
            else:
                parts.append(markdown)
        return "\n\n".join(parts).strip()
    return ""


def simplify_image_analysis(record: dict[str, Any]) -> dict[str, Any]:
    analysis = record.get("analysis") or {}
    rich_markdown = analysis.get("rich_markdown") or analysis.get("notes") or ""
    return {
        "question_name": record.get("question_name") or "",
        "caption_guess": analysis.get("caption_guess") or "",
        "notes": analysis.get("notes") or "",
        "ocr_text": analysis.get("ocr_text") or "",
        "rich_html": markdown_to_html(rich_markdown),
        "keywords": list(analysis.get("keywords") or []),
    }


def figure_note_sort_key(record: dict[str, Any]) -> tuple[int, str]:
    question_name = str(record.get("question_name") or "").strip()
    normalized = question_name.lower()
    if "methods" in normalized and "figure" in normalized:
        group = 0
    elif "results" in normalized and "figure" in normalized:
        group = 1
    else:
        group = 2
    return (group, question_name)


def order_figure_notes(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(list(records), key=figure_note_sort_key)


def build_figure_text_blob(enriched_abstract: dict[str, Any]) -> str:
    parts: list[str] = []
    for record in order_figure_notes(enriched_abstract.get("figure_analyses", []) or []):
        analysis = record.get("analysis") or {}
        for value in (
            analysis.get("caption_guess"),
            analysis.get("notes"),
            analysis.get("ocr_text"),
        ):
            text = str(value or "").strip()
            if text:
                parts.append(text)
        rich_markdown = str(analysis.get("rich_markdown") or "").strip()
        if rich_markdown:
            parts.append(markdown_to_plain_text(rich_markdown))
        keywords = [str(keyword).strip() for keyword in analysis.get("keywords", []) if str(keyword).strip()]
        if keywords:
            parts.append(" ".join(keywords))
    return "\n".join(part for part in parts if part)


def load_image_analysis_lookup(path: Path) -> dict[int, list[dict[str, Any]]]:
    if not path.exists():
        return {}
    analyses = load_json(path).get("analyses") or {}
    lookup: dict[int, list[dict[str, Any]]] = {}
    for record in analyses.values():
        abstract_id = int(record.get("abstract_id"))
        lookup.setdefault(abstract_id, []).append(simplify_image_analysis(record))
    for abstract_id, items in lookup.items():
        lookup[abstract_id] = order_figure_notes(items)
    return lookup


def load_reference_lookup(path: Path) -> dict[int, dict[str, Any]]:
    data = load_json(path)
    reference_map = {
        item["reference_key"]: item
        for item in data.get("references", [])
    }
    lookup: dict[int, dict[str, Any]] = {}
    for abstract in data.get("abstracts", []):
        matched_items: list[dict[str, Any]] = []
        unmatched_items: list[dict[str, Any]] = []
        for ref in abstract.get("references", []):
            ref_data = reference_map.get(ref.get("reference_key") or "")
            if ref.get("matched") and ref_data and ref_data.get("openalex"):
                openalex = ref_data["openalex"]
                matched_items.append(
                    {
                        "title": openalex.get("display_name") or ref_data.get("title_guess") or "",
                        "journal": openalex.get("journal") or "",
                        "year": openalex.get("publication_year"),
                        "cited_by_count": openalex.get("cited_by_count"),
                        "doi": openalex.get("doi"),
                        "openalex_id": openalex.get("openalex_id"),
                    }
                )
            else:
                unmatched_items.append(
                    {
                        "title": ref_data.get("title_guess") or ref.get("title_guess") or "",
                        "raw_text": ref_data.get("raw_text") or ref.get("raw_text") or "",
                    }
                )
        lookup[int(abstract["id"])] = {
            "matched_count": len(matched_items),
            "unmatched_count": len(unmatched_items),
            "items": matched_items[:10],
            "unmatched_items": unmatched_items[:10],
        }
    return lookup


def load_neighbors(path: Path, top_k: int) -> dict[int, list[dict[str, Any]]]:
    data = load_json(path)
    return {
        int(abstract_id): list(entries[:top_k])
        for abstract_id, entries in (data.get("neighbors") or {}).items()
    }


def load_cluster_partition(path: Path, key: str) -> dict[str, Any]:
    assignments = load_json(path / "cluster_assignments.json").get("assignments") or {}
    clusters = load_json(path / "cluster_summaries.json").get("clusters") or []
    return {
        "key": key,
        "assignments": {int(abstract_id): int(cluster_id) for abstract_id, cluster_id in assignments.items()},
        "clusters": {
            int(cluster["cluster_id"]): {
                "cluster_id": int(cluster["cluster_id"]),
                "label": cluster.get("label") or "",
                "size": int(cluster.get("size") or 0),
                "keywords": list(cluster.get("keywords") or []),
                "accepted_for_counts": cluster.get("accepted_for_counts") or {},
                "most_similar_cluster_id": cluster.get("most_similar_cluster_id"),
                "most_similar_cluster_score": cluster.get("most_similar_cluster_score"),
                "representative_abstracts": list(cluster.get("representative_abstracts") or []),
            }
            for cluster in clusters
        },
    }


def normalize_cluster_value(cluster_id: int | None, partition: dict[str, Any]) -> str:
    if cluster_id is None:
        return "Unknown"
    cluster = partition["clusters"].get(cluster_id)
    if not cluster:
        return f"Cluster {cluster_id}"
    label = cluster.get("label") or f"Cluster {cluster_id}"
    return f"{cluster_id}: {label}"


def load_umap_projection(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    data = load_json(path)
    points = []
    for point in data.get("points") or []:
        points.append(
            {
                "id": int(point["id"]),
                "title": cleaned_abstract_title(point.get("title")),
                "accepted_for": point.get("accepted_for") or "",
                "primary_topic": point.get("primary_topic") or "",
                "keywords": list(point.get("keywords") or []),
                "x": float(point["x"]),
                "y": float(point["y"]),
            }
        )
    return {
        "title": data.get("title") or "UMAP projection",
        "count": len(points),
        "points": points,
    }


def find_pattern_matches(text: str, pattern_map: dict[str, tuple[str, ...]]) -> list[str]:
    matches: list[str] = []
    for label, patterns in pattern_map.items():
        if isinstance(patterns, str):
            patterns = (patterns,)
        if any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns):
            matches.append(label)
    return matches


def build_domain_facets(raw_abstract: dict[str, Any], enriched_abstract: dict[str, Any], metadata: dict[str, Any]) -> dict[str, list[str]]:
    figure_text = build_figure_text_blob(enriched_abstract)
    text = "\n".join(
        part
        for part in (
            cleaned_abstract_title(raw_abstract.get("title")),
            enriched_abstract.get("methods_markdown") or "",
            enriched_abstract.get("results_markdown") or "",
            render_additional_content_markdown(enriched_abstract.get("additional_content_questions_markdown")),
            figure_text,
            " ".join(metadata.get("keywords") or []),
            " ".join(metadata.get("methods") or []),
        )
        if part
    )
    return {
        "species": find_pattern_matches(text, SPECIES_PATTERNS),
        "recording_technology": find_pattern_matches(text, RECORDING_TECH_PATTERNS),
        "brain_regions": find_pattern_matches(text, BRAIN_REGION_PATTERNS),
        "brain_networks": find_pattern_matches(text, BRAIN_NETWORK_PATTERNS),
    }


def build_metadata(raw_abstract: dict[str, Any], enriched_abstract: dict[str, Any], partitions: dict[str, Any]) -> dict[str, Any]:
    questions = question_lookup(raw_abstract)
    metadata = {
        "accepted_for": raw_abstract.get("accepted_for") or "Unknown",
        "primary_topic": primary_topic_from_questions(questions),
        "secondary_topic": secondary_topic_from_questions(questions),
        "secondary_topic_facets": topic_subcategories_from_questions(questions),
        "keywords": parse_string_list_value(questions.get("Keywords")),
        "figure_keywords": list(enriched_abstract.get("figure_keywords") or []),
        "methods": parse_string_list_value(questions.get(QUESTION_MAP["methods"])),
        "study_type": parse_string_list_value(questions.get(QUESTION_MAP["study_type"])),
        "population": parse_string_list_value(questions.get(QUESTION_MAP["population"])),
        "field_strength": parse_string_list_value(questions.get(QUESTION_MAP["field_strength"])),
        "processing_packages": parse_string_list_value(questions.get(QUESTION_MAP["processing_packages"])),
    }
    abstract_id = int(raw_abstract["id"])
    metadata["semantic_25"] = [
        normalize_cluster_value(partitions["semantic_25"]["assignments"].get(abstract_id), partitions["semantic_25"])
    ]
    metadata["claims_28"] = [
        normalize_cluster_value(partitions["claims_28"]["assignments"].get(abstract_id), partitions["claims_28"])
    ]
    return metadata


def build_search_blob(raw_abstract: dict[str, Any], enriched_abstract: dict[str, Any], metadata: dict[str, Any]) -> str:
    figure_text = build_figure_text_blob(enriched_abstract)
    parts = [
        cleaned_abstract_title(raw_abstract.get("title")),
        enriched_abstract.get("introduction_markdown") or "",
        enriched_abstract.get("methods_markdown") or "",
        enriched_abstract.get("results_markdown") or "",
        enriched_abstract.get("conclusion_markdown") or "",
        render_additional_content_markdown(enriched_abstract.get("additional_content_questions_markdown")),
        figure_text,
        " ".join(metadata.get("keywords") or []),
        " ".join(metadata.get("figure_keywords") or []),
        metadata.get("primary_topic") or "",
        " ".join(metadata.get("secondary_topic_facets") or [metadata.get("secondary_topic") or ""]),
        " ".join(metadata.get("methods") or []),
        " ".join(metadata.get("study_type") or []),
        " ".join(metadata.get("population") or []),
        " ".join(metadata.get("field_strength") or []),
        " ".join(metadata.get("processing_packages") or []),
    ]
    return markdown_to_plain_text("\n".join(part for part in parts if part))


def load_semantic_search_payload(
    vectors_path: Path,
    metadata_path: Path,
    abstract_ids: list[int],
) -> dict[str, Any] | None:
    if not vectors_path.exists() or not metadata_path.exists():
        return None
    metadata = load_json(metadata_path)
    ids = [int(value) for value in metadata.get("ids") or []]
    if not ids:
        return None
    vectors = np.load(vectors_path)
    if vectors.ndim != 2 or vectors.shape[0] != len(ids):
        raise UIBuildError(
            f"Semantic vector bundle mismatch: {vectors_path} has shape {vectors.shape}, metadata has {len(ids)} ids"
        )
    index_by_id = {abstract_id: position for position, abstract_id in enumerate(ids)}
    ordered_vectors: list[np.ndarray] = []
    missing_ids: list[int] = []
    for abstract_id in abstract_ids:
        position = index_by_id.get(abstract_id)
        if position is None:
            missing_ids.append(abstract_id)
            ordered_vectors.append(np.zeros((vectors.shape[1],), dtype=np.float32))
            continue
        ordered_vectors.append(vectors[position].astype(np.float32, copy=False))
    matrix = np.vstack(ordered_vectors).astype(np.float32, copy=False)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0.0] = 1.0
    normalized = matrix / norms
    return {
        "vectors": normalized,
        "metadata": {
            "count": int(normalized.shape[0]),
            "dimension": int(normalized.shape[1]),
            "embedding_name": metadata.get("embedding_name") or metadata.get("model_name") or "semantic_bundle",
            "model_name": metadata.get("model_name") or metadata.get("embedding_name") or "",
            "embedding_fields": list(metadata.get("embedding_fields") or []),
            "browser_model": BROWSER_SEMANTIC_MODEL,
            "filename": SEMANTIC_VECTOR_FILENAME,
            "missing_ids": missing_ids,
        },
    }


def build_sections(enriched_abstract: dict[str, Any]) -> list[dict[str, str]]:
    sections: list[dict[str, str]] = []
    for key, label in SECTION_FIELDS:
        if key == "additional_content_questions_markdown":
            markdown = render_additional_content_markdown(enriched_abstract.get(key))
        else:
            markdown = str(enriched_abstract.get(key) or "").strip()
        if not markdown:
            continue
        sections.append({"label": label, "markdown": markdown, "html": markdown_to_html(markdown)})
    return sections


def compute_facets(search_records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    counts: dict[str, Counter[str]] = {group: Counter() for group in FACET_GROUPS}
    for record in search_records:
        metadata = record["facets"]
        for group in FACET_GROUPS:
            values = metadata.get(group) or []
            for value in values:
                counts[group][str(value)] += 1
    return {
        group: [
            {"value": value, "count": count}
            for value, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
        ]
        for group, counter in counts.items()
    }


def build_ui_payload(
    raw_input: Path,
    enriched_input: Path,
    references_input: Path,
    image_analyses_input: Path,
    neighbors_input: Path,
    cluster_15_dir: Path,
    cluster_21_dir: Path,
    cluster_25_dir: Path,
    claims_cluster_dir: Path,
    semantic_vectors_input: Path,
    semantic_metadata_input: Path,
    umap_input: Path,
    top_neighbors: int = 8,
) -> dict[str, Any]:
    raw_abstracts = load_json(raw_input).get("abstracts") or []
    enriched_abstracts = load_json(enriched_input).get("abstracts") or []
    enriched_lookup = {int(abstract["id"]): abstract for abstract in enriched_abstracts}
    image_lookup = load_image_analysis_lookup(image_analyses_input)
    reference_lookup = load_reference_lookup(references_input)
    neighbors = load_neighbors(neighbors_input, top_neighbors)
    partitions = {
        "semantic_25": load_cluster_partition(cluster_25_dir, "semantic_25"),
        "claims_28": load_cluster_partition(claims_cluster_dir, "claims_28"),
    }
    umap_projection = load_umap_projection(umap_input)

    search_records: list[dict[str, Any]] = []
    detail_records: dict[str, Any] = {}
    relations: dict[str, Any] = {}
    abstract_ids: list[int] = []

    for raw_abstract in raw_abstracts:
        abstract_id = int(raw_abstract["id"])
        enriched_abstract = enriched_lookup.get(abstract_id)
        if not enriched_abstract:
            continue
        title = cleaned_abstract_title(raw_abstract.get("title"))
        metadata = build_metadata(raw_abstract, enriched_abstract, partitions)
        domain_facets = build_domain_facets(raw_abstract, enriched_abstract, metadata)
        abstract_ids.append(abstract_id)
        search_record = {
            "id": abstract_id,
            "title": title,
            "accepted_for": metadata["accepted_for"][0] if isinstance(metadata["accepted_for"], list) else metadata["accepted_for"],
            "primary_topic": metadata["primary_topic"],
            "secondary_topic": metadata["secondary_topic"],
            "keywords": metadata["keywords"],
            "figure_keywords": metadata["figure_keywords"],
            "facets": {
                "accepted_for": [metadata["accepted_for"]],
                "semantic_25": metadata["semantic_25"],
                "claims_28": metadata["claims_28"],
                "primary_topic": [metadata["primary_topic"]],
                "secondary_topic": metadata["secondary_topic_facets"],
                "keywords": metadata["keywords"],
                "methods": metadata["methods"],
                "study_type": metadata["study_type"],
                "population": metadata["population"],
                "field_strength": metadata["field_strength"],
                "processing_packages": metadata["processing_packages"],
                "species": domain_facets["species"],
                "recording_technology": domain_facets["recording_technology"],
                "brain_regions": domain_facets["brain_regions"],
                "brain_networks": domain_facets["brain_networks"],
            },
            "search_blob": build_search_blob(raw_abstract, enriched_abstract, metadata),
        }
        search_records.append(search_record)

        enriched_figure_analyses = [
            simplify_image_analysis(record)
            for record in order_figure_notes(enriched_abstract.get("figure_analyses") or [])
        ]
        detail_records[str(abstract_id)] = {
            "id": abstract_id,
            "title": title,
            "accepted_for": metadata["accepted_for"],
            "primary_topic": metadata["primary_topic"],
            "secondary_topic": metadata["secondary_topic"],
            "keywords": metadata["keywords"],
            "figure_keywords": metadata["figure_keywords"],
            "methods": metadata["methods"],
            "study_type": metadata["study_type"],
            "population": metadata["population"],
            "field_strength": metadata["field_strength"],
            "processing_packages": metadata["processing_packages"],
            "species": domain_facets["species"],
            "recording_technology": domain_facets["recording_technology"],
            "brain_regions": domain_facets["brain_regions"],
            "brain_networks": domain_facets["brain_networks"],
            "sections": build_sections(enriched_abstract),
            "claim_extraction": enriched_abstract.get("claim_extraction"),
            "figure_analyses": enriched_figure_analyses or image_lookup.get(abstract_id, []),
            "reference_summary": reference_lookup.get(abstract_id, {"matched_count": 0, "unmatched_count": 0, "items": []}),
        }

        relations[str(abstract_id)] = {
            "neighbors": neighbors.get(abstract_id, []),
            "clusters": {
                "semantic_25": partitions["semantic_25"]["assignments"].get(abstract_id),
                "claims_28": partitions["claims_28"]["assignments"].get(abstract_id),
            },
        }

    clusters_payload = {
        key: {
            "clusters": sorted(partition["clusters"].values(), key=lambda cluster: cluster["cluster_id"]),
        }
        for key, partition in partitions.items()
    }
    semantic_search = load_semantic_search_payload(
        vectors_path=semantic_vectors_input,
        metadata_path=semantic_metadata_input,
        abstract_ids=abstract_ids,
    )
    files = [
        "abstracts.search.json",
        "abstracts.detail.json",
        "facets.json",
        "relations.json",
        "clusters.json",
    ]
    if semantic_search:
        files.append(SEMANTIC_VECTOR_FILENAME)
    if umap_projection:
        files.append("projection.umap.json")

    return {
        "search": {
            "abstract_count": len(search_records),
            "abstracts": search_records,
        },
        "details": {
            "abstracts": detail_records,
        },
        "facets": {
            "groups": list(FACET_GROUPS),
            "facets": compute_facets(search_records),
        },
        "relations": {
            "abstracts": relations,
        },
        "clusters": {
            "partitions": clusters_payload,
        },
        "projection": {
            "umap": umap_projection,
        },
        "manifest": {
            "generated_at": datetime.now(UTC).isoformat(),
            "abstract_count": len(search_records),
            "neighbors_source": str(neighbors_input),
            "partitions": {
                "semantic_25": str(cluster_25_dir),
                "claims_28": str(claims_cluster_dir),
            },
            "files": files,
            "semantic_search": semantic_search["metadata"] if semantic_search else None,
            "projection": {
                "umap_source": str(umap_input),
                "count": umap_projection["count"] if umap_projection else 0,
            },
        },
        "semantic_search": semantic_search,
    }


def export_ui_bundle(output_dir: Path, payload: dict[str, Any]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "manifest.json", payload["manifest"])
    write_json(output_dir / "abstracts.search.json", payload["search"])
    write_json(output_dir / "abstracts.detail.json", payload["details"])
    write_json(output_dir / "facets.json", payload["facets"])
    write_json(output_dir / "relations.json", payload["relations"])
    write_json(output_dir / "clusters.json", payload["clusters"])
    write_json(output_dir / "projection.umap.json", payload["projection"])
    semantic_search = payload.get("semantic_search")
    if semantic_search:
        semantic_path = output_dir / semantic_search["metadata"]["filename"]
        semantic_path.write_bytes(semantic_search["vectors"].astype(np.float32, copy=False).tobytes(order="C"))


def copy_ui_assets(source_dir: Path, output_dir: Path) -> None:
    if not source_dir.exists():
        raise UIBuildError(f"UI source directory does not exist: {source_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    for path in source_dir.iterdir():
        if path.name.startswith("."):
            continue
        target = output_dir / path.name
        if path.is_dir():
            shutil.copytree(path, target, dirs_exist_ok=True)
        else:
            shutil.copy2(path, target)


def build_export_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export a static JSON bundle for the OHBM abstract search UI")
    parser.add_argument("--raw-input", default=DEFAULT_RAW_INPUT)
    parser.add_argument("--enriched-input", default=DEFAULT_ENRICHED_INPUT)
    parser.add_argument("--references-input", default=DEFAULT_REFERENCES_INPUT)
    parser.add_argument("--image-analyses-input", default=DEFAULT_IMAGE_ANALYSES_INPUT)
    parser.add_argument("--neighbors-input", default=DEFAULT_NEIGHBORS_INPUT)
    parser.add_argument("--cluster-15-dir", default=DEFAULT_CLUSTER_15_DIR)
    parser.add_argument("--cluster-21-dir", default=DEFAULT_CLUSTER_21_DIR)
    parser.add_argument("--cluster-25-dir", default=DEFAULT_CLUSTER_25_DIR)
    parser.add_argument("--claims-cluster-dir", default=DEFAULT_CLAIMS_CLUSTER_DIR)
    parser.add_argument("--semantic-vectors-input", default=DEFAULT_SEMANTIC_VECTORS_INPUT)
    parser.add_argument("--semantic-metadata-input", default=DEFAULT_SEMANTIC_METADATA_INPUT)
    parser.add_argument("--umap-input", default=DEFAULT_UMAP_INPUT)
    parser.add_argument("--output-dir", default=DEFAULT_EXPORT_OUTPUT)
    parser.add_argument("--top-neighbors", type=int, default=8)
    return parser


def export_ui_main(argv: list[str] | None = None) -> int:
    args = build_export_parser().parse_args(argv)
    payload = build_ui_payload(
        raw_input=Path(args.raw_input),
        enriched_input=Path(args.enriched_input),
        references_input=Path(args.references_input),
        image_analyses_input=Path(args.image_analyses_input),
        neighbors_input=Path(args.neighbors_input),
        cluster_15_dir=Path(args.cluster_15_dir),
        cluster_21_dir=Path(args.cluster_21_dir),
        cluster_25_dir=Path(args.cluster_25_dir),
        claims_cluster_dir=Path(args.claims_cluster_dir),
        semantic_vectors_input=Path(args.semantic_vectors_input),
        semantic_metadata_input=Path(args.semantic_metadata_input),
        umap_input=Path(args.umap_input),
        top_neighbors=args.top_neighbors,
    )
    export_ui_bundle(Path(args.output_dir), payload)
    print(
        json.dumps(
            {
                "output_dir": args.output_dir,
                "abstract_count": payload["manifest"]["abstract_count"],
                "top_neighbors": args.top_neighbors,
            },
            indent=2,
        )
    )
    return 0


def build_ui_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the standalone static OHBM abstract search UI")
    parser.add_argument("--raw-input", default=DEFAULT_RAW_INPUT)
    parser.add_argument("--enriched-input", default=DEFAULT_ENRICHED_INPUT)
    parser.add_argument("--references-input", default=DEFAULT_REFERENCES_INPUT)
    parser.add_argument("--image-analyses-input", default=DEFAULT_IMAGE_ANALYSES_INPUT)
    parser.add_argument("--neighbors-input", default=DEFAULT_NEIGHBORS_INPUT)
    parser.add_argument("--cluster-15-dir", default=DEFAULT_CLUSTER_15_DIR)
    parser.add_argument("--cluster-21-dir", default=DEFAULT_CLUSTER_21_DIR)
    parser.add_argument("--cluster-25-dir", default=DEFAULT_CLUSTER_25_DIR)
    parser.add_argument("--claims-cluster-dir", default=DEFAULT_CLAIMS_CLUSTER_DIR)
    parser.add_argument("--semantic-vectors-input", default=DEFAULT_SEMANTIC_VECTORS_INPUT)
    parser.add_argument("--semantic-metadata-input", default=DEFAULT_SEMANTIC_METADATA_INPUT)
    parser.add_argument("--umap-input", default=DEFAULT_UMAP_INPUT)
    parser.add_argument("--top-neighbors", type=int, default=8)
    parser.add_argument("--source-dir", default=DEFAULT_SITE_SOURCE)
    parser.add_argument("--site-output-dir", default=DEFAULT_SITE_OUTPUT)
    return parser


def build_ui_main(argv: list[str] | None = None) -> int:
    args = build_ui_parser().parse_args(argv)
    site_output_dir = Path(args.site_output_dir)
    copy_ui_assets(Path(args.source_dir), site_output_dir)
    payload = build_ui_payload(
        raw_input=Path(args.raw_input),
        enriched_input=Path(args.enriched_input),
        references_input=Path(args.references_input),
        image_analyses_input=Path(args.image_analyses_input),
        neighbors_input=Path(args.neighbors_input),
        cluster_15_dir=Path(args.cluster_15_dir),
        cluster_21_dir=Path(args.cluster_21_dir),
        cluster_25_dir=Path(args.cluster_25_dir),
        claims_cluster_dir=Path(args.claims_cluster_dir),
        semantic_vectors_input=Path(args.semantic_vectors_input),
        semantic_metadata_input=Path(args.semantic_metadata_input),
        umap_input=Path(args.umap_input),
        top_neighbors=args.top_neighbors,
    )
    export_ui_bundle(site_output_dir / "data", payload)
    print(
        json.dumps(
            {
                "site_output_dir": str(site_output_dir),
                "abstract_count": payload["manifest"]["abstract_count"],
            },
            indent=2,
        )
    )
    return 0
