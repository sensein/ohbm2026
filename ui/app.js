const DATA_FILES = {
  manifest: "./data/manifest.json",
  search: "./data/abstracts.search.json",
  details: "./data/abstracts.detail.json",
  facets: "./data/facets.json",
  relations: "./data/relations.json",
  clusters: "./data/clusters.json",
  projection: "./data/projection.umap.json",
};

const FACET_LABELS = {
  accepted_for: "Accepted for",
  primary_topic: "Primary topic",
  keywords: "Keywords",
  figure_keywords: "Figure keywords",
  methods: "Methods",
  study_type: "Study type",
  population: "Population",
  field_strength: "Field strength",
  processing_packages: "Processing packages",
  species: "Species",
  recording_technology: "Recording technology",
  brain_regions: "Brain regions",
  brain_networks: "Brain networks",
  semantic_15: "Semantic clusters (15)",
  semantic_21: "Semantic clusters (21)",
};

const CLUSTER_LAYER_LABELS = {
  semantic_15: "15-cluster view",
  semantic_21: "21-cluster view",
};

const SEARCH_MODE_LABELS = {
  lexical: "Lexical",
  semantic: "Semantic",
};

const SEARCH_MODE_DESCRIPTIONS = {
  lexical: "Quoted phrases, AND by default, OR between clauses, and -term exclusion.",
  semantic: "Embeds the query in-browser and ranks by vector similarity.",
};
const DEFAULT_OPEN_FACETS = new Set();

const state = {
  query: "",
  selectedId: null,
  clusterLayer: "semantic_15",
  searchMode: "lexical",
  semanticThreshold: 0,
  facets: {},
  expandedFacets: new Set(DEFAULT_OPEN_FACETS),
  projectionSelection: new Set(),
  semantic: {
    activeQuery: "",
    scores: null,
    status: "",
    busy: false,
    ready: false,
    requestId: 0,
  },
};

let store = null;
let searchRenderTimer = null;
let semanticBundlePromise = null;
let semanticExtractorPromise = null;

function tokenize(text) {
  return String(text || "")
    .toLowerCase()
    .split(/[^a-z0-9+.-]+/g)
    .map((token) => token.trim())
    .filter(Boolean);
}

