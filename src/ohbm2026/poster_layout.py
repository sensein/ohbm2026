from __future__ import annotations

import argparse
import csv
import itertools
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026 import artifacts
from ohbm2026.analyze.storage import (
    load_embedding_bundle,
    parse_string_list_value,
)
from ohbm2026.titles import cleaned_abstract_title

SESSION_IDS = (1, 2, 3, 4)
SESSION_TO_BLOCK = {1: 1, 2: 1, 3: 2, 4: 2}
BLOCK_TO_SESSIONS = {1: (1, 2), 2: (3, 4)}
SESSION_LABELS = {
    1: "June 15-16 alternating pattern A",
    2: "June 15-16 alternating pattern B",
    3: "June 17-18 alternating pattern A",
    4: "June 17-18 alternating pattern B",
}
BLOCK_LABELS = {
    1: "June 15-16 block",
    2: "June 17-18 block",
}
SESSION_STANDBY_WINDOWS = {
    1: (
        "Monday, June 15 | 13:45-14:45",
        "Tuesday, June 16 | 13:30-14:30",
    ),
    2: (
        "Monday, June 15 | 14:45-15:45",
        "Tuesday, June 16 | 12:30-13:30",
    ),
    3: (
        "Wednesday, June 17 | 12:45-13:45",
        "Thursday, June 18 | 14:45-15:45",
    ),
    4: (
        "Wednesday, June 17 | 13:45-14:45",
        "Thursday, June 18 | 13:45-14:45",
    ),
}
HALL_LABELS = {
    1: "Poster Hall",
}
LAYOUT_POSTER_FACES_PER_BOARD = 2
DEFAULT_LAYOUT_GEOMETRY = str(artifacts.INPUT_LAYOUT_GEOMETRY_PATH)
DEFAULT_PROPOSAL_CSV_VOYAGE_EMBEDDINGS_DIR = str(artifacts.EMBEDDINGS_ROOT / "voyage_stage2_published")
DEFAULT_PROPOSAL_CSV_CLAIMS_EMBEDDINGS_DIR = str(artifacts.EMBEDDINGS_ROOT / "minilm_claims")
UNKNOWN_CATEGORY = "Unknown"
LISTING_TEMPLATE_COLUMNS = (
    "Abstract ID Number",
    "NEW POSTER NUMBER *USE THIS NUMBER FOR YOUR LOCATION IN THE POSTER HALL",
    "First Stand-by Time",
    "Second Stand-by Time",
    "Abstract Title",
    "Primary Category",
    "Last Name of First Author",
)
DEFAULT_LISTING_INTRO = (
    "OHBM 2026 POSTER LISTING\n"
    "POSTER HALL LOCATION: EXHIBITION HALL 1\n\n"
    "Please use this document to confirm your poster number and stand-by times at OHBM 2026. "
    "Each poster presenter has two total stand-by times during the event, one on each day of their assigned 2-day block."
)
LISTING_CSV_ENCODING = "utf-8-sig"


class PosterLayoutError(RuntimeError):
    """Raised when poster layout inputs or optimization are invalid."""


@dataclass(frozen=True)
class AcceptedAbstract:
    abstract_id: int
    accepted_for: str
    title: str
    primary_parent_category: str
    primary_subcategory: str
    primary_category: str
    layout_parent_label: str
    layout_exact_label: str
    layout_label_system: str
    first_author_id: int | None
    embedding_index: int
    claims_cluster_id: int | None
    claims_cluster_label: str | None


@dataclass(frozen=True)
class LayoutInputs:
    records: list[AcceptedAbstract]
    normalized_matrix: np.ndarray
    poster_records: list[AcceptedAbstract]
    oral_records: list[AcceptedAbstract]
    claims_cluster_by_id: dict[int, int]
    claims_cluster_summaries: dict[int, dict[str, Any]]
    layout_label_system: str
    layout_label_source: str
    layout_parent_count: int
    layout_exact_count: int


@dataclass(frozen=True)
class OptimizationWeights:
    exact_session_weight: float = 3.0
    parent_session_weight: float = 1.5
    exact_block_weight: float = 2.25
    parent_block_weight: float = 1.0
    claims_session_weight: float = 0.0
    claims_block_weight: float = 0.0
    fill_weight: float = 0.75


@dataclass(frozen=True)
class PathProposalConfig:
    primary_embedding_name: str
    secondary_embedding_name: str | None = None
    seed_strategy: str = "lowest_abstract_id_oral"


DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS = str(artifacts.EMBEDDINGS_ROOT / "minilm_claims" / "clustering_benchmark_25_30" / "cluster_assignments.json")
DEFAULT_CLAIMS_CLUSTER_SUMMARIES = str(artifacts.EMBEDDINGS_ROOT / "minilm_claims" / "clustering_benchmark_25_30" / "cluster_summaries.json")
DEFAULT_LAYOUT_LABEL_SYSTEM = "submitter_primary_secondary"


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def standby_time_labels_for_session(session_id: int) -> tuple[str, str]:
    if session_id not in SESSION_STANDBY_WINDOWS:
        raise PosterLayoutError(f"Unknown standby session pattern: {session_id}")
    return SESSION_STANDBY_WINDOWS[session_id]


def standby_session_for_block_and_poster_number(block_id: int, poster_number: int) -> int:
    if block_id not in BLOCK_TO_SESSIONS:
        raise PosterLayoutError(f"Unknown poster block: {block_id}")
    if int(poster_number) <= 0:
        raise PosterLayoutError("Poster numbers must be positive integers")
    block_sessions = BLOCK_TO_SESSIONS[int(block_id)]
    return block_sessions[0] if int(poster_number) % 2 == 1 else block_sessions[1]


def _format_poster_number(poster_number: int) -> str:
    return f"{int(poster_number):04d}"


def _sanitize_author_last_name(value: str | None) -> str:
    raw_value = str(value or "").strip()
    if not raw_value:
        return ""
    cleaned = re.sub(r"\s+", " ", raw_value)
    return cleaned


def load_author_last_names(path: Path | None) -> dict[int, str]:
    if path is None or not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_authors = payload.get("authors", payload if isinstance(payload, list) else [])
    if not isinstance(raw_authors, list):
        return {}
    last_names: dict[int, str] = {}
    for author in raw_authors:
        if not isinstance(author, dict):
            continue
        author_id = author.get("id")
        if not isinstance(author_id, int):
            continue
        last_name = _sanitize_author_last_name(author.get("last_name"))
        if not last_name:
            continue
        last_names[author_id] = last_name
    return last_names


def load_cluster_inputs(
    assignments_path: Path | None,
    summaries_path: Path | None,
) -> tuple[dict[int, int], dict[int, dict[str, Any]]]:
    assignments: dict[int, int] = {}
    summaries: dict[int, dict[str, Any]] = {}
    if assignments_path and assignments_path.exists():
        payload = json.loads(assignments_path.read_text(encoding="utf-8"))
        raw_assignments = payload.get("assignments", payload)
        if isinstance(raw_assignments, dict):
            assignments = {
                int(abstract_id): int(cluster_id)
                for abstract_id, cluster_id in raw_assignments.items()
                if str(abstract_id).strip()
            }
    if summaries_path and summaries_path.exists():
        payload = json.loads(summaries_path.read_text(encoding="utf-8"))
        raw_clusters = payload.get("clusters", payload)
        if isinstance(raw_clusters, list):
            summaries = {
                int(item["cluster_id"]): item
                for item in raw_clusters
                if isinstance(item, dict) and isinstance(item.get("cluster_id"), int)
            }
    return assignments, summaries


def load_claims_cluster_inputs(
    assignments_path: Path | None,
    summaries_path: Path | None,
) -> tuple[dict[int, int], dict[int, dict[str, Any]]]:
    return load_cluster_inputs(assignments_path, summaries_path)


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    matrix = np.asarray(matrix, dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms > 0.0, norms, 1.0)
    return matrix / norms


def _extract_primary_category_parts(abstract: dict[str, Any]) -> tuple[str, str]:
    for response in abstract.get("responses", []):
        question_name = str(response.get("question_name") or "").strip().lower()
        if question_name != "primary parent category & sub-category":
            continue
        values = parse_string_list_value(response.get("value"))
        parent = values[0] if values else UNKNOWN_CATEGORY
        subcategory = values[1] if len(values) > 1 else UNKNOWN_CATEGORY
        return parent or UNKNOWN_CATEGORY, subcategory or UNKNOWN_CATEGORY
    return UNKNOWN_CATEGORY, UNKNOWN_CATEGORY


def _extract_first_author_id(abstract: dict[str, Any]) -> int | None:
    authors = sorted(list(abstract.get("authors", [])), key=lambda item: int(item.get("author_order", 0)))
    if not authors:
        return None
    author_id = authors[0].get("id")
    return int(author_id) if isinstance(author_id, int) else None


def _record_from_abstract(
    abstract: dict[str, Any],
    embedding_index: int,
    claims_cluster_by_id: dict[int, int],
    claims_cluster_summaries: dict[int, dict[str, Any]],
    layout_cluster_by_id: dict[int, int] | None = None,
    layout_cluster_summaries: dict[int, dict[str, Any]] | None = None,
    layout_label_system: str = DEFAULT_LAYOUT_LABEL_SYSTEM,
) -> AcceptedAbstract:
    abstract_id = abstract.get("id")
    if not isinstance(abstract_id, int):
        raise PosterLayoutError("Accepted abstract is missing an integer id")
    accepted_for = str(abstract.get("accepted_for") or "Unknown").strip() or "Unknown"
    parent, subcategory = _extract_primary_category_parts(abstract)
    primary_category = f"{parent} :: {subcategory}"
    layout_parent_label = parent
    layout_exact_label = primary_category
    effective_layout_label_system = DEFAULT_LAYOUT_LABEL_SYSTEM
    if layout_cluster_by_id:
        layout_cluster_id = layout_cluster_by_id.get(abstract_id)
        if layout_cluster_id is None:
            raise PosterLayoutError(f"Accepted abstract {abstract_id} is missing from the selected layout label system")
        layout_summary = (layout_cluster_summaries or {}).get(layout_cluster_id, {})
        layout_exact_label = str(layout_summary.get("label") or f"Semantic cluster {layout_cluster_id}")
        layout_parent_label = str(layout_summary.get("parent_label") or layout_exact_label)
        effective_layout_label_system = layout_label_system or "semantic_cluster"
    claims_cluster_id = claims_cluster_by_id.get(abstract_id)
    claims_cluster_label = None
    if claims_cluster_id is not None:
        claims_cluster_label = str(
            claims_cluster_summaries.get(claims_cluster_id, {}).get("label") or f"Claims cluster {claims_cluster_id}"
        )
    return AcceptedAbstract(
        abstract_id=abstract_id,
        accepted_for=accepted_for,
        title=cleaned_abstract_title(abstract.get("title") or ""),
        primary_parent_category=parent,
        primary_subcategory=subcategory,
        primary_category=primary_category,
        layout_parent_label=layout_parent_label,
        layout_exact_label=layout_exact_label,
        layout_label_system=effective_layout_label_system,
        first_author_id=_extract_first_author_id(abstract),
        embedding_index=int(embedding_index),
        claims_cluster_id=claims_cluster_id,
        claims_cluster_label=claims_cluster_label,
    )


