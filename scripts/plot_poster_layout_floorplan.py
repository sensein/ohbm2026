from __future__ import annotations

import argparse
import html
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import plotly.graph_objects as go
from plotly.offline.offline import get_plotlyjs

from ohbm2026.analyze import build_distinct_color_map
from ohbm2026.poster_layout import layout_slot_for_block_position, load_layout_geometry

DEFAULT_UI_UMAP = "export/ui-site/data/projection.umap.json"
VOYAGE25_ASSIGNMENTS = Path("data/embeddings/voyage_stage2_published/clustering_benchmark/cluster_assignments.json")
VOYAGE25_SUMMARIES = Path("data/embeddings/voyage_stage2_published/clustering_benchmark/cluster_summaries.json")
VOYAGE31_ASSIGNMENTS = Path("data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_assignments.json")
VOYAGE31_SUMMARIES = Path("data/embeddings/voyage_stage2_published/clustering_benchmark_spectral/cluster_summaries.json")
CLAIMS28_ASSIGNMENTS = Path("data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_assignments.json")
CLAIMS28_SUMMARIES = Path("data/embeddings/minilm_claims/clustering_benchmark_25_30/cluster_summaries.json")


LINKED_SELECTION_POST_SCRIPT = r"""
const plotIds = ['block-1-plot', 'block-2-plot', 'umap-plot'];
const plots = Object.fromEntries(plotIds.map((id) => [id, document.getElementById(id)]).filter(([, value]) => Boolean(value)));
const plotConfigs = __PLOT_CONFIGS__;
const filterRecords = __FILTER_RECORDS__;
const filterGroups = {
  categorical_primary_label: { label: 'Categorical primary' },
  voyage25_label: { label: 'Voyage 25' },
  voyage31_label: { label: 'Voyage 31' },
  claims28_label: { label: 'Claims 28' },
};
const colorModeButtons = Array.from(document.querySelectorAll('[data-color-mode]'));
const clearFiltersButton = document.getElementById('clear-category-filters');
const clearSelectionButton = document.getElementById('clear-plot-selection');
const modeLabel = document.getElementById('current-color-mode');
const selectionStatus = document.getElementById('linked-selection-status');
const correspondence = document.getElementById('category-correspondence');
const detailPanel = document.getElementById('poster-detail-card');
let currentMode = __DEFAULT_MODE__;
let interactionSelection = null;
let filterSelection = null;
let pinnedDetail = null;
let hoveredDetail = null;
let syncing = false;
const defaultSelectionText = 'Lasso or click in any plot to select posters across both blocks and the UMAP.';

function selectedValues(groupName) {
  const checked = Array.from(document.querySelectorAll(`input[data-filter-group="${groupName}"]:checked`));
  return new Set(checked.map((item) => item.value));
}

function updateFacetMeta() {
  Object.keys(filterGroups).forEach((groupName) => {
    const meta = document.querySelector(`[data-filter-meta="${groupName}"]`);
    if (!meta) {
      return;
    }
    const count = selectedValues(groupName).size;
    meta.textContent = count ? `${count} selected` : 'All';
  });
}

function currentFilterIds() {
  const activeGroups = Object.keys(filterGroups).map((groupName) => [groupName, selectedValues(groupName)]);
  const hasFilters = activeGroups.some(([, values]) => values.size > 0);
  if (!hasFilters) {
    return null;
  }
  const selected = new Set();
  filterRecords.forEach((record) => {
    const matches = activeGroups.every(([groupName, values]) => {
      if (values.size === 0) {
        return true;
      }
      return values.has(String(record[groupName] ?? 'Unknown'));
    });
    if (matches) {
      selected.add(String(record.abstract_id));
    }
  });
  return selected;
}

function effectiveSelection() {
  if (filterSelection && interactionSelection) {
    const intersection = new Set();
    filterSelection.forEach((item) => {
      if (interactionSelection.has(item)) {
        intersection.add(item);
      }
    });
    return intersection;
  }
  return interactionSelection || filterSelection || null;
}

function selectionIndicesForTrace(trace, selectedIds) {
  if (!Array.isArray(trace.customdata)) {
    return null;
  }
  const indices = [];
  trace.customdata.forEach((item, index) => {
    const abstractId = Array.isArray(item) ? item[0] : null;
    if (abstractId !== null && selectedIds && selectedIds.has(String(abstractId))) {
      indices.push(index);
    }
  });
  return selectedIds && selectedIds.size ? indices : null;
}

function activateButtons(value) {
  colorModeButtons.forEach((button) => {
    const active = button.dataset.colorMode === value;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

function applyColorMode(modeName) {
  currentMode = modeName;
  Object.entries(plots).forEach(([plotId, plot]) => {
    const config = plotConfigs[plotId];
    if (!config) {
      return;
    }
    const visible = new Array(plot.data.length).fill(false);
    (config.background || []).forEach((index) => {
      visible[index] = true;
    });
    ((config.modes || {})[modeName] || []).forEach((index) => {
      visible[index] = true;
    });
    const traceIndices = plot.data.map((_trace, index) => index);
    Plotly.restyle(plot, { visible }, traceIndices);
  });
  activateButtons(modeName);
  if (modeLabel) {
    const labels = {
      categorical_primary_label: 'Categorical primary',
      voyage25_label: 'Voyage 25',
      voyage31_label: 'Voyage 31',
      claims28_label: 'Claims 28',
    };
    modeLabel.textContent = labels[modeName] || modeName;
  }
  applySelection();
  resizePlots();
}

function detailHtml(customdata) {
  if (!customdata) {
    return `
      <div class="detail-empty">
        <strong>No poster selected</strong>
        <p>Hover or click a poster in any plot to inspect its details here.</p>
      </div>
    `;
  }
  return `
    <div class="detail-kicker">${customdata[13]}</div>
    <h3>${customdata[3]}</h3>
    <div class="detail-grid">
      <div><span>Poster</span><strong>${customdata[1]}</strong></div>
      <div><span>Board</span><strong>${customdata[2]}</strong></div>
      <div><span>Standby</span><strong>${customdata[4]}</strong></div>
      <div><span>Block</span><strong>${customdata[7]}</strong></div>
      <div><span>Categorical primary</span><strong>${customdata[5]}</strong></div>
      <div><span>Voyage 25</span><strong>${customdata[6]}</strong></div>
      <div><span>Voyage 31</span><strong>${customdata[14]}</strong></div>
      <div><span>Claims 28</span><strong>${customdata[15]}</strong></div>
      <div><span>Location</span><strong>Row ${customdata[10]}, unit ${customdata[11]}, edge ${customdata[12]}, side ${customdata[9]}</strong></div>
    </div>
  `;
}

function renderDetails() {
  if (!detailPanel) {
    return;
  }
  const activeDetail = hoveredDetail || pinnedDetail;
  detailPanel.innerHTML = detailHtml(activeDetail);
  if (window.parent !== window) {
    window.parent.postMessage({ type: 'layout-review-detail', html: detailPanel.innerHTML }, '*');
  }
}

function updateCorrespondenceSummary() {
  if (!correspondence) {
    return;
  }
  const activeGroups = Object.keys(filterGroups).map((groupName) => [groupName, selectedValues(groupName)]);
  const hasFilters = activeGroups.some(([, values]) => values.size > 0);
  const matchingRecords = filterRecords.filter((record) => {
    return activeGroups.every(([groupName, values]) => {
      if (values.size === 0) {
        return true;
      }
      return values.has(String(record[groupName] ?? 'Unknown'));
    });
  });
  if (!hasFilters) {
    correspondence.textContent = 'No category filters applied.';
    return;
  }
  const summary = [`${matchingRecords.length} posters match the active filters.`];
  activeGroups.forEach(([groupName, values]) => {
    if (values.size > 0) {
      const picked = Array.from(values);
      summary.push(`${filterGroups[groupName].label}: ${picked.slice(0, 3).join('; ')}${picked.length > 3 ? '…' : ''}`);
    }
  });
  correspondence.textContent = summary.join(' ');
}

function applySelection() {
  const selectedIds = effectiveSelection();
  syncing = true;
  Object.values(plots).forEach((plot) => {
    const selectedpoints = plot.data.map((trace) => selectionIndicesForTrace(trace, selectedIds));
    const traceIndices = plot.data.map((_trace, index) => index);
    Plotly.restyle(plot, { selectedpoints }, traceIndices);
  });
  syncing = false;
  if (selectionStatus) {
    selectionStatus.textContent = selectedIds && selectedIds.size
      ? `${selectedIds.size} posters selected across both hall blocks and the UMAP.`
      : defaultSelectionText;
  }
  updateCorrespondenceSummary();
}

function updateFilters() {
  filterSelection = currentFilterIds();
  applySelection();
}

function setDetailFromEventPoint(point, pin) {
  const customdata = point?.customdata || null;
  if (!customdata) {
    return;
  }
  if (pin) {
    pinnedDetail = customdata;
  } else {
    hoveredDetail = customdata;
  }
  renderDetails();
}

function clearInteractionSelection() {
  interactionSelection = null;
  pinnedDetail = null;
  hoveredDetail = null;
  renderDetails();
  applySelection();
  Object.values(plots).forEach((plot) => {
    if (!plot) {
      return;
    }
    Plotly.relayout(plot, { selections: [] });
    if (Plotly.Fx && typeof Plotly.Fx.unhover === 'function') {
      Plotly.Fx.unhover(plot);
    }
  });
}

function hasActiveInteractionSelection() {
  return Boolean(interactionSelection && interactionSelection.size);
}

function plotHasSelectionOverlay(plot) {
  const selections = plot?.layout?.selections || plot?._fullLayout?.selections || [];
  return Array.isArray(selections) && selections.length > 0;
}

function resizePlots() {
  Object.values(plots).forEach((plot) => {
    Plotly.Plots.resize(plot);
  });
  reportLayoutReviewHeight();
}

Object.values(plots).forEach((plot) => {
  plot.on('plotly_selected', (event) => {
    if (syncing) {
      return;
    }
    interactionSelection = new Set(
      (event?.points || [])
        .map((point) => point.customdata?.[0])
        .filter((value) => value !== null && value !== undefined)
        .map((value) => String(value))
    );
    applySelection();
  });

  plot.on('plotly_click', (event) => {
    if (syncing) {
      return;
    }
    if (plotHasSelectionOverlay(plot) || (hasActiveInteractionSelection() && plotHasSelectedPoints(plot))) {
      return;
    }
    const point = event?.points?.[0];
    const firstId = point?.customdata?.[0];
    if (firstId === null || firstId === undefined) {
      return;
    }
    interactionSelection = new Set([String(firstId)]);
    setDetailFromEventPoint(point, true);
    applySelection();
  });

  plot.on('plotly_hover', (event) => {
    const point = event?.points?.[0];
    if (point) {
      setDetailFromEventPoint(point, false);
    }
  });

  plot.on('plotly_unhover', () => {
    hoveredDetail = null;
    renderDetails();
  });

  plot.on('plotly_doubleclick', () => {
    if (syncing) {
      return;
    }
  });

  plot.on('plotly_deselect', () => {
    if (syncing) {
      return;
    }
    clearInteractionSelection();
  });
});

document.querySelectorAll('input[data-filter-group]').forEach((input) => {
  input.addEventListener('change', () => {
    updateFacetMeta();
    updateFilters();
  });
});

document.querySelectorAll('.layout-filter-toggle').forEach((button) => {
  button.addEventListener('click', () => {
    const groupName = button.getAttribute('data-target-group');
    const section = document.querySelector(`[data-filter-section="${groupName}"]`);
    if (!section) {
      return;
    }
    const collapsed = section.classList.toggle('is-collapsed');
    button.setAttribute('aria-expanded', String(!collapsed));
    const chevron = button.querySelector('[data-filter-chevron]');
    if (chevron) {
      chevron.textContent = collapsed ? '+' : '−';
    }
    reportLayoutReviewHeight();
  });
});

clearFiltersButton?.addEventListener('click', () => {
  document.querySelectorAll('input[data-filter-group]').forEach((input) => {
    input.checked = false;
  });
  updateFacetMeta();
  updateFilters();
});

clearSelectionButton?.addEventListener('click', () => {
  clearInteractionSelection();
});

colorModeButtons.forEach((button) => {
  button.addEventListener('click', () => {
    const modeName = button.dataset.colorMode;
    if (modeName) {
      applyColorMode(modeName);
    }
  });
});

function reportLayoutReviewHeight() {
  if (window.parent === window) {
    return;
  }
  window.parent.postMessage({ type: 'layout-review-height', height: document.documentElement.scrollHeight }, '*');
}

window.addEventListener('load', () => {
  updateFacetMeta();
  renderDetails();
  updateCorrespondenceSummary();
  applyColorMode(currentMode);
  if ('ResizeObserver' in window) {
    const observer = new ResizeObserver(() => resizePlots());
    document.querySelectorAll('.plot-card').forEach((card) => observer.observe(card));
    observer.observe(document.body);
  }
});

window.addEventListener('resize', resizePlots);
"""


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_cluster_label_lookup(assignments_path: Path, summaries_path: Path) -> dict[int, str]:
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


