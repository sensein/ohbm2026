from __future__ import annotations

import argparse
import html
import importlib.util
import json
from pathlib import Path
from typing import Any


def _load_floorplan_module():
    module_path = Path(__file__).resolve().parent / "plot_poster_layout_floorplan.py"
    spec = importlib.util.spec_from_file_location("plot_poster_layout_floorplan", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load plot_poster_layout_floorplan module")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _layout_system_display_name(layout_label_system: str) -> str:
    mapping = {
        "submitter_primary_secondary": "Submitter primary/subcategory taxonomy",
        "voyage_stage2_kmeans_25": "Voyage Stage 2 k-means (25 clusters)",
        "voyage_stage2_spectral_31": "Voyage Stage 2 spectral (31 clusters)",
        "minilm_claims_kmeans_28": "MiniLM claims k-means (28 clusters)",
        "voyage_stage2_olo_contiguous_31": "Voyage OLO contiguous categories (31 clusters)",
    }
    return mapping.get(layout_label_system, layout_label_system.replace("_", " "))


def _proposal_label(proposal_dir: Path) -> str:
    proposal = _load_json(proposal_dir / "proposal.json")
    metadata = dict(proposal.get("metadata") or {})
    layout_label_system = str(metadata.get("layout_label_system") or "submitter_primary_secondary")
    return f"{proposal_dir.name} - {_layout_system_display_name(layout_label_system)}"


def _short_proposal_label(proposal_name: str) -> str:
    mapping = {
        "block_spread_soft": "Block Spread Soft",
        "semantic_layout_voyage25": "Voyage 25",
        "semantic_layout_voyage31": "Voyage 31",
        "semantic_layout_claims28": "Claims 28",
        "semantic_path_voyage31_olo_two_opt_knn20_p8": "Voyage31 OLO + 2-opt k20",
        "semantic_path_voyage31_olo_two_opt_knn40_p8": "Voyage31 OLO + 2-opt k40",
    }
    return mapping.get(proposal_name, proposal_name.replace("_", " "))


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value) * 100:.1f}%"
    except (TypeError, ValueError):
        return "n/a"


def _format_float(value: Any, digits: int = 3) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except (TypeError, ValueError):
        return "n/a"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a top-level poster layout review hub")
    parser.add_argument("--proposal-dir", action="append", required=True)
    parser.add_argument("--output-html", default="data/poster_layout/proposals/layout_review.html")
    parser.add_argument("--keep-individual-html", action="store_true")
    return parser