def load_layout_inputs(
    raw_input: Path,
    embeddings_dir: Path,
    claims_cluster_assignments: Path | None = None,
    claims_cluster_summaries: Path | None = None,
    layout_cluster_assignments: Path | None = None,
    layout_cluster_summaries: Path | None = None,
    layout_label_system: str = DEFAULT_LAYOUT_LABEL_SYSTEM,
) -> LayoutInputs:
    raw_database = json.loads(raw_input.read_text(encoding="utf-8"))
    bundle = load_embedding_bundle(embeddings_dir)
    ids = bundle.get("ids", [])
    matrix = np.asarray(bundle.get("matrix"), dtype=np.float32)
    if int(matrix.shape[0]) != len(ids):
        raise PosterLayoutError("Embedding bundle ids do not align with vectors")

    embedding_index_by_id = {int(abstract_id): index for index, abstract_id in enumerate(ids)}
    cluster_by_id, cluster_summaries = load_claims_cluster_inputs(claims_cluster_assignments, claims_cluster_summaries)
    layout_cluster_by_id, layout_cluster_summary_map = load_cluster_inputs(layout_cluster_assignments, layout_cluster_summaries)
    effective_layout_label_system = (
        layout_label_system if layout_cluster_by_id else DEFAULT_LAYOUT_LABEL_SYSTEM
    )
    records: list[AcceptedAbstract] = []
    for abstract in raw_database.get("abstracts", []):
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        accepted_for = str(abstract.get("accepted_for") or "").strip()
        if accepted_for not in {"Poster", "Oral"}:
            continue
        if abstract_id not in embedding_index_by_id:
            raise PosterLayoutError(f"Accepted abstract {abstract_id} is missing from {embeddings_dir}")
        records.append(
            _record_from_abstract(
                abstract,
                embedding_index_by_id[abstract_id],
                cluster_by_id,
                cluster_summaries,
                layout_cluster_by_id if layout_cluster_by_id else None,
                layout_cluster_summary_map if layout_cluster_summary_map else None,
                effective_layout_label_system,
            )
        )

    normalized_matrix = _normalize_rows(matrix)
    poster_records = [record for record in records if record.accepted_for == "Poster"]
    oral_records = [record for record in records if record.accepted_for == "Oral"]
    layout_parent_count = len({record.layout_parent_label for record in records})
    layout_exact_count = len({record.layout_exact_label for record in records})
    return LayoutInputs(
        records=records,
        normalized_matrix=normalized_matrix,
        poster_records=poster_records,
        oral_records=oral_records,
        claims_cluster_by_id=cluster_by_id,
        claims_cluster_summaries=cluster_summaries,
        layout_label_system=effective_layout_label_system,
        layout_label_source=(
            str(layout_cluster_assignments)
            if layout_cluster_by_id and layout_cluster_assignments is not None
            else "submitter primary parent/subcategory responses"
        ),
        layout_parent_count=layout_parent_count,
        layout_exact_count=layout_exact_count,
    )


def _session_targets(total_posters: int) -> dict[int, int]:
    base = total_posters // len(SESSION_IDS)
    remainder = total_posters % len(SESSION_IDS)
    return {
        session_id: base + (1 if index < remainder else 0)
        for index, session_id in enumerate(SESSION_IDS)
    }


def _author_groups(records: list[AcceptedAbstract]) -> list[list[AcceptedAbstract]]:
    groups: dict[tuple[str, int], list[AcceptedAbstract]] = defaultdict(list)
    for record in records:
        if record.first_author_id is None:
            groups[("abstract", record.abstract_id)].append(record)
        else:
            groups[("author", record.first_author_id)].append(record)
    grouped = list(groups.values())
    for group in grouped:
        if len(group) > len(SESSION_IDS):
            first_author_id = group[0].first_author_id
            raise PosterLayoutError(
                f"First author {first_author_id} has {len(group)} posters, which exceeds the four standby patterns"
            )
    grouped.sort(
        key=lambda group: (
            -len(group),
            min(record.layout_exact_label for record in group),
            min(record.abstract_id for record in group),
        )
    )
    return grouped


def _assignment_delta(
    record: AcceptedAbstract,
    session_id: int,
    exact_session_counts: dict[str, dict[int, int]],
    parent_session_counts: dict[str, dict[int, int]],
    exact_block_counts: dict[str, dict[int, int]],
    parent_block_counts: dict[str, dict[int, int]],
    claims_session_counts: dict[int, dict[int, int]],
    claims_block_counts: dict[int, dict[int, int]],
    session_sizes: dict[int, int],
    session_targets: dict[int, int],
    exact_targets: dict[str, float],
    parent_targets: dict[str, float],
    exact_block_targets: dict[str, float],
    parent_block_targets: dict[str, float],
    claims_session_targets: dict[int, float],
    claims_block_targets: dict[int, float],
    weights: OptimizationWeights,
) -> float:
    if session_sizes[session_id] >= session_targets[session_id]:
        return float("inf")

    block_id = SESSION_TO_BLOCK[session_id]
    exact_counts = exact_session_counts[record.layout_exact_label]
    parent_counts = parent_session_counts[record.layout_parent_label]
    exact_block_count_map = exact_block_counts[record.layout_exact_label]
    parent_block_count_map = parent_block_counts[record.layout_parent_label]
    exact_target = exact_targets[record.layout_exact_label]
    parent_target = parent_targets[record.layout_parent_label]
    exact_block_target = exact_block_targets[record.layout_exact_label]
    parent_block_target = parent_block_targets[record.layout_parent_label]
    claims_before = 0.0
    claims_after = 0.0
    claims_block_before = 0.0
    claims_block_after = 0.0
    if record.claims_cluster_id is not None:
        claims_cluster_id = int(record.claims_cluster_id)
        claims_counts = claims_session_counts[claims_cluster_id]
        claims_block_count_map = claims_block_counts[claims_cluster_id]
        claims_target = claims_session_targets[claims_cluster_id]
        claims_block_target = claims_block_targets[claims_cluster_id]
        claims_before = float((claims_counts[session_id] - claims_target) ** 2)
        claims_after = float((claims_counts[session_id] + 1 - claims_target) ** 2)
        claims_block_before = float((claims_block_count_map[block_id] - claims_block_target) ** 2)
        claims_block_after = float((claims_block_count_map[block_id] + 1 - claims_block_target) ** 2)

    exact_before = float((exact_counts[session_id] - exact_target) ** 2)
    exact_after = float((exact_counts[session_id] + 1 - exact_target) ** 2)
    parent_before = float((parent_counts[session_id] - parent_target) ** 2)
    parent_after = float((parent_counts[session_id] + 1 - parent_target) ** 2)
    exact_block_before = float((exact_block_count_map[block_id] - exact_block_target) ** 2)
    exact_block_after = float((exact_block_count_map[block_id] + 1 - exact_block_target) ** 2)
    parent_block_before = float((parent_block_count_map[block_id] - parent_block_target) ** 2)
    parent_block_after = float((parent_block_count_map[block_id] + 1 - parent_block_target) ** 2)

    fill_ratio_before = session_sizes[session_id] / session_targets[session_id]
    fill_ratio_after = (session_sizes[session_id] + 1) / session_targets[session_id]

    return (
        weights.exact_session_weight * (exact_after - exact_before)
        + weights.parent_session_weight * (parent_after - parent_before)
        + weights.exact_block_weight * (exact_block_after - exact_block_before)
        + weights.parent_block_weight * (parent_block_after - parent_block_before)
        + weights.claims_session_weight * (claims_after - claims_before)
        + weights.claims_block_weight * (claims_block_after - claims_block_before)
        + weights.fill_weight * ((fill_ratio_after**2) - (fill_ratio_before**2))
    )


def optimize_session_assignment(
    records: list[AcceptedAbstract],
    weights: OptimizationWeights | None = None,
) -> dict[int, int]:
    if not records:
        return {}
    weights = OptimizationWeights() if weights is None else weights

    session_targets = _session_targets(len(records))
    exact_targets = {
        category: count / len(SESSION_IDS)
        for category, count in Counter(record.layout_exact_label for record in records).items()
    }
    parent_targets = {
        category: count / len(SESSION_IDS)
        for category, count in Counter(record.layout_parent_label for record in records).items()
    }
    exact_block_targets = {
        category: count / len(BLOCK_TO_SESSIONS)
        for category, count in Counter(record.layout_exact_label for record in records).items()
    }
    parent_block_targets = {
        category: count / len(BLOCK_TO_SESSIONS)
        for category, count in Counter(record.layout_parent_label for record in records).items()
    }
    claims_session_targets = {
        int(cluster_id): count / len(SESSION_IDS)
        for cluster_id, count in Counter(
            int(record.claims_cluster_id) for record in records if record.claims_cluster_id is not None
        ).items()
    }
    claims_block_targets = {
        int(cluster_id): count / len(BLOCK_TO_SESSIONS)
        for cluster_id, count in Counter(
            int(record.claims_cluster_id) for record in records if record.claims_cluster_id is not None
        ).items()
    }

    exact_session_counts: dict[str, dict[int, int]] = defaultdict(lambda: {session_id: 0 for session_id in SESSION_IDS})
    parent_session_counts: dict[str, dict[int, int]] = defaultdict(lambda: {session_id: 0 for session_id in SESSION_IDS})
    exact_block_counts: dict[str, dict[int, int]] = defaultdict(lambda: {block_id: 0 for block_id in BLOCK_TO_SESSIONS})
    parent_block_counts: dict[str, dict[int, int]] = defaultdict(lambda: {block_id: 0 for block_id in BLOCK_TO_SESSIONS})
    claims_session_counts: dict[int, dict[int, int]] = defaultdict(lambda: {session_id: 0 for session_id in SESSION_IDS})
    claims_block_counts: dict[int, dict[int, int]] = defaultdict(lambda: {block_id: 0 for block_id in BLOCK_TO_SESSIONS})
    session_sizes = {session_id: 0 for session_id in SESSION_IDS}
    assignments: dict[int, int] = {}

    for group in _author_groups(records):
        available_sessions = [session_id for session_id in SESSION_IDS if session_sizes[session_id] < session_targets[session_id]]
        if len(available_sessions) < len(group):
            raise PosterLayoutError("Not enough standby capacity remains to place a first-author group without conflicts")

        best_cost: float | None = None
        best_assignment: list[tuple[AcceptedAbstract, int]] | None = None
        ordered_group = sorted(group, key=lambda record: (record.layout_exact_label, record.abstract_id))
        for candidate_sessions in itertools.permutations(available_sessions, len(ordered_group)):
            temp_exact = {key: value.copy() for key, value in exact_session_counts.items()}
            temp_parent = {key: value.copy() for key, value in parent_session_counts.items()}
            temp_exact_blocks = {key: value.copy() for key, value in exact_block_counts.items()}
            temp_parent_blocks = {key: value.copy() for key, value in parent_block_counts.items()}
            temp_claims = {key: value.copy() for key, value in claims_session_counts.items()}
            temp_claims_blocks = {key: value.copy() for key, value in claims_block_counts.items()}
            temp_sizes = session_sizes.copy()
            total_cost = 0.0
            feasible = True
            for record, session_id in zip(ordered_group, candidate_sessions):
                delta = _assignment_delta(
                    record,
                    session_id,
                    defaultdict(lambda: {session: 0 for session in SESSION_IDS}, temp_exact),
                    defaultdict(lambda: {session: 0 for session in SESSION_IDS}, temp_parent),
                    defaultdict(lambda: {block: 0 for block in BLOCK_TO_SESSIONS}, temp_exact_blocks),
                    defaultdict(lambda: {block: 0 for block in BLOCK_TO_SESSIONS}, temp_parent_blocks),
                    defaultdict(lambda: {session: 0 for session in SESSION_IDS}, temp_claims),
                    defaultdict(lambda: {block: 0 for block in BLOCK_TO_SESSIONS}, temp_claims_blocks),
                    temp_sizes,
                    session_targets,
                    exact_targets,
                    parent_targets,
                    exact_block_targets,
                    parent_block_targets,
                    claims_session_targets,
                    claims_block_targets,
                    weights,
                )
                if not np.isfinite(delta):
                    feasible = False
                    break
                total_cost += delta
                temp_exact.setdefault(record.layout_exact_label, {session: 0 for session in SESSION_IDS})[session_id] += 1
                temp_parent.setdefault(record.layout_parent_label, {session: 0 for session in SESSION_IDS})[session_id] += 1
                block_id = SESSION_TO_BLOCK[session_id]
                temp_exact_blocks.setdefault(record.layout_exact_label, {block: 0 for block in BLOCK_TO_SESSIONS})[block_id] += 1
                temp_parent_blocks.setdefault(record.layout_parent_label, {block: 0 for block in BLOCK_TO_SESSIONS})[
                    block_id
                ] += 1
                if record.claims_cluster_id is not None:
                    claims_cluster_id = int(record.claims_cluster_id)
                    temp_claims.setdefault(claims_cluster_id, {session: 0 for session in SESSION_IDS})[session_id] += 1
                    temp_claims_blocks.setdefault(claims_cluster_id, {block: 0 for block in BLOCK_TO_SESSIONS})[
                        block_id
                    ] += 1
                temp_sizes[session_id] += 1

            if feasible and (best_cost is None or total_cost < best_cost):
                best_cost = total_cost
                best_assignment = list(zip(ordered_group, candidate_sessions))

        if best_assignment is None:
            raise PosterLayoutError("Could not find a feasible standby assignment for a first-author group")

        for record, session_id in best_assignment:
            assignments[record.abstract_id] = session_id
            exact_session_counts[record.layout_exact_label][session_id] += 1
            parent_session_counts[record.layout_parent_label][session_id] += 1
            block_id = SESSION_TO_BLOCK[session_id]
            exact_block_counts[record.layout_exact_label][block_id] += 1
            parent_block_counts[record.layout_parent_label][block_id] += 1
            if record.claims_cluster_id is not None:
                claims_cluster_id = int(record.claims_cluster_id)
                claims_session_counts[claims_cluster_id][session_id] += 1
                claims_block_counts[claims_cluster_id][block_id] += 1
            session_sizes[session_id] += 1

    if any(session_sizes[session_id] != session_targets[session_id] for session_id in SESSION_IDS):
        raise PosterLayoutError("Poster assignment did not land on the expected session targets")
    return assignments