def _enrich_assignments_with_label_schemes(assignments: list[dict[str, Any]]) -> None:
    voyage25_lookup = _load_cluster_label_lookup(VOYAGE25_ASSIGNMENTS, VOYAGE25_SUMMARIES)
    voyage31_lookup = _load_cluster_label_lookup(VOYAGE31_ASSIGNMENTS, VOYAGE31_SUMMARIES)
    claims28_lookup = _load_cluster_label_lookup(CLAIMS28_ASSIGNMENTS, CLAIMS28_SUMMARIES)
    for record in assignments:
        abstract_id = int(record.get("abstract_id") or 0)
        record["categorical_primary_label"] = _field_value(record, "primary_parent_category")
        record["voyage25_label"] = voyage25_lookup.get(abstract_id, "Unknown")
        record["voyage31_label"] = voyage31_lookup.get(abstract_id, "Unknown")
        record["claims28_label"] = claims28_lookup.get(abstract_id, "Unknown")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Plot a poster proposal on the venue floorplan layout")
    parser.add_argument("--proposal-dir", required=True)
    parser.add_argument("--ui-umap-input", default=DEFAULT_UI_UMAP)
    parser.add_argument("--output-primary-html")
    parser.add_argument("--output-semantic-html")
    return parser


def _assignments_with_layout(proposal: dict[str, Any]) -> list[dict[str, Any]]:
    assignments: list[dict[str, Any]] = []
    for assignment in proposal.get("assignments", []):
        if (
            "hall_id" in assignment
            and "hall_x" in assignment
            and "hall_y" in assignment
            and "hall_edge_x0" in assignment
            and "hall_edge_y0" in assignment
            and "hall_edge_x1" in assignment
            and "hall_edge_y1" in assignment
            and "board_number" in assignment
            and "board_side" in assignment
        ):
            assignments.append(dict(assignment))
            continue
        layout_slot = layout_slot_for_block_position(int(assignment["block_position"]))
        assignments.append({**assignment, **layout_slot})
    return assignments