function buildTokenFrequency(text) {
  const frequency = new Map();
  for (const token of tokenize(text)) {
    frequency.set(token, (frequency.get(token) || 0) + 1);
  }
  return frequency;
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function formatTopicSummary(primaryTopic, secondaryTopic) {
  const primary = String(primaryTopic || "").trim();
  const secondary = String(secondaryTopic || "").trim();
  if (!secondary || secondary === "Unknown" || secondary.toLowerCase() === primary.toLowerCase()) {
    return primary;
  }
  return `${primary} · ${secondary}`;
}

function loadUrlState() {
  const params = new URLSearchParams(window.location.search);
  state.query = params.get("q") || "";
  state.selectedId = params.get("abstract");
  state.clusterLayer = params.get("clusterView") || "semantic_15";
  state.searchMode = params.get("mode") || "lexical";
  state.semanticThreshold = Number(params.get("semanticThreshold") || "0") || 0;
  for (const group of Object.keys(FACET_LABELS)) {
    const value = params.get(group);
    state.facets[group] = new Set(value ? value.split("|").filter(Boolean) : []);
  }
}

function syncUrlState() {
  const params = new URLSearchParams();
  if (state.query) {
    params.set("q", state.query);
  }
  if (state.selectedId) {
    params.set("abstract", state.selectedId);
  }
  if (state.clusterLayer !== "semantic_15") {
    params.set("clusterView", state.clusterLayer);
  }
  if (state.searchMode !== "lexical") {
    params.set("mode", state.searchMode);
  }
  if (state.semanticThreshold > 0) {
    params.set("semanticThreshold", state.semanticThreshold.toFixed(2));
  }
  for (const [group, values] of Object.entries(state.facets)) {
    if (values.size > 0) {
      params.set(group, [...values].join("|"));
    }
  }
  const query = params.toString();
  history.replaceState({}, "", query ? `?${query}` : window.location.pathname);
}

function arrayValue(values) {
  return Array.isArray(values) ? values : values ? [values] : [];
}

function facetMatch(record, facetGroup, values) {
  if (!values || values.size === 0) {
    return true;
  }
  const recordValues = new Set(arrayValue(record.facets[facetGroup]));
  for (const value of values) {
    if (recordValues.has(value)) {
      return true;
    }
  }
  return false;
}

function matchesAllFacets(record, ignoredGroup = null) {
  if (state.projectionSelection.size > 0 && !state.projectionSelection.has(String(record.id))) {
    return false;
  }
  for (const [group, selected] of Object.entries(state.facets)) {
    if (group === ignoredGroup) {
      continue;
    }
    if (!facetMatch(record, group, selected)) {
      return false;
    }
  }
  return true;
}

function parseSearchQuery(query) {
  const tokens = String(query || "").match(/-?"[^"]+"|-?\S+/g) || [];
  const groups = [];
  let current = { must: [], mustNot: [] };

  function flushGroup() {
    if (current.must.length || current.mustNot.length) {
      groups.push(current);
    }
    current = { must: [], mustNot: [] };
  }

  for (const rawToken of tokens) {
    if (rawToken.toUpperCase() === "OR") {
      flushGroup();
      continue;
    }
    const negative = rawToken.startsWith("-");
    let value = negative ? rawToken.slice(1) : rawToken;
    if (value.startsWith('"') && value.endsWith('"')) {
      value = value.slice(1, -1);
    }
    value = value.trim().toLowerCase();
    if (!value) {
      continue;
    }
    const term = {
      value,
      isPhrase: /\s/.test(value),
    };
    if (negative) {
      current.mustNot.push(term);
    } else {
      current.must.push(term);
    }
  }
  flushGroup();
  return groups;
}

function recordMatchesTerm(record, term) {
  if (term.isPhrase) {
    return record._allTextLower.includes(term.value);
  }
  return record._allTokens.has(term.value);
}

function scoreTerm(record, term) {
  if (term.isPhrase) {
    let score = 0;
    if (record._titleLower.includes(term.value)) {
      score += 24;
    }
    if (record._allTextLower.includes(term.value)) {
      score += 10;
    }
    return score;
  }
  let score = 0;
  score += (record._titleTokens.get(term.value) || 0) * 10;
  score += (record._topicTokens.get(term.value) || 0) * 6;
  score += (record._keywordTokens.get(term.value) || 0) * 5;
  score += (record._blobTokens.get(term.value) || 0) * 1.5;
  return score;
}

function scoreLexicalRecord(record, queryGroups) {
  if (!queryGroups.length) {
    return 0;
  }

  let bestScore = Number.NEGATIVE_INFINITY;
  for (const group of queryGroups) {
    const groupBlocked = group.mustNot.some((term) => recordMatchesTerm(record, term));
    if (groupBlocked) {
      continue;
    }
    const allRequiredMatch = group.must.every((term) => recordMatchesTerm(record, term));
    if (!allRequiredMatch) {
      continue;
    }
    let groupScore = 0;
    for (const term of group.must) {
      groupScore += scoreTerm(record, term);
    }
    if (!group.must.length) {
      groupScore = 1;
    }
    bestScore = Math.max(bestScore, groupScore);
  }
  return Number.isFinite(bestScore) ? bestScore : 0;
}

function renderSemanticStatus() {
  const root = document.getElementById("semantic-status");
  if (!root) {
    return;
  }
  root.textContent = state.semantic.status || SEARCH_MODE_DESCRIPTIONS[state.searchMode] || "";
}

function renderSemanticThresholdControl() {
  const input = document.getElementById("semantic-threshold-input");
  const valueNode = document.getElementById("semantic-threshold-value");
  if (!input || !valueNode) {
    return;
  }
  input.value = state.semanticThreshold.toFixed(2);
  input.disabled = state.searchMode !== "semantic";
  valueNode.textContent = state.semanticThreshold.toFixed(2);
}

function semanticAvailable() {
  return Boolean(store?.manifest?.semantic_search);
}

async function ensureSemanticBundle() {
  if (!semanticAvailable()) {
    return null;
  }
  if (!semanticBundlePromise) {
    semanticBundlePromise = (async () => {
      const metadata = store.manifest.semantic_search;
      const response = await fetch(`./data/${metadata.filename}`);
      if (!response.ok) {
        throw new Error(`Failed to fetch semantic vectors: ${response.status}`);
      }
      const buffer = await response.arrayBuffer();
      return {
        metadata,
        vectors: new Float32Array(buffer),
      };
    })();
  }
  return semanticBundlePromise;
}

async function ensureSemanticExtractor() {
  if (!semanticExtractorPromise) {
    semanticExtractorPromise = (async () => {
      const module = await import("https://cdn.jsdelivr.net/npm/@xenova/transformers@2.17.2");
      module.env.allowLocalModels = false;
      return module.pipeline("feature-extraction", store.manifest.semantic_search.browser_model, {
        quantized: true,
      });
    })();
  }
  return semanticExtractorPromise;
}

function computeSemanticScores(queryVector, bundle) {
  const { dimension, count } = bundle.metadata;
  const scores = new Map();
  const vectors = bundle.vectors;
  for (let row = 0; row < count; row += 1) {
    const base = row * dimension;
    let score = 0;
    for (let column = 0; column < dimension; column += 1) {
      score += vectors[base + column] * queryVector[column];
    }
    scores.set(String(store.search.abstracts[row].id), score);
  }
  return scores;
}

async function refreshSemanticQuery(query) {
  const normalizedQuery = String(query || "").trim();
  state.semantic.requestId += 1;
  const requestId = state.semantic.requestId;

  if (!normalizedQuery || state.searchMode !== "semantic") {
    state.semantic.activeQuery = "";
    state.semantic.scores = null;
    state.semantic.busy = false;
    state.semantic.ready = false;
    state.semantic.status = SEARCH_MODE_DESCRIPTIONS[state.searchMode] || "";
    renderSemanticStatus();
    render();
    return;
  }

  if (!semanticAvailable()) {
    state.semantic.status = "Semantic search assets are not available in this export.";
    state.semantic.scores = null;
    renderSemanticStatus();
    render();
    return;
  }

  if (state.semantic.ready && state.semantic.activeQuery === normalizedQuery) {
    state.semantic.status = "Semantic ranking ready.";
    renderSemanticStatus();
    render();
    return;
  }

  state.semantic.busy = true;
  state.semantic.ready = false;
  state.semantic.status = "Computing browser-side query embedding…";
  renderSemanticStatus();
  render();

  try {
    const [bundle, extractor] = await Promise.all([ensureSemanticBundle(), ensureSemanticExtractor()]);
    const output = await extractor(normalizedQuery, {
      pooling: "mean",
      normalize: true,
    });
    if (requestId !== state.semantic.requestId) {
      return;
    }
    const queryVector = Array.from(output.data || []);
    state.semantic.scores = computeSemanticScores(queryVector, bundle);
    state.semantic.activeQuery = normalizedQuery;
    state.semantic.ready = true;
    state.semantic.busy = false;
    state.semantic.status = "Semantic ranking ready.";
    renderSemanticStatus();
    render();
  } catch (error) {
    if (requestId !== state.semantic.requestId) {
      return;
    }
    state.semantic.scores = null;
    state.semantic.busy = false;
    state.semantic.ready = false;
    state.semantic.status = `Semantic search unavailable: ${error.message}`;
    renderSemanticStatus();
    render();
  }
}

function filteredResults() {
  return rankedResults();
}

function rankedResults(ignoredFacetGroup = null) {
  const query = String(state.query || "").trim();
  const lexicalGroups = parseSearchQuery(query);
  const baseRecords = store.search.abstracts.filter((record) => matchesAllFacets(record, ignoredFacetGroup));
  const semanticModeReady =
    state.searchMode === "semantic" &&
    semanticAvailable() &&
    state.semantic.ready &&
    state.semantic.activeQuery === query &&
    state.semantic.scores;

  if (!query) {
    return baseRecords
      .map((record) => ({ record, score: 0 }))
      .sort((left, right) => left.record.title.localeCompare(right.record.title));
  }

  if (semanticModeReady) {
    return baseRecords
      .map((record) => ({
        record,
        score: state.semantic.scores.get(String(record.id)) || 0,
      }))
      .filter((item) => item.score >= state.semanticThreshold)
      .sort((left, right) => {
        if (right.score !== left.score) {
          return right.score - left.score;
        }
        return left.record.title.localeCompare(right.record.title);
      });
  }

  return baseRecords
    .map((record) => ({ record, score: scoreLexicalRecord(record, lexicalGroups) }))
    .filter((item) => item.score > 0)
    .sort((left, right) => {
      if (right.score !== left.score) {
        return right.score - left.score;
      }
      return left.record.title.localeCompare(right.record.title);
    });
}

function dynamicFacetOptions(group) {
  const counts = new Map();
  for (const { record } of rankedResults(group)) {
    for (const value of arrayValue(record.facets[group])) {
      const key = String(value);
      counts.set(key, (counts.get(key) || 0) + 1);
    }
  }
  for (const selected of state.facets[group] || []) {
    if (!counts.has(selected)) {
      counts.set(selected, 0);
    }
  }
  return [...counts.entries()]
    .map(([value, count]) => ({ value, count }))
    .sort((left, right) => left.value.localeCompare(right.value, undefined, { sensitivity: "base" }));
}

function setSelectedId(id) {
  state.selectedId = id ? String(id) : null;
  syncUrlState();
  render();
}

function toggleFacet(group, value) {
  const selection = state.facets[group];
  if (selection.has(value)) {
    selection.delete(value);
  } else {
    selection.add(value);
  }
  syncUrlState();
  render();
}

function resetFacets() {
  for (const group of Object.keys(FACET_LABELS)) {
    state.facets[group].clear();
  }
  syncUrlState();
  render();
}

function clearProjectionSelection() {
  state.projectionSelection.clear();
  render();
}

function toggleFacetGroup(group) {
  if (state.expandedFacets.has(group)) {
    state.expandedFacets.delete(group);
  } else {
    state.expandedFacets.add(group);
  }
  render();
}

function addFacetChip(label, onClick, extraClass = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = `chip is-action ${extraClass}`.trim();
  button.textContent = label;
  button.addEventListener("click", onClick);
  return button;
}

function renderClusterToggle() {
  const root = document.getElementById("cluster-toggle");
  root.replaceChildren();
  for (const [key, label] of Object.entries(CLUSTER_LAYER_LABELS)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = key === state.clusterLayer ? "is-active" : "";
    button.addEventListener("click", () => {
      state.clusterLayer = key;
      syncUrlState();
      render();
    });
    root.appendChild(button);
  }
}

function renderSearchModeToggle() {
  const root = document.getElementById("search-mode-toggle");
  root.replaceChildren();
  for (const [key, label] of Object.entries(SEARCH_MODE_LABELS)) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = label;
    button.className = key === state.searchMode ? "is-active" : "";
    button.addEventListener("click", () => {
      state.searchMode = key;
      if (key !== "semantic") {
        state.semantic.status = SEARCH_MODE_DESCRIPTIONS[key];
        state.semantic.busy = false;
      }
      syncUrlState();
      refreshSemanticQuery(state.query);
    });
    root.appendChild(button);
  }
}

