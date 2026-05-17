from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import plotly.graph_objects as go
import plotly.io as pio
import umap

from ohbm2026.analyze.storage import build_distinct_color_map


def load_dataset(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _parse_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return [text]
    if isinstance(parsed, list):
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [str(parsed).strip()]


def _extract_primary_topic(abstract: dict[str, Any]) -> str:
    for response in list(abstract.get("responses") or []):
        if not isinstance(response, dict):
            continue
        question_name = str(response.get("question_name") or "").strip().lower()
        if question_name != "primary parent category & sub-category":
            continue
        values = _parse_string_list(response.get("value"))
        if values:
            return values[0]
    return "Unknown"


def _extract_keywords(abstract: dict[str, Any], limit: int = 6) -> list[str]:
    for response in list(abstract.get("responses") or []):
        if not isinstance(response, dict):
            continue
        question_name = str(response.get("question_name") or "").strip().lower()
        if question_name != "keywords":
            continue
        return _parse_string_list(response.get("value"))[:limit]
    return []


def load_records_by_id(abstracts_path: Path) -> dict[int, dict[str, Any]]:
    payload = load_json(abstracts_path)
    raw_abstracts = list(payload.get("abstracts") or [])
    records_by_id: dict[int, dict[str, Any]] = {}
    for abstract in raw_abstracts:
        if not isinstance(abstract, dict):
            continue
        abstract_id = abstract.get("id")
        if not isinstance(abstract_id, int):
            continue
        records_by_id[int(abstract_id)] = {
            "id": int(abstract_id),
            "title": str(abstract.get("title") or "Untitled"),
            "accepted_for": str(abstract.get("accepted_for") or "Unknown"),
            "primary_topic": _extract_primary_topic(abstract),
            "keywords": _extract_keywords(abstract),
        }
    return records_by_id


def load_cluster_labels(assignments_path: Path, summaries_path: Path) -> dict[int, str]:
    assignment_payload = load_json(assignments_path)
    summary_payload = load_json(summaries_path)
    raw_assignments = assignment_payload.get("assignments", assignment_payload)
    raw_clusters = summary_payload.get("clusters", summary_payload)
    cluster_labels = {
        int(item["cluster_id"]): str(item.get("label") or f"Cluster {int(item['cluster_id'])}")
        for item in raw_clusters
        if isinstance(item, dict) and item.get("cluster_id") is not None
    }
    return {
        int(abstract_id): cluster_labels.get(int(cluster_id), f"Cluster {int(cluster_id)}")
        for abstract_id, cluster_id in raw_assignments.items()
    }


def compute_umap_3d(
    matrix: np.ndarray,
    n_neighbors: int,
    min_dist: float,
    metric: str,
    random_state: int,
) -> np.ndarray:
    reducer = umap.UMAP(
        n_components=3,
        n_neighbors=int(n_neighbors),
        min_dist=float(min_dist),
        metric=str(metric),
        random_state=int(random_state),
    )
    return np.asarray(reducer.fit_transform(matrix), dtype=np.float32)


def _camera_eye(angle_radians: float, radius: float, height: float) -> dict[str, float]:
    return {
        "x": float(radius * math.cos(angle_radians)),
        "y": float(radius * math.sin(angle_radians)),
        "z": float(height),
    }


def _rotation_step_radians(frame_count: int) -> float:
    safe_frame_count = max(1, int(frame_count))
    return (2.0 * math.pi) / float(safe_frame_count)


def render_rotating_html(
    figure: go.Figure,
    legend_rows: list[dict[str, Any]],
    frame_count: int,
    orbit_radius: float,
    orbit_height: float,
    interval_ms: int = 90,
) -> str:
    div_id = "voyage-stage2-umap-3d"
    plot_html = pio.to_html(
        figure,
        include_plotlyjs="cdn",
        full_html=False,
        div_id=div_id,
        default_width="100%",
        default_height="calc(100vh - 150px)",
        config={"responsive": True, "displaylogo": False},
    )
    step = _rotation_step_radians(frame_count)
    legend_markup = "".join(
        (
            f'<div class="legend-item">'
            f'<span class="legend-swatch" style="background:{row["color"]};"></span>'
            f'<span class="legend-label">{row["label"]}</span>'
            f'<span class="legend-count">{int(row["count"])}</span>'
            f"</div>"
        )
        for row in legend_rows
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Voyage Stage 2 Embeddings: 3D UMAP</title>
    <style>
      body {{
        margin: 0;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        background: #edf5f6;
        color: #1f2933;
      }}
      .shell {{
        min-height: 100vh;
        display: grid;
        grid-template-rows: auto 1fr;
      }}
      .toolbar {{
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        gap: 20px;
        padding: 16px 18px 12px;
        border-bottom: 1px solid rgba(185, 209, 204, 0.95);
        background: rgba(255, 255, 255, 0.88);
      }}
      .title-block h1 {{
        margin: 0 0 6px;
        font-size: 24px;
      }}
      .title-block p {{
        margin: 0;
        color: #52606d;
        line-height: 1.45;
        max-width: 820px;
      }}
      .controls {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }}
      .controls button {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
        padding: 8px 12px;
        cursor: pointer;
        font-weight: 600;
      }}
      .status {{
        color: #5f6c7b;
        font-size: 14px;
      }}
      .content {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) 300px;
        min-height: 0;
      }}
      .plot-panel {{
        padding: 10px 12px 14px;
      }}
      .legend-panel {{
        border-left: 1px solid rgba(185, 209, 204, 0.95);
        background: rgba(255, 255, 255, 0.92);
        padding: 14px 14px 18px;
        overflow-y: auto;
      }}
      .legend-panel h2 {{
        margin: 0 0 10px;
        font-size: 16px;
      }}
      .legend-note {{
        margin: 0 0 12px;
        color: #52606d;
        font-size: 13px;
        line-height: 1.4;
      }}
      .legend-list {{
        display: grid;
        gap: 8px;
      }}
      .legend-item {{
        display: grid;
        grid-template-columns: 12px minmax(0, 1fr) auto;
        gap: 8px;
        align-items: center;
        font-size: 13px;
      }}
      .legend-swatch {{
        width: 12px;
        height: 12px;
        border-radius: 999px;
        box-shadow: inset 0 0 0 1px rgba(15, 23, 42, 0.18);
      }}
      .legend-label {{
        overflow-wrap: anywhere;
      }}
      .legend-count {{
        color: #52606d;
        font-variant-numeric: tabular-nums;
      }}
      @media (max-width: 1180px) {{
        .toolbar,
        .content {{
          grid-template-columns: 1fr;
          display: grid;
        }}
        .legend-panel {{
          border-left: 0;
          border-top: 1px solid rgba(185, 209, 204, 0.95);
          max-height: 280px;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <div class="toolbar">
        <div class="title-block">
          <h1>Voyage Stage 2 Embeddings: 3D UMAP</h1>
          <p>Interactive 3D UMAP of all accepted abstracts, colored by the Voyage stage 2 spectral cluster labels. Hover a point for title and topic details.</p>
        </div>
        <div class="controls">
          <button id="rotate-button" type="button">Rotate</button>
          <button id="pause-button" type="button">Pause</button>
          <span id="rotation-status" class="status">Rotation: running</span>
        </div>
      </div>
      <div class="content">
        <div class="plot-panel">
          {plot_html}
        </div>
        <aside class="legend-panel">
          <h2>Voyage 31 Clusters</h2>
          <p class="legend-note">Counts show how many abstracts fall in each spectral cluster.</p>
          <div class="legend-list">{legend_markup}</div>
        </aside>
      </div>
    </div>
    <script>
      (function() {{
        const gd = document.getElementById({json.dumps(div_id)});
        const rotateButton = document.getElementById('rotate-button');
        const pauseButton = document.getElementById('pause-button');
        const status = document.getElementById('rotation-status');
        let angle = 0.0;
        let timer = null;
        const step = {step};
        const intervalMs = {int(interval_ms)};
        const radius = {float(orbit_radius)};
        const height = {float(orbit_height)};

        function setStatus(value) {{
          if (status) {{
            status.textContent = value;
          }}
        }}

        function cameraEye() {{
          return {{
            x: radius * Math.cos(angle),
            y: radius * Math.sin(angle),
            z: height
          }};
        }}

        function applyCamera() {{
          Plotly.relayout(gd, {{'scene.camera.eye': cameraEye()}});
        }}

        function startRotation() {{
          if (timer !== null) {{
            return;
          }}
          timer = window.setInterval(() => {{
            angle += step;
            applyCamera();
          }}, intervalMs);
          setStatus('Rotation: running');
        }}

        function stopRotation() {{
          if (timer !== null) {{
            window.clearInterval(timer);
            timer = null;
          }}
          setStatus('Rotation: paused');
        }}

        rotateButton?.addEventListener('click', startRotation);
        pauseButton?.addEventListener('click', stopRotation);
        startRotation();
      }})();
    </script>
  </body>
</html>
"""


def build_figure(
    coordinates: np.ndarray,
    ordered_ids: list[int],
    records_by_id: dict[int, dict[str, Any]],
    cluster_label_by_id: dict[int, str],
    frame_count: int,
    orbit_radius: float,
    orbit_height: float,
) -> go.Figure:
    labels = [cluster_label_by_id.get(abstract_id, "Unknown") for abstract_id in ordered_ids]
    color_map = build_distinct_color_map(labels)
    grouped_indices: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        grouped_indices.setdefault(label, []).append(index)

    figure = go.Figure()
    legend_rows: list[dict[str, Any]] = []
    for label in sorted(grouped_indices, key=lambda item: (-len(grouped_indices[item]), item)):
        indices = grouped_indices[label]
        legend_rows.append(
            {
                "label": label,
                "count": len(indices),
                "color": color_map.get(label, "hsl(0, 0%, 50%)"),
            }
        )
        customdata = [
            [
                ordered_ids[index],
                records_by_id[ordered_ids[index]]["title"],
                records_by_id[ordered_ids[index]]["accepted_for"],
                records_by_id[ordered_ids[index]]["primary_topic"],
                ", ".join(records_by_id[ordered_ids[index]]["keywords"]),
                label,
            ]
            for index in indices
        ]
        figure.add_trace(
            go.Scatter3d(
                x=coordinates[indices, 0],
                y=coordinates[indices, 1],
                z=coordinates[indices, 2],
                mode="markers",
                name=label,
                legendgroup=label,
                marker={
                    "size": 3.5,
                    "opacity": 0.85,
                    "color": color_map.get(label, "hsl(0, 0%, 50%)"),
                },
                customdata=customdata,
                hovertemplate=(
                    "id=%{customdata[0]}<br>"
                    "title=%{customdata[1]}<br>"
                    "accepted_for=%{customdata[2]}<br>"
                    "primary_topic=%{customdata[3]}<br>"
                    "voyage31_label=%{customdata[5]}<br>"
                    "keywords=%{customdata[4]}<extra></extra>"
                ),
                showlegend=False,
            )
        )

    initial_eye = _camera_eye(0.0, orbit_radius, orbit_height)
    figure.update_layout(
        template="plotly_white",
        height=920,
        scene={
            "xaxis_title": "UMAP-1",
            "yaxis_title": "UMAP-2",
            "zaxis_title": "UMAP-3",
            "camera": {"eye": initial_eye},
            "aspectmode": "data",
        },
        margin={"l": 0, "r": 0, "t": 0, "b": 0},
    )
    return figure, legend_rows


def write_outputs(
    output_dir: Path,
    coordinates: np.ndarray,
    ordered_ids: list[int],
    records_by_id: dict[int, dict[str, Any]],
    cluster_label_by_id: dict[int, str],
    n_neighbors: int,
    min_dist: float,
    metric: str,
    random_state: int,
    frame_count: int,
    orbit_radius: float,
    orbit_height: float,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    figure, legend_rows = build_figure(
        coordinates=coordinates,
        ordered_ids=ordered_ids,
        records_by_id=records_by_id,
        cluster_label_by_id=cluster_label_by_id,
        frame_count=frame_count,
        orbit_radius=orbit_radius,
        orbit_height=orbit_height,
    )
    html_path = output_dir / "voyage_stage2_umap_3d.html"
    html = render_rotating_html(
        figure,
        legend_rows=legend_rows,
        frame_count=frame_count,
        orbit_radius=orbit_radius,
        orbit_height=orbit_height,
        interval_ms=90,
    )
    write_text(html_path, html)

    points = []
    for index, abstract_id in enumerate(ordered_ids):
        record = records_by_id[abstract_id]
        points.append(
            {
                "id": int(abstract_id),
                "title": str(record["title"]),
                "accepted_for": str(record["accepted_for"]),
                "primary_topic": str(record["primary_topic"]),
                "keywords": list(record["keywords"]),
                "voyage31_label": str(cluster_label_by_id.get(abstract_id, "Unknown")),
                "x": float(coordinates[index, 0]),
                "y": float(coordinates[index, 1]),
                "z": float(coordinates[index, 2]),
            }
        )
    write_json(
        output_dir / "voyage_stage2_umap_3d.json",
        {
            "count": len(points),
            "points": points,
        },
    )
    diagnostics = {
        "embedding_dir": "data/embeddings/voyage_stage2_published",
        "cluster_label_system": "voyage_stage2_spectral_31",
        "count": len(ordered_ids),
        "umap_n_components": 3,
        "umap_n_neighbors": int(n_neighbors),
        "umap_min_dist": float(min_dist),
        "umap_metric": str(metric),
        "random_state": int(random_state),
        "frame_count": int(frame_count),
        "orbit_radius": float(orbit_radius),
        "orbit_height": float(orbit_height),
    }
    write_json(output_dir / "diagnostics.json", diagnostics)
    write_text(
        output_dir / "summary.md",
        "\n".join(
            [
                "# Voyage Stage 2 3D UMAP",
                "",
                f"- Count: `{len(ordered_ids)}` abstracts",
                f"- UMAP params: `n_neighbors={int(n_neighbors)}`, `min_dist={float(min_dist)}`, `metric={metric}`, `random_state={int(random_state)}`",
                f"- Rotation params: `frames={int(frame_count)}`, `radius={float(orbit_radius)}`, `height={float(orbit_height)}`",
                f"- Main output: `{html_path}`",
                "",
            ]
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a rotating 3D UMAP for Voyage stage 2 embeddings")
    parser.add_argument("--abstracts-input", default="data/abstracts.json")
    parser.add_argument("--embeddings-dir", default="data/embeddings/voyage_stage2_published")
    parser.add_argument(
        "--cluster-assignments",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json",
    )
    parser.add_argument(
        "--cluster-summaries",
        default="data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json",
    )
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--n-neighbors", type=int, default=30)
    parser.add_argument("--min-dist", type=float, default=0.05)
    parser.add_argument("--metric", default="cosine")
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--frame-count", type=int, default=120)
    parser.add_argument("--orbit-radius", type=float, default=1.9)
    parser.add_argument("--orbit-height", type=float, default=0.8)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    embeddings_dir = Path(args.embeddings_dir)
    metadata = load_json(embeddings_dir / "metadata.json")
    ordered_ids = [int(value) for value in list(metadata.get("ids") or [])]
    vectors = np.asarray(np.load(embeddings_dir / "vectors.npy"), dtype=np.float32)
    if vectors.shape[0] != len(ordered_ids):
        raise RuntimeError("Voyage stage 2 metadata ids do not align with vectors.npy")

    records_by_id = load_records_by_id(Path(args.abstracts_input))
    missing_ids = [abstract_id for abstract_id in ordered_ids if abstract_id not in records_by_id]
    if missing_ids:
        raise RuntimeError(f"Missing {len(missing_ids)} abstract records for Voyage stage 2 bundle")
    cluster_label_by_id = load_cluster_labels(Path(args.cluster_assignments), Path(args.cluster_summaries))
    coordinates = compute_umap_3d(
        matrix=vectors,
        n_neighbors=args.n_neighbors,
        min_dist=args.min_dist,
        metric=str(args.metric),
        random_state=args.random_state,
    )
    write_outputs(
        output_dir=Path(args.output_dir),
        coordinates=coordinates,
        ordered_ids=ordered_ids,
        records_by_id=records_by_id,
        cluster_label_by_id=cluster_label_by_id,
        n_neighbors=args.n_neighbors,
        min_dist=args.min_dist,
        metric=str(args.metric),
        random_state=args.random_state,
        frame_count=args.frame_count,
        orbit_radius=args.orbit_radius,
        orbit_height=args.orbit_height,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