def _background_boards() -> list[dict[str, Any]]:
    geometry = load_layout_geometry()
    return [dict(board) for board in geometry.get("boards", [])]


def _load_ui_umap_points(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload.get("umap"), dict):
        return list(payload["umap"].get("points") or [])
    return list(payload.get("points") or [])


def _field_value(record: dict[str, Any], field_name: str) -> str:
    value = str(record.get(field_name) or "").strip()
    if value:
        return value
    if field_name == "layout_exact_label":
        primary = str(record.get("primary_category") or "").strip()
        if primary:
            return primary
    return "Unknown"


def _hover_customdata(record: dict[str, Any]) -> list[Any]:
    return [
        int(record.get("abstract_id") or 0),
        int(record.get("poster_number") or 0),
        str(record.get("board_label") or "Unknown"),
        str(record.get("title") or "Untitled"),
        str(record.get("standby_session_label") or "Unknown"),
        _field_value(record, "categorical_primary_label"),
        _field_value(record, "voyage25_label"),
        str(record.get("block_label") or "Unknown"),
        int(record.get("board_number") or 0),
        str(record.get("board_side") or "Unknown"),
        int(record.get("hall_row") or 0),
        int(record.get("hall_segment") or 0),
        int(record.get("hall_face_position") or 0),
        str(record.get("accepted_for") or "Unknown"),
        _field_value(record, "voyage31_label"),
        _field_value(record, "claims28_label"),
    ]