function renderActiveFilters() {
  const root = document.getElementById("active-filters");
  root.replaceChildren();
  const chips = [];
  if (state.query) {
    chips.push(
      addFacetChip(`Query (${state.searchMode}): ${state.query}`, () => {
        state.query = "";
        state.semantic.activeQuery = "";
        state.semantic.scores = null;
        document.getElementById("search-input").value = "";
        syncUrlState();
        render();
      })
    );
  }
  if (state.projectionSelection.size > 0) {
    chips.push(
      addFacetChip(`Projection selection: ${state.projectionSelection.size}`, () => {
        clearProjectionSelection();
      })
    );
  }
  if (state.searchMode === "semantic" && state.semanticThreshold > 0) {
    chips.push(
      addFacetChip(`Semantic threshold: ${state.semanticThreshold.toFixed(2)}`, () => {
        state.semanticThreshold = 0;
        syncUrlState();
        render();
      })
    );
  }
  for (const [group, values] of Object.entries(state.facets)) {
    for (const value of values) {
      chips.push(
        addFacetChip(`${FACET_LABELS[group]}: ${value}`, () => {
          toggleFacet(group, value);
        })
      );
    }
  }
  if (chips.length === 0) {
    return;
  }
  for (const chip of chips) {
    root.appendChild(chip);
  }
}

