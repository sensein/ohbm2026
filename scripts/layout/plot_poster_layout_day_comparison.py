from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.subplots import make_subplots


SESSION_TITLES = {
    1: "June 15-16 alternating pattern A",
    2: "June 15-16 alternating pattern B",
    3: "June 17-18 alternating pattern A",
    4: "June 17-18 alternating pattern B",
}


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Plot poster paired-standby-pattern selections on the UI UMAP"
    )
    parser.add_argument("--proposal-dir", required=True)
    parser.add_argument(
        "--umap-input",
        default="data/embeddings/minilm_stage1/umap_title-introduction-methods-results-conclusion.json",
    )
    parser.add_argument("--stage1-embeddings-dir", default="data/embeddings/minilm_stage1")
    parser.add_argument("--claims-embeddings-dir", default="data/embeddings/minilm_claims")
    parser.add_argument("--neighbor-count", type=int, default=5)
    parser.add_argument("--output-html")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    proposal_dir = Path(args.proposal_dir)
    output_html = Path(args.output_html) if args.output_html else proposal_dir / "session_day_umap.html"

    proposal = load_json(proposal_dir / "proposal.json")
    umap = load_json(Path(args.umap_input))
    assignments = {int(item["abstract_id"]): int(item["standby_session"]) for item in proposal.get("assignments", [])}
    poster_numbers = {int(item["abstract_id"]): int(item["poster_number"]) for item in proposal.get("assignments", [])}
    points = list(umap.get("points") or [])

    x_values = [float(point["x"]) for point in points]
    y_values = [float(point["y"]) for point in points]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    x_pad = (x_max - x_min) * 0.05
    y_pad = (y_max - y_min) * 0.05

    figure = make_subplots(
        rows=2,
        cols=2,
        subplot_titles=(
            SESSION_TITLES[1],
            SESSION_TITLES[2],
            SESSION_TITLES[3],
            SESSION_TITLES[4],
        ),
        horizontal_spacing=0.05,
        vertical_spacing=0.08,
    )

    for session_id in (1, 2, 3, 4):
        row = 1 if session_id in (1, 2) else 2
        col = 1 if session_id in (1, 3) else 2
        colorbar_x = 0.46 if col == 1 else 1.02
        colorbar_y = 0.82 if row == 1 else 0.28

        figure.add_trace(
            go.Scattergl(
                x=x_values,
                y=y_values,
                mode="markers",
                marker={"size": 5, "color": "rgba(160,160,160,0.20)"},
                name="All accepted",
                showlegend=session_id == 1,
                hoverinfo="skip",
            ),
            row=row,
            col=col,
        )

        selected_points = sorted(
            [point for point in points if assignments.get(int(point["id"])) == session_id],
            key=lambda point: poster_numbers[int(point["id"])],
        )
        selected_poster_numbers = [poster_numbers[int(point["id"])] for point in selected_points]
        color_min = min(selected_poster_numbers) if selected_poster_numbers else 1
        color_max = max(selected_poster_numbers) if selected_poster_numbers else 1
        if color_min == color_max:
            color_max = color_min + 1

        customdata = [
            [
                int(point["id"]),
                int(poster_numbers[int(point["id"])]),
                str(point.get("title") or "Untitled"),
                str(point.get("accepted_for") or "Unknown"),
                str(point.get("primary_topic") or "Unknown"),
            ]
            for point in selected_points
        ]
        figure.add_trace(
            go.Scatter(
                x=[float(point["x"]) for point in selected_points],
                y=[float(point["y"]) for point in selected_points],
                mode="markers",
                marker={
                    "size": 6,
                    "opacity": 0.92,
                    "color": selected_poster_numbers,
                    "colorscale": "Viridis",
                    "cmin": color_min,
                    "cmax": color_max,
                    "colorbar": {
                        "title": "Poster number",
                        "len": 0.28,
                        "x": colorbar_x,
                        "y": colorbar_y,
                    },
                    "showscale": True,
                    "line": {"width": 0},
                },
                name=f"{SESSION_TITLES[session_id]} abstracts",
                showlegend=False,
                customdata=customdata,
                hovertemplate=(
                    "Poster %{customdata[1]}<br>"
                    "%{customdata[2]}<br>"
                    "%{customdata[3]}<br>"
                    "%{customdata[4]}<extra></extra>"
                ),
            ),
            row=row,
            col=col,
        )

        figure.update_xaxes(range=[x_min - x_pad, x_max + x_pad], row=row, col=col, title_text="UMAP x")
        figure.update_yaxes(range=[y_min - y_pad, y_max + y_pad], row=row, col=col, title_text="UMAP y")

    figure.update_layout(
        title=(
            f"Accepted Abstract Standby Pattern Selection on UI UMAP: {proposal_dir.name}<br>"
            "<sup>Grey = all accepted abstracts; colored dots = abstracts in that paired standby pattern shaded by poster number.</sup>"
        ),
        template="plotly_white",
        height=1000,
        width=1320,
        legend={"orientation": "h", "y": 1.03},
        hovermode="closest",
    )

    output_html.parent.mkdir(parents=True, exist_ok=True)
    figure.write_html(str(output_html), include_plotlyjs="cdn")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