def _edge_arrays(records: list[dict[str, Any]]) -> tuple[list[float | None], list[float | None]]:
    x_values: list[float | None] = []
    y_values: list[float | None] = []
    for record in records:
        x_values.extend([float(record["hall_edge_x0"]), float(record["hall_edge_x1"]), None])
        y_values.extend([float(record["hall_edge_y0"]), float(record["hall_edge_y1"]), None])
    return x_values, y_values


def _background_face_arrays(records: list[dict[str, Any]]) -> tuple[list[float], list[float]]:
    x_values: list[float] = []
    y_values: list[float] = []
    for record in records:
        x_values.extend([float(record["hall_face_a_x"]), float(record["hall_face_b_x"])])
        y_values.extend([float(record["hall_face_a_y"]), float(record["hall_face_b_y"])])
    return x_values, y_values


def _assignment_face_arrays(records: list[dict[str, Any]]) -> tuple[list[float], list[float], list[list[Any]]]:
    x_values: list[float] = []
    y_values: list[float] = []
    customdata: list[list[Any]] = []
    for record in records:
        x_values.append(float(record["hall_x"]))
        y_values.append(float(record["hall_y"]))
        customdata.append(_hover_customdata(record))
    return x_values, y_values, customdata


def _facet_group_markup(group_name: str, label: str, counts: Counter[str], collapsed: bool) -> str:
    options = []
    for value, count in sorted(counts.items()):
        escaped_value = html.escape(value, quote=True)
        options.append(
            f'<label class="layout-filter-option" data-filter-option data-filter-group-row="{group_name}" data-filter-value="{escaped_value}">'
            f'<input type="checkbox" data-filter-group="{group_name}" value="{escaped_value}" />'
            f'<span>{html.escape(value)}</span><span class="layout-filter-count" data-filter-count-value>{int(count)}</span></label>'
        )
    collapsed_class = " is-collapsed" if collapsed else ""
    expanded = "false" if collapsed else "true"
    chevron = "+" if collapsed else "−"
    return (
        f'<section class="layout-filter-section{collapsed_class}" data-filter-section="{group_name}">'
        f'<button type="button" class="layout-filter-toggle" data-target-group="{group_name}" aria-expanded="{expanded}">'
        f'<span class="layout-filter-label">{html.escape(label)}</span>'
        f'<span class="layout-filter-meta" data-filter-meta="{group_name}">All</span>'
        f'<span class="layout-filter-chevron" data-filter-chevron>{chevron}</span>'
        f"</button>"
        f'<div class="layout-filter-options">{"".join(options)}</div>'
        f"</section>"
    )


def _default_color_field(proposal: dict[str, Any]) -> str:
    metadata = dict(proposal.get("metadata") or {})
    layout_label_system = str(metadata.get("layout_label_system") or "").strip()
    mapping = {
        "submitter_primary_secondary": "categorical_primary_label",
        "voyage_stage2_kmeans_25": "voyage25_label",
        "voyage_stage2_spectral_31": "voyage31_label",
        "minilm_claims_kmeans_28": "claims28_label",
    }
    return mapping.get(layout_label_system, "categorical_primary_label")


def _category_color_maps(assignments: list[dict[str, Any]], color_fields: list[str]) -> dict[str, dict[str, str]]:
    return {
        field: build_distinct_color_map([_field_value(record, field) for record in assignments])
        for field in color_fields
    }