def render_hub_html(pages: list[dict[str, Any]]) -> str:
    if not pages:
        raise ValueError("At least one review page is required")
    payload = {page["slug"]: page for page in pages}
    first_slug = pages[0]["slug"]
    plotly_js = str(pages[0].get("plotly_js") or "")
    proposal_buttons = "\n".join(
        (
            f'<button type="button" class="proposal-item" data-proposal-slug="{html.escape(str(page["slug"]), quote=True)}">'
            f'<span class="proposal-item-title">{html.escape(str(page["short_label"]))}</span>'
            f'<span class="proposal-item-meta">{html.escape(str(page["taxonomy"]))}</span>'
            f'<span class="proposal-item-meta">{html.escape(str(page["layout_count_label"]))}</span>'
            f"</button>"
        )
        for page in pages
    )
    return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Poster Layout Review Hub</title>
    <style>
      body {{
        margin: 0;
        font-family: "Avenir Next", "Segoe UI", sans-serif;
        background: #f4faf8;
        color: #1f2933;
      }}
      .shell {{
        padding: 14px 16px 16px;
        display: grid;
        grid-template-columns: minmax(270px, 320px) minmax(0, 1fr);
        gap: 14px;
      }}
      .sidebar {{
        display: flex;
        flex-direction: column;
        gap: 8px;
        min-width: 0;
      }}
      .main {{
        min-width: 0;
      }}
      .panel {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 18px;
        background: rgba(255, 255, 255, 0.94);
        padding: 11px 12px;
        min-width: 0;
      }}
      .panel h1,
      .panel h2 {{
        margin: 0 0 10px;
        font-size: 18px;
      }}
      .panel.tight {{
        padding: 14px 16px;
      }}
      .panel h3 {{
        margin: 0 0 8px;
        font-size: 15px;
      }}
      .eyebrow {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
        margin-bottom: 8px;
      }}
      .panel-header-row {{
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 8px;
        margin-bottom: 6px;
      }}
      .panel-header-row .eyebrow {{
        margin-bottom: 0;
      }}
      .selector-header-actions {{
        display: inline-flex;
        gap: 6px;
        align-items: center;
      }}
      .icon-button {{
        width: 22px;
        height: 22px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
        color: #0f766e;
        cursor: pointer;
        font-size: 11px;
        line-height: 1;
        padding: 0;
      }}
      .proposal-list {{
        display: grid;
        gap: 10px;
      }}
      .is-hidden {{
        display: none !important;
      }}
      .proposal-item {{
        width: 100%;
        text-align: left;
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 14px;
        background: white;
        padding: 12px 13px;
        display: grid;
        gap: 4px;
        cursor: pointer;
        min-width: 0;
      }}
      .proposal-item.is-active {{
        border-color: #0f766e;
        background: #eaf8f5;
        box-shadow: inset 0 0 0 1px rgba(15, 118, 110, 0.18);
      }}
      .proposal-item-title {{
        font-weight: 700;
        font-size: 13px;
        line-height: 1.25;
        display: block;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .proposal-item-meta,
      .note,
      .meta-copy {{
        color: #5f6c7b;
        font-size: 14px;
        line-height: 1.5;
      }}
      .proposal-item-meta {{
        display: block;
        font-size: 12px;
        line-height: 1.35;
        overflow-wrap: anywhere;
        word-break: break-word;
      }}
      .main {{
        display: flex;
        flex-direction: column;
        gap: 10px;
      }}
      .detail-row {{
        display: flex;
        gap: 10px;
        align-items: flex-start;
      }}
      .detail-row > .panel {{
        min-width: 0;
      }}
      .detail-row > .panel:first-child {{
        flex: 0.92;
      }}
      .detail-row > .panel:last-child {{
        flex: 1.28;
      }}
      .headline {{
        display: grid;
        gap: 8px;
        min-width: 0;
      }}
      .headline h1 {{
        margin: 0;
        font-size: 26px;
      }}
      .headline p {{
        margin: 6px 0 0;
      }}
      .badge-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
        min-width: 0;
      }}
      .badge {{
        border-radius: 999px;
        background: #eaf8f5;
        color: #0f766e;
        padding: 5px 9px;
        font-size: 11px;
        font-weight: 700;
        line-height: 1.3;
        white-space: normal;
        overflow-wrap: anywhere;
      }}
      .badge.is-metric {{
        background: white;
        border: 1px solid rgba(185, 209, 204, 0.95);
        color: #1f2933;
      }}
      .detail-host {{
        display: grid;
        gap: 6px;
        min-height: 118px;
        max-height: 148px;
        overflow: auto;
        padding-right: 2px;
        min-width: 0;
      }}
      .layout-detail-host {{
        display: grid;
        gap: 6px;
        align-content: start;
        min-width: 0;
      }}
      .preview-img {{
        width: 100%;
        border-radius: 12px;
        border: 1px solid rgba(185, 209, 204, 0.95);
        background: white;
      }}
      .selector-host {{
        display: grid;
        gap: 6px;
      }}
      .selector-host .layout-filter-section {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 14px;
        background: rgba(255, 255, 255, 0.92);
      }}
      .selector-host .layout-filter-toggle {{
        width: 100%;
        display: grid;
        grid-template-columns: minmax(0, 1fr) auto auto;
        gap: 8px;
        align-items: center;
        padding: 7px 10px;
        border: 0;
        background: transparent;
        text-align: left;
        cursor: pointer;
      }}
      .selector-host .layout-filter-label {{
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
      }}
      .selector-host .layout-filter-meta {{
        color: #5f6c7b;
        font-size: 12px;
      }}
      .selector-host .layout-filter-chevron {{
        width: 16px;
        height: 16px;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
        font-size: 10px;
        line-height: 1;
      }}
      .selector-host .layout-filter-options {{
        display: grid;
        gap: 6px;
        max-height: 260px;
        overflow-y: auto;
        padding: 0 10px 8px;
      }}
      .selector-host .layout-filter-section.is-collapsed .layout-filter-options {{
        display: none;
      }}
      .selector-host .layout-filter-option {{
        display: grid;
        grid-template-columns: 18px minmax(0, 1fr) auto;
        gap: 6px;
        align-items: start;
        font-size: 13px;
      }}
      .selector-host .layout-filter-option.is-unavailable {{
        display: none;
      }}
      .selector-host .layout-filter-option.is-empty-checked {{
        opacity: 0.6;
      }}
      .selector-host .layout-filter-option input {{
        margin-top: 2px;
      }}
      .selector-host .layout-filter-count {{
        color: #5f6c7b;
        font-variant-numeric: tabular-nums;
      }}
      .detail-empty strong {{
        display: block;
        margin-bottom: 6px;
      }}
      .detail-empty p {{
        margin: 0;
        color: #5f6c7b;
        line-height: 1.5;
      }}
      .detail-kicker {{
        font-size: 11px;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: #0f766e;
        margin-bottom: 2px;
      }}
      .detail-title {{
        margin: 0;
        font-size: 14px;
        line-height: 1.25;
      }}
      .detail-inline-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        align-items: center;
      }}
      .detail-inline-item {{
        font-size: 11px;
        line-height: 1.2;
        color: #334155;
        white-space: normal;
        overflow-wrap: anywhere;
      }}
      .detail-inline-item strong {{
        color: #111827;
      }}
      .detail-meta-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px 10px;
        align-items: center;
      }}
      .detail-meta-item {{
        font-size: 11px;
        line-height: 1.2;
        color: #334155;
        white-space: normal;
        overflow-wrap: anywhere;
      }}
      .detail-meta-item strong {{
        color: #111827;
      }}
      .controls-panel {{
        display: grid;
        gap: 6px;
      }}
      .navigator-panel {{
        display: grid;
        gap: 6px;
        padding-top: 2px;
      }}
      .navigator-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        align-items: center;
      }}
      .toggle-group {{
        display: inline-flex;
        gap: 4px;
        align-items: center;
        padding: 3px;
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: #f8fcfb;
      }}
      .toggle-group button {{
        border: 0;
        border-radius: 999px;
        background: transparent;
        color: #4b5563;
        padding: 5px 9px;
        cursor: pointer;
        font-size: 12px;
        line-height: 1.2;
      }}
      .toggle-group button.is-active {{
        background: #0f766e;
        color: white;
      }}
      .navigator-slider-wrap {{
        flex: 1 1 280px;
        display: grid;
        gap: 3px;
      }}
      .navigator-slider-wrap input[type="range"] {{
        width: 100%;
        margin: 0;
        accent-color: #0f766e;
      }}
      .navigator-status {{
        font-size: 12px;
        color: #334155;
        overflow-wrap: anywhere;
      }}
      .navigator-shortcut {{
        font-size: 11px;
        color: #5f6c7b;
        overflow-wrap: anywhere;
      }}
      .controls-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
      }}
      .mode-buttons,
      .action-buttons {{
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        align-items: center;
      }}
      .mode-buttons button,
      .action-buttons button {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 999px;
        background: white;
        padding: 6px 10px;
        cursor: pointer;
        font-size: 12px;
        line-height: 1.2;
      }}
      .mode-buttons button.is-active {{
        background: #0f766e;
        color: white;
        border-color: #0f766e;
      }}
      .plot-grid {{
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
      }}
      .plot-card {{
        border: 1px solid rgba(185, 209, 204, 0.95);
        border-radius: 16px;
        background: white;
        padding: 6px;
        min-width: 0;
      }}
      .plot-card > div {{
        width: 100%;
      }}
      .compact-note-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px 14px;
        align-items: center;
      }}
      .compact-note-row .note {{
        margin: 0;
        font-size: 12px;
        line-height: 1.35;
        min-width: 0;
        overflow-wrap: anywhere;
      }}
      @media (max-width: 1080px) {{
        .shell {{
          grid-template-columns: 1fr;
        }}
        .detail-row {{
          display: grid;
          grid-template-columns: 1fr;
        }}
        .plot-grid {{
          grid-template-columns: 1fr;
        }}
      }}
      @media (max-width: 720px) {{
        .detail-grid {{
          grid-template-columns: repeat(2, minmax(0, 1fr));
        }}
      }}
    </style>
  </head>
  <body>
    <div class="shell">
      <aside class="sidebar">
        <section class="panel">
          <div class="panel-header-row">
            <div class="eyebrow">Layout Proposals</div>
            <div class="selector-header-actions">
              <button id="expand-proposals" class="icon-button" type="button" title="Expand layout proposals" aria-label="Expand layout proposals">▾</button>
              <button id="collapse-proposals" class="icon-button" type="button" title="Collapse layout proposals" aria-label="Collapse layout proposals">▴</button>
            </div>
          </div>
          <div id="proposal-list" class="proposal-list">{proposal_buttons}</div>
        </section>
        <section class="panel">
          <div class="panel-header-row">
            <div class="eyebrow">Category Selectors</div>
            <div class="selector-header-actions">
              <button id="expand-all-filters" class="icon-button" type="button" title="Expand all selectors" aria-label="Expand all selectors">▾</button>
              <button id="collapse-all-filters" class="icon-button" type="button" title="Collapse all selectors" aria-label="Collapse all selectors">▴</button>
            </div>
          </div>
          <div id="sidebar-category-selectors" class="selector-host"></div>
        </section>
      </aside>
      <main class="main">
        <section class="detail-row">
          <section class="panel tight">
            <div class="eyebrow">Layout Details</div>
            <div id="layout-detail-card" class="layout-detail-host">
              <div class="badge-row">
                <span class="badge" id="badge-layout-count">{html.escape(str(pages[0]["layout_count_label"]))}</span>
                <span class="badge" id="badge-sessions">{html.escape(str(pages[0]["session_count_label"]))}</span>
                <span class="badge is-metric" id="badge-adjacent">Adjacent match {html.escape(str(pages[0]["adjacent_match"]))}</span>
                <span class="badge is-metric" id="badge-distance">Semantic distance {html.escape(str(pages[0]["semantic_distance"]))}</span>
                <span class="badge is-metric" id="badge-conflicts">Author conflicts {html.escape(str(pages[0]["author_conflicts"]))}</span>
              </div>
            </div>
          </section>
          <section class="panel">
            <div class="headline">
              <div>
                <div class="eyebrow">Poster Details</div>
                <div id="poster-detail-card" class="detail-host"></div>
              </div>
            </div>
          </section>
        </section>
        <section class="plot-grid">
          <div class="plot-card"><div id="block-1-plot"></div></div>
          <div class="plot-card"><div id="block-2-plot"></div></div>
          <div class="plot-card"><div id="umap-plot"></div></div>
        </section>
        <section class="panel controls-panel">
          <div class="eyebrow">Review Controls</div>
          <div class="controls-row">
            <div class="mode-buttons">
              <button type="button" data-color-mode="categorical_primary_label">Categorical primary</button>
              <button type="button" data-color-mode="voyage25_label">Voyage 25</button>
              <button type="button" data-color-mode="voyage31_label">Voyage 31</button>
              <button type="button" data-color-mode="claims28_label">Claims 28</button>
            </div>
            <div class="action-buttons">
              <button id="clear-plot-selection" type="button">Clear selection</button>
              <button id="clear-category-filters" type="button">Clear filters</button>
            </div>
          </div>
          <div class="compact-note-row">
            <p class="note">Color mode: <strong id="current-color-mode">Categorical primary</strong></p>
            <p class="note" id="linked-selection-status">Lasso or click in any plot to select posters across both blocks and the UMAP.</p>
            <p class="note" id="category-correspondence">No category filters applied.</p>
          </div>
          <div class="navigator-panel">
            <div class="navigator-row">
              <div class="toggle-group" role="group" aria-label="Block selector">
                <button type="button" data-nav-block="1" aria-pressed="true">Block 1</button>
                <button type="button" data-nav-block="2" aria-pressed="false">Block 2</button>
              </div>
              <div class="navigator-slider-wrap">
                <input id="block-nav-slider" type="range" min="1" max="1" value="1" step="1" />
                <div class="navigator-row">
                  <span id="block-nav-status" class="navigator-status">Block 1 · poster 1 of 1</span>
                  <span class="navigator-shortcut">Keys: `1`/`2` switch blocks, `←`/`→` step posters</span>
                </div>
              </div>
            </div>
          </div>
        </section>
      </main>
    </div>
    <script>{plotly_js}</script>
    <script>
      const pages = {json.dumps(payload)};
      const proposalButtons = Array.from(document.querySelectorAll('[data-proposal-slug]'));
      const proposalList = document.getElementById('proposal-list');
      const selectorHost = document.getElementById('sidebar-category-selectors');
      const detailPanel = document.getElementById('poster-detail-card');
      const badgeLayout = document.getElementById('badge-layout-count');
      const badgeSessions = document.getElementById('badge-sessions');
      const badgeAdjacent = document.getElementById('badge-adjacent');
      const badgeDistance = document.getElementById('badge-distance');
      const badgeConflicts = document.getElementById('badge-conflicts');
      const modeLabel = document.getElementById('current-color-mode');
      const selectionStatus = document.getElementById('linked-selection-status');
      const correspondence = document.getElementById('category-correspondence');
      const clearSelectionButton = document.getElementById('clear-plot-selection');
      const clearFiltersButton = document.getElementById('clear-category-filters');
      const expandAllFiltersButton = document.getElementById('expand-all-filters');
      const collapseAllFiltersButton = document.getElementById('collapse-all-filters');
      const expandProposalsButton = document.getElementById('expand-proposals');
      const collapseProposalsButton = document.getElementById('collapse-proposals');
      const colorModeButtons = Array.from(document.querySelectorAll('[data-color-mode]'));
      const navBlockButtons = Array.from(document.querySelectorAll('[data-nav-block]'));
      const navSlider = document.getElementById('block-nav-slider');
      const navStatus = document.getElementById('block-nav-status');
      const plotIds = ['block-1-plot', 'block-2-plot', 'umap-plot'];
      const plots = Object.fromEntries(plotIds.map((id) => [id, document.getElementById(id)]));
      const filterGroups = {{
        categorical_primary_label: {{ label: 'Categorical primary' }},
        voyage25_label: {{ label: 'Voyage 25' }},
        voyage31_label: {{ label: 'Voyage 31' }},
        claims28_label: {{ label: 'Claims 28' }},
      }};
      let currentSlug = {json.dumps(first_slug)};
      let plotConfigs = {{}};
      let filterRecords = [];
      let currentMode = 'categorical_primary_label';
      let interactionSelection = null;
      let interactionSelectionSource = null;
      let pendingClickTimers = {{}};
      let ignoreClickUntil = {{}};
      let filterSelection = null;
      let pinnedDetail = null;
      let hoveredDetail = null;
      let hoveredDetailSource = null;
      let navigatorBlockId = '1';
      let navigatorIndexByBlock = {{ '1': 1, '2': 1 }};
      let navigatorUiBound = false;
      let renderEpoch = 0;
      let syncing = false;
      const defaultSelectionText = 'Lasso or click in any plot to select posters across both blocks and the UMAP.';
      function defaultDetailHtml(selected) {{
        const layoutName = selected?.short_label || 'selected proposal';
        return `
          <div class="detail-empty">
            <strong>No poster selected</strong>
            <p>Hover or click a poster in any plot to inspect its details here. Current layout: ${{layoutName}}.</p>
          </div>
        `;
      }}
      function detailHtml(customdata) {{
        if (!customdata) {{
          return defaultDetailHtml(pages[currentSlug]);
        }}
        return `
          <h3 class="detail-title">${{customdata[3]}}</h3>
          <div class="detail-inline-row">
            <span class="detail-inline-item"><strong>Poster</strong> ${{customdata[1]}}</span>
            <span class="detail-inline-item"><strong>Board</strong> ${{customdata[2]}}</span>
            <span class="detail-inline-item"><strong>Standby</strong> ${{customdata[4]}}</span>
            <span class="detail-inline-item"><strong>Block</strong> ${{customdata[7]}}</span>
            <span class="detail-inline-item"><strong>Location</strong> Row ${{customdata[10]}}, unit ${{customdata[11]}}, edge ${{customdata[12]}}, side ${{customdata[9]}}</span>
          </div>
          <div class="detail-meta-row">
            <span class="detail-meta-item"><strong>Abstract ID</strong> ${{customdata[0]}}</span>
            <span class="detail-meta-item"><strong>Categorical primary</strong> ${{customdata[5]}}</span>
            <span class="detail-meta-item"><strong>Voyage 25</strong> ${{customdata[6]}}</span>
            <span class="detail-meta-item"><strong>Voyage 31</strong> ${{customdata[14]}}</span>
            <span class="detail-meta-item"><strong>Claims 28</strong> ${{customdata[15]}}</span>
          </div>
        `;
      }}
      function setActiveButton(slug) {{
        proposalButtons.forEach((button) => {{
          const active = button.dataset.proposalSlug === slug;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', String(active));
        }});
      }}
      function renderDetails() {{
        if (!detailPanel) {{
          return;
        }}
        detailPanel.innerHTML = detailHtml(hoveredDetail || pinnedDetail);
      }}
      function selectedValues(groupName) {{
        const checked = Array.from(document.querySelectorAll(`#sidebar-category-selectors input[data-filter-group="${{groupName}}"]:checked`));
        return new Set(checked.map((item) => item.value));
      }}
      function selectorBaseRecords() {{
        const activeIds = interactionSelection;
        if (!activeIds || !activeIds.size) {{
          return filterRecords;
        }}
        return filterRecords.filter((record) => activeIds.has(String(record.abstract_id)));
      }}
      function updateFacetMeta() {{
        Object.keys(filterGroups).forEach((groupName) => {{
          const meta = document.querySelector(`#sidebar-category-selectors [data-filter-meta="${{groupName}}"]`);
          if (!meta) {{
            return;
          }}
          const count = selectedValues(groupName).size;
          meta.textContent = count ? `${{count}} selected` : 'All';
        }});
      }}
      function setAllFilterSections(collapsed) {{
        selectorHost.querySelectorAll('.layout-filter-section').forEach((section) => {{
          section.classList.toggle('is-collapsed', collapsed);
          const button = section.querySelector('.layout-filter-toggle');
          if (button) {{
            button.setAttribute('aria-expanded', String(!collapsed));
          }}
          const chevron = section.querySelector('[data-filter-chevron]');
          if (chevron) {{
            chevron.textContent = collapsed ? '+' : '−';
          }}
        }});
      }}
      function setProposalListCollapsed(collapsed) {{
        proposalList?.classList.toggle('is-hidden', collapsed);
      }}
      function updateSelectorOptions() {{
        const records = selectorBaseRecords();
        const countsByGroup = Object.fromEntries(
          Object.keys(filterGroups).map((groupName) => [groupName, new Map()])
        );
        records.forEach((record) => {{
          Object.keys(filterGroups).forEach((groupName) => {{
            const value = String(record[groupName] ?? 'Unknown');
            const groupCounts = countsByGroup[groupName];
            groupCounts.set(value, (groupCounts.get(value) || 0) + 1);
          }});
        }});
        document.querySelectorAll('#sidebar-category-selectors [data-filter-option]').forEach((option) => {{
          const groupName = option.getAttribute('data-filter-group-row');
          const value = option.getAttribute('data-filter-value') || 'Unknown';
          const input = option.querySelector('input[data-filter-group]');
          const countEl = option.querySelector('[data-filter-count-value]');
          const count = countsByGroup[groupName]?.get(value) || 0;
          if (countEl) {{
            countEl.textContent = String(count);
          }}
          const isChecked = Boolean(input?.checked);
          option.classList.toggle('is-unavailable', count === 0 && !isChecked);
          option.classList.toggle('is-empty-checked', count === 0 && isChecked);
        }});
      }}
      function currentFilterIds() {{
        const activeGroups = Object.keys(filterGroups).map((groupName) => [groupName, selectedValues(groupName)]);
        const hasFilters = activeGroups.some(([, values]) => values.size > 0);
        if (!hasFilters) {{
          return null;
        }}
        const selected = new Set();
        filterRecords.forEach((record) => {{
          const matches = activeGroups.every(([groupName, values]) => {{
            if (values.size === 0) {{
              return true;
            }}
            return values.has(String(record[groupName] ?? 'Unknown'));
          }});
          if (matches) {{
            selected.add(String(record.abstract_id));
          }}
        }});
        return selected;
      }}
      function effectiveSelection() {{
        if (filterSelection && interactionSelection) {{
          const intersection = new Set();
          filterSelection.forEach((item) => {{
            if (interactionSelection.has(item)) {{
              intersection.add(item);
            }}
          }});
          return intersection;
        }}
        return interactionSelection || filterSelection || null;
      }}
      function selectionForPlot(plotId) {{
        const selectedIds = effectiveSelection();
        if (!selectedIds || !selectedIds.size) {{
          return null;
        }}
        if (!interactionSelection || !interactionSelectionSource) {{
          return selectedIds;
        }}
        if (interactionSelectionSource === 'umap-plot') {{
          return selectedIds;
        }}
        if (plotId === interactionSelectionSource || plotId === 'umap-plot') {{
          return selectedIds;
        }}
        return null;
      }}
      function selectionIndicesForTrace(trace, selectedIds) {{
        if (!Array.isArray(trace.customdata)) {{
          return null;
        }}
        const indices = [];
        trace.customdata.forEach((item, index) => {{
          const abstractId = Array.isArray(item) ? item[0] : null;
          if (abstractId !== null && selectedIds && selectedIds.has(String(abstractId))) {{
            indices.push(index);
          }}
        }});
        return selectedIds && selectedIds.size ? indices : null;
      }}
      function updateCorrespondenceSummary() {{
        if (!correspondence) {{
          return;
        }}
        const activeGroups = Object.keys(filterGroups).map((groupName) => [groupName, selectedValues(groupName)]);
        const hasFilters = activeGroups.some(([, values]) => values.size > 0);
        const matchingRecords = filterRecords.filter((record) => {{
          return activeGroups.every(([groupName, values]) => {{
            if (values.size === 0) {{
              return true;
            }}
            return values.has(String(record[groupName] ?? 'Unknown'));
          }});
        }});
        if (!hasFilters) {{
          correspondence.textContent = 'No category filters applied.';
          return;
        }}
        const summary = [`${{matchingRecords.length}} posters match the active filters.`];
        activeGroups.forEach(([groupName, values]) => {{
          if (values.size > 0) {{
            const picked = Array.from(values);
            summary.push(`${{filterGroups[groupName].label}}: ${{picked.slice(0, 3).join('; ')}}${{picked.length > 3 ? '…' : ''}}`);
          }}
        }});
        correspondence.textContent = summary.join(' ');
      }}
      function navigatorRecordsForBlock(blockId) {{
        const blockRecords = pages[currentSlug]?.review?.block_navigation?.[blockId]?.records || [];
        if (!filterSelection || !filterSelection.size) {{
          return blockRecords;
        }}
        return blockRecords.filter((record) => filterSelection.has(String(record.abstract_id)));
      }}
      function findNavigatorLocation(abstractId) {{
        if (abstractId === null || abstractId === undefined) {{
          return null;
        }}
        const target = String(abstractId);
        for (const blockId of ['1', '2']) {{
          const records = navigatorRecordsForBlock(blockId);
          const index = records.findIndex((record) => String(record.abstract_id) === target);
          if (index >= 0) {{
            return {{ blockId, index, record: records[index], count: records.length }};
          }}
        }}
        return null;
      }}
      function activeSingleSelectionId() {{
        const selectedIds = effectiveSelection();
        if (!selectedIds || selectedIds.size !== 1) {{
          return null;
        }}
        return Array.from(selectedIds)[0];
      }}
      function updateNavigator() {{
        const selectedLocation = findNavigatorLocation(activeSingleSelectionId());
        if (selectedLocation) {{
          navigatorBlockId = selectedLocation.blockId;
          navigatorIndexByBlock[navigatorBlockId] = selectedLocation.index + 1;
        }}
        navBlockButtons.forEach((button) => {{
          const active = button.dataset.navBlock === navigatorBlockId;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', String(active));
        }});
        const records = navigatorRecordsForBlock(navigatorBlockId);
        const count = records.length;
        const currentIndex = Math.min(Math.max(navigatorIndexByBlock[navigatorBlockId] || 1, 1), Math.max(count, 1));
        navigatorIndexByBlock[navigatorBlockId] = currentIndex;
        if (navSlider) {{
          navSlider.min = '1';
          navSlider.max = String(Math.max(count, 1));
          navSlider.value = String(currentIndex);
          navSlider.disabled = count === 0;
        }}
        if (!navStatus) {{
          return;
        }}
        if (count === 0) {{
          navStatus.textContent = `Block ${{navigatorBlockId}} · no posters match the current filters`;
          return;
        }}
        const currentRecord = records[currentIndex - 1];
        navStatus.textContent = `Block ${{navigatorBlockId}} · ${{currentIndex}} of ${{count}} · Poster ${{currentRecord.poster_number}} · ${{currentRecord.board_label}}`;
      }}
      function activateNavigatorSelection(index) {{
        const records = navigatorRecordsForBlock(navigatorBlockId);
        if (!records.length) {{
          updateNavigator();
          return;
        }}
        const clampedIndex = Math.min(Math.max(index, 0), records.length - 1);
        navigatorIndexByBlock[navigatorBlockId] = clampedIndex + 1;
        const record = records[clampedIndex];
        hoveredDetail = null;
        hoveredDetailSource = null;
        pinnedDetail = record.customdata;
        interactionSelection = new Set([String(record.abstract_id)]);
        interactionSelectionSource = navigatorBlockId === '1' ? 'block-1-plot' : 'block-2-plot';
        renderDetails();
        applySelection();
      }}
      function applySelection() {{
        syncing = true;
        Object.entries(plots).forEach(([plotId, plot]) => {{
          if (!plot || !plot.data) {{
            return;
          }}
          const selectedIds = selectionForPlot(plotId);
          const selectedpoints = plot.data.map((trace) => selectionIndicesForTrace(trace, selectedIds));
          const traceIndices = plot.data.map((_trace, index) => index);
          Plotly.restyle(plot, {{ selectedpoints }}, traceIndices);
          const shouldKeepOverlay = Boolean(
            interactionSelection &&
            interactionSelectionSource &&
            interactionSelectionSource === plotId
          );
          if (!shouldKeepOverlay) {{
            Plotly.relayout(plot, {{ selections: [] }});
          }}
        }});
        syncing = false;
        const selectedIds = effectiveSelection();
        if (selectionStatus) {{
          selectionStatus.textContent = selectedIds && selectedIds.size
            ? `${{selectedIds.size}} posters selected across both hall blocks and the UMAP.`
            : defaultSelectionText;
        }}
        updateCorrespondenceSummary();
        updateSelectorOptions();
        updateNavigator();
      }}
      function setDetailFromEventPoint(point, pin, source = null) {{
        const customdata = point?.customdata || null;
        if (!customdata) {{
          return;
        }}
        if (pin) {{
          pinnedDetail = customdata;
        }} else {{
          hoveredDetail = customdata;
          hoveredDetailSource = source;
        }}
        renderDetails();
      }}
      function clearInteractionSelection() {{
        Object.values(pendingClickTimers).forEach((timerId) => {{
          if (timerId) {{
            window.clearTimeout(timerId);
          }}
        }});
        pendingClickTimers = {{}};
        interactionSelection = null;
        interactionSelectionSource = null;
        pinnedDetail = null;
        hoveredDetail = null;
        hoveredDetailSource = null;
        renderDetails();
        applySelection();
        Object.values(plots).forEach((plot) => {{
          if (!plot) {{
            return;
          }}
          Plotly.relayout(plot, {{ selections: [] }});
          if (Plotly.Fx && typeof Plotly.Fx.unhover === 'function') {{
            Plotly.Fx.unhover(plot);
          }}
        }});
      }}
      function resetPendingInteractions() {{
        Object.values(pendingClickTimers).forEach((timerId) => {{
          if (timerId) {{
            window.clearTimeout(timerId);
          }}
        }});
        pendingClickTimers = {{}};
        ignoreClickUntil = {{}};
      }}
      function suppressPlotClicks(plotId, duration = 350) {{
        ignoreClickUntil[plotId] = Date.now() + duration;
      }}
      function shouldIgnorePlotClick(plotId) {{
        const until = Number(ignoreClickUntil[plotId] || 0);
        return until > Date.now();
      }}
      function updateFilters() {{
        filterSelection = currentFilterIds();
        applySelection();
      }}
      function activateButtons(value) {{
        colorModeButtons.forEach((button) => {{
          const active = button.dataset.colorMode === value;
          button.classList.toggle('is-active', active);
          button.setAttribute('aria-pressed', String(active));
        }});
      }}
      function applyColorMode(modeName) {{
        currentMode = modeName;
        Object.entries(plots).forEach(([plotId, plot]) => {{
          const config = plotConfigs[plotId];
          if (!config || !plot?.data) {{
            return;
          }}
          const visible = new Array(plot.data.length).fill(false);
          (config.background || []).forEach((index) => {{
            visible[index] = true;
          }});
          ((config.modes || {{}})[modeName] || []).forEach((index) => {{
            visible[index] = true;
          }});
          const traceIndices = plot.data.map((_trace, index) => index);
          Plotly.restyle(plot, {{ visible }}, traceIndices);
        }});
        activateButtons(modeName);
        const labels = {{
          categorical_primary_label: 'Categorical primary',
          voyage25_label: 'Voyage 25',
          voyage31_label: 'Voyage 31',
          claims28_label: 'Claims 28',
        }};
        if (modeLabel) {{
          modeLabel.textContent = labels[modeName] || modeName;
        }}
        applySelection();
      }}
      function bindFilterUi() {{
        selectorHost.querySelectorAll('.layout-filter-toggle').forEach((button) => {{
          button.addEventListener('click', () => {{
            const section = button.closest('.layout-filter-section');
            if (section) {{
              const collapsed = section.classList.toggle('is-collapsed');
              button.setAttribute('aria-expanded', String(!collapsed));
              const chevron = button.querySelector('[data-filter-chevron]');
              if (chevron) {{
                chevron.textContent = collapsed ? '+' : '−';
              }}
            }}
          }});
        }});
        selectorHost.querySelectorAll('input[data-filter-group]').forEach((input) => {{
          input.addEventListener('change', () => {{
            updateFacetMeta();
            updateFilters();
          }});
        }});
      }}
      function bindNavigatorUi() {{
        if (navigatorUiBound) {{
          return;
        }}
        navigatorUiBound = true;
        navBlockButtons.forEach((button) => {{
          button.addEventListener('click', () => {{
            const nextBlockId = button.dataset.navBlock || '1';
            navigatorBlockId = nextBlockId;
            updateNavigator();
            activateNavigatorSelection((navigatorIndexByBlock[navigatorBlockId] || 1) - 1);
          }});
        }});
        navSlider?.addEventListener('input', () => {{
          const nextIndex = Math.max(Number(navSlider.value || '1') - 1, 0);
          activateNavigatorSelection(nextIndex);
        }});
        document.addEventListener('keydown', (event) => {{
          const target = event.target;
          if (event.metaKey || event.ctrlKey || event.altKey) {{
            return;
          }}
          if (
            target instanceof HTMLElement &&
            (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' || target.tagName === 'SELECT' || target.isContentEditable)
          ) {{
            return;
          }}
          if (event.key === '1' || event.key === '2') {{
            navigatorBlockId = event.key;
            updateNavigator();
            activateNavigatorSelection((navigatorIndexByBlock[navigatorBlockId] || 1) - 1);
            event.preventDefault();
            return;
          }}
          if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {{
            const delta = event.key === 'ArrowRight' ? 1 : -1;
            const currentIndex = (navigatorIndexByBlock[navigatorBlockId] || 1) - 1;
            activateNavigatorSelection(currentIndex + delta);
            event.preventDefault();
          }}
        }});
      }}
      function hasActiveInteractionSelection() {{
        return Boolean(interactionSelection && interactionSelection.size);
      }}
      function plotHasSelectionOverlay(plot) {{
        const selections = plot?.layout?.selections || plot?._fullLayout?.selections || [];
        return Array.isArray(selections) && selections.length > 0;
      }}
      function plotHasSelectedPoints(plot) {{
        return Boolean(
          plot?.data && plot.data.some((trace) => Array.isArray(trace?.selectedpoints) && trace.selectedpoints.length > 0)
        );
      }}
      function bindPlotEvents() {{
        Object.values(plots).forEach((plot) => {{
          const queuePlotSelection = (customdata, point = null) => {{
            if (!customdata) {{
              return;
            }}
            if (shouldIgnorePlotClick(plot.id)) {{
              return;
            }}
            if (pendingClickTimers[plot.id]) {{
              window.clearTimeout(pendingClickTimers[plot.id]);
            }}
            const scheduledEpoch = renderEpoch;
            pendingClickTimers[plot.id] = window.setTimeout(() => {{
              pendingClickTimers[plot.id] = null;
              if (scheduledEpoch !== renderEpoch) {{
                return;
              }}
              interactionSelection = new Set([String(customdata[0])]);
              interactionSelectionSource = plot.id;
              if (point) {{
                setDetailFromEventPoint(point, true, plot.id);
              }} else {{
                pinnedDetail = customdata;
                renderDetails();
              }}
              applySelection();
            }}, 220);
          }};
          plot.on('plotly_selected', (event) => {{
            if (syncing) {{
              return;
            }}
            interactionSelection = new Set(
              (event?.points || [])
                .map((point) => point.customdata?.[0])
                .filter((value) => value !== null && value !== undefined)
                .map((value) => String(value))
            );
            interactionSelectionSource = plot.id;
            applySelection();
          }});
          plot.on('plotly_click', (event) => {{
            if (syncing) {{
              return;
            }}
            if (shouldIgnorePlotClick(plot.id)) {{
              return;
            }}
            if (plotHasSelectionOverlay(plot) || (hasActiveInteractionSelection() && plotHasSelectedPoints(plot))) {{
              if ((event?.event?.detail || 0) >= 2) {{
                suppressPlotClicks(plot.id);
                clearInteractionSelection();
              }}
              return;
            }}
            const point = event?.points?.[0];
            const firstId = point?.customdata?.[0];
            if (firstId === null || firstId === undefined) {{
              return;
            }}
            queuePlotSelection(point.customdata, point);
          }});
          plot.on('plotly_hover', (event) => {{
            const point = event?.points?.[0];
            if (point) {{
              setDetailFromEventPoint(point, false, plot.id);
            }}
          }});
          plot.on('plotly_unhover', () => {{
            hoveredDetail = null;
            hoveredDetailSource = null;
            renderDetails();
          }});
          plot.on('plotly_doubleclick', () => {{
            if (syncing) {{
              return;
            }}
            if (pendingClickTimers[plot.id]) {{
              window.clearTimeout(pendingClickTimers[plot.id]);
              pendingClickTimers[plot.id] = null;
            }}
            if (plotHasSelectionOverlay(plot) || (hasActiveInteractionSelection() && plotHasSelectedPoints(plot))) {{
              suppressPlotClicks(plot.id);
              clearInteractionSelection();
            }}
          }});
          plot.on('plotly_deselect', () => {{
            if (syncing) {{
              return;
            }}
            clearInteractionSelection();
          }});
        }});
      }}
      function bindPointDomEvents() {{
        // Exact marker hover/click should come from Plotly's own point events.
        // Custom DOM mapping can drift when traces are filtered or recolored.
      }}
      function visiblePointCatalog(plot) {{
        const xaxis = plot?._fullLayout?.xaxis;
        const yaxis = plot?._fullLayout?.yaxis;
        if (!plot?.data || !xaxis || !yaxis) {{
          return [];
        }}
        const points = [];
        plot.data.forEach((trace) => {{
          if (trace?.visible === false || !Array.isArray(trace?.customdata) || !Array.isArray(trace?.x) || !Array.isArray(trace?.y)) {{
            return;
          }}
          trace.customdata.forEach((customdata, index) => {{
            const xValue = trace.x[index];
            const yValue = trace.y[index];
            if (xValue === null || xValue === undefined || yValue === null || yValue === undefined) {{
              return;
            }}
            points.push({{
              customdata,
              px: xaxis.l2p(xValue) + xaxis._offset,
              py: yaxis.l2p(yValue) + yaxis._offset,
            }});
          }});
        }});
        return points;
      }}
      function nearestVisiblePoint(plot, event) {{
        const points = visiblePointCatalog(plot);
        if (!points.length) {{
          return null;
        }}
        const rect = plot.getBoundingClientRect();
        const mouseX = event.clientX - rect.left;
        const mouseY = event.clientY - rect.top;
        let best = null;
        let bestDistance = Infinity;
        points.forEach((point) => {{
          const dx = point.px - mouseX;
          const dy = point.py - mouseY;
          const distance = Math.hypot(dx, dy);
          if (distance < bestDistance) {{
            bestDistance = distance;
            best = point;
          }}
        }});
        return bestDistance <= 18 ? best : null;
      }}
      function bindSurfaceEvents() {{
        Object.values(plots).forEach((plot) => {{
          const dragSurface = plot.querySelector('.draglayer .nsewdrag') || plot;
          const surfaces = [plot, dragSurface].filter(Boolean);
          const handleMove = () => {{
            // Keep hover details driven by actual Plotly/point hover events rather
            // than an approximate nearest-point scan over the entire plot area.
          }};
          const handleLeave = () => {{
            hoveredDetail = null;
            hoveredDetailSource = null;
            renderDetails();
          }};
          const handleClick = (event) => {{
            if (syncing) {{
              return;
            }}
            if (shouldIgnorePlotClick(plot.id)) {{
              return;
            }}
            if (event.target && typeof event.target.closest === 'function' && event.target.closest('.points path')) {{
              return;
            }}
            if (plotHasSelectionOverlay(plot) || (hasActiveInteractionSelection() && plotHasSelectedPoints(plot))) {{
              if ((event.detail || 0) >= 2) {{
                event.preventDefault();
                event.stopPropagation();
                suppressPlotClicks(plot.id);
                clearInteractionSelection();
              }}
              return;
            }}
            const customdata = nearestVisiblePoint(plot, event)?.customdata;
            if (!customdata) {{
              return;
            }}
            if (pendingClickTimers[plot.id]) {{
              window.clearTimeout(pendingClickTimers[plot.id]);
            }}
            const scheduledEpoch = renderEpoch;
            pendingClickTimers[plot.id] = window.setTimeout(() => {{
              pendingClickTimers[plot.id] = null;
              if (scheduledEpoch !== renderEpoch) {{
                return;
              }}
              pinnedDetail = customdata;
              interactionSelection = new Set([String(customdata[0])]);
              interactionSelectionSource = plot.id;
              renderDetails();
              applySelection();
            }}, 220);
          }};
          const handleDoubleClick = (event) => {{
            if (pendingClickTimers[plot.id]) {{
              window.clearTimeout(pendingClickTimers[plot.id]);
              pendingClickTimers[plot.id] = null;
            }}
            if (syncing || !(plotHasSelectionOverlay(plot) || (hasActiveInteractionSelection() && plotHasSelectedPoints(plot)))) {{
              return;
            }}
            event.preventDefault();
            event.stopPropagation();
            suppressPlotClicks(plot.id);
            clearInteractionSelection();
          }};
          surfaces.forEach((surface) => {{
            if (surface.dataset.layoutReviewBound === 'true') {{
              return;
            }}
            surface.dataset.layoutReviewBound = 'true';
            surface.addEventListener('mousemove', handleMove);
            surface.addEventListener('pointermove', handleMove);
            surface.addEventListener('mouseleave', handleLeave);
            surface.addEventListener('pointerleave', handleLeave);
            surface.addEventListener('click', handleClick, true);
            surface.addEventListener('dblclick', handleDoubleClick, true);
          }});
        }});
      }}
      function resizePlots() {{
        Object.values(plots).forEach((plot) => {{
          if (plot) {{
            Plotly.Plots.resize(plot);
          }}
        }});
      }}
      async function renderSelected() {{
        const selected = pages[currentSlug];
        if (!selected) {{
          return;
        }}
        renderEpoch += 1;
        resetPendingInteractions();
        plotConfigs = selected.review.plot_configs;
        filterRecords = selected.review.filter_records;
        currentMode = selected.review.default_color_field;
        interactionSelection = null;
        interactionSelectionSource = null;
        filterSelection = null;
        pinnedDetail = null;
        hoveredDetail = null;
        hoveredDetailSource = null;
        navigatorBlockId = '1';
        navigatorIndexByBlock = {{ '1': 1, '2': 1 }};
        selectorHost.innerHTML = selected.review.facet_markup;
        renderDetails();
        badgeLayout.textContent = selected.layout_count_label;
        badgeSessions.textContent = selected.session_count_label;
        badgeAdjacent.textContent = `Adjacent match ${{selected.adjacent_match}}`;
        badgeDistance.textContent = `Semantic distance ${{selected.semantic_distance}}`;
        badgeConflicts.textContent = `Author conflicts ${{selected.author_conflicts}}`;
        setActiveButton(currentSlug);
        bindFilterUi();
        await Plotly.newPlot('block-1-plot', selected.review.block_one_figure.data, selected.review.block_one_figure.layout, {{ responsive: true, displaylogo: false }});
        await Plotly.newPlot('block-2-plot', selected.review.block_two_figure.data, selected.review.block_two_figure.layout, {{ responsive: true, displaylogo: false }});
        await Plotly.newPlot('umap-plot', selected.review.umap_figure.data, selected.review.umap_figure.layout, {{ responsive: true, displaylogo: false }});
        bindPlotEvents();
        bindSurfaceEvents();
        bindNavigatorUi();
        updateFacetMeta();
        updateCorrespondenceSummary();
        updateSelectorOptions();
        applyColorMode(currentMode);
        resizePlots();
      }}
      clearSelectionButton?.addEventListener('click', () => {{
        clearInteractionSelection();
      }});
      clearFiltersButton?.addEventListener('click', () => {{
        document.querySelectorAll('#sidebar-category-selectors input[data-filter-group]').forEach((input) => {{
          input.checked = false;
        }});
        updateFacetMeta();
        updateFilters();
        updateSelectorOptions();
      }});
        expandAllFiltersButton?.addEventListener('click', () => {{
          setAllFilterSections(false);
        }});
        collapseAllFiltersButton?.addEventListener('click', () => {{
          setAllFilterSections(true);
        }});
        expandProposalsButton?.addEventListener('click', () => {{
          setProposalListCollapsed(false);
        }});
        collapseProposalsButton?.addEventListener('click', () => {{
          setProposalListCollapsed(true);
        }});
      colorModeButtons.forEach((button) => {{
        button.addEventListener('click', () => {{
          const modeName = button.dataset.colorMode;
          if (modeName) {{
            applyColorMode(modeName);
          }}
        }});
      }});
      proposalButtons.forEach((button) => {{
        button.addEventListener('click', async () => {{
          currentSlug = button.dataset.proposalSlug;
          await renderSelected();
        }});
      }});
      window.addEventListener('resize', resizePlots);
      renderSelected();
    </script>
  </body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    module = _load_floorplan_module()
    proposal_dirs = [Path(item) for item in args.proposal_dir]
    pages: list[dict[str, str]] = []
    output_path = Path(args.output_html)
    summary_path = output_path.parent / "summary.json"
    report_path = output_path.parent / "layout_review_checks" / "report.json"
    summary_rows = {str(item.get("proposal_name")): item for item in (_load_json(summary_path).get("proposals") or [])} if summary_path.exists() else {}
    report_rows = {str(item.get("value")): item for item in (_load_json(report_path).get("proposals") or [])} if report_path.exists() else {}

    plotly_js = ""
    for proposal_dir in proposal_dirs:
        review_payload = module.build_review_payload(proposal_dir)
        if not plotly_js:
            plotly_js = str(review_payload.get("plotly_js") or "")
        review_payload = {
            key: value
            for key, value in review_payload.items()
            if key
            in {
                "facet_markup",
                "filter_records",
                "plot_configs",
                "block_navigation",
                "default_color_field",
                "block_one_figure",
                "block_two_figure",
                "umap_figure",
            }
        }
        summary_row = dict(summary_rows.get(proposal_dir.name) or {})
        taxonomy = _layout_system_display_name(str(summary_row.get("layout_label_system") or "submitter_primary_secondary"))
        session_counts = summary_row.get("session_counts") or {}
        session_count_label = "/".join(str(session_counts.get(str(i), 0)) for i in (1, 2, 3, 4))
        layout_label_system = str(summary_row.get("layout_label_system") or "submitter_primary_secondary")
        if layout_label_system == "submitter_primary_secondary":
            layout_count = int(summary_row.get("layout_parent_label_count") or 0)
            layout_count_label = f"{layout_count} primary categories"
        else:
            layout_count = int(summary_row.get("layout_exact_label_count") or 0)
            layout_count_label = f"{layout_count} layout categories"
        pages.append(
            {
                "slug": proposal_dir.name,
                "label": _proposal_label(proposal_dir),
                "short_label": _short_proposal_label(proposal_dir.name),
                "taxonomy": taxonomy,
                "layout_count_label": layout_count_label,
                "session_count_label": f"Sessions {session_count_label}",
                "adjacent_match": _format_percent(summary_row.get("block_adjacent_exact_category_match_rate")),
                "semantic_distance": _format_float(summary_row.get("block_adjacent_mean_semantic_distance")),
                "claims_match": _format_percent(summary_row.get("claims_adjacent_same_cluster_rate")),
                "author_conflicts": str(int(summary_row.get("author_conflict_total") or 0)),
                "screenshot": f"layout_review_checks/{proposal_dir.name}.png",
                "review": review_payload,
            }
        )

    if pages and plotly_js:
        pages[0]["plotly_js"] = plotly_js

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(render_hub_html(pages), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