def _cosine_distance(matrix: np.ndarray, left_index: int, right_index: int) -> float:
    similarity = float(np.dot(matrix[left_index], matrix[right_index]))
    similarity = max(-1.0, min(1.0, similarity))
    return 1.0 - similarity


def category_distance(left: AcceptedAbstract, right: AcceptedAbstract) -> float:
    if left.layout_parent_label == right.layout_parent_label:
        if left.layout_exact_label == right.layout_exact_label:
            return 0.0
        return 0.5
    return 1.0


def _nearest_neighbor_order(indices: list[int], normalized_matrix: np.ndarray) -> list[int]:
    if len(indices) <= 2:
        return list(indices)
    subset = normalized_matrix[indices]
    centroid = subset.mean(axis=0)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm > 0.0:
        centroid = centroid / centroid_norm
    start_position = int(np.argmax(subset @ centroid))
    remaining = set(range(len(indices)))
    order_positions = [start_position]
    remaining.remove(start_position)
    current_position = start_position
    while remaining:
        remaining_positions = np.asarray(sorted(remaining), dtype=np.int32)
        similarities = subset[remaining_positions] @ subset[current_position]
        next_position = int(remaining_positions[int(np.argmax(similarities))])
        order_positions.append(next_position)
        remaining.remove(next_position)
        current_position = next_position
    return [indices[position] for position in order_positions]


def _spectral_clustered_group_order(
    indices: list[int],
    normalized_matrix: np.ndarray,
    target_cluster_size: int = 16,
    max_clusters: int = 8,
) -> list[int]:
    if len(indices) <= max(4, int(target_cluster_size)):
        return _nearest_neighbor_order(indices, normalized_matrix)

    from sklearn.cluster import SpectralClustering

    subset = np.asarray(normalized_matrix[indices], dtype=np.float32)
    cluster_count = min(
        max(2, int(round(len(indices) / max(1, int(target_cluster_size))))),
        max(2, int(max_clusters)),
        len(indices) - 1,
    )
    if cluster_count < 2:
        return _nearest_neighbor_order(indices, normalized_matrix)

    affinity = np.clip(subset @ subset.T, 0.0, 1.0)
    np.fill_diagonal(affinity, 1.0)
    try:
        labels = SpectralClustering(
            n_clusters=int(cluster_count),
            affinity="precomputed",
            assign_labels="kmeans",
            random_state=42,
        ).fit_predict(affinity)
    except Exception:
        return _nearest_neighbor_order(indices, normalized_matrix)

    cluster_names = sorted({int(value) for value in labels})
    if len(cluster_names) <= 1:
        return _nearest_neighbor_order(indices, normalized_matrix)

    cluster_centroids: list[np.ndarray] = []
    for cluster_name in cluster_names:
        member_positions = np.where(labels == int(cluster_name))[0]
        centroid = subset[member_positions].mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        cluster_centroids.append(centroid / centroid_norm if centroid_norm > 0.0 else centroid)
    cluster_order_positions = _nearest_neighbor_order(
        list(range(len(cluster_names))),
        np.asarray(cluster_centroids, dtype=np.float32),
    )

    ordered_indices: list[int] = []
    for cluster_position in cluster_order_positions:
        cluster_name = cluster_names[int(cluster_position)]
        member_positions = np.where(labels == int(cluster_name))[0].tolist()
        member_indices = [indices[int(position)] for position in member_positions]
        ordered_indices.extend(_nearest_neighbor_order(member_indices, normalized_matrix))
    return ordered_indices


def _within_group_order(
    indices: list[int],
    normalized_matrix: np.ndarray,
    strategy: str = "nearest_neighbor",
) -> list[int]:
    if strategy == "spectral_cluster":
        return _spectral_clustered_group_order(indices, normalized_matrix)
    return _nearest_neighbor_order(indices, normalized_matrix)


def _ordered_label_subset(preferred_labels: list[str], available_labels: list[str]) -> list[str]:
    available = set(available_labels)
    ordered = [label for label in preferred_labels if label in available]
    seen = set(ordered)
    ordered.extend(label for label in available_labels if label not in seen)
    return ordered


def build_shared_layout_group_order(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
) -> tuple[list[str], dict[str, list[str]]]:
    if not records:
        return [], {}

    grouped_by_parent: dict[str, list[AcceptedAbstract]] = defaultdict(list)
    for record in records:
        grouped_by_parent[record.layout_parent_label].append(record)

    parent_names = sorted(grouped_by_parent)
    parent_centroids: list[np.ndarray] = []
    for parent_name in parent_names:
        group_indices = [record.embedding_index for record in grouped_by_parent[parent_name]]
        centroid = normalized_matrix[group_indices].mean(axis=0)
        centroid_norm = np.linalg.norm(centroid)
        parent_centroids.append(centroid / centroid_norm if centroid_norm > 0.0 else centroid)
    parent_order_positions = _nearest_neighbor_order(
        list(range(len(parent_names))),
        np.asarray(parent_centroids, dtype=np.float32),
    )
    ordered_parent_names = [parent_names[position] for position in parent_order_positions]

    ordered_subcategories_by_parent: dict[str, list[str]] = {}
    for parent_name in ordered_parent_names:
        grouped_by_subcategory: dict[str, list[AcceptedAbstract]] = defaultdict(list)
        for record in grouped_by_parent[parent_name]:
            grouped_by_subcategory[record.layout_exact_label].append(record)

        subcategory_names = sorted(grouped_by_subcategory)
        subcategory_centroids: list[np.ndarray] = []
        for subcategory_name in subcategory_names:
            group_indices = [record.embedding_index for record in grouped_by_subcategory[subcategory_name]]
            centroid = normalized_matrix[group_indices].mean(axis=0)
            centroid_norm = np.linalg.norm(centroid)
            subcategory_centroids.append(centroid / centroid_norm if centroid_norm > 0.0 else centroid)
        subcategory_order_positions = _nearest_neighbor_order(
            list(range(len(subcategory_names))),
            np.asarray(subcategory_centroids, dtype=np.float32),
        )
        ordered_subcategories_by_parent[parent_name] = [
            subcategory_names[position] for position in subcategory_order_positions
        ]

    return ordered_parent_names, ordered_subcategories_by_parent


def build_block_numeric_order(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    shared_parent_order: list[str] | None = None,
    shared_subcategory_order: dict[str, list[str]] | None = None,
) -> list[int]:
    if not records:
        return []

    grouped_by_parent: dict[str, list[AcceptedAbstract]] = defaultdict(list)
    for record in records:
        grouped_by_parent[record.layout_parent_label].append(record)

    if shared_parent_order:
        ordered_parent_names = _ordered_label_subset(shared_parent_order, sorted(grouped_by_parent))
    else:
        ordered_parent_names, _ = build_shared_layout_group_order(records, normalized_matrix)

    ordered_embedding_indices: list[int] = []
    for parent_name in ordered_parent_names:
        grouped_by_subcategory: dict[str, list[AcceptedAbstract]] = defaultdict(list)
        for record in grouped_by_parent[parent_name]:
            grouped_by_subcategory[record.layout_exact_label].append(record)

        if shared_subcategory_order and parent_name in shared_subcategory_order:
            ordered_subcategories = _ordered_label_subset(
                shared_subcategory_order[parent_name],
                sorted(grouped_by_subcategory),
            )
        else:
            _, ordered_subcategories_by_parent = build_shared_layout_group_order(grouped_by_parent[parent_name], normalized_matrix)
            ordered_subcategories = ordered_subcategories_by_parent[parent_name]

        for subcategory_name in ordered_subcategories:
            poster_indices = [record.embedding_index for record in grouped_by_subcategory[subcategory_name]]
            ordered_embedding_indices.extend(_nearest_neighbor_order(poster_indices, normalized_matrix))

    return ordered_embedding_indices


def build_global_numeric_order(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    shared_parent_order: list[str] | None = None,
    shared_subcategory_order: dict[str, list[str]] | None = None,
    within_group_strategy: str = "nearest_neighbor",
) -> list[int]:
    if not records:
        return []

    grouped_by_parent: dict[str, list[AcceptedAbstract]] = defaultdict(list)
    for record in records:
        grouped_by_parent[record.layout_parent_label].append(record)

    if shared_parent_order:
        ordered_parent_names = _ordered_label_subset(shared_parent_order, sorted(grouped_by_parent))
    else:
        ordered_parent_names, _ = build_shared_layout_group_order(records, normalized_matrix)

    ordered_embedding_indices: list[int] = []
    for parent_name in ordered_parent_names:
        grouped_by_subcategory: dict[str, list[AcceptedAbstract]] = defaultdict(list)
        for record in grouped_by_parent[parent_name]:
            grouped_by_subcategory[record.layout_exact_label].append(record)

        if shared_subcategory_order and parent_name in shared_subcategory_order:
            ordered_subcategories = _ordered_label_subset(
                shared_subcategory_order[parent_name],
                sorted(grouped_by_subcategory),
            )
        else:
            _, ordered_subcategories_by_parent = build_shared_layout_group_order(
                grouped_by_parent[parent_name],
                normalized_matrix,
            )
            ordered_subcategories = ordered_subcategories_by_parent[parent_name]

        for subcategory_name in ordered_subcategories:
            poster_indices = [record.embedding_index for record in grouped_by_subcategory[subcategory_name]]
            ordered_embedding_indices.extend(
                _within_group_order(
                    poster_indices,
                    normalized_matrix,
                    strategy=within_group_strategy,
                )
            )

    return ordered_embedding_indices