function renderProjection() {
  const meta = document.getElementById("projection-meta");
  const root = document.getElementById("projection-plot");
  const hoverPanel = document.getElementById("projection-hover");
  if (!root) {
    return;
  }
  if (hoverPanel) {
    hoverPanel.innerHTML = "Hover a point to inspect its title, topic, and keywords without covering the plot.";
  }
  if (!window.Plotly) {
    meta.textContent = "Projection library unavailable.";
    root.innerHTML = `<div class="empty-state">Plotly did not load.</div>`;
    return;
  }
  const projection = store.projection?.umap;
  if (!projection || !(projection.points || []).length) {
    meta.textContent = "No projection exported for this site build.";
    root.innerHTML = `<div class="empty-state">No UMAP projection is available.</div>`;
    return;
  }

  const points = projection.points;
  const filteredIds = new Set(rankedResults().map(({ record }) => String(record.id)));
  const hasSubsetSelection =
    Boolean(String(state.query || "").trim()) ||
    state.projectionSelection.size > 0 ||
    Object.values(state.facets).some((values) => values.size > 0);
  const selectedIndices = [];
  points.forEach((point, index) => {
    if (!hasSubsetSelection || filteredIds.has(String(point.id))) {
      selectedIndices.push(index);
    }
  });
  const focusedPoint = state.selectedId
    ? points.find((point) => String(point.id) === String(state.selectedId))
    : null;
  meta.textContent =
    state.projectionSelection.size > 0
      ? `${state.projectionSelection.size} abstracts selected from the map`
      : "Click a point to open an abstract. Box- or lasso-select to create a result subset.";

  const traces = [{
    type: "scattergl",
    mode: "markers",
    x: points.map((point) => point.x),
    y: points.map((point) => point.y),
    text: points.map((point) => point.title),
    customdata: points.map((point) => [String(point.id), point.primary_topic, (point.keywords || []).join(", ")]),
    hoverinfo: "none",
    marker: {
      size: 7,
      color: "rgba(15, 118, 110, 0.65)",
      line: { width: 0 },
    },
    selectedpoints: hasSubsetSelection ? selectedIndices : null,
    selected: {
      marker: {
        color: "rgba(29, 78, 216, 0.95)",
        size: 9,
      },
    },
    unselected: {
      marker: {
        opacity: hasSubsetSelection ? 0.14 : 0.72,
      },
    },
  }];
  if (focusedPoint) {
    traces.push({
      type: "scattergl",
      mode: "markers",
      x: [focusedPoint.x],
      y: [focusedPoint.y],
      text: [focusedPoint.title],
      hoverinfo: "skip",
      marker: {
        size: 13,
        color: "rgba(180, 70, 120, 0.95)",
        line: {
          width: 2,
          color: "rgba(255, 255, 255, 0.95)",
        },
        symbol: "circle-open-dot",
      },
      showlegend: false,
    });
  }

  const layout = {
    margin: { l: 32, r: 16, t: 12, b: 36 },
    dragmode: "lasso",
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(255,255,255,0.92)",
    xaxis: { title: "UMAP 1", zeroline: false },
    yaxis: { title: "UMAP 2", zeroline: false },
  };

  window.Plotly.react(root, traces, layout, {
    displayModeBar: true,
    responsive: true,
    modeBarButtonsToRemove: ["select2d", "zoomIn2d", "zoomOut2d", "autoScale2d"],
  });

  if (!root.dataset.boundSelection) {
    root.on("plotly_hover", (event) => {
      const point = event?.points?.[0];
      if (!point || !hoverPanel) {
        return;
      }
      hoverPanel.innerHTML = `
        <strong>${escapeHtml(point.text || "Abstract")}</strong><br />
        #${escapeHtml(point.customdata?.[0] || "")}<br />
        ${escapeHtml(point.customdata?.[1] || "")}<br />
        ${escapeHtml(point.customdata?.[2] || "")}
      `;
    });
    root.on("plotly_unhover", () => {
      if (!hoverPanel) {
        return;
      }
      hoverPanel.innerHTML = "Hover a point to inspect its title, topic, and keywords without covering the plot.";
    });
    root.on("plotly_click", (event) => {
      const point = event?.points?.[0];
      if (!point) {
        return;
      }
      const abstractId = point.customdata?.[0];
      if (!abstractId) {
        return;
      }
      state.projectionSelection.clear();
      state.projectionSelection.add(String(abstractId));
      setSelectedId(abstractId);
    });
    root.on("plotly_selected", (event) => {
      if (!event?.points?.length) {
        return;
      }
      const nextSelection = new Set(event.points.map((point) => String(point.customdata?.[0])).filter(Boolean));
      state.projectionSelection = nextSelection;
      const firstId = event.points[0]?.customdata?.[0];
      if (firstId) {
        state.selectedId = String(firstId);
      }
      render();
    });
    root.on("plotly_doubleclick", () => {
      clearProjectionSelection();
    });
    root.dataset.boundSelection = "true";
  }
}