def _build_block_figure(
    block_id: int,
    assignments: list[dict[str, Any]],
    background: list[dict[str, Any]],
    color_fields: list[str],
    color_maps: dict[str, dict[str, str]],
) -> tuple[go.Figure, list[int], dict[str, list[int]]]:
    geometry_metadata = dict(load_layout_geometry().get("metadata") or {})
    x_min = float(geometry_metadata.get("x_min") or 0.0) - 10.0
    x_max = float(geometry_metadata.get("x_max") or 0.0) + 10.0
    y_min = float(geometry_metadata.get("y_min") or 0.0) - 10.0
    y_max = float(geometry_metadata.get("y_max") or 0.0) + 10.0
    background_edge_x, background_edge_y = _edge_arrays(background)
    background_face_x, background_face_y = _background_face_arrays(background)

    figure = go.Figure()
    background_indices: list[int] = []
    mode_trace_indices: dict[str, list[int]] = {field: [] for field in color_fields}

    figure.add_trace(
        go.Scatter(
            x=background_edge_x,
            y=background_edge_y,
            mode="lines",
            line={"width": 2, "color": "rgba(140,140,140,0.35)"},
            hoverinfo="skip",
            hovertemplate=None,
            showlegend=False,
            name="Board edges",
        )
    )
    background_indices.append(len(figure.data) - 1)
    figure.add_trace(
        go.Scatter(
            x=background_face_x,
            y=background_face_y,
            mode="markers",
            marker={"size": 4, "color": "rgba(160,160,160,0.30)"},
            hoverinfo="skip",
            hovertemplate=None,
            showlegend=False,
            name="Poster faces",
        )
    )
    background_indices.append(len(figure.data) - 1)

    block_assignments = [record for record in assignments if int(record["block_id"]) == block_id]
    for field in color_fields:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for record in block_assignments:
            grouped[_field_value(record, field)].append(record)
        for category in sorted(grouped):
            x_values, y_values, customdata = _assignment_face_arrays(grouped[category])
            figure.add_trace(
                go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode="markers",
                    marker={
                        "size": 7,
                        "color": color_maps[field].get(category, "hsl(0, 0%, 50%)"),
                        "line": {"width": 0.8, "color": "#111111"},
                    },
                    selected={"marker": {"size": 9}},
                    unselected={"marker": {"opacity": 0.15}},
                    customdata=customdata,
                    hoverinfo="none",
                    hovertemplate=None,
                    showlegend=False,
                    visible=False,
                    name=category,
                )
            )
            mode_trace_indices[field].append(len(figure.data) - 1)
            # Add an invisible but larger hit target so hover/click interactions
            # remain usable on the dense board layout without changing the visual.
            figure.add_trace(
                go.Scatter(
                    x=x_values,
                    y=y_values,
                    mode="markers",
                    marker={
                        "size": 16,
                        "color": "rgba(15, 23, 42, 0.001)",
                        "line": {"width": 0},
                    },
                    selected={"marker": {"size": 16}},
                    unselected={"marker": {"opacity": 1.0}},
                    customdata=customdata,
                    hoverinfo="none",
                    hovertemplate=None,
                    showlegend=False,
                    visible=False,
                    name=f"{category} hit area",
                )
            )
            mode_trace_indices[field].append(len(figure.data) - 1)

    figure.update_layout(
        template="plotly_white",
        height=440,
        dragmode="lasso",
        hovermode="closest",
        margin={"l": 10, "r": 10, "t": 42, "b": 10},
        title={"text": "June 15-16 block" if block_id == 1 else "June 17-18 block", "x": 0.02},
        uirevision="layout-review-block",
    )
    figure.update_xaxes(range=[x_min, x_max], showticklabels=False, showgrid=False, zeroline=False)
    figure.update_yaxes(
        range=[y_min, y_max],
        showticklabels=False,
        showgrid=False,
        zeroline=False,
    )
    return figure, background_indices, mode_trace_indices


