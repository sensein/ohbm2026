"""Stage 4 projections: UMAP + t-SNE visualization helpers.

Owns the legacy projection surface lifted out of the monolithic
`analyze.py`:

- 2D / 3D UMAP + t-SNE fit helpers (`compute_umap_projection`,
  `compute_tsne_projection`).
- HTML comparison + interactive panel builders
  (`write_projection_comparison_outputs`,
  `_add_projection_panel_traces`, `_build_linked_highlight_script`).
- Per-bundle UMAP output writers (`write_umap_outputs`,
  `default_umap_output_paths`, `default_projection_output_paths`).
- Projection scoring + hyperparameter optimization
  (`build_projection_graph`, `score_projection`,
  `_cluster_distance_metrics`, `optimize_projection_parameters`,
  `_projection_rank_key`).
- CLI entrypoints (`umap_main`, `projection_compare_main`,
  `projection_optimize_main`).

The Stage 4 `project_into_umap(new_vectors, bundle, algorithm=…)`
function (US2) lands in `analyze/umap.py` separately; this module is
the home for legacy visualization helpers retained for the existing
test surface and downstream scripts.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

import numpy as np

from ohbm2026 import artifacts
from ohbm2026.analyze.clusters import (
    _cluster_distance_metrics,
    detect_semantic_communities,
)
from ohbm2026.analyze.storage import (
    DEFAULT_EMBEDDING_FIELDS,
    NeuroScapeError,
    build_distinct_color_map,
    build_embedding_output_name,
    build_embedding_visualization_title,
    build_visualization_records,
    embedding_variant_name,
    extract_primary_topic,
    extract_raw_keywords,
    load_annotation_lookup,
    load_embedding_bundle,
    load_title_lookup,
    model_name_slug,
    normalize_embedding_fields,
    parse_string_list_value,
    unique_strings,
    write_json,
)

DEFAULT_UMAP_NEIGHBORS = 15
DEFAULT_UMAP_MIN_DIST = 0.1
DEFAULT_TSNE_PERPLEXITY = 30.0
DEFAULT_TSNE_LEARNING_RATE = "auto"
DEFAULT_TSNE_EARLY_EXAGGERATION = 12.0


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
    basis = artifacts.build_dependency_basis(
        input_sources=[str(embeddings_dir)],
        options={"embedding_fields": embedding_fields},
    )
    output_root = artifacts.build_output_path("experiments", basename, artifacts.build_state_key(basis))
    return output_root / "report.html", output_root / "projection.json"


def default_projection_output_paths(
    embeddings_dir: Path,
    embedding_fields: list[str],
) -> tuple[Path, Path]:
    fieldset = "-".join(embedding_fields)
    basename = f"projection_comparison_{fieldset}"
    basis = artifacts.build_dependency_basis(
        input_sources=[str(embeddings_dir)],
        options={"embedding_fields": embedding_fields},
    )
    output_root = artifacts.build_output_path("experiments", basename, artifacts.build_state_key(basis))
    return output_root / "report.html", output_root / "projection.json"


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
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
    parser.add_argument("--raw-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--enriched-input", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
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
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
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
    parser.add_argument("--embeddings-dir", default=str(artifacts.EMBEDDINGS_ROOT / "minilm_stage1"))
    parser.add_argument("--raw-input", default=str(artifacts.PRIMARY_ABSTRACTS_PATH))
    parser.add_argument("--enriched-input", default=str(artifacts.PRIMARY_ENRICHED_ABSTRACTS_PATH))
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