function renderFacets() {
  const root = document.getElementById("facet-groups");
  root.replaceChildren();
  for (const group of store.facets.groups) {
    const options = dynamicFacetOptions(group);
    if (!options.length) {
      continue;
    }
    const section = document.createElement("section");
    section.className = "facet-group";
    const isExpanded = state.expandedFacets.has(group) || state.facets[group].size > 0;
    if (!isExpanded) {
      section.classList.add("is-collapsed");
    }
    const headingButton = document.createElement("button");
    headingButton.type = "button";
    headingButton.className = "facet-group__toggle";
    headingButton.setAttribute("aria-expanded", String(isExpanded));
    headingButton.addEventListener("click", () => toggleFacetGroup(group));
    const headingLabel = document.createElement("span");
    headingLabel.className = "facet-group__label";
    headingLabel.textContent = FACET_LABELS[group] || group;
    const headingMeta = document.createElement("span");
    headingMeta.className = "facet-group__meta";
    headingMeta.textContent = state.facets[group].size > 0 ? `${state.facets[group].size} selected` : `${options.length} matching`;
    const headingChevron = document.createElement("span");
    headingChevron.className = "facet-group__chevron";
    headingChevron.textContent = isExpanded ? "−" : "+";
    headingButton.append(headingLabel, headingMeta, headingChevron);
    section.appendChild(headingButton);
    const optionsList = document.createElement("div");
    optionsList.className = "facet-options";
    for (const option of options) {
      const label = document.createElement("label");
      label.className = "facet-option";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.checked = state.facets[group].has(option.value);
      checkbox.addEventListener("change", () => toggleFacet(group, option.value));
      const value = document.createElement("span");
      value.textContent = option.value;
      const countNode = document.createElement("span");
      countNode.className = "facet-count";
      countNode.textContent = String(option.count);
      label.append(checkbox, value, countNode);
      optionsList.appendChild(label);
    }
    section.appendChild(optionsList);
    root.appendChild(section);
  }
}