def _build_umap_figure(
    assignments: list[dict[str, Any]],
    ui_umap_points: list[dict[str, Any]],
    color_fields: list[str],
    color_maps: dict[str, dict[str, str]],
) -> tuple[go.Figure, list[int], dict[str, list[int]]]:
    figure = go.Figure()
    background_indices: list[int] = []
    mode_trace_indices: dict[str, list[int]] = {field: [] for field in color_fields}

    valid_points = [point for point in ui_umap_points if isinstance(point, dict) and "x" in point and "y" in point]
    x_values_all = [float(point["x"]) for point in valid_points]
    y_values_all = [float(point["y"]) for point in valid_points]
    x_min = min(x_values_all) if x_values_all else -1.0
    x_max = max(x_values_all) if x_values_all else 1.0
    y_min = min(y_values_all) if y_values_all else -1.0
    y_max = max(y_values_all) if y_values_all else 1.0
    x_center = (x_min + x_max) / 2.0
    y_center = (y_min + y_max) / 2.0
    span = max(x_max - x_min, y_max - y_min) * 0.55
    if span <= 0.0:
        span = 1.0

    figure.add_trace(
        go.Scatter(
            x=x_values_all,
            y=y_values_all,
            mode="markers",
            marker={"size": 5, "color": "rgba(160,160,160,0.18)"},
            hoverinfo="skip",
            hovertemplate=None,
            showlegend=False,
            name="All accepted",
        )
    )
    background_indices.append(len(figure.data) - 1)

    points_by_id = {
        int(point["id"]): dict(point)
        for point in valid_points
        if isinstance(point.get("id"), int)
    }
    filtered_assignments = [record for record in assignments if int(record.get("abstract_id") or 0) in points_by_id]
    for field in color_fields:
        grouped: dict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
        for record in filtered_assignments:
            grouped[_field_value(record, field)].append((record, points_by_id[int(record["abstract_id"])]))
        for category in sorted(grouped):
            pairs = grouped[category]
            figure.add_trace(
                go.Scatter(
                    x=[float(point["x"]) for _record, point in pairs],
                    y=[float(point["y"]) for _record, point in pairs],
                    mode="markers",
                    marker={
                        "size": 7,
                        "color": color_maps[field].get(category, "hsl(0, 0%, 50%)"),
                        "line": {"width": 0.7, "color": "rgba(17,17,17,0.82)"},
                    },
                    selected={"marker": {"size": 9}},
                    unselected={"marker": {"opacity": 0.14}},
                    customdata=[_hover_customdata(record) for record, _point in pairs],
                    hoverinfo="none",
                    hovertemplate=None,
                    showlegend=False,
                    visible=False,
                    name=category,
                )
            )
            mode_trace_indices[field].append(len(figure.data) - 1)
            figure.add_trace(
                go.Scatter(
                    x=[float(point["x"]) for _record, point in pairs],
                    y=[float(point["y"]) for _record, point in pairs],
                    mode="markers",
                    marker={
                        "size": 14,
                        "color": "rgba(15, 23, 42, 0.001)",
                        "line": {"width": 0},
                    },
                    selected={"marker": {"size": 14}},
                    unselected={"marker": {"opacity": 1.0}},
                    customdata=[_hover_customdata(record) for record, _point in pairs],
                    hoverinfo="none",
                    hovertemplate=None,
                    showlegend=False,
                    visible=False,
                    name=f"{category} hit area",
                )
            )
            mode_trace_indices[field].append(len(figure.data) - 1)

    figure.update_layout(
        template="plotly_white",
        height=500,
        dragmode="lasso",
        hovermode="closest",
        margin={"l": 40, "r": 10, "t": 42, "b": 40},
        title={"text": "UI UMAP", "x": 0.02},
        uirevision="layout-review-umap",
    )
    figure.update_xaxes(title_text="UMAP 1", range=[x_center - span, x_center + span], zeroline=False)
    figure.update_yaxes(
        title_text="UMAP 2",
        range=[y_center - span, y_center + span],
        zeroline=False,
    )
    return figure, background_indices, mode_trace_indices


def _figure_markup(figure: go.Figure, div_id: str, include_plotlyjs: str | bool) -> str:
    return figure.to_html(
        include_plotlyjs=include_plotlyjs,
        full_html=False,
        div_id=div_id,
        config={"responsive": True, "displaylogo": False},
    )


def build_review_payload(proposal_dir: Path, ui_umap_input: Path | None = None) -> dict[str, Any]:
    proposal = load_json(proposal_dir / "proposal.json")
    assignments = _assignments_with_layout(proposal)
    ui_umap_points = _load_ui_umap_points(ui_umap_input or Path(DEFAULT_UI_UMAP))
    return _build_review_payload_from_loaded(proposal, assignments, ui_umap_points)