def _load_normalized_embedding_bundle(bundle_dir: Path) -> tuple[dict[int, int], np.ndarray]:
    bundle = load_embedding_bundle(bundle_dir)
    ids = [int(value) for value in bundle.get("ids", [])]
    matrix = _normalize_rows(np.asarray(bundle.get("matrix"), dtype=np.float32))
    if int(matrix.shape[0]) != len(ids):
        raise PosterLayoutError(f"Embedding bundle ids do not align with vectors in {bundle_dir}")
    return {abstract_id: index for index, abstract_id in enumerate(ids)}, matrix


@lru_cache(maxsize=4)
def _load_optional_normalized_embedding_bundle(bundle_dir: str) -> tuple[dict[int, int], np.ndarray] | None:
    path = Path(bundle_dir)
    if not path.exists():
        return None
    try:
        return _load_normalized_embedding_bundle(path)
    except Exception:
        return None


def _ordered_neighbor_mean_cosine_similarity(
    ordered_assignments: list[dict[str, Any]],
    bundle_dir: str,
    neighbor_count: int = 5,
) -> dict[int, float | None]:
    bundle = _load_optional_normalized_embedding_bundle(bundle_dir)
    if bundle is None:
        return {
            int(item.get("abstract_id")): None
            for item in ordered_assignments
            if isinstance(item.get("abstract_id"), int)
        }
    index_by_id, matrix = bundle
    scores: dict[int, float | None] = {}
    total = len(ordered_assignments)
    for position, item in enumerate(ordered_assignments):
        abstract_id = item.get("abstract_id")
        if not isinstance(abstract_id, int) or abstract_id not in index_by_id:
            if isinstance(abstract_id, int):
                scores[abstract_id] = None
            continue
        candidate_positions = sorted(
            (other for other in range(total) if other != position),
            key=lambda other: (abs(other - position), other),
        )[:neighbor_count]
        similarities: list[float] = []
        for other_position in candidate_positions:
            other_id = ordered_assignments[other_position].get("abstract_id")
            if not isinstance(other_id, int) or other_id not in index_by_id:
                continue
            left_index = index_by_id[abstract_id]
            right_index = index_by_id[other_id]
            similarities.append(float(np.dot(matrix[left_index], matrix[right_index])))
        scores[abstract_id] = float(np.mean(similarities)) if similarities else None
    return scores


def _path_distance_key(
    current_id: int,
    candidate_id: int,
    primary_index_by_id: dict[int, int],
    primary_matrix: np.ndarray,
    secondary_index_by_id: dict[int, int] | None = None,
    secondary_matrix: np.ndarray | None = None,
) -> tuple[float, float, int]:
    primary_distance = _cosine_distance(
        primary_matrix,
        primary_index_by_id[current_id],
        primary_index_by_id[candidate_id],
    )
    secondary_distance = 0.0
    if (
        secondary_index_by_id is not None
        and secondary_matrix is not None
        and current_id in secondary_index_by_id
        and candidate_id in secondary_index_by_id
    ):
        secondary_distance = _cosine_distance(
            secondary_matrix,
            secondary_index_by_id[current_id],
            secondary_index_by_id[candidate_id],
        )
    return (float(primary_distance), float(secondary_distance), int(candidate_id))


def build_semantic_path_order(
    records: list[AcceptedAbstract],
    primary_index_by_id: dict[int, int],
    primary_matrix: np.ndarray,
    secondary_index_by_id: dict[int, int] | None = None,
    secondary_matrix: np.ndarray | None = None,
    seed_id: int | None = None,
) -> list[int]:
    if not records:
        return []
    record_ids = [int(record.abstract_id) for record in records]
    available = set(record_ids)
    if seed_id is None or seed_id not in available:
        seed_id = min(record_ids)
    order = [int(seed_id)]
    available.remove(int(seed_id))
    current_id = int(seed_id)
    while available:
        next_id = min(
            available,
            key=lambda candidate_id: _path_distance_key(
                current_id,
                int(candidate_id),
                primary_index_by_id,
                primary_matrix,
                secondary_index_by_id,
                secondary_matrix,
            ),
        )
        order.append(int(next_id))
        available.remove(int(next_id))
        current_id = int(next_id)
    return order


def _block_targets(total_records: int) -> dict[int, int]:
    first_block = (total_records + 1) // 2
    second_block = total_records - first_block
    return {1: first_block, 2: second_block}


def assign_path_to_blocks(
    ordered_ids: list[int],
    records_by_id: dict[int, AcceptedAbstract],
) -> tuple[dict[int, int], dict[int, list[int]]]:
    block_targets = _block_targets(len(ordered_ids))
    block_sizes = {1: 0, 2: 0}
    block_author_counts: dict[int, Counter[int]] = {1: Counter(), 2: Counter()}
    block_sequences: dict[int, list[int]] = {1: [], 2: []}
    block_by_id: dict[int, int] = {}

    for index, abstract_id in enumerate(ordered_ids):
        preferred_block = 1 if index % 2 == 0 else 2
        record = records_by_id[abstract_id]
        candidates = [preferred_block, 2 if preferred_block == 1 else 1]
        chosen_block: int | None = None
        for block_id in candidates:
            if block_sizes[block_id] >= block_targets[block_id]:
                continue
            if record.first_author_id is not None and block_author_counts[block_id][record.first_author_id] >= 2:
                continue
            chosen_block = block_id
            break
        if chosen_block is None:
            for block_id in candidates:
                if block_sizes[block_id] < block_targets[block_id]:
                    chosen_block = block_id
                    break
        if chosen_block is None:
            raise PosterLayoutError("Could not split the semantic path across the two blocks")
        block_by_id[abstract_id] = chosen_block
        block_sequences[chosen_block].append(abstract_id)
        block_sizes[chosen_block] += 1
        if record.first_author_id is not None:
            block_author_counts[chosen_block][record.first_author_id] += 1

    return block_by_id, block_sequences


def assign_block_sequences_to_sessions(
    block_sequences: dict[int, list[int]],
    records_by_id: dict[int, AcceptedAbstract],
) -> dict[int, int]:
    session_targets = _session_targets(sum(len(sequence) for sequence in block_sequences.values()))
    assignments: dict[int, int] = {}
    session_sizes = {session_id: 0 for session_id in SESSION_IDS}
    session_authors: dict[int, set[int]] = {session_id: set() for session_id in SESSION_IDS}

    for block_id, block_sessions in BLOCK_TO_SESSIONS.items():
        block_session_list = list(block_sessions)
        for index, abstract_id in enumerate(block_sequences.get(block_id, [])):
            record = records_by_id[abstract_id]
            preferred_session = block_session_list[index % len(block_session_list)]
            alternate_sessions = [session_id for session_id in block_session_list if session_id != preferred_session]
            ordered_candidates = [preferred_session, *alternate_sessions]

            chosen_session: int | None = None
            for session_id in ordered_candidates:
                if session_sizes[session_id] >= session_targets[session_id]:
                    continue
                if record.first_author_id is not None and record.first_author_id in session_authors[session_id]:
                    continue
                chosen_session = session_id
                break

            if chosen_session is None:
                for session_id in ordered_candidates:
                    if session_sizes[session_id] < session_targets[session_id]:
                        chosen_session = session_id
                        break

            if chosen_session is None:
                raise PosterLayoutError(
                    f"Could not place abstract {abstract_id} into block {block_id} without exceeding session targets"
                )
            assignments[abstract_id] = chosen_session
            session_sizes[chosen_session] += 1
            if record.first_author_id is not None:
                session_authors[chosen_session].add(record.first_author_id)

    if any(session_sizes[session_id] != session_targets[session_id] for session_id in SESSION_IDS):
        raise PosterLayoutError("Semantic path assignment did not land on the expected session targets")
    return assignments


def _session_summary(records: list[AcceptedAbstract], assignments: dict[int, int]) -> dict[str, Any]:
    summaries: dict[str, Any] = {}
    for session_id in SESSION_IDS:
        session_records = [record for record in records if assignments.get(record.abstract_id) == session_id]
        first_standby_label, second_standby_label = standby_time_labels_for_session(session_id)
        summaries[str(session_id)] = {
            "session_id": session_id,
            "session_label": SESSION_LABELS[session_id],
            "block_id": SESSION_TO_BLOCK[session_id],
            "block_label": BLOCK_LABELS[SESSION_TO_BLOCK[session_id]],
            "first_standby_time_label": first_standby_label,
            "second_standby_time_label": second_standby_label,
            "poster_count": len(session_records),
            "layout_parent_label_counts": dict(sorted(Counter(record.layout_parent_label for record in session_records).items())),
            "layout_exact_label_counts": dict(sorted(Counter(record.layout_exact_label for record in session_records).items())),
            "submitter_parent_category_counts": dict(
                sorted(Counter(record.primary_parent_category for record in session_records).items())
            ),
            "submitter_subcategory_counts": dict(sorted(Counter(record.primary_category for record in session_records).items())),
        }
    return summaries


def _default_layout_geometry_payload() -> dict[str, Any]:
    image_width = 1192.0
    image_height = 676.0
    row_centers_image = [35.12, 81.66, 128.20, 174.74, 221.28, 267.82, 314.36, 360.90, 407.44, 453.98, 500.52, 547.06, 593.60, 640.14]
    vertex_amplitude_y = 4.01
    face_offset = 2.1
    row_templates = [
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1136.0, 20)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1136.0, 20)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1136.0, 20)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1136.0, 20)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(232.0, 319.0, 10), (378.0, 465.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10), (964.0, 1051.0, 10)],
        [(378.0, 463.0, 10), (524.0, 612.0, 10), (671.0, 758.0, 10), (817.0, 905.0, 10)],
    ]
    boards: list[dict[str, Any]] = []
    board_number = 1

    for row_index, row_segments in enumerate(row_templates):
        row_direction = "left_to_right" if row_index % 2 == 0 else "right_to_left"
        row_center_image = row_centers_image[row_index]
        unit_order = range(len(row_segments)) if row_direction == "left_to_right" else range(len(row_segments) - 1, -1, -1)
        for unit_index in unit_order:
            segment_x0, segment_x1, edge_count = row_segments[unit_index]
            edge_order = range(edge_count) if row_direction == "left_to_right" else range(edge_count - 1, -1, -1)
            for edge_index in edge_order:
                vertex_x = np.linspace(segment_x0, segment_x1, edge_count + 1)
                x0 = float(vertex_x[edge_index])
                x1 = float(vertex_x[edge_index + 1])
                y0_img = row_center_image + vertex_amplitude_y * ((-1) ** edge_index)
                y1_img = row_center_image + vertex_amplitude_y * ((-1) ** (edge_index + 1))
                y0 = image_height - y0_img
                y1 = image_height - y1_img
                midpoint_x = (x0 + x1) / 2.0
                midpoint_y = (y0 + y1) / 2.0
                dx = x1 - x0
                dy = y1 - y0
                length = float(np.hypot(dx, dy))
                if length <= 0.0:
                    normal_x = 0.0
                    normal_y = face_offset
                else:
                    normal_x = (-dy / length) * face_offset
                    normal_y = (dx / length) * face_offset
                boards.append(
                    {
                        "hall_id": 1,
                        "hall_label": HALL_LABELS[1],
                        "hall_slot": board_number,
                        "board_number": board_number,
                        "hall_row": row_index + 1,
                        "hall_segment": unit_index + 1,
                        "hall_face_position": edge_index + 1,
                        "hall_row_direction": row_direction,
                        "hall_edge_x0": float(x0),
                        "hall_edge_y0": float(y0),
                        "hall_edge_x1": float(x1),
                        "hall_edge_y1": float(y1),
                        "hall_edge_mid_x": float(midpoint_x),
                        "hall_edge_mid_y": float(midpoint_y),
                        "hall_face_a_x": float(midpoint_x + normal_x),
                        "hall_face_a_y": float(midpoint_y + normal_y),
                        "hall_face_b_x": float(midpoint_x - normal_x),
                        "hall_face_b_y": float(midpoint_y - normal_y),
                    }
                )
                board_number += 1

    return {
        "metadata": {
            "source_images": [
                "Poster Board Numbering.png",
                "Poster Numbering Pattern.jpg",
            ],
            "source_note": (
                "Board-edge geometry was fit from the supplied OHBM layout images. "
                "Each numbered board edge has two poster faces, one on each side."
            ),
            "image_width": image_width,
            "image_height": image_height,
            "row_count": len(row_templates),
            "units_per_row": max(len(row_segments) for row_segments in row_templates),
            "edges_per_unit": 10,
            "boards_per_block": len(boards),
            "poster_faces_per_board": LAYOUT_POSTER_FACES_PER_BOARD,
            "poster_capacity_per_block": len(boards) * LAYOUT_POSTER_FACES_PER_BOARD,
            "row_templates": row_templates,
            "x_min": float(min(min(item["hall_edge_x0"], item["hall_edge_x1"]) for item in boards)),
            "x_max": float(max(max(item["hall_edge_x0"], item["hall_edge_x1"]) for item in boards)),
            "y_min": float(min(min(item["hall_edge_y0"], item["hall_edge_y1"]) for item in boards)),
            "y_max": float(max(max(item["hall_edge_y0"], item["hall_edge_y1"]) for item in boards)),
            "face_offset": face_offset,
        },
        "boards": boards,
    }