function renderResults(items) {
  const root = document.getElementById("results-list");
  const resultsTitle = document.getElementById("results-title");
  const resultsMeta = document.getElementById("results-meta");
  root.replaceChildren();
  resultsTitle.textContent = `${items.length.toLocaleString()} matching abstracts`;

  if (!state.query) {
    resultsMeta.textContent = "Sorted alphabetically until a query is entered";
  } else if (state.searchMode === "semantic") {
    resultsMeta.textContent = state.semantic.ready
      ? `Semantic ranking for “${state.query}” · threshold ${state.semanticThreshold.toFixed(2)}`
      : `Preparing semantic ranking for “${state.query}”`;
  } else {
    resultsMeta.textContent = `Lexical ranking for “${state.query}”`;
  }

  if (items.length === 0) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "No abstracts match the current query and facet combination.";
    root.appendChild(empty);
    return;
  }

  const template = document.getElementById("result-template");
  for (const { record, score } of items.slice(0, 250)) {
    const node = template.content.firstElementChild.cloneNode(true);
    const button = node.querySelector(".result-card__button");
    if (String(record.id) === state.selectedId) {
      button.classList.add("is-selected");
    }
    button.addEventListener("click", () => setSelectedId(record.id));
    node.querySelector(".result-card__meta").textContent = `#${record.id} · ${record.accepted_for}`;
    node.querySelector(".result-card__title").textContent = record.title;
    node.querySelector(".result-card__topic").textContent = formatTopicSummary(
      record.primary_topic,
      record.secondary_topic
    );
    node.querySelector(".result-card__score").textContent = state.query ? score.toFixed(3) : "";

    const chipRow = node.querySelector(".chip-row");
    chipRow.appendChild(addFacetChip(record.primary_topic, () => toggleFacet("primary_topic", record.primary_topic), "is-topic"));
    for (const keyword of [...(record.keywords || []), ...(record.figure_keywords || [])].slice(0, 4)) {
      chipRow.appendChild(addFacetChip(keyword, () => toggleFacet("keywords", keyword), "is-muted"));
    }
    root.appendChild(node);
  }
}