def _build_review_payload_from_loaded(
    proposal: dict[str, Any],
    assignments: list[dict[str, Any]],
    ui_umap_points: list[dict[str, Any]],
) -> dict[str, Any]:
    _enrich_assignments_with_label_schemes(assignments)
    background = _background_boards()
    color_fields = ["categorical_primary_label", "voyage25_label", "voyage31_label", "claims28_label"]
    color_maps = _category_color_maps(assignments, color_fields)
    default_color_field = _default_color_field(proposal)

    block_one_figure, block_one_background, block_one_modes = _build_block_figure(
        1,
        assignments,
        background,
        color_fields,
        color_maps,
    )
    block_two_figure, block_two_background, block_two_modes = _build_block_figure(
        2,
        assignments,
        background,
        color_fields,
        color_maps,
    )
    umap_figure, umap_background, umap_modes = _build_umap_figure(
        assignments,
        ui_umap_points,
        color_fields,
        color_maps,
    )

    for figure, background_indices, mode_indices in (
        (block_one_figure, block_one_background, block_one_modes),
        (block_two_figure, block_two_background, block_two_modes),
        (umap_figure, umap_background, umap_modes),
    ):
        visible = [False] * len(figure.data)
        for index in background_indices:
            visible[index] = True
        for index in mode_indices.get(default_color_field, []):
            visible[index] = True
        for index, is_visible in enumerate(visible):
            figure.data[index].visible = is_visible

    filter_records = [
        {
            "abstract_id": int(record.get("abstract_id") or 0),
            "categorical_primary_label": _field_value(record, "categorical_primary_label"),
            "voyage25_label": _field_value(record, "voyage25_label"),
            "voyage31_label": _field_value(record, "voyage31_label"),
            "claims28_label": _field_value(record, "claims28_label"),
        }
        for record in assignments
    ]

    facet_markup = "".join(
        [
            _facet_group_markup(
                "categorical_primary_label",
                "Categorical primary",
                Counter(_field_value(record, "categorical_primary_label") for record in assignments),
                collapsed=True,
            ),
            _facet_group_markup(
                "voyage25_label",
                "Voyage 25",
                Counter(_field_value(record, "voyage25_label") for record in assignments),
                collapsed=True,
            ),
            _facet_group_markup(
                "voyage31_label",
                "Voyage 31",
                Counter(_field_value(record, "voyage31_label") for record in assignments),
                collapsed=True,
            ),
            _facet_group_markup(
                "claims28_label",
                "Claims 28",
                Counter(_field_value(record, "claims28_label") for record in assignments),
                collapsed=True,
            ),
        ]
    )

    plot_configs = {
        "block-1-plot": {"background": block_one_background, "modes": block_one_modes},
        "block-2-plot": {"background": block_two_background, "modes": block_two_modes},
        "umap-plot": {"background": umap_background, "modes": umap_modes},
    }
    block_navigation: dict[str, Any] = {}
    for block_id, block_label in ((1, "June 15-16 block"), (2, "June 17-18 block")):
        ordered = sorted(
            [record for record in assignments if int(record.get("block_id") or 0) == block_id],
            key=lambda record: int(record.get("poster_number") or 0),
        )
        block_navigation[str(block_id)] = {
            "label": block_label,
            "records": [
                {
                    "abstract_id": int(record.get("abstract_id") or 0),
                    "poster_number": int(record.get("poster_number") or 0),
                    "board_label": str(record.get("board_label") or "Unknown"),
                    "standby_session_label": str(record.get("standby_session_label") or "Unknown"),
                    "title": str(record.get("title") or "Untitled"),
                    "customdata": _hover_customdata(record),
                }
                for record in ordered
            ],
        }

    return {
        "proposal": proposal,
        "assignments": assignments,
        "facet_markup": facet_markup,
        "filter_records": filter_records,
        "plot_configs": plot_configs,
        "block_navigation": block_navigation,
        "default_color_field": default_color_field,
        "block_one_figure": block_one_figure.to_plotly_json(),
        "block_two_figure": block_two_figure.to_plotly_json(),
        "umap_figure": umap_figure.to_plotly_json(),
        "plotly_js": get_plotlyjs(),
    }