@lru_cache(maxsize=1)
def load_layout_geometry(path: str | Path = DEFAULT_LAYOUT_GEOMETRY) -> dict[str, Any]:
    geometry_path = Path(path)
    if geometry_path.exists():
        payload = json.loads(geometry_path.read_text(encoding="utf-8"))
    else:
        payload = _default_layout_geometry_payload()
    boards = payload.get("boards")
    if not isinstance(boards, list) or not boards:
        raise PosterLayoutError("Layout geometry is missing the boards list")
    return payload


@lru_cache(maxsize=1)
def _layout_board_lookup() -> dict[int, dict[str, Any]]:
    geometry = load_layout_geometry()
    boards = geometry.get("boards", [])
    lookup = {int(board["board_number"]): dict(board) for board in boards}
    if not lookup:
        raise PosterLayoutError("Layout geometry did not produce any board positions")
    return lookup


@lru_cache(maxsize=1)
def _layout_face_sequence() -> list[dict[str, Any]]:
    geometry = load_layout_geometry()
    boards = [dict(board) for board in geometry.get("boards", [])]
    boards_by_row: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for board in boards:
        boards_by_row[int(board["hall_row"])].append(board)

    sequence: list[dict[str, Any]] = []
    for hall_row in sorted(boards_by_row):
        # Use physical left-to-right board order within each row so the overall
        # face traversal snakes continuously through space rather than jumping
        # to the numbering-origin side of the next row.
        row_boards = sorted(
            boards_by_row[hall_row],
            key=lambda item: float(item.get("hall_edge_mid_x") or item.get("hall_face_a_x") or 0.0),
        )
        for board_side, face_x_key, face_y_key, side_boards in (
            ("A", "hall_face_a_x", "hall_face_a_y", row_boards),
            # Walk back along the opposite face so the full row traversal snakes
            # instead of jumping back to the far-left board before continuing.
            ("B", "hall_face_b_x", "hall_face_b_y", list(reversed(row_boards))),
        ):
            for board in side_boards:
                sequence.append(
                    {
                        **board,
                        "board_side": board_side,
                        "board_label": f"{int(board['board_number'])}{board_side}",
                        "hall_x": float(board[face_x_key]),
                        "hall_y": float(board[face_y_key]),
                    }
                )
    return sequence


def layout_slot_for_block_position(block_position: int) -> dict[str, Any]:
    if int(block_position) <= 0:
        raise PosterLayoutError("Block positions must be positive integers")

    zero_based_position = int(block_position) - 1
    face_sequence = _layout_face_sequence()
    if zero_based_position >= len(face_sequence):
        max_position = len(face_sequence)
        raise PosterLayoutError(
            f"Block position {block_position} exceeds the configured block layout capacity of {max_position} posters"
        )
    return dict(face_sequence[zero_based_position])


def build_layout_proposal(
    inputs: LayoutInputs,
    weights: OptimizationWeights | None = None,
) -> dict[str, Any]:
    weights = OptimizationWeights() if weights is None else weights
    layout_geometry = load_layout_geometry()
    layout_metadata = dict(layout_geometry.get("metadata") or {})
    assigned_records = list(inputs.records)
    session_assignments = optimize_session_assignment(assigned_records, weights=weights)
    records_by_id = {record.abstract_id: record for record in assigned_records}
    embedding_to_id = {record.embedding_index: record.abstract_id for record in assigned_records}
    shared_parent_order, shared_subcategory_order = build_shared_layout_group_order(
        assigned_records,
        inputs.normalized_matrix,
    )

    poster_numbers: dict[int, int] = {}
    block_positions: dict[int, int] = {}
    current_number = 1
    for block_id in sorted(BLOCK_TO_SESSIONS):
        block_records = [
            record
            for record in assigned_records
            if SESSION_TO_BLOCK[session_assignments[record.abstract_id]] == block_id
        ]
        ordered_indices = build_block_numeric_order(
            block_records,
            inputs.normalized_matrix,
            shared_parent_order=shared_parent_order,
            shared_subcategory_order=shared_subcategory_order,
        )
        for block_position, embedding_index in enumerate(ordered_indices, start=1):
            abstract_id = embedding_to_id[int(embedding_index)]
            poster_numbers[abstract_id] = current_number
            block_positions[abstract_id] = block_position
            current_number += 1

    final_session_assignments: dict[int, int] = {}
    for abstract_id, poster_number in poster_numbers.items():
        block_id = SESSION_TO_BLOCK[session_assignments[abstract_id]]
        final_session_assignments[abstract_id] = standby_session_for_block_and_poster_number(block_id, poster_number)

    assignments = []
    for abstract_id in sorted(final_session_assignments, key=lambda value: poster_numbers[value]):
        record = records_by_id[abstract_id]
        session_id = final_session_assignments[abstract_id]
        block_id = SESSION_TO_BLOCK[session_id]
        layout_slot = layout_slot_for_block_position(block_positions[abstract_id])
        first_standby_label, second_standby_label = standby_time_labels_for_session(session_id)
        assignments.append(
            {
                "abstract_id": abstract_id,
                "accepted_for": record.accepted_for,
                "title": record.title,
                "primary_parent_category": record.primary_parent_category,
                "primary_subcategory": record.primary_subcategory,
                "primary_category": record.primary_category,
                "layout_parent_label": record.layout_parent_label,
                "layout_exact_label": record.layout_exact_label,
                "layout_label_system": record.layout_label_system,
                "first_author_id": record.first_author_id,
                "claims_cluster_id": record.claims_cluster_id,
                "claims_cluster_label": record.claims_cluster_label,
                "standby_session": session_id,
                "standby_session_label": SESSION_LABELS[session_id],
                "first_standby_time_label": first_standby_label,
                "second_standby_time_label": second_standby_label,
                "block_id": block_id,
                "block_label": BLOCK_LABELS[block_id],
                "poster_number": poster_numbers[abstract_id],
                "block_position": block_positions[abstract_id],
                **layout_slot,
            }
        )

    return {
        "metadata": {
            "proposal_kind": "weighted_assignment",
            "proposal_method": inputs.layout_label_system,
            "poster_count": len(assigned_records),
            "oral_count": len(inputs.oral_records),
            "accepted_count": len(inputs.records),
            "claims_cluster_count": len(inputs.claims_cluster_summaries),
            "layout_label_system": inputs.layout_label_system,
            "layout_label_source": inputs.layout_label_source,
            "layout_parent_label_count": inputs.layout_parent_count,
            "layout_exact_label_count": inputs.layout_exact_count,
            "layout_has_distinct_parent_labels": inputs.layout_parent_count != inputs.layout_exact_count,
            "session_targets": _session_targets(len(assigned_records)),
            "layout_rows_per_hall": layout_metadata.get("row_count"),
            "layout_segments_per_row": layout_metadata.get("units_per_row"),
            "layout_posters_per_segment": layout_metadata.get("edges_per_unit"),
            "layout_hall_capacity": layout_metadata.get("boards_per_block"),
            "layout_halls_per_block": 1,
            "layout_poster_faces_per_board": layout_metadata.get("poster_faces_per_board"),
            "layout_geometry_source": layout_metadata.get("source_images"),
            "weights": {
                "exact_session_weight": weights.exact_session_weight,
                "parent_session_weight": weights.parent_session_weight,
                "exact_block_weight": weights.exact_block_weight,
                "parent_block_weight": weights.parent_block_weight,
                "claims_session_weight": weights.claims_session_weight,
                "claims_block_weight": weights.claims_block_weight,
                "fill_weight": weights.fill_weight,
            },
            "assumption": (
                "Assignment is optimized over all accepted abstracts, including posters and oral presentations. "
                "Each accepted abstract receives a paired standby pattern with one one-hour standby on each day of its assigned block, "
                "plus a board-face position."
            ),
        },
        "session_summaries": _session_summary(assigned_records, final_session_assignments),
        "assignments": assignments,
    }