function renderDetail() {
  const empty = document.getElementById("detail-empty");
  const view = document.getElementById("detail-view");
  view.replaceChildren();
  if (!state.selectedId || !store.details.abstracts[state.selectedId]) {
    empty.classList.remove("hidden");
    view.classList.add("hidden");
    return;
  }
  empty.classList.add("hidden");
  view.classList.remove("hidden");

  const detail = store.details.abstracts[state.selectedId];
  const relation = store.relations.abstracts[state.selectedId] || { neighbors: [], clusters: {} };
  const activePartition = store.clusters.partitions[state.clusterLayer];
  const activeClusterId = relation.clusters[state.clusterLayer];
  const activeCluster = activePartition?.clusters.find((cluster) => cluster.cluster_id === activeClusterId);

  const header = document.createElement("section");
  header.className = "detail-header";
  header.innerHTML = `
    <div>
      <p class="eyebrow">${escapeHtml(detail.accepted_for)} · #${escapeHtml(detail.id)}</p>
      <h2>${escapeHtml(detail.title)}</h2>
      <p class="detail-meta">${escapeHtml(formatTopicSummary(detail.primary_topic, detail.secondary_topic))}</p>
    </div>
  `;
  view.appendChild(header);

  const chips = document.createElement("div");
  chips.className = "chip-row";
  for (const keyword of (detail.keywords || []).slice(0, 8)) {
    chips.appendChild(addFacetChip(keyword, () => toggleFacet("keywords", keyword), "is-muted"));
  }
  for (const keyword of (detail.figure_keywords || []).slice(0, 4)) {
    chips.appendChild(addFacetChip(keyword, () => toggleFacet("figure_keywords", keyword), "is-cluster"));
  }
  view.appendChild(chips);

  const metadataBlock = document.createElement("section");
  metadataBlock.className = "detail-block";
  metadataBlock.innerHTML = "<h3>Metadata</h3>";
  const metadataGrid = document.createElement("div");
  metadataGrid.className = "detail-grid";
  const metadataItems = [
    ["Methods", detail.methods],
    ["Study type", detail.study_type],
    ["Population", detail.population],
    ["Field strength", detail.field_strength],
    ["Processing packages", detail.processing_packages],
    ["Species", detail.species],
    ["Recording technology", detail.recording_technology],
    ["Brain regions", detail.brain_regions],
    ["Brain networks", detail.brain_networks],
  ];
  for (const [label, values] of metadataItems) {
    const card = document.createElement("div");
    card.className = "detail-card";
    card.innerHTML = `<h4>${escapeHtml(label)}</h4><p>${escapeHtml(arrayValue(values).join(", ") || "Not specified")}</p>`;
    metadataGrid.appendChild(card);
  }
  metadataBlock.appendChild(metadataGrid);
  view.appendChild(metadataBlock);

  const clusterBlock = document.createElement("section");
  clusterBlock.className = "detail-block";
  clusterBlock.innerHTML = `<h3>Semantic context · ${escapeHtml(CLUSTER_LAYER_LABELS[state.clusterLayer])}</h3>`;
  if (activeCluster) {
    const card = document.createElement("div");
    card.className = "detail-card";
    card.innerHTML = `
      <h4>Cluster ${activeCluster.cluster_id}: ${escapeHtml(activeCluster.label)}</h4>
      <p class="section-note">${activeCluster.size.toLocaleString()} abstracts · keywords: ${escapeHtml(activeCluster.keywords.join(", "))}</p>
    `;
    const representativeList = document.createElement("div");
    representativeList.className = "link-list";
    for (const item of activeCluster.representative_abstracts.slice(0, 4)) {
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `<strong>#${item.id}</strong><br />${escapeHtml(item.title)}`;
      button.addEventListener("click", () => setSelectedId(item.id));
      representativeList.appendChild(button);
    }
    card.appendChild(representativeList);
    clusterBlock.appendChild(card);
  } else {
    clusterBlock.innerHTML += `<div class="empty-state">No cluster assignment found for the active semantic layer.</div>`;
  }
  view.appendChild(clusterBlock);

  const relationsBlock = document.createElement("section");
  relationsBlock.className = "detail-block";
  relationsBlock.innerHTML = "<h3>Related abstracts</h3>";
  if ((relation.neighbors || []).length > 0) {
    const list = document.createElement("div");
    list.className = "link-list";
    for (const neighbor of relation.neighbors.slice(0, 8)) {
      const record = store.byId[String(neighbor.id)];
      const button = document.createElement("button");
      button.type = "button";
      button.innerHTML = `
        <strong>#${neighbor.id}</strong> · ${escapeHtml(record?.accepted_for || "Unknown")}<br />
        ${escapeHtml(record?.title || "Unknown abstract")}<br />
        <span class="reference-note">Similarity ${Number(neighbor.score).toFixed(3)}</span>
      `;
      button.addEventListener("click", () => setSelectedId(neighbor.id));
      list.appendChild(button);
    }
    relationsBlock.appendChild(list);
  } else {
    relationsBlock.innerHTML += `<div class="empty-state">No precomputed nearest neighbors available.</div>`;
  }
  view.appendChild(relationsBlock);

  const sectionsBlock = document.createElement("section");
  sectionsBlock.className = "detail-block";
  sectionsBlock.innerHTML = "<h3>Abstract content</h3>";
  for (const section of detail.sections) {
    const article = document.createElement("article");
    article.className = "detail-card";
    article.innerHTML = `<h4>${escapeHtml(section.label)}</h4><div class="section-html">${section.html}</div>`;
    sectionsBlock.appendChild(article);
  }
  view.appendChild(sectionsBlock);

  const figureBlock = document.createElement("section");
  figureBlock.className = "detail-block";
  figureBlock.innerHTML = "<h3>Figure notes</h3>";
  if ((detail.figure_analyses || []).length > 0) {
    for (const figure of detail.figure_analyses) {
      const card = document.createElement("article");
      card.className = "detail-card";
      card.innerHTML = `
        <h4>${escapeHtml(figure.question_name || "Figure analysis")}</h4>
        <p class="section-note">${escapeHtml(figure.caption_guess || "No caption guess")}</p>
        <div class="section-html">${figure.rich_html || `<p>${escapeHtml(figure.notes || "")}</p>`}</div>
      `;
      figureBlock.appendChild(card);
    }
  } else {
    figureBlock.innerHTML += `<div class="empty-state">No cached figure analysis is available for this abstract.</div>`;
  }
  view.appendChild(figureBlock);

  const referencesBlock = document.createElement("section");
  referencesBlock.className = "detail-block";
  referencesBlock.innerHTML = "<h3>Reference matches</h3>";
  const referenceSummary = detail.reference_summary || { matched_count: 0, unmatched_count: 0, items: [], unmatched_items: [] };
  const headerNote = document.createElement("p");
  headerNote.className = "reference-note";
  headerNote.textContent = `${referenceSummary.matched_count} matched · ${referenceSummary.unmatched_count} unmatched`;
  referencesBlock.appendChild(headerNote);
  if ((referenceSummary.items || []).length > 0) {
    const list = document.createElement("div");
    list.className = "link-list";
    for (const item of referenceSummary.items) {
      const link = item.openalex_id
        ? `<a href="${item.openalex_id}" target="_blank" rel="noreferrer">OpenAlex</a>`
        : "";
      const container = document.createElement("div");
      container.className = "detail-card";
      container.innerHTML = `
        <h4>${escapeHtml(item.title || "Matched reference")}</h4>
        <p class="section-note">${escapeHtml([item.journal, item.year].filter(Boolean).join(" · "))}</p>
        <p class="reference-note">Cited by ${item.cited_by_count ?? "?"} ${link}</p>
      `;
      list.appendChild(container);
    }
    referencesBlock.appendChild(list);
  } else {
    referencesBlock.innerHTML += `<div class="empty-state">No OpenAlex-matched references are cached for this abstract.</div>`;
  }
  if ((referenceSummary.unmatched_items || []).length > 0) {
    const unmatchedHeading = document.createElement("h4");
    unmatchedHeading.textContent = "Unmatched references";
    referencesBlock.appendChild(unmatchedHeading);
    const unmatchedList = document.createElement("div");
    unmatchedList.className = "link-list";
    for (const item of referenceSummary.unmatched_items) {
      const container = document.createElement("div");
      container.className = "detail-card";
      container.innerHTML = `
        <h4>${escapeHtml(item.title || "Unmatched reference")}</h4>
        <p class="reference-note">${escapeHtml(item.raw_text || "No reference text available.")}</p>
      `;
      unmatchedList.appendChild(container);
    }
    referencesBlock.appendChild(unmatchedList);
  }
  view.appendChild(referencesBlock);
}