def _plot_category_floorplan(
    proposal: dict[str, Any],
    assignments: list[dict[str, Any]],
    ui_umap_points: list[dict[str, Any]],
    title: str,
    output_html: Path,
) -> None:
    payload = _build_review_payload_from_loaded(proposal, assignments, ui_umap_points)
    default_color_field = str(payload["default_color_field"])
    default_mode_label = {
        "categorical_primary_label": "Categorical primary",
        "voyage25_label": "Voyage 25",
        "voyage31_label": "Voyage 31",
        "claims28_label": "Claims 28",
    }.get(default_color_field, "Categorical primary")
    review_html = f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>{html.escape(title)}</title>
    <style>
      body {{
        margin: 0;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        background: #f6fbfb;
        color: #1f2933;
      }}
      .layout-review-shell {{
        display: grid;
        gap: 16px;
        padding: 16px 18px 22px;
      }}
      .layout-main {{
        display: flex;
        flex-direction: column;
        gap: 14px;
        min-width: 0;
      }}
      #layout-filter-state {{
        display: none;
      }}
      .layout-card {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 16px;
        background: rgba(255, 255, 255, 0.96);
        padding: 14px 16px;
      }}
      .layout-card h1,
      .layout-card h2,
      .layout-card h3 {{
        margin: 0 0 8px;
      }}
      .layout-card p {{
        margin: 0;
        color: #5f6c7b;
        line-height: 1.5;
        font-size: 14px;
      }}
      .layout-toolbar {{
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto;
        gap: 14px;
        align-items: start;
      }}
      .layout-mode-buttons,
      .layout-action-buttons {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }}
      .layout-mode-buttons button,
      .layout-action-buttons button,
      #clear-category-filters {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
        padding: 8px 12px;
        cursor: pointer;
      }}
      .layout-mode-buttons button.is-active {{
        background: #0f766e;
        color: white;
        border-color: #0f766e;
      }}
      .layout-plots-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 14px;
      }}
      .plot-card {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 16px;
        background: white;
        padding: 8px;
        min-width: 0;
      }}
      .layout-summary-chips {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 10px;
      }}
      .layout-summary-chip {{
        border-radius: 999px;
        background: #eaf8f5;
        color: #0f766e;
        padding: 7px 10px;
        font-size: 12px;
        font-weight: 700;
      }}
      .layout-filter-stack {{
        display: grid;
        gap: 10px;
      }}
      .layout-filter-section {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.92);
      }}
      .layout-filter-toggle {{
        width: 100%;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 10px;
        align-items: center;
        padding: 12px 14px;
        border: 0;
        background: transparent;
        text-align: left;
        cursor: pointer;
      }}
      .layout-filter-label {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
      }}
      .layout-filter-meta {{
        color: #5f6c7b;
        font-size: 12px;
      }}
      .layout-filter-chevron {{
        width: 28px;
        height: 28px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
      }}
      .layout-filter-options {{
        display: grid;
        gap: 8px;
        max-height: 240px;
        overflow-y: auto;
        padding: 0 14px 14px;
      }}
      .layout-filter-section.is-collapsed .layout-filter-options {{
        display: none;
      }}
      .layout-filter-option {{
        display: grid;
        grid-template-columns: 18px minmax(0, 1fr) auto;
        gap: 10px;
        align-items: start;
        font-size: 14px;
      }}
      .layout-filter-option input {{
        margin-top: 2px;
      }}
      .layout-filter-count {{
        color: #5f6c7b;
        font-variant-numeric: tabular-nums;
      }}
      .layout-review-note {{
        color: #5f6c7b;
        font-size: 13px;
        line-height: 1.45;
      }}
      .detail-empty strong {{
        display: block;
        margin-bottom: 6px;
      }}
      .detail-empty p {{
        margin: 0;
      }}
      .detail-kicker {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
        margin-bottom: 6px;
      }}
      .detail-grid {{
        display: grid;
        gap: 10px;
      }}
      .detail-grid div {{
        display: grid;
        gap: 2px;
      }}
      .detail-grid span {{
        color: #5f6c7b;
        font-size: 12px;
        text-transform: uppercase;
        letter-spacing: 0.05em;
      }}
      .detail-grid strong {{
        font-size: 14px;
      }}
      @media (max-width: 1100px) {{
        .layout-toolbar,
        .layout-plots-grid {{
          grid-template-columns: 1fr;
        }}
      }}
    </style>
  </head>
  <body>
    <div class="layout-review-shell">
      <div id="layout-filter-state"><div class="layout-filter-stack">{payload["facet_markup"]}</div></div>
      <main class="layout-main">
        <section class="layout-toolbar">
          <div class="layout-card">
            <h2>Poster Details</h2>
            <div id="poster-detail-card"></div>
            <div class="layout-summary-chips">
              <span class="layout-summary-chip">Physical arrangement from the selected proposal</span>
              <span class="layout-summary-chip">Colors and filters can switch across 4 label schemes</span>
            </div>
          </div>
          <div class="layout-card">
            <h2>Review Controls</h2>
            <p>Use the chips to switch the coloring and clear linked selections or filters.</p>
            <div class="layout-mode-buttons">
              <button type="button" data-color-mode="categorical_primary_label">Categorical primary</button>
              <button type="button" data-color-mode="voyage25_label">Voyage 25</button>
              <button type="button" data-color-mode="voyage31_label">Voyage 31</button>
              <button type="button" data-color-mode="claims28_label">Claims 28</button>
            </div>
            <div class="layout-action-buttons">
              <button id="clear-plot-selection" type="button">Clear selection</button>
              <button id="clear-category-filters" type="button">Clear filters</button>
            </div>
            <p>Current color mode: <strong id="current-color-mode">{html.escape(default_mode_label)}</strong></p>
            <div class="layout-action-buttons">
              <span class="layout-review-note" id="linked-selection-status">Lasso or click in any plot to select posters across both blocks and the UMAP.</span>
              <span class="layout-review-note" id="category-correspondence">No category filters applied.</span>
            </div>
          </div>
        </section>
        <section class="layout-plots-grid">
          <div class="plot-card">{_figure_markup(go.Figure(payload["block_one_figure"]), "block-1-plot", True)}</div>
          <div class="plot-card">{_figure_markup(go.Figure(payload["block_two_figure"]), "block-2-plot", False)}</div>
          <div class="plot-card">{_figure_markup(go.Figure(payload["umap_figure"]), "umap-plot", False)}</div>
        </section>
      </main>
    </div>
    <script>
      {LINKED_SELECTION_POST_SCRIPT.replace("__PLOT_CONFIGS__", json.dumps(payload["plot_configs"])).replace("__FILTER_RECORDS__", json.dumps(payload["filter_records"])).replace("__DEFAULT_MODE__", json.dumps(default_color_field))}
    </script>
  </body>
</html>
"""
    output_html.parent.mkdir(parents=True, exist_ok=True)
    output_html.write_text(review_html, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    proposal_dir = Path(args.proposal_dir)
    review_output = proposal_dir / "layout_review.html"
    primary_output = Path(args.output_primary_html) if args.output_primary_html else proposal_dir / "layout_primary_category.html"
    semantic_output = Path(args.output_semantic_html) if args.output_semantic_html else proposal_dir / "layout_semantic_category.html"

    proposal = load_json(proposal_dir / "proposal.json")
    assignments = _assignments_with_layout(proposal)
    ui_umap_points = _load_ui_umap_points(Path(args.ui_umap_input))
    _plot_category_floorplan(
        proposal,
        assignments,
        ui_umap_points,
        title=f"Poster layout review: {proposal_dir.name}",
        output_html=review_output,
    )
    rendered = review_output.read_text(encoding="utf-8")
    primary_output.write_text(rendered, encoding="utf-8")
    semantic_output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