def build_semantic_path_proposal(
    inputs: LayoutInputs,
    primary_embeddings_dir: Path,
    secondary_embeddings_dir: Path | None = None,
    config: PathProposalConfig | None = None,
) -> dict[str, Any]:
    layout_geometry = load_layout_geometry()
    layout_metadata = dict(layout_geometry.get("metadata") or {})
    assigned_records = list(inputs.records)
    records_by_id = {record.abstract_id: record for record in assigned_records}

    primary_index_by_id, primary_matrix = _load_normalized_embedding_bundle(primary_embeddings_dir)
    secondary_index_by_id: dict[int, int] | None = None
    secondary_matrix: np.ndarray | None = None
    if secondary_embeddings_dir is not None:
        secondary_index_by_id, secondary_matrix = _load_normalized_embedding_bundle(secondary_embeddings_dir)

    missing_primary = [record.abstract_id for record in assigned_records if record.abstract_id not in primary_index_by_id]
    if missing_primary:
        raise PosterLayoutError(f"Primary path embeddings are missing ids: {missing_primary[:5]}")

    config = PathProposalConfig(primary_embedding_name=primary_embeddings_dir.name) if config is None else config
    oral_seed_ids = sorted(record.abstract_id for record in inputs.oral_records)
    seed_id = oral_seed_ids[0] if oral_seed_ids else min(record.abstract_id for record in assigned_records)

    ordered_ids = build_semantic_path_order(
        assigned_records,
        primary_index_by_id,
        primary_matrix,
        secondary_index_by_id,
        secondary_matrix,
        seed_id=seed_id,
    )
    _block_by_id, block_sequences = assign_path_to_blocks(ordered_ids, records_by_id)
    poster_numbers: dict[int, int] = {}
    block_positions: dict[int, int] = {}
    current_number = 1
    for block_id in sorted(BLOCK_TO_SESSIONS):
        for block_position, abstract_id in enumerate(block_sequences[block_id], start=1):
            poster_numbers[abstract_id] = current_number
            block_positions[abstract_id] = block_position
            current_number += 1

    session_assignments = {
        abstract_id: standby_session_for_block_and_poster_number(
            1 if abstract_id in block_sequences[1] else 2,
            poster_numbers[abstract_id],
        )
        for abstract_id in poster_numbers
    }

    assignments = []
    for abstract_id in sorted(session_assignments, key=lambda value: poster_numbers[value]):
        record = records_by_id[abstract_id]
        session_id = session_assignments[abstract_id]
        block_id = SESSION_TO_BLOCK[session_id]
        layout_slot = layout_slot_for_block_position(block_positions[abstract_id])
        first_standby_label, second_standby_label = standby_time_labels_for_session(session_id)
        assignments.append(
            {
                "abstract_id": abstract_id,
                "accepted_for": record.accepted_for,
                "title": record.title,
                "primary_parent_category": record.primary_parent_category,
                "primary_subcategory": record.primary_subcategory,
                "primary_category": record.primary_category,
                "layout_parent_label": record.layout_parent_label,
                "layout_exact_label": record.layout_exact_label,
                "layout_label_system": record.layout_label_system,
                "first_author_id": record.first_author_id,
                "claims_cluster_id": record.claims_cluster_id,
                "claims_cluster_label": record.claims_cluster_label,
                "standby_session": session_id,
                "standby_session_label": SESSION_LABELS[session_id],
                "first_standby_time_label": first_standby_label,
                "second_standby_time_label": second_standby_label,
                "block_id": block_id,
                "block_label": BLOCK_LABELS[block_id],
                "poster_number": poster_numbers[abstract_id],
                "block_position": block_positions[abstract_id],
                **layout_slot,
            }
        )

    return {
        "metadata": {
            "proposal_kind": "semantic_path",
            "proposal_method": config.primary_embedding_name if config.secondary_embedding_name is None else f"{config.primary_embedding_name}+{config.secondary_embedding_name}",
            "poster_count": len(assigned_records),
            "oral_count": len(inputs.oral_records),
            "accepted_count": len(inputs.records),
            "claims_cluster_count": len(inputs.claims_cluster_summaries),
            "layout_label_system": inputs.layout_label_system,
            "layout_label_source": inputs.layout_label_source,
            "layout_parent_label_count": inputs.layout_parent_count,
            "layout_exact_label_count": inputs.layout_exact_count,
            "layout_has_distinct_parent_labels": inputs.layout_parent_count != inputs.layout_exact_count,
            "session_targets": _session_targets(len(assigned_records)),
            "layout_rows_per_hall": layout_metadata.get("row_count"),
            "layout_segments_per_row": layout_metadata.get("units_per_row"),
            "layout_posters_per_segment": layout_metadata.get("edges_per_unit"),
            "layout_hall_capacity": layout_metadata.get("boards_per_block"),
            "layout_halls_per_block": 1,
            "layout_poster_faces_per_board": layout_metadata.get("poster_faces_per_board"),
            "layout_geometry_source": layout_metadata.get("source_images"),
            "path_primary_embeddings_dir": str(primary_embeddings_dir),
            "path_secondary_embeddings_dir": None if secondary_embeddings_dir is None else str(secondary_embeddings_dir),
            "path_seed_abstract_id": seed_id,
            "path_seed_strategy": config.seed_strategy,
            "assumption": (
                "A single semantic nearest-neighbor path is built across all accepted abstracts, seeded by an oral presentation. "
                "The path is then split into two near-alternating block sequences and balanced across paired standby patterns "
                "with one one-hour standby on each day of the assigned block."
            ),
        },
        "session_summaries": _session_summary(assigned_records, session_assignments),
        "assignments": assignments,
    }


def _window_distances(
    records: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    window_size: int,
    exact_label_attr: str = "layout_exact_label",
    parent_label_attr: str = "layout_parent_label",
) -> dict[str, Any]:
    if len(records) <= 1:
        return {
            "count": len(records),
            "adjacent_pair_count": 0,
            "adjacent_mean_semantic_distance": 0.0,
            "adjacent_median_semantic_distance": 0.0,
            "adjacent_mean_category_distance": 0.0,
            "adjacent_exact_category_match_rate": 0.0,
            "adjacent_parent_category_match_rate": 0.0,
            "window_pair_count": 0,
            "window_mean_semantic_distance": 0.0,
            "window_mean_category_distance": 0.0,
            "window_exact_category_match_rate": 0.0,
            "window_parent_category_match_rate": 0.0,
        }

    adjacent_semantic: list[float] = []
    adjacent_category: list[float] = []
    adjacent_exact_matches: list[float] = []
    adjacent_parent_matches: list[float] = []
    window_semantic: list[float] = []
    window_category: list[float] = []
    window_exact_matches: list[float] = []
    window_parent_matches: list[float] = []
    for index, record in enumerate(records[:-1]):
        next_record = records[index + 1]
        record_exact_label = str(getattr(record, exact_label_attr))
        next_exact_label = str(getattr(next_record, exact_label_attr))
        record_parent_label = str(getattr(record, parent_label_attr))
        next_parent_label = str(getattr(next_record, parent_label_attr))
        adjacent_semantic.append(_cosine_distance(normalized_matrix, record.embedding_index, next_record.embedding_index))
        if record_parent_label == next_parent_label:
            adjacent_category.append(0.0 if record_exact_label == next_exact_label else 0.5)
        else:
            adjacent_category.append(1.0)
        adjacent_exact_matches.append(1.0 if record_exact_label == next_exact_label else 0.0)
        adjacent_parent_matches.append(1.0 if record_parent_label == next_parent_label else 0.0)

    for index, record in enumerate(records):
        upper_bound = min(len(records), index + window_size + 1)
        for neighbor_index in range(index + 1, upper_bound):
            other = records[neighbor_index]
            record_exact_label = str(getattr(record, exact_label_attr))
            other_exact_label = str(getattr(other, exact_label_attr))
            record_parent_label = str(getattr(record, parent_label_attr))
            other_parent_label = str(getattr(other, parent_label_attr))
            window_semantic.append(_cosine_distance(normalized_matrix, record.embedding_index, other.embedding_index))
            if record_parent_label == other_parent_label:
                window_category.append(0.0 if record_exact_label == other_exact_label else 0.5)
            else:
                window_category.append(1.0)
            window_exact_matches.append(1.0 if record_exact_label == other_exact_label else 0.0)
            window_parent_matches.append(1.0 if record_parent_label == other_parent_label else 0.0)

    return {
        "count": len(records),
        "adjacent_pair_count": len(adjacent_semantic),
        "adjacent_mean_semantic_distance": float(np.mean(adjacent_semantic)) if adjacent_semantic else 0.0,
        "adjacent_median_semantic_distance": float(np.median(adjacent_semantic)) if adjacent_semantic else 0.0,
        "adjacent_mean_category_distance": float(np.mean(adjacent_category)) if adjacent_category else 0.0,
        "adjacent_exact_category_match_rate": float(np.mean(adjacent_exact_matches)) if adjacent_exact_matches else 0.0,
        "adjacent_parent_category_match_rate": float(np.mean(adjacent_parent_matches)) if adjacent_parent_matches else 0.0,
        "window_pair_count": len(window_semantic),
        "window_mean_semantic_distance": float(np.mean(window_semantic)) if window_semantic else 0.0,
        "window_mean_category_distance": float(np.mean(window_category)) if window_category else 0.0,
        "window_exact_category_match_rate": float(np.mean(window_exact_matches)) if window_exact_matches else 0.0,
        "window_parent_category_match_rate": float(np.mean(window_parent_matches)) if window_parent_matches else 0.0,
    }


def _paired_session(session_id: int) -> int:
    if session_id == 1:
        return 2
    if session_id == 2:
        return 1
    if session_id == 3:
        return 4
    return 3


def _discoverability_metrics(records: list[AcceptedAbstract], assignments: dict[int, int]) -> dict[str, Any]:
    return _discoverability_metrics_for_labels(records, assignments, "layout_exact_label", "layout_parent_label")


def _discoverability_metrics_for_labels(
    records: list[AcceptedAbstract],
    assignments: dict[int, int],
    exact_label_attr: str,
    parent_label_attr: str,
) -> dict[str, Any]:
    exact_totals = Counter(str(getattr(record, exact_label_attr)) for record in records)
    parent_totals = Counter(str(getattr(record, parent_label_attr)) for record in records)
    exact_session_totals = Counter((str(getattr(record, exact_label_attr)), assignments[record.abstract_id]) for record in records)
    parent_session_totals = Counter((str(getattr(record, parent_label_attr)), assignments[record.abstract_id]) for record in records)

    by_session: dict[str, Any] = {}
    for session_id in SESSION_IDS:
        session_records = [record for record in records if assignments[record.abstract_id] == session_id]
        exact_other_counts: list[int] = []
        exact_paired_counts: list[int] = []
        parent_other_counts: list[int] = []
        parent_paired_counts: list[int] = []
        for record in session_records:
            paired_session_id = _paired_session(session_id)
            exact_label = str(getattr(record, exact_label_attr))
            parent_label = str(getattr(record, parent_label_attr))
            same_exact_in_session = exact_session_totals[(exact_label, session_id)]
            same_parent_in_session = parent_session_totals[(parent_label, session_id)]
            exact_other_counts.append(exact_totals[exact_label] - same_exact_in_session)
            exact_paired_counts.append(exact_session_totals[(exact_label, paired_session_id)])
            parent_other_counts.append(parent_totals[parent_label] - same_parent_in_session)
            parent_paired_counts.append(parent_session_totals[(parent_label, paired_session_id)])

        by_session[str(session_id)] = {
            "session_id": session_id,
            "paired_session_id": _paired_session(session_id),
            "mean_exact_category_posters_outside_session": float(np.mean(exact_other_counts)) if exact_other_counts else 0.0,
            "mean_exact_category_posters_in_paired_session": float(np.mean(exact_paired_counts)) if exact_paired_counts else 0.0,
            "mean_parent_category_posters_outside_session": float(np.mean(parent_other_counts)) if parent_other_counts else 0.0,
            "mean_parent_category_posters_in_paired_session": float(np.mean(parent_paired_counts)) if parent_paired_counts else 0.0,
            "fraction_with_exact_category_in_paired_session": float(np.mean([count > 0 for count in exact_paired_counts]))
            if exact_paired_counts
            else 0.0,
            "fraction_with_parent_category_in_paired_session": float(np.mean([count > 0 for count in parent_paired_counts]))
            if parent_paired_counts
            else 0.0,
        }

    return {
        "by_session": by_session,
        "overall": {
            "mean_exact_category_posters_outside_session": float(
                np.mean([metrics["mean_exact_category_posters_outside_session"] for metrics in by_session.values()])
            )
            if by_session
            else 0.0,
            "mean_exact_category_posters_in_paired_session": float(
                np.mean([metrics["mean_exact_category_posters_in_paired_session"] for metrics in by_session.values()])
            )
            if by_session
            else 0.0,
            "mean_parent_category_posters_outside_session": float(
                np.mean([metrics["mean_parent_category_posters_outside_session"] for metrics in by_session.values()])
            )
            if by_session
            else 0.0,
            "mean_parent_category_posters_in_paired_session": float(
                np.mean([metrics["mean_parent_category_posters_in_paired_session"] for metrics in by_session.values()])
            )
            if by_session
            else 0.0,
        },
    }