function render() {
  const items = filteredResults();
  document.getElementById("summary-text").textContent = `${store.manifest.abstract_count.toLocaleString()} abstracts loaded`;
  renderSearchModeToggle();
  renderClusterToggle();
  renderSemanticStatus();
  renderSemanticThresholdControl();
  renderActiveFilters();
  renderFacets();
  renderProjection();
  renderResults(items);
  if (!state.selectedId && items.length > 0) {
    state.selectedId = String(items[0].record.id);
    syncUrlState();
  }
  renderDetail();
}

async function loadStore() {
  const [manifest, search, details, facets, relations, clusters, projection] = await Promise.all(
    Object.values(DATA_FILES).map((url) => fetch(url).then((response) => response.json()))
  );
  const preparedSearchAbstracts = search.abstracts.map((record) => {
    const allText = [
      record.title || "",
      record.primary_topic || "",
      ...(record.keywords || []),
      ...(record.figure_keywords || []),
      record.search_blob || "",
    ].join(" ");
    return {
      ...record,
      _titleLower: String(record.title || "").toLowerCase(),
      _allTextLower: allText.toLowerCase(),
      _titleTokens: buildTokenFrequency(record.title || ""),
      _topicTokens: buildTokenFrequency(record.primary_topic || ""),
      _keywordTokens: buildTokenFrequency([...(record.keywords || []), ...(record.figure_keywords || [])].join(" ")),
      _blobTokens: buildTokenFrequency(record.search_blob || ""),
      _allTokens: buildTokenFrequency(allText),
    };
  });
  search.abstracts = preparedSearchAbstracts;
  const byId = Object.fromEntries(search.abstracts.map((record) => [String(record.id), record]));
  return { manifest, search, details, facets, relations, clusters, projection, byId };
}

function scheduleSearchRefresh(nextValue) {
  window.clearTimeout(searchRenderTimer);
  searchRenderTimer = window.setTimeout(() => {
    state.query = nextValue.trim();
    syncUrlState();
    render();
    refreshSemanticQuery(state.query);
  }, 140);
}

function attachEvents() {
  const searchInput = document.getElementById("search-input");
  searchInput.value = state.query;
  searchInput.addEventListener("input", (event) => {
    scheduleSearchRefresh(event.target.value);
  });
  document.getElementById("clear-search").addEventListener("click", () => {
    state.query = "";
    state.semantic.activeQuery = "";
    state.semantic.scores = null;
    searchInput.value = "";
    syncUrlState();
    render();
    refreshSemanticQuery("");
  });
  document.getElementById("clear-filters").addEventListener("click", () => {
    resetFacets();
  });
  document.getElementById("clear-projection-selection").addEventListener("click", () => {
    clearProjectionSelection();
  });
  document.getElementById("semantic-threshold-input").addEventListener("input", (event) => {
    state.semanticThreshold = Number(event.target.value || "0") || 0;
    syncUrlState();
    render();
  });
}

async function main() {
  loadUrlState();
  Object.keys(FACET_LABELS).forEach((group) => {
    state.facets[group] = state.facets[group] || new Set();
    if (state.facets[group].size > 0) {
      state.expandedFacets.add(group);
    }
  });
  attachEvents();
  store = await loadStore();
  state.semantic.status = SEARCH_MODE_DESCRIPTIONS[state.searchMode] || "";
  render();
  await refreshSemanticQuery(state.query);
}

main().catch((error) => {
  const root = document.getElementById("results-list");
  root.innerHTML = `<div class="empty-state">Failed to load static UI data: ${escapeHtml(error.message)}</div>`;
  console.error(error);
});