def _top_claims_clusters(
    records: list[AcceptedAbstract],
    cluster_summaries: dict[int, dict[str, Any]],
    limit: int = 8,
) -> list[dict[str, Any]]:
    counts = Counter(record.claims_cluster_id for record in records if record.claims_cluster_id is not None)
    rows: list[dict[str, Any]] = []
    for cluster_id, count in counts.most_common(limit):
        summary = cluster_summaries.get(int(cluster_id), {})
        rows.append(
            {
                "claims_cluster_id": int(cluster_id),
                "label": str(summary.get("label") or f"Claims cluster {cluster_id}"),
                "count": int(count),
                "keywords": list(summary.get("keywords") or []),
                "representative_abstracts": list(summary.get("representative_abstracts") or []),
                "total_size": int(summary.get("size") or count),
                "accepted_for_counts": dict(summary.get("accepted_for_counts") or {}),
            }
        )
    return rows


def _claims_category_analysis(
    records: list[AcceptedAbstract],
    ordered_records: list[AcceptedAbstract],
    assignments: dict[int, int],
    cluster_summaries: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    cluster_records = [record for record in records if record.claims_cluster_id is not None]
    if not cluster_records:
        return {
            "cluster_count": 0,
            "clusters_used_by_posters": 0,
            "overall": {},
            "top_clusters_overall": [],
            "session_top_clusters": {},
            "block_top_clusters": {},
        }

    cluster_totals = Counter(int(record.claims_cluster_id) for record in cluster_records if record.claims_cluster_id is not None)
    cluster_session_totals = Counter(
        (int(record.claims_cluster_id), assignments[record.abstract_id])
        for record in cluster_records
        if record.claims_cluster_id is not None
    )
    cluster_block_totals = Counter(
        (int(record.claims_cluster_id), SESSION_TO_BLOCK[assignments[record.abstract_id]])
        for record in cluster_records
        if record.claims_cluster_id is not None
    )

    same_cluster_outside_session: list[int] = []
    same_cluster_in_paired_session: list[int] = []
    for record in cluster_records:
        session_id = assignments[record.abstract_id]
        paired_session_id = _paired_session(session_id)
        cluster_id = int(record.claims_cluster_id)
        same_cluster_outside_session.append(cluster_totals[cluster_id] - cluster_session_totals[(cluster_id, session_id)])
        same_cluster_in_paired_session.append(cluster_session_totals[(cluster_id, paired_session_id)])

    adjacent_match_values: list[float] = []
    for left, right in zip(ordered_records, ordered_records[1:]):
        if left.claims_cluster_id is None or right.claims_cluster_id is None:
            continue
        adjacent_match_values.append(1.0 if left.claims_cluster_id == right.claims_cluster_id else 0.0)

    session_top_clusters: dict[str, Any] = {}
    for session_id in SESSION_IDS:
        session_records = [record for record in cluster_records if assignments[record.abstract_id] == session_id]
        session_top_clusters[str(session_id)] = _top_claims_clusters(session_records, cluster_summaries, limit=8)

    block_top_clusters: dict[str, Any] = {}
    for block_id in sorted(BLOCK_TO_SESSIONS):
        block_records = [
            record for record in cluster_records if SESSION_TO_BLOCK[assignments[record.abstract_id]] == block_id
        ]
        block_top_clusters[str(block_id)] = _top_claims_clusters(block_records, cluster_summaries, limit=10)

    cluster_spread = {
        cluster_id: {
            "sessions": {session_id for session_id in SESSION_IDS if cluster_session_totals[(cluster_id, session_id)] > 0},
            "blocks": {
                block_id for block_id in BLOCK_TO_SESSIONS if cluster_block_totals[(cluster_id, block_id)] > 0
            },
            "count": count,
        }
        for cluster_id, count in cluster_totals.items()
    }

    return {
        "cluster_count": len(cluster_summaries),
        "clusters_used_by_posters": len(cluster_totals),
        "overall": {
            "adjacent_same_claims_cluster_rate": float(np.mean(adjacent_match_values)) if adjacent_match_values else 0.0,
            "mean_same_claims_cluster_posters_outside_session": float(np.mean(same_cluster_outside_session))
            if same_cluster_outside_session
            else 0.0,
            "mean_same_claims_cluster_posters_in_paired_session": float(np.mean(same_cluster_in_paired_session))
            if same_cluster_in_paired_session
            else 0.0,
            "claims_clusters_single_block": sum(1 for data in cluster_spread.values() if len(data["blocks"]) == 1),
            "claims_clusters_single_block_multi_poster": sum(
                1 for data in cluster_spread.values() if len(data["blocks"]) == 1 and int(data["count"]) > 1
            ),
            "claims_clusters_all_four_sessions": sum(1 for data in cluster_spread.values() if len(data["sessions"]) == 4),
            "claims_clusters_three_plus_sessions": sum(
                1 for data in cluster_spread.values() if len(data["sessions"]) >= 3
            ),
        },
        "top_clusters_overall": _top_claims_clusters(cluster_records, cluster_summaries, limit=12),
        "session_top_clusters": session_top_clusters,
        "block_top_clusters": block_top_clusters,
    }


def _author_conflicts(records: list[AcceptedAbstract]) -> dict[str, Any]:
    author_to_records: dict[int, list[int]] = defaultdict(list)
    for record in records:
        if record.first_author_id is None:
            continue
        author_to_records[record.first_author_id].append(record.abstract_id)
    conflicts = {
        str(author_id): sorted(abstract_ids)
        for author_id, abstract_ids in author_to_records.items()
        if len(abstract_ids) > 1
    }
    return {
        "conflict_count": sum(max(0, len(abstract_ids) - 1) for abstract_ids in conflicts.values()),
        "conflicting_authors": conflicts,
    }


def _centroid_oral_matches(
    posters: list[AcceptedAbstract],
    orals: list[AcceptedAbstract],
    normalized_matrix: np.ndarray,
    top_k: int,
) -> list[dict[str, Any]]:
    if not posters or not orals:
        return []
    poster_indices = [record.embedding_index for record in posters]
    oral_indices = [record.embedding_index for record in orals]
    centroid = normalized_matrix[poster_indices].mean(axis=0)
    centroid_norm = np.linalg.norm(centroid)
    if centroid_norm > 0.0:
        centroid = centroid / centroid_norm
    similarities = normalized_matrix[oral_indices] @ centroid
    ranked_positions = np.argsort(similarities)[::-1][:top_k]
    return [
        {
            "abstract_id": orals[int(position)].abstract_id,
            "title": orals[int(position)].title,
            "primary_parent_category": orals[int(position)].primary_parent_category,
            "primary_subcategory": orals[int(position)].primary_subcategory,
            "similarity": float(similarities[int(position)]),
        }
        for position in ranked_positions
    ]


def analyze_layout_proposal(
    inputs: LayoutInputs,
    proposal: dict[str, Any],
    window_size: int = 5,
    oral_top_k: int = 10,
) -> dict[str, Any]:
    proposal_assignments = proposal.get("assignments", [])
    if not isinstance(proposal_assignments, list):
        raise PosterLayoutError("Proposal file is missing an assignments list")

    records_by_id = {record.abstract_id: record for record in inputs.records}
    ordered_posters: list[tuple[dict[str, Any], AcceptedAbstract]] = []
    for item in proposal_assignments:
        abstract_id = item.get("abstract_id")
        if not isinstance(abstract_id, int):
            raise PosterLayoutError("Proposal contains an assignment without an integer abstract_id")
        if abstract_id not in records_by_id:
            raise PosterLayoutError(f"Proposal references accepted abstract {abstract_id}, which is not in the accepted corpus")
        ordered_posters.append((item, records_by_id[abstract_id]))

    ordered_posters.sort(key=lambda item: int(item[0].get("poster_number", 0)))
    session_records: dict[int, list[AcceptedAbstract]] = {session_id: [] for session_id in SESSION_IDS}
    block_records: dict[int, list[AcceptedAbstract]] = {block_id: [] for block_id in BLOCK_TO_SESSIONS}
    for assignment, record in ordered_posters:
        session_id = int(assignment.get("standby_session"))
        block_id = int(assignment.get("block_id", SESSION_TO_BLOCK[session_id]))
        session_records[session_id].append(record)
        block_records[block_id].append(record)

    assignments_by_id = {
        int(assignment["abstract_id"]): int(assignment["standby_session"])
        for assignment, _record in ordered_posters
    }

    session_analysis: dict[str, Any] = {}
    for session_id in SESSION_IDS:
        records = session_records[session_id]
        first_standby_label, second_standby_label = standby_time_labels_for_session(session_id)
        session_analysis[str(session_id)] = {
            "session_id": session_id,
            "session_label": SESSION_LABELS[session_id],
            "block_id": SESSION_TO_BLOCK[session_id],
            "first_standby_time_label": first_standby_label,
            "second_standby_time_label": second_standby_label,
            "counts": {
                "posters": len(records),
                "layout_parent_labels": len({record.layout_parent_label for record in records}),
                "layout_exact_labels": len({record.layout_exact_label for record in records}),
                "submitter_parent_categories": len({record.primary_parent_category for record in records}),
                "submitter_subcategories": len({record.primary_category for record in records}),
                "accepted_for_counts": dict(sorted(Counter(record.accepted_for for record in records).items())),
            },
            "author_conflicts": _author_conflicts(records),
            "locality": _window_distances(records, inputs.normalized_matrix, window_size=window_size),
            "submitter_locality": _window_distances(
                records,
                inputs.normalized_matrix,
                window_size=window_size,
                exact_label_attr="primary_category",
                parent_label_attr="primary_parent_category",
            ),
            "top_claims_clusters": _top_claims_clusters(records, inputs.claims_cluster_summaries, limit=8),
            "nearest_oral_presentations": _centroid_oral_matches(
                records,
                inputs.oral_records,
                inputs.normalized_matrix,
                top_k=oral_top_k,
            ),
        }

    block_analysis: dict[str, Any] = {}
    for block_id in sorted(BLOCK_TO_SESSIONS):
        records = block_records[block_id]
        block_analysis[str(block_id)] = {
            "block_id": block_id,
            "block_label": BLOCK_LABELS[block_id],
            "counts": {
                "posters": len(records),
                "layout_parent_labels": len({record.layout_parent_label for record in records}),
                "layout_exact_labels": len({record.layout_exact_label for record in records}),
                "submitter_parent_categories": len({record.primary_parent_category for record in records}),
                "submitter_subcategories": len({record.primary_category for record in records}),
                "accepted_for_counts": dict(sorted(Counter(record.accepted_for for record in records).items())),
            },
            "locality": _window_distances(records, inputs.normalized_matrix, window_size=window_size),
            "submitter_locality": _window_distances(
                records,
                inputs.normalized_matrix,
                window_size=window_size,
                exact_label_attr="primary_category",
                parent_label_attr="primary_parent_category",
            ),
            "top_claims_clusters": _top_claims_clusters(records, inputs.claims_cluster_summaries, limit=10),
            "nearest_oral_presentations": _centroid_oral_matches(
                records,
                inputs.oral_records,
                inputs.normalized_matrix,
                top_k=oral_top_k,
            ),
        }

    all_conflicts = {
        str(session_id): session_analysis[str(session_id)]["author_conflicts"]
        for session_id in SESSION_IDS
    }
    oral_assignments = []
    for oral in inputs.oral_records:
        assigned_session_id = assignments_by_id.get(oral.abstract_id)
        first_standby_label = None
        second_standby_label = None
        if assigned_session_id is not None:
            first_standby_label, second_standby_label = standby_time_labels_for_session(assigned_session_id)
        oral_assignments.append(
            {
                "abstract_id": oral.abstract_id,
                "title": oral.title,
                "primary_parent_category": oral.primary_parent_category,
                "primary_subcategory": oral.primary_subcategory,
                "layout_parent_label": oral.layout_parent_label,
                "layout_exact_label": oral.layout_exact_label,
                "assigned_session_id": assigned_session_id,
                "assigned_session_label": None if assigned_session_id is None else SESSION_LABELS[assigned_session_id],
                "first_standby_time_label": first_standby_label,
                "second_standby_time_label": second_standby_label,
                "assigned_block_id": None if assigned_session_id is None else SESSION_TO_BLOCK[assigned_session_id],
            }
        )

    return {
        "metadata": {
            "window_size": window_size,
            "oral_top_k": oral_top_k,
            "accepted_count": len(inputs.records),
            "poster_count": len(inputs.poster_records),
            "oral_count": len(inputs.oral_records),
            "layout_label_system": inputs.layout_label_system,
            "layout_label_source": inputs.layout_label_source,
        },
        "author_conflicts_by_session": all_conflicts,
        "block_analysis": block_analysis,
        "claims_category_analysis": _claims_category_analysis(
            inputs.records,
            [record for _assignment, record in ordered_posters],
            assignments_by_id,
            inputs.claims_cluster_summaries,
        ),
        "discoverability": _discoverability_metrics(inputs.records, assignments_by_id),
        "submitter_discoverability": _discoverability_metrics_for_labels(
            inputs.records,
            assignments_by_id,
            "primary_category",
            "primary_parent_category",
        ),
        "session_analysis": session_analysis,
        "oral_presentations": oral_assignments,
    }


def write_layout_csv(path: Path, proposal: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered_assignments = sorted(
        list(proposal.get("assignments", [])),
        key=lambda item: (
            int(item.get("poster_number") or 0),
            int(item.get("abstract_id") or 0),
        ),
    )
    voyage_neighbor_scores = _ordered_neighbor_mean_cosine_similarity(
        ordered_assignments,
        DEFAULT_PROPOSAL_CSV_VOYAGE_EMBEDDINGS_DIR,
    )
    claims_neighbor_scores = _ordered_neighbor_mean_cosine_similarity(
        ordered_assignments,
        DEFAULT_PROPOSAL_CSV_CLAIMS_EMBEDDINGS_DIR,
    )
    fieldnames = [
        "poster_number",
        "board_number",
        "board_side",
        "board_label",
        "abstract_id",
        "primary_parent_category",
        "primary_subcategory",
        "primary_category",
        "title",
        "voyage_stage2_neighbor5_mean_cosine_similarity",
        "claims_neighbor5_mean_cosine_similarity",
        "standby_session",
        "standby_session_label",
        "first_standby_time_label",
        "second_standby_time_label",
        "block_id",
        "block_label",
        "block_position",
        "hall_id",
        "hall_label",
        "hall_slot",
        "hall_row",
        "hall_row_direction",
        "hall_segment",
        "hall_face_position",
        "hall_edge_x0",
        "hall_edge_y0",
        "hall_edge_x1",
        "hall_edge_y1",
        "hall_edge_mid_x",
        "hall_edge_mid_y",
        "hall_face_a_x",
        "hall_face_a_y",
        "hall_face_b_x",
        "hall_face_b_y",
        "hall_x",
        "hall_y",
        "layout_parent_label",
        "layout_exact_label",
        "layout_label_system",
        "first_author_id",
        "claims_cluster_id",
        "claims_cluster_label",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in ordered_assignments:
            abstract_id = row.get("abstract_id")
            enriched_row = dict(row)
            if isinstance(abstract_id, int):
                enriched_row["voyage_stage2_neighbor5_mean_cosine_similarity"] = voyage_neighbor_scores.get(abstract_id)
                enriched_row["claims_neighbor5_mean_cosine_similarity"] = claims_neighbor_scores.get(abstract_id)
            else:
                enriched_row["voyage_stage2_neighbor5_mean_cosine_similarity"] = None
                enriched_row["claims_neighbor5_mean_cosine_similarity"] = None
            writer.writerow({fieldname: enriched_row.get(fieldname) for fieldname in fieldnames})


def write_listing_csv(
    path: Path,
    proposal: dict[str, Any],
    authors_input: Path | None = None,
    intro_text: str = DEFAULT_LISTING_INTRO,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    author_last_names = load_author_last_names(authors_input)
    ordered_assignments = sorted(
        list(proposal.get("assignments", [])),
        key=lambda item: (
            int(item.get("poster_number") or 0),
            int(item.get("abstract_id") or 0),
        ),
    )
    # Use a UTF-8 BOM so Excel and similar spreadsheet tools reliably detect
    # Unicode surnames without mojibake.
    with path.open("w", encoding=LISTING_CSV_ENCODING, newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow([intro_text, *([""] * (len(LISTING_TEMPLATE_COLUMNS) - 1))])
        writer.writerow(list(LISTING_TEMPLATE_COLUMNS))
        for row in ordered_assignments:
            poster_number = int(row.get("poster_number") or 0)
            abstract_id = int(row.get("abstract_id") or 0)
            first_author_id = row.get("first_author_id")
            writer.writerow(
                [
                    abstract_id,
                    _format_poster_number(poster_number),
                    str(row.get("first_standby_time_label") or ""),
                    str(row.get("second_standby_time_label") or ""),
                    str(row.get("title") or ""),
                    str(row.get("primary_parent_category") or row.get("primary_category") or ""),
                    author_last_names.get(int(first_author_id), "") if isinstance(first_author_id, int) else "",
                ]
            )


def load_proposal(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def default_layout_output_dir(
    raw_input: Path = artifacts.PRIMARY_ABSTRACTS_PATH,
    embeddings_dir: Path = Path(str(artifacts.EMBEDDINGS_ROOT / "minilm_claims")),
    authors_input: Path = Path(str(artifacts.INPUT_AUTHORS_PATH)),
) -> Path:
    basis = artifacts.build_dependency_basis(
        input_sources=[str(raw_input), str(embeddings_dir), str(authors_input)],
    )
    return artifacts.build_output_path("proposals", "layout_proposal", artifacts.build_state_key(basis))


def default_layout_analysis_output_path(
    raw_input: Path = artifacts.PRIMARY_ABSTRACTS_PATH,
    embeddings_dir: Path = Path(str(artifacts.EMBEDDINGS_ROOT / "minilm_claims")),
) -> Path:
    basis = artifacts.build_dependency_basis(
        input_sources=[str(raw_input), str(embeddings_dir)],
    )
    return artifacts.build_output_path("proposals", "layout_analysis", artifacts.build_state_key(basis)) / "analysis.json"


def build_optimize_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Optimize OHBM poster standby patterns and numeric poster order")
    parser.add_argument("--raw-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_claims"))
    parser.add_argument("--authors-input", default=str(artifacts.INPUT_AUTHORS_PATH))
    parser.add_argument("--claims-cluster-assignments", default=DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS)
    parser.add_argument("--claims-cluster-summaries", default=DEFAULT_CLAIMS_CLUSTER_SUMMARIES)
    parser.add_argument("--layout-cluster-assignments")
    parser.add_argument("--layout-cluster-summaries")
    parser.add_argument("--layout-label-system", default=DEFAULT_LAYOUT_LABEL_SYSTEM)
    parser.add_argument("--output-dir", default=str(default_layout_output_dir()))
    parser.add_argument("--exact-session-weight", type=float, default=OptimizationWeights.exact_session_weight)
    parser.add_argument("--parent-session-weight", type=float, default=OptimizationWeights.parent_session_weight)
    parser.add_argument("--exact-block-weight", type=float, default=OptimizationWeights.exact_block_weight)
    parser.add_argument("--parent-block-weight", type=float, default=OptimizationWeights.parent_block_weight)
    parser.add_argument("--claims-session-weight", type=float, default=OptimizationWeights.claims_session_weight)
    parser.add_argument("--claims-block-weight", type=float, default=OptimizationWeights.claims_block_weight)
    parser.add_argument("--fill-weight", type=float, default=OptimizationWeights.fill_weight)
    return parser


def parse_optimize_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_optimize_parser().parse_args(argv)


def optimize_main(argv: list[str] | None = None) -> int:
    args = parse_optimize_args(argv)
    output_dir = Path(args.output_dir)
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.embeddings_dir),
        Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
        Path(args.layout_cluster_assignments) if args.layout_cluster_assignments else None,
        Path(args.layout_cluster_summaries) if args.layout_cluster_summaries else None,
        str(args.layout_label_system or DEFAULT_LAYOUT_LABEL_SYSTEM),
    )
    proposal = build_layout_proposal(
        inputs,
        weights=OptimizationWeights(
            exact_session_weight=float(args.exact_session_weight),
            parent_session_weight=float(args.parent_session_weight),
            exact_block_weight=float(args.exact_block_weight),
            parent_block_weight=float(args.parent_block_weight),
            claims_session_weight=float(args.claims_session_weight),
            claims_block_weight=float(args.claims_block_weight),
            fill_weight=float(args.fill_weight),
        ),
    )
    write_json(output_dir / "proposal.json", proposal)
    write_layout_csv(output_dir / "proposal.csv", proposal)
    write_listing_csv(
        output_dir / "proposal_listing.csv",
        proposal,
        authors_input=Path(args.authors_input) if args.authors_input else None,
    )
    write_json(output_dir / "session_summaries.json", proposal.get("session_summaries", {}))
    return 0


def build_analysis_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Analyze an OHBM poster layout proposal")
    parser.add_argument("--assignment", default=str(default_layout_output_dir() / "proposal.json"))
    parser.add_argument("--raw-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_claims"))
    parser.add_argument("--claims-cluster-assignments", default=DEFAULT_CLAIMS_CLUSTER_ASSIGNMENTS)
    parser.add_argument("--claims-cluster-summaries", default=DEFAULT_CLAIMS_CLUSTER_SUMMARIES)
    parser.add_argument("--layout-cluster-assignments")
    parser.add_argument("--layout-cluster-summaries")
    parser.add_argument("--layout-label-system", default=DEFAULT_LAYOUT_LABEL_SYSTEM)
    parser.add_argument("--output", default=str(default_layout_analysis_output_path()))
    parser.add_argument("--window-size", type=int, default=5)
    parser.add_argument("--oral-top-k", type=int, default=10)
    return parser


def parse_analysis_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_analysis_parser().parse_args(argv)


def analyze_main(argv: list[str] | None = None) -> int:
    args = parse_analysis_args(argv)
    inputs = load_layout_inputs(
        Path(args.raw_input),
        Path(args.embeddings_dir),
        Path(args.claims_cluster_assignments) if args.claims_cluster_assignments else None,
        Path(args.claims_cluster_summaries) if args.claims_cluster_summaries else None,
        Path(args.layout_cluster_assignments) if args.layout_cluster_assignments else None,
        Path(args.layout_cluster_summaries) if args.layout_cluster_summaries else None,
        str(args.layout_label_system or DEFAULT_LAYOUT_LABEL_SYSTEM),
    )
    proposal = load_proposal(Path(args.assignment))
    analysis = analyze_layout_proposal(
        inputs,
        proposal,
        window_size=args.window_size,
        oral_top_k=args.oral_top_k,
    )
    write_json(Path(args.output), analysis)
    session_summaries_path = Path(args.output).with_name("session_summaries.json")
    write_json(session_summaries_path, analysis.get("session_analysis", {}))
    return 0
