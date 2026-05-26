<script lang="ts">
	import { createEventDispatcher, onMount, onDestroy } from 'svelte';
	import { selectedCell, lassoSelection, focusedAbstract } from '$lib/stores/selection';
	import { effectiveTheme } from '$lib/stores/theme';
	import { loadCell, loadTopics, type CellShard, type TopicShard } from '$lib/shards';
	import type { AbstractRecord } from '$lib/shards';

	/**
	 * Stage 15 — unified UMAP panel. Drives all three subsites:
	 *
	 *   - `mode='ohbm'` (default; existing behaviour) — renders the
	 *     OHBM 2026 home page's per-community scatter from
	 *     `cell_shard` + `abstracts`. Lasso writes to
	 *     `$lassoSelection`; click writes to `$focusedAbstract`.
	 *     Per-community marker symbols cycle through 5 shapes ×
	 *     Tol-bright colour palette.
	 *   - `mode='atlas' | 'neuroscape'` (Stage 15 new) — renders a
	 *     simpler two-trace scatter from `backdropPoints` +
	 *     `overlayPoints` + `clusters`. Cluster count is usually too
	 *     large (~175) for shape variation to read, so per-point
	 *     symbol cycling is gated by `shapeVariation`:
	 *       - 'auto'        → shape if `clusters.length ≤ 7`
	 *       - 'color-only'  → no symbol cycling (default for atlas)
	 *       - 'color+shape' → force shape cycling
	 *     Atlas mode dispatches `pointclick`, `lassoselect`,
	 *     `lassoclear` events instead of writing to the OHBM stores;
	 *     the parent decides whether to open a detail panel or
	 *     navigate.
	 *
	 *  Common across all modes: 2D + 3D side-by-side; pause/rotate
	 *  with camera-preserved-across-toggle (`currentEye3D` tracked
	 *  via `plotly_relayout` listener); mobile-responsive stacked
	 *  layout; theme-aware colours.
	 */
	export let mode: 'ohbm' | 'atlas' | 'neuroscape' = 'ohbm';

	// === OHBM mode props (existing) ========================================
	export let abstracts: AbstractRecord[] = [];
	/**
	 * Set of poster_ids the rest of the app considers "currently selected"
	 * — i.e. the intersection of search ∩ lasso ∩ facets. The UMAP dims
	 * everything outside this set so picking a cluster or facet visually
	 * narrows the map alongside the result list. `null` = no narrowing
	 * (every point at full opacity).
	 */
	export let selection: Set<number> | null = null;
	/**
	 * Mobile breakpoint — desktop ≥ 1024px renders 2D + 3D side-by-side
	 * with lasso on the 2D pane. Smaller viewports stack vertically and
	 * use tap-to-filter-by-community for the 2D pane (FR-005 Edge Case).
	 */
	export let mobileBreakpoint = 1024;

	// === Atlas/neuroscape mode props (Stage 15 new) =========================
	type BackdropPoint = {
		pubmed_id: number;
		title: string;
		year: number;
		cluster_id: number;
		umap_2d?: [number, number];
		umap_3d: [number, number, number];
	};
	type OverlayPoint = {
		submission_id: number;
		poster_id: number;
		title: string;
		nearest_cluster_id: number;
		umap_2d?: [number, number];
		umap_3d: [number, number, number];
	};
	type AtlasCluster = {
		cluster_id: number;
		title: string;
		colour_hex: string;
	};

	export let backdropPoints: BackdropPoint[] = [];
	export let overlayPoints: OverlayPoint[] = [];
	export let atlasClusters: AtlasCluster[] = [];
	export let showOverlay = true;
	export let backdropOpacity = 0.05;
	/** Symbol cycling policy for the new atlas/neuroscape modes. */
	export let shapeVariation: 'auto' | 'color-only' | 'color+shape' = 'auto';
	/**
	 * Lasso highlight sets (atlas / neuroscape mode). When non-empty,
	 * the 2D scattergl traces set `selectedpoints` + dim the
	 * unselected via Plotly's selected/unselected marker styles, AND
	 * the 3D scene zooms to the bounding box of the selected points.
	 *
	 * The parent owns the sets (so the result list can filter to the
	 * lasso simultaneously); the panel reads them and updates the
	 * scatter visuals.
	 */
	export let lassoOhbmSet: Set<number> = new Set();
	export let lassoNeuroSet: Set<number> = new Set();
	/** Focus halo — when the inline detail panel is open on atlas-root
	 *  / neuroscape, the parent passes the selected point's kind + id
	 *  so the chart can render a bigger outlined marker at the
	 *  matching point's coordinates. Without this, "Show on atlas"
	 *  navigates from the abstract permalink to the home but the
	 *  visitor has no visual hint of WHICH dot they were looking at.
	 */
	export let atlasFocusKind: 'ohbm2026' | 'neuroscape' | null = null;
	export let atlasFocusId: number | null = null;

	const dispatch = createEventDispatcher<{
		pointclick: { kind: 'ohbm2026' | 'neuroscape'; id: number };
		lassoselect: { ohbm2026_ids: number[]; neuroscape_ids: number[] };
		lassoclear: void;
	}>();

	$: clustersById = new Map(atlasClusters.map((c) => [c.cluster_id, c]));
	$: useAtlasShapes = (() => {
		if (shapeVariation === 'color-only') return false;
		if (shapeVariation === 'color+shape') return true;
		// 'auto': shape only if we have few enough clusters.
		return atlasClusters.length > 0 && atlasClusters.length <= 7;
	})();

	type PlotlyApi = typeof import('plotly.js-dist-min');

	let plotly: PlotlyApi | null = null;
	let plotlyLoading = false;
	let plotlyError: string | null = null;

	let chart2dEl: HTMLDivElement | null = null;
	let chart3dEl: HTMLDivElement | null = null;
	let cellShard: CellShard | null = null;
	let topicsShard: TopicShard | null = null;
	let cellLoading = false;
	let cellError: string | null = null;

	let viewportWidth = typeof window !== 'undefined' ? window.innerWidth : 1280;
	let mobile = viewportWidth < mobileBreakpoint;

	let autoRotate = true;
	let rotateFrame: number | null = null;
	let rotateAngle = 0;

	// Track whether each chart already has event listeners attached so we
	// don't stack duplicate handlers on every render (Plotly's `on(...)`
	// stacks; only `react()` is idempotent for the chart itself).
	let handlers2dAttached = false;
	let handlers3dAttached = false;
	let chart3dInitialized = false;

	// Authoritative camera eye for the 3D chart, kept in sync with both
	// programmatic rotation frames AND user mouse interactions via the
	// `plotly_relayout` event. Reading `_fullLayout.scene.camera.eye` after
	// a pause+zoom turned out to be unreliable in this Plotly bundle —
	// listening to the event gives us a deterministic source of truth.
	let currentEye3D: { x: number; y: number; z: number } | null = null;

	$: cellKey = `${$selectedCell.model}_${$selectedCell.input}`;

	function onResize() {
		viewportWidth = window.innerWidth;
		mobile = viewportWidth < mobileBreakpoint;
		if (plotly) {
			if (chart2dEl) plotly.Plots.resize(chart2dEl);
			if (chart3dEl) plotly.Plots.resize(chart3dEl);
		}
	}

	// Pause/resume rotation tied to tab visibility + page hide. The
	// browser bfcache can leave the page suspended for a long time —
	// when it returns, any rAF callbacks scheduled before suspension
	// fire immediately + can pile onto a fresh ensureRotate from the
	// remount. These listeners stop the loop deterministically.
	//
	// pagehide additionally purges the Plotly charts so their WebGL
	// contexts release the GPU. Why: cross-deployment sibling
	// navigation (e.g. /neuroscape/ → /ohbm2026/) bfcaches the prior
	// page; without purge the suspended page keeps its WebGL contexts
	// allocated, contending with the new page's charts (browsers cap
	// at ~16 contexts/origin) and producing visible lag on the new
	// page. We re-render on pageshow if the page is bfcache-restored.
	let renderToken = 0;
	/**
	 * Force-release a Plotly chart's WebGL context. `Plotly.purge`
	 * alone doesn't always destroy the underlying gl-vis canvas
	 * (plotly.js#2852, #6365): the canvas element survives in the
	 * div, holding its WebGL context open. Browsers cap origin-wide
	 * GL contexts (~16 in Chrome), so toggling hide/show on the
	 * 461k-point scatter3d a few times exhausts the pool. Explicitly
	 * iterating canvas children + calling `loseContext()` releases
	 * the context immediately; then clearing innerHTML wipes any
	 * remaining DOM bookkeeping Plotly held.
	 */
	function destroyChart(el: HTMLDivElement | null) {
		if (!el) return;
		if (plotly) plotly.purge(el);
		// Iterate ALL canvases (Plotly creates several — 2D scattergl
		// uses one, scatter3d uses one + an HUD canvas).
		for (const canvas of Array.from(el.querySelectorAll('canvas'))) {
			const gl =
				(canvas as HTMLCanvasElement).getContext?.('webgl2') ??
				(canvas as HTMLCanvasElement).getContext?.('webgl');
			const lc = gl?.getExtension?.('WEBGL_lose_context');
			lc?.loseContext?.();
		}
		el.innerHTML = '';
	}
	function purgeCharts() {
		destroyChart(chart2dEl);
		destroyChart(chart3dEl);
		handlers2dAttached = false;
		handlers3dAttached = false;
		atlas2dHandlersAttached = false;
		atlas3dHandlersAttached = false;
		chart3dInitialized = false;
		// Reset the focus tracker so the next render after a bfcache
		// restore or Hide/Show cycle re-applies the zoom-to-focus
		// range (the chart's prior range was wiped along with the
		// rest of its state).
		last2dFocusKey = '';
		last2dUirev = 'atlas-2d';
		current2dXSpan = 0;
		// Drop the 2D array cache so post-bfcache restore renders
		// build fresh references that match the (purged-then-reborn)
		// chart's internal data buffers. Stale cached arrays could
		// otherwise cause Plotly's identity comparison to short-
		// circuit the rebuild it actually needs.
		cached2dBackdropArrays = null;
		cached2dBackdropKey = '';
		cached2dOverlayArrays = null;
		cached2dOverlayKey = '';
	}
	function onVisibilityChange() {
		if (typeof document === 'undefined') return;
		if (document.visibilityState === 'hidden') {
			stopRotate();
		} else if (autoRotate) {
			ensureRotate();
		}
	}
	function onPageHide() {
		stopRotate();
		purgeCharts();
	}
	function onPageShow(ev: PageTransitionEvent) {
		if (!ev.persisted) return;
		// bfcache restore. Belt-and-braces reset before re-render:
		// pagehide should have purged the charts already, but a race
		// can leave latent rAF callbacks or stale `currentEye3D` /
		// `rotateAngle` that produce a visible camera jolt on the
		// next ensureRotate tick. Re-purge + reset the rotation state
		// so the chart inits from a clean slate. The parquet itself
		// is held in the Cache API (see `data_package/cache.ts`), so
		// the re-render reads from cache — no network hit.
		stopRotate();
		purgeCharts();
		rotateAngle = 0;
		currentEye3D = null;
		renderToken += 1;
	}

	onMount(async () => {
		window.addEventListener('resize', onResize);
		document.addEventListener('visibilitychange', onVisibilityChange);
		window.addEventListener('pagehide', onPageHide);
		window.addEventListener('pageshow', onPageShow);
		await ensurePlotly();
	});

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('resize', onResize);
			window.removeEventListener('pagehide', onPageHide);
			window.removeEventListener('pageshow', onPageShow);
		}
		if (typeof document !== 'undefined') {
			document.removeEventListener('visibilitychange', onVisibilityChange);
		}
		stopRotate();
		purgeCharts();
	});

	async function ensurePlotly() {
		if (plotly || plotlyLoading) return;
		plotlyLoading = true;
		try {
			plotly = (await import('plotly.js-dist-min')).default as PlotlyApi;
		} catch (err) {
			plotlyError = (err as Error).message;
		} finally {
			plotlyLoading = false;
		}
	}

	$: void (async () => {
		// Cell-shard load only runs in OHBM mode — atlas/neuroscape get
		// their cluster geometry from the `atlasClusters` prop.
		if (mode !== 'ohbm') return;
		const key = cellKey;
		cellLoading = true;
		cellError = null;
		const [shard, topics] = await Promise.all([
			loadCell(key),
			loadTopics(key, 'communities')
		]);
		if (key === cellKey) {
			cellShard = shard;
			topicsShard = topics;
			cellLoading = false;
			if (shard === null) cellError = 'cell shard not available';
		}
	})();

	$: theme = $effectiveTheme;
	$: topicByCluster = (() => {
		const map = new Map<number, string>();
		if (topicsShard) {
			for (const t of topicsShard.topics) {
				const label = t.title || (t.keywords.length ? t.keywords.slice(0, 3).join(', ') : `cluster ${t.cluster_id}`);
				map.set(t.cluster_id, label);
			}
		}
		return map;
	})();
	// poster_id of the user-focused abstract (the one whose detail panel is
	// open). Highlighted on both charts with a halo marker.
	$: focusedAbstractId = (() => {
		if (!$focusedAbstract) return null;
		const rec = abstracts.find((a) => a.poster_id === $focusedAbstract);
		return rec ? rec.poster_id : null;
	})();
	$: if (mode === 'ohbm') {
		// renderToken is a tracked dep so bfcache-restore (which purges
		// the charts) re-fires this block from onPageShow.
		void renderToken;
		void renderChart2D(
			plotly,
			chart2dEl,
			cellShard,
			abstracts,
			selection,
			mobile,
			theme,
			topicByCluster,
			focusedAbstractId
		);
		void renderChart3D(
			plotly,
			chart3dEl,
			cellShard,
			abstracts,
			selection,
			theme,
			topicByCluster,
			focusedAbstractId
		);
	} else {
		// Atlas / neuroscape mode — 2D render. Tracks lasso state so
		// scattergl's native `selectedpoints` + selected/unselected
		// marker opacity update on every lasso change. The 3D render
		// is split into a SEPARATE reactive block below (intentionally
		// not lasso-aware at this point-count). See that block for
		// the rationale.
		void renderToken;
		void renderAtlasChart2D(
			plotly,
			chart2dEl,
			backdropPoints,
			overlayPoints,
			clustersById,
			showOverlay,
			backdropOpacity,
			useAtlasShapes,
			lassoOhbmSet,
			lassoNeuroSet,
			atlasFocusKind,
			atlasFocusId,
			theme
		);
	}

	// Atlas / neuroscape 3D render — INTENTIONALLY lasso-agnostic at
	// this point-count (461k backdrop + 3,240 overlay). Mirroring the
	// 2D lasso here would require a dual-trace selected/unselected
	// split (scatter3d ignores `selectedpoints`) and the per-cycle
	// `Plotly.react` rebuild leaks ~620 MB / cycle via plotly.js#6365
	// (WebGL contexts not destroyed when trace count changes).
	//
	// Single-clicked points still get the magenta focus halo via
	// `atlasFocusKind` + `atlasFocusId` — the per-single-point
	// highlight stays cheap (one extra trace, one point). "See this
	// lassoed point in 3D" works by clicking any result in the
	// narrowed list → focus halo + detail panel.
	//
	// OHBM mode (renderChart3D, above) is unaffected — its per-
	// community scatter is ~3k points total, well below where the
	// leak matters, so its existing selection mirror keeps working.
	//
	// Separate reactive block so Svelte's dep tracker does NOT pick
	// up `lassoOhbmSet` / `lassoNeuroSet` here. The 3D render fires
	// only on data, theme, overlay-toggle, opacity, or focus changes.
	$: if (mode !== 'ohbm') {
		void renderToken;
		void renderAtlasChart3D(
			plotly,
			chart3dEl,
			backdropPoints,
			overlayPoints,
			clustersById,
			showOverlay,
			backdropOpacity,
			useAtlasShapes,
			atlasFocusKind,
			atlasFocusId,
			theme
		);
	}

	// Paul Tol's "bright" qualitative palette — high-contrast, deuteranopia /
	// protanopia / tritanopia safe. Communities are CATEGORICAL (the integer
	// ids are labels, not magnitudes) so we MUST use a discrete palette and
	// NOT a continuous colorscale. To extend past 7 distinct communities the
	// renderer also cycles through marker symbols, giving 7 × N_SYMBOLS
	// (~35–40) perceptually distinct combinations before any pair repeats.
	const TOL_BRIGHT = [
		'#4477AA', // blue
		'#EE6677', // red-pink
		'#228833', // green
		'#CCBB44', // yellow
		'#66CCEE', // cyan
		'#AA3377', // purple
		'#BBBBBB' // grey
	];
	const SYMBOLS_2D = ['circle', 'diamond', 'square', 'triangle-up', 'cross'];
	// scatter3d supports a narrower set; use only those.
	const SYMBOLS_3D = ['circle', 'diamond', 'square', 'cross', 'x'];

	function colorFor(communityId: number): string {
		const idx = ((communityId % TOL_BRIGHT.length) + TOL_BRIGHT.length) % TOL_BRIGHT.length;
		return TOL_BRIGHT[idx];
	}
	function symbol2DFor(communityId: number): string {
		const bucket = Math.floor(communityId / TOL_BRIGHT.length);
		return SYMBOLS_2D[((bucket % SYMBOLS_2D.length) + SYMBOLS_2D.length) % SYMBOLS_2D.length];
	}
	function symbol3DFor(communityId: number): string {
		const bucket = Math.floor(communityId / TOL_BRIGHT.length);
		return SYMBOLS_3D[((bucket % SYMBOLS_3D.length) + SYMBOLS_3D.length) % SYMBOLS_3D.length];
	}

	function buildSeries(
		shard: CellShard,
		records: AbstractRecord[],
		selected: Set<number> | null,
		topicMap: Map<number, string>
	) {
		const xs2: number[] = [];
		const ys2: number[] = [];
		const xs3: number[] = [];
		const ys3: number[] = [];
		const zs3: number[] = [];
		const posters: number[] = [];
		const titles: string[] = [];
		const communityLabels: string[] = [];
		const communityIds: number[] = [];
		const markerColors: string[] = [];
		const markerSymbols2D: string[] = [];
		const markerSymbols3D: string[] = [];
		const selectedIdx: number[] = [];
		const idx2dByAbstract = new Map<number, number>();
		for (let i = 0; i < shard.rows.length; i++) {
			const row = shard.rows[i];
			const rec = records[i];
			if (!rec) continue;
			if (row.umap_missing) continue;
			xs2.push(row.umap2d[0]);
			ys2.push(row.umap2d[1]);
			xs3.push(row.umap3d[0]);
			ys3.push(row.umap3d[1]);
			zs3.push(row.umap3d[2]);
			posters.push(rec.poster_id);
			titles.push(rec.title);
			communityLabels.push(topicMap.get(row.community_id) ?? `community ${row.community_id}`);
			communityIds.push(row.community_id);
			markerColors.push(colorFor(row.community_id));
			markerSymbols2D.push(symbol2DFor(row.community_id));
			markerSymbols3D.push(symbol3DFor(row.community_id));
			idx2dByAbstract.set(row.poster_id, xs2.length - 1);
			if (selected !== null && selected.has(row.poster_id)) selectedIdx.push(xs2.length - 1);
		}
		return {
			xs2,
			ys2,
			xs3,
			ys3,
			zs3,
			posters,
			titles,
			communityLabels,
			communityIds,
			markerColors,
			markerSymbols2D,
			markerSymbols3D,
			selectedIdx,
			idx2dByAbstract
		};
	}

	function themedColors(t: 'light' | 'dark') {
		return t === 'dark'
			? { paper: '#0f1419', plot: '#161b22', font: '#e8e8e8', grid: '#2a3138' }
			: { paper: '#ffffff', plot: '#fafafa', font: '#222222', grid: '#d6d6d6' };
	}

	function renderChart2D(
		api: PlotlyApi | null,
		el: HTMLDivElement | null,
		shard: CellShard | null,
		records: AbstractRecord[],
		selected: Set<number> | null,
		isMobile: boolean,
		t: 'light' | 'dark',
		topicMap: Map<number, string>,
		focusedId: number | null
	) {
		if (!api || !el || !shard) return;
		const s = buildSeries(shard, records, selected, topicMap);
		// Locate the focused abstract's position in the visible-points arrays.
		let focusedIdx = -1;
		if (focusedId !== null) {
			let visibleIdx = 0;
			for (const row of shard.rows) {
				if (row.umap_missing) continue;
				if (row.poster_id === focusedId) {
					focusedIdx = visibleIdx;
					break;
				}
				visibleIdx += 1;
			}
		}
		const t1 = {
			type: 'scatter' as const,
			mode: 'markers' as const,
			x: s.xs2,
			y: s.ys2,
			marker: {
				size: 7,
				color: s.markerColors,
				symbol: s.markerSymbols2D,
				opacity: 0.85,
				line: { width: 0 }
			},
			customdata: s.posters.map((p, i) => [p, s.titles[i], s.communityLabels[i]]) as unknown as number[][],
			hovertemplate:
				'<b>%{customdata[0]}</b><br>%{customdata[1]}<br><i>%{customdata[2]}</i><extra></extra>',
			selectedpoints: s.selectedIdx.length ? s.selectedIdx : undefined,
			unselected: { marker: { opacity: 0.2 } },
			selected: { marker: { opacity: 1 } }
		};
		// Second trace: a single halo marker for the user-focused abstract so
		// it pops above the colour-cluster carpet. Drawn last (on top).
		// For Plotly's `circle-open` symbol the OUTLINE colour comes from
		// `marker.color` (not `marker.line.color`). Use a thick filled-circle
		// outline behind a smaller filled circle in the cluster colour — that
		// way the highlight reads even if the underlying point is dimmed by
		// the lasso/facet selection.
		const traces2d: unknown[] = [t1];
		if (focusedIdx >= 0) {
			const haloOutline = t === 'dark' ? '#FFFFFF' : '#000000';
			traces2d.push({
				type: 'scatter' as const,
				mode: 'markers' as const,
				name: 'focused',
				x: [s.xs2[focusedIdx]],
				y: [s.ys2[focusedIdx]],
				marker: {
					size: 22,
					color: haloOutline,
					symbol: 'circle-open',
					line: { width: 3, color: haloOutline },
					opacity: 1
				},
				hovertemplate:
					'<b>FOCUSED · %{customdata[0]}</b><br>%{customdata[1]}<extra></extra>',
				customdata: [[s.posters[focusedIdx], s.titles[focusedIdx]]] as unknown as number[][],
				hoverinfo: undefined,
				showlegend: false
			});
		}
		const c = themedColors(t);
		const layout = {
			margin: { l: 0, r: 0, t: 0, b: 0 },
			showlegend: false,
			hovermode: 'closest',
			dragmode: isMobile ? 'pan' : 'lasso',
			paper_bgcolor: c.paper,
			plot_bgcolor: c.plot,
			font: { color: c.font },
			xaxis: { visible: false, scaleanchor: 'y' },
			yaxis: { visible: false },
			// uirevision pinned constant so axis zoom + pan + selection state
			// survive react() calls (selection / theme / cell switches all
			// reach this code path).
			uirevision: 'umap-2d',
			selectionrevision: 'umap-2d-sel'
		};
		const config = {
			responsive: true,
			displaylogo: false,
			modeBarButtonsToRemove: ['autoScale2d'],
			scrollZoom: true
		};
		(api as unknown as { react: (...args: unknown[]) => Promise<unknown> })
			.react(el, traces2d, layout, config)
			.then(() => {
				if (handlers2dAttached) return;
				handlers2dAttached = true;
				const node = el as unknown as { on: (e: string, h: (e: unknown) => void) => void };
				node.on('plotly_selected', (e: unknown) => {
					const ev = e as { points?: Array<{ pointIndex: number }> } | null;
					// Plotly fires a *second* `plotly_selected` with an empty
					// `points` array immediately after its internal
					// `plotly_relayout` — that's a no-op for us, not a real
					// deselect. The real deselect comes via `plotly_deselect`
					// (double-click on empty space). So ignore empty events.
					if (!ev || !ev.points || ev.points.length === 0) return;
					// Capture the CURRENT shard via the cellShard module
					// variable so a model-switch since render uses fresh data.
					const shardNow = cellShard;
					if (!shardNow) return;
					const visibleIds: number[] = [];
					for (let i = 0; i < shardNow.rows.length; i++) {
						const row = shardNow.rows[i];
						if (row.umap_missing) continue;
						visibleIds.push(row.poster_id);
					}
					const ids: Set<number> = new Set();
					for (const p of ev.points) {
						const aid = visibleIds[p.pointIndex];
						if (aid !== undefined) ids.add(aid);
					}
					if (ids.size > 0) $lassoSelection = ids;
				});
				node.on('plotly_deselect', () => {
					$lassoSelection = null;
				});
				node.on('plotly_click', (e: unknown) => {
					const ev = e as { points?: Array<{ pointIndex: number }> } | null;
					const pt = ev?.points?.[0];
					if (!pt) return;
					const shardNow = cellShard;
					if (!shardNow) return;
					const visibleRows = shardNow.rows.filter((r) => !r.umap_missing);
					const row = visibleRows[pt.pointIndex];
					if (!row) return;
					if (isMobile) {
						const commId = row.community_id;
						const ids: Set<number> = new Set();
						for (const r of shardNow.rows) {
							if (!r.umap_missing && r.community_id === commId) ids.add(r.poster_id);
						}
						$lassoSelection = ids;
					}
					const idxInAbstracts = shardNow.rows.indexOf(row);
					const rec = records[idxInAbstracts];
					if (rec?.poster_id) $focusedAbstract = rec.poster_id;
				});
			})
			.catch((err: Error) => {
				plotlyError = err.message;
			});
	}

	// ========================================================================
	// Atlas / NeuroScape mode renderers (Stage 15).
	//
	// Two traces per pane: backdrop (cluster-coloured, low opacity for the
	// dense 461k-point case) + overlay (cluster-coloured, larger outlined
	// marker, full opacity). 2D pane uses scattergl + dragmode='lasso';
	// 3D pane uses scatter3d. Customdata = {kind, id}.
	// ========================================================================

	const ATLAS_SHAPES_2D = ['circle', 'diamond', 'square', 'triangle-up', 'cross'];
	const ATLAS_SHAPES_3D = ['circle', 'diamond', 'square', 'cross', 'x'];
	function atlasShape2D(communityId: number): string {
		const i = ((communityId % ATLAS_SHAPES_2D.length) + ATLAS_SHAPES_2D.length) % ATLAS_SHAPES_2D.length;
		return ATLAS_SHAPES_2D[i];
	}
	function atlasShape3D(communityId: number): string {
		const i = ((communityId % ATLAS_SHAPES_3D.length) + ATLAS_SHAPES_3D.length) % ATLAS_SHAPES_3D.length;
		return ATLAS_SHAPES_3D[i];
	}

	function atlasEscape(s: string): string {
		return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
	}

	function buildAtlasBackdropTrace(
		points: BackdropPoint[],
		clusters: Map<number, AtlasCluster>,
		opacity: number,
		useShapes: boolean,
		is3d: boolean,
		lassoSet: Set<number>
	) {
		const x = points.map((p) => (is3d ? p.umap_3d[0] : (p.umap_2d ?? [0, 0])[0]));
		const y = points.map((p) => (is3d ? p.umap_3d[1] : (p.umap_2d ?? [0, 0])[1]));
		// `selectedpoints` is the canonical Plotly mechanism for "these
		// indices are selected" — combined with `selected.marker` +
		// `unselected.marker` it dims the un-lassoed and pops the
		// lassoed. Only set when the lasso is active; when empty,
		// Plotly defaults to "everything at full opacity".
		const selectedIdx: number[] = [];
		if (lassoSet.size > 0) {
			for (let i = 0; i < points.length; i++) {
				if (lassoSet.has(points[i].pubmed_id)) selectedIdx.push(i);
			}
		}
		const colours = points.map((p) => clusters.get(p.cluster_id)?.colour_hex ?? '#9c9c9c');
		const hoverText = points.map(
			(p) =>
				`<b>${atlasEscape(p.title)}</b><br>${p.year} · ${atlasEscape(
					clusters.get(p.cluster_id)?.title ?? `Cluster ${p.cluster_id}`
				)}`
		);
		const customdata = points.map((p) => ({ kind: 'neuroscape', id: p.pubmed_id }));
		const symbol = useShapes ? points.map((p) => atlasShape2D(p.cluster_id)) : undefined;
		// In 2D lasso mode the unselected backdrop stays VISIBLE so
		// the cluster carpet remains readable as context for where
		// the selection sits inside the corpus. Bump from
		// `Math.max(opacity * 2, 0.10)` to `Math.max(opacity * 4,
		// 0.20)`: with the default 0.05 backdrop opacity that's
		// 0.20 unselected (was 0.10), enough that cluster colours
		// are recognisable while still leaving the selected points
		// pop visually distinct at opacity 1.0.
		const selectedConfig = selectedIdx.length
			? {
					selectedpoints: selectedIdx,
					selected: { marker: { opacity: 1 } },
					unselected: { marker: { opacity: Math.max(opacity * 4, 0.2) } }
			  }
			: {};
		if (is3d) {
			return {
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				x,
				y,
				z: points.map((p) => p.umap_3d[2]),
				name: 'NeuroScape backdrop',
				marker: {
					size: 2,
					color: colours,
					opacity,
					line: { width: 0 },
					...(useShapes ? { symbol: points.map((p) => atlasShape3D(p.cluster_id)) } : {})
				},
				hovertemplate: '%{text}<extra></extra>',
				text: hoverText,
				showlegend: false,
				customdata,
				...selectedConfig
			};
		}
		return {
			type: 'scattergl' as const,
			mode: 'markers' as const,
			x,
			y,
			name: 'NeuroScape backdrop',
			marker: { size: 3, color: colours, opacity, line: { width: 0 }, ...(symbol ? { symbol } : {}) },
			hovertemplate: '%{text}<extra></extra>',
			text: hoverText,
			showlegend: false,
			customdata,
			...selectedConfig
		};
	}

	function buildAtlasOverlayTrace(
		points: OverlayPoint[],
		clusters: Map<number, AtlasCluster>,
		visible: boolean,
		useShapes: boolean,
		is3d: boolean,
		lassoSet: Set<number>
	) {
		if (points.length === 0) return null;
		const x = points.map((p) => (is3d ? p.umap_3d[0] : (p.umap_2d ?? [0, 0])[0]));
		const y = points.map((p) => (is3d ? p.umap_3d[1] : (p.umap_2d ?? [0, 0])[1]));
		const selectedIdx: number[] = [];
		if (lassoSet.size > 0) {
			for (let i = 0; i < points.length; i++) {
				if (lassoSet.has(points[i].poster_id)) selectedIdx.push(i);
			}
		}
		// 2D overlay: unselected stays visible (0.25) so the user
		// sees where the non-lassoed OHBM overlay points are; selected
		// at full opacity pops against them.
		const selectedConfig = selectedIdx.length
			? {
					selectedpoints: selectedIdx,
					selected: { marker: { opacity: 1 } },
					unselected: { marker: { opacity: 0.25 } }
			  }
			: {};
		const colours = points.map(
			(p) => clusters.get(p.nearest_cluster_id)?.colour_hex ?? '#1f77b4'
		);
		const hoverText = points.map(
			(p) =>
				`<b>${atlasEscape(p.title)}</b><br>OHBM 2026 poster #${p.poster_id} · near ${atlasEscape(
					clusters.get(p.nearest_cluster_id)?.title ?? `Cluster ${p.nearest_cluster_id}`
				)}`
		);
		const customdata = points.map((p) => ({ kind: 'ohbm2026', id: p.poster_id }));
		if (is3d) {
			return {
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				x,
				y,
				z: points.map((p) => p.umap_3d[2]),
				name: 'OHBM 2026 overlay',
				visible,
				marker: {
					size: 3,
					color: colours,
					opacity: 1.0,
					line: { color: '#111111', width: 1.5 },
					...(useShapes ? { symbol: points.map((p) => atlasShape3D(p.nearest_cluster_id)) } : {})
				},
				hovertemplate: '%{text}<extra></extra>',
				text: hoverText,
				showlegend: false,
				customdata,
				...selectedConfig
			};
		}
		return {
			type: 'scattergl' as const,
			mode: 'markers' as const,
			x,
			y,
			name: 'OHBM 2026 overlay',
			visible,
			marker: {
				size: 5,
				color: colours,
				opacity: 1.0,
				line: { color: '#111111', width: 1.5 },
				...(useShapes ? { symbol: points.map((p) => atlasShape2D(p.nearest_cluster_id)) } : {})
			},
			hovertemplate: '%{text}<extra></extra>',
			text: hoverText,
			showlegend: false,
			customdata,
			...selectedConfig
		};
	}

	let atlas2dHandlersAttached = false;
	let atlas3dHandlersAttached = false;

	// Track the last focused (kind, id) the 2D chart zoomed to.
	// Only triggers a fresh `Plotly.relayout({ xaxis.range, yaxis.range,
	// uirevision: ... })` when the focus actually changes; subsequent
	// renders with the SAME focus don't re-zoom (which would override
	// the user's manual zoom out / pan).
	let last2dFocusKey = '';
	// Sticky uirevision for the 2D atlas chart. Only bumps when we
	// auto-snap to a focus point; otherwise reused across renders so
	// the user's manual pan/zoom survives close-detail / theme / data
	// changes.
	let last2dUirev = 'atlas-2d';

	// Zoom-aware backdrop opacity. The 2D scattergl renders the full
	// 461k-point backdrop at a low scalar opacity (~0.05) so the
	// cluster carpet shows through without saturating. As the user
	// zooms in, points-per-pixel drops and at high zoom the dots
	// become almost invisible against the page background. The
	// plotly_relayout handler below catches every axis-range change
	// and rescales `marker.opacity` on the backdrop trace (index 0
	// in renderAtlasChart2D) inversely to the visible x-range. The
	// `data2dFullSpan` cache is the corpus' full x-extent, computed
	// once when the parquet finishes loading.
	let data2dFullSpan = 0;
	// Live x-span of the 2D chart's current viewport. Updated by the
	// `plotly_relayout` handler on every pan / zoom / autorange
	// change. Used by the focus-zoom logic to decide whether to snap
	// the camera in (when the user is at default / zoomed out) or to
	// leave the existing zoom alone (when the user has already
	// manually zoomed closer than the focus-snap target).
	let current2dXSpan = 0;
	// Re-cache the full x-span whenever the backdrop dataset arrives
	// or changes (parquet load, mode swap). Cheap one-pass scan.
	$: data2dFullSpan = computeAtlasFullSpan(backdropPoints);
	function computeAtlasFullSpan(points: BackdropPoint[]): number {
		if (points.length === 0) return 0;
		let xmin = Infinity;
		let xmax = -Infinity;
		for (const p of points) {
			const x = (p.umap_2d ?? [0, 0])[0];
			if (x < xmin) xmin = x;
			if (x > xmax) xmax = x;
		}
		const span = xmax - xmin;
		return Number.isFinite(span) && span > 0 ? span : 0;
	}
	function applyAtlasZoomOpacity(
		api: PlotlyApi,
		el: HTMLDivElement,
		baseOpacity: number,
		currentSpan: number
	) {
		if (data2dFullSpan <= 0 || currentSpan <= 0) return;
		// Linear zoom factor (fullSpan / currentSpan); clamped to a
		// minimum of 1 so zooming OUT never goes below the base
		// opacity. Top opacity capped at 0.85 so the points still
		// read as a cloud, not a solid line, at extreme zoom.
		const zoomFactor = Math.max(1, data2dFullSpan / currentSpan);
		const op = Math.min(0.85, baseOpacity * zoomFactor);
		void (
			api as unknown as {
				restyle: (e: HTMLDivElement, u: Record<string, unknown[]>, idx: number[]) => Promise<unknown>;
			}
		).restyle(el, { 'marker.opacity': [op] }, [0]);
	}

	/**
	 * Per-render 2D trace-array cache. Without it, every lasso state
	 * change in `renderAtlasChart2D` rebuilds the same 461k-point
	 * arrays (x, y, colours, hoverText, customdata, optional symbol)
	 * from scratch — the lasso-cycle heap probe measured this as the
	 * residual ~300 MB / cycle growth after the 3D mirror was
	 * removed. The cache key is the (pointsRef, useShapes, theme,
	 * is3d) tuple; cluster-colour changes invalidate via the theme
	 * key (light/dark) — they shouldn't change at runtime otherwise.
	 *
	 * Plotly.react reads the array references; passing the SAME
	 * reference across renders lets it skip the internal data-buffer
	 * rebuild. Lasso state changes only flip `selectedpoints` +
	 * `selected/unselected.marker.opacity` — orders of magnitude
	 * less per-render allocation.
	 */
	type Atlas2dArrayCache = {
		x: number[];
		y: number[];
		colours: string[];
		hoverText: string[];
		customdata: Array<{ kind: string; id: number }>;
		symbol?: string[];
	};
	let cached2dBackdropArrays: Atlas2dArrayCache | null = null;
	let cached2dBackdropKey = '';
	let cached2dOverlayArrays: Atlas2dArrayCache | null = null;
	let cached2dOverlayKey = '';
	function atlas2dArrayKey(
		pointsLength: number,
		useShapes: boolean,
		theme: string
	): string {
		// `pointsLength` is a stand-in for "data-ref identity" — the
		// parent rebuilds the array when the parquet finishes loading
		// (one-time) or on a state-key change. If the user toggles
		// theme or useShapes we rebuild; otherwise the cache wins.
		return `${pointsLength}|${useShapes}|${theme}`;
	}
	function getAtlasBackdropArrays(
		points: BackdropPoint[],
		clusters: Map<number, AtlasCluster>,
		useShapes: boolean,
		theme: string
	): Atlas2dArrayCache {
		const key = atlas2dArrayKey(points.length, useShapes, theme);
		if (cached2dBackdropArrays && cached2dBackdropKey === key) {
			return cached2dBackdropArrays;
		}
		cached2dBackdropArrays = {
			x: points.map((p) => (p.umap_2d ?? [0, 0])[0]),
			y: points.map((p) => (p.umap_2d ?? [0, 0])[1]),
			colours: points.map((p) => clusters.get(p.cluster_id)?.colour_hex ?? '#9c9c9c'),
			hoverText: points.map(
				(p) =>
					`<b>${atlasEscape(p.title)}</b><br>${p.year} · ${atlasEscape(
						clusters.get(p.cluster_id)?.title ?? `Cluster ${p.cluster_id}`
					)}`
			),
			customdata: points.map((p) => ({ kind: 'neuroscape', id: p.pubmed_id })),
			symbol: useShapes ? points.map((p) => atlasShape2D(p.cluster_id)) : undefined
		};
		cached2dBackdropKey = key;
		return cached2dBackdropArrays;
	}
	function getAtlasOverlayArrays(
		points: OverlayPoint[],
		clusters: Map<number, AtlasCluster>,
		useShapes: boolean,
		theme: string
	): Atlas2dArrayCache {
		const key = atlas2dArrayKey(points.length, useShapes, theme);
		if (cached2dOverlayArrays && cached2dOverlayKey === key) {
			return cached2dOverlayArrays;
		}
		cached2dOverlayArrays = {
			x: points.map((p) => (p.umap_2d ?? [0, 0])[0]),
			y: points.map((p) => (p.umap_2d ?? [0, 0])[1]),
			colours: points.map(
				(p) => clusters.get(p.nearest_cluster_id)?.colour_hex ?? '#1f77b4'
			),
			hoverText: points.map(
				(p) =>
					`<b>${atlasEscape(p.title)}</b><br>OHBM 2026 poster #${p.poster_id} · near ${atlasEscape(
						clusters.get(p.nearest_cluster_id)?.title ?? `Cluster ${p.nearest_cluster_id}`
					)}`
			),
			customdata: points.map((p) => ({ kind: 'ohbm2026', id: p.poster_id })),
			symbol: useShapes
				? points.map((p) => atlasShape2D(p.nearest_cluster_id))
				: undefined
		};
		cached2dOverlayKey = key;
		return cached2dOverlayArrays;
	}

	/**
	 * Find a focused point's coordinates so the chart can render a
	 * halo trace at its position. Searches the overlay first (OHBM
	 * markers are larger + the more likely focus target on
	 * atlas-root), then the backdrop. Returns null if the id isn't
	 * in either set or the focus is unset.
	 */
	function atlasFocusCoords(
		focusKind: 'ohbm2026' | 'neuroscape' | null,
		focusId: number | null,
		backdrop: BackdropPoint[],
		overlay: OverlayPoint[],
		is3d: boolean
	): { x: number; y: number; z?: number } | null {
		if (!focusKind || focusId === null) return null;
		if (focusKind === 'ohbm2026') {
			for (const p of overlay) {
				if (p.poster_id !== focusId) continue;
				return is3d
					? { x: p.umap_3d[0], y: p.umap_3d[1], z: p.umap_3d[2] }
					: { x: (p.umap_2d ?? [0, 0])[0], y: (p.umap_2d ?? [0, 0])[1] };
			}
		} else {
			for (const p of backdrop) {
				if (p.pubmed_id !== focusId) continue;
				return is3d
					? { x: p.umap_3d[0], y: p.umap_3d[1], z: p.umap_3d[2] }
					: { x: (p.umap_2d ?? [0, 0])[0], y: (p.umap_2d ?? [0, 0])[1] };
			}
		}
		return null;
	}

	function renderAtlasChart2D(
		api: PlotlyApi | null,
		el: HTMLDivElement | null,
		backdrop: BackdropPoint[],
		overlay: OverlayPoint[],
		clusters: Map<number, AtlasCluster>,
		showOverlayTrace: boolean,
		opacity: number,
		useShapes: boolean,
		ohbmLassoSet: Set<number>,
		neuroLassoSet: Set<number>,
		focusKind: 'ohbm2026' | 'neuroscape' | null,
		focusId: number | null,
		t: 'light' | 'dark'
	) {
		if (!api || !el) return;
		const c = themedColors(t);

		// Pull the 461k-point arrays from the cache instead of
		// rebuilding them every lasso adjustment. Cache invalidates on
		// data-ref / shapes / theme change; lasso changes don't touch
		// it. The `selectedpoints` + selected/unselected opacity
		// configs are still computed fresh per render — they're tiny
		// (just an indices array up to lasso size).
		const bdr = getAtlasBackdropArrays(backdrop, clusters, useShapes, t);
		const ovr = getAtlasOverlayArrays(overlay, clusters, useShapes, t);

		const backdropSelectedIdx: number[] = [];
		if (neuroLassoSet.size > 0) {
			for (let i = 0; i < backdrop.length; i++) {
				if (neuroLassoSet.has(backdrop[i].pubmed_id)) backdropSelectedIdx.push(i);
			}
		}
		const backdropSelectedConfig = backdropSelectedIdx.length
			? {
					selectedpoints: backdropSelectedIdx,
					selected: { marker: { opacity: 1 } },
					unselected: { marker: { opacity: Math.max(opacity * 4, 0.2) } }
			  }
			: {};
		const backdropTrace: Record<string, unknown> = {
			type: 'scattergl' as const,
			mode: 'markers' as const,
			x: bdr.x,
			y: bdr.y,
			name: 'NeuroScape backdrop',
			marker: {
				size: 3,
				color: bdr.colours,
				opacity,
				line: { width: 0 },
				...(bdr.symbol ? { symbol: bdr.symbol } : {})
			},
			hovertemplate: '%{text}<extra></extra>',
			text: bdr.hoverText,
			showlegend: false,
			customdata: bdr.customdata,
			...backdropSelectedConfig
		};
		const traces: unknown[] = [backdropTrace];

		if (overlay.length > 0) {
			const overlaySelectedIdx: number[] = [];
			if (ohbmLassoSet.size > 0) {
				for (let i = 0; i < overlay.length; i++) {
					if (ohbmLassoSet.has(overlay[i].poster_id)) overlaySelectedIdx.push(i);
				}
			}
			const overlaySelectedConfig = overlaySelectedIdx.length
				? {
						selectedpoints: overlaySelectedIdx,
						selected: { marker: { opacity: 1 } },
						unselected: { marker: { opacity: 0.25 } }
				  }
				: {};
			traces.push({
				type: 'scattergl' as const,
				mode: 'markers' as const,
				x: ovr.x,
				y: ovr.y,
				name: 'OHBM 2026 overlay',
				visible: showOverlayTrace,
				marker: {
					size: 5,
					color: ovr.colours,
					opacity: 1.0,
					line: { color: '#111111', width: 1.5 },
					...(ovr.symbol ? { symbol: ovr.symbol } : {})
				},
				hovertemplate: '%{text}<extra></extra>',
				text: ovr.hoverText,
				showlegend: false,
				customdata: ovr.customdata,
				...overlaySelectedConfig
			});
		}
		// Focus halo — TWO concentric magenta rings at the focused
		// point's coordinates. Outer ring (size 38, low-alpha fill +
		// soft border) reads as an "aura" at zoomed-out scales where
		// the point would otherwise be a speck in the 461k-point
		// carpet; inner ring (size 22, sharp magenta stroke) gives
		// the precise anchor when the camera zooms in. Both sit ON
		// TOP of every other trace so they're the obvious visual
		// signal of "you asked to focus this dot".
		const focus2d = atlasFocusCoords(focusKind, focusId, backdrop, overlay, false);
		const focusKey2d = focus2d && focusKind && focusId !== null ? `${focusKind}:${focusId}` : '';
		if (focus2d) {
			traces.push({
				type: 'scattergl' as const,
				mode: 'markers' as const,
				x: [focus2d.x],
				y: [focus2d.y],
				name: 'focus-aura',
				marker: {
					size: 38,
					color: 'rgba(255, 0, 255, 0.18)',
					line: { color: 'rgba(255, 0, 255, 0.45)', width: 1 },
					symbol: 'circle'
				},
				hoverinfo: 'skip' as const,
				showlegend: false
			});
			traces.push({
				type: 'scattergl' as const,
				mode: 'markers' as const,
				x: [focus2d.x],
				y: [focus2d.y],
				name: 'focus',
				marker: {
					size: 22,
					color: 'rgba(0,0,0,0)',
					line: { color: '#ff00ff', width: 2.5 },
					symbol: 'circle'
				},
				hoverinfo: 'skip' as const,
				showlegend: false
			});
		}
		// Camera zoom on focus change. When the focus id changed
		// since the last render AND the user isn't already zoomed in
		// closer than the focus-snap target, snap the 2D viewport to
		// a tight window around the focused point so the visitor
		// sees it even when the rest of the corpus is dense.
		//
		// Rule: respect the user's existing zoom level. If they've
		// manually zoomed in tighter than the focus-snap target
		// (current2dXSpan < FOCUS_WINDOW_SPAN), DON'T pan/zoom — they
		// clicked a different point at high zoom and expect to stay
		// there, with just the halo moving. Only auto-snap when the
		// current view is wider than the focus target.
		const focusChanged2d = focusKey2d !== last2dFocusKey;
		const ZOOM_HALF_SPAN = 3.0; // ~6 UMAP units of window
		const FOCUS_WINDOW_SPAN = ZOOM_HALF_SPAN * 2;
		// `current2dXSpan === 0` on first render (handler hasn't
		// fired yet) → treat as default zoom = full span, so the
		// focus snap applies.
		const userWiderThanFocus =
			current2dXSpan === 0 || current2dXSpan > FOCUS_WINDOW_SPAN;
		const shouldZoomToFocus = focus2d && focusChanged2d && userWiderThanFocus;
		const xRange = shouldZoomToFocus
			? [focus2d.x - ZOOM_HALF_SPAN, focus2d.x + ZOOM_HALF_SPAN]
			: null;
		const yRange = shouldZoomToFocus
			? [focus2d.y - ZOOM_HALF_SPAN, focus2d.y + ZOOM_HALF_SPAN]
			: null;
		// uirevision is STICKY — only bumps when we actually want to
		// override the user's zoom. Otherwise we reuse the previous
		// render's uirev so Plotly preserves the user's manual
		// pan/zoom gesture across re-renders (theme change, focus
		// clear, etc.). Closing the detail panel does NOT yank the
		// user back to autorange; their exploration is preserved.
		if (shouldZoomToFocus) {
			last2dUirev = `atlas-2d-focus-${focusKey2d}`;
		}
		const uirev2d = last2dUirev;
		last2dFocusKey = focusKey2d;
		// We DON'T set `selectionrevision` — see the earlier attempt
		// that emitted `unrecognized GUI edit: selections[0].yref`
		// when Plotly tried to merge a preserved selection into a
		// shifted trace structure. Letting it default to "no
		// preservation" drops the polygon outline on re-render —
		// acceptable since lassoed points stay highlighted via
		// `selectedpoints` + the dim-unselected opacity, and the
		// "Clear selection" button is the authoritative deselect.
		const layout: Record<string, unknown> = {
			autosize: true,
			margin: { l: 0, r: 0, t: 0, b: 0 },
			hovermode: 'closest' as const,
			dragmode: 'lasso' as const,
			paper_bgcolor: c.paper,
			plot_bgcolor: c.plot,
			font: { color: c.font },
			showlegend: false,
			xaxis: xRange
				? { visible: false, scaleanchor: 'y', range: xRange, autorange: false }
				: { visible: false, scaleanchor: 'y' },
			yaxis: yRange
				? { visible: false, range: yRange, autorange: false }
				: { visible: false },
			uirevision: uirev2d
		};
		const config = {
			responsive: true,
			displaylogo: false,
			scrollZoom: true
		};
		(api as unknown as { react: (...args: unknown[]) => Promise<unknown> })
			.react(el, traces, layout, config)
			.then(() => {
				// Re-apply zoom-aware opacity after EVERY react. The
				// backdrop trace's `marker.opacity` is rebuilt to the
				// base value (e.g. 0.05) on every render, which would
				// otherwise overwrite the restyle that
				// `plotly_relayout` performs on zoom. Two cases:
				//   1. We just snapped to a new focus window
				//      (`xRange` set) — use that as the current span.
				//   2. The user was already zoomed in / out manually
				//      (`current2dXSpan > 0`) — preserve their state.
				// First render before any handler fires falls through
				// to the base opacity, which is correct for the
				// default autorange view.
				const reapplySpan = xRange
					? Math.abs(xRange[1] - xRange[0])
					: current2dXSpan > 0
						? current2dXSpan
						: 0;
				if (reapplySpan > 0) {
					applyAtlasZoomOpacity(
						api as PlotlyApi,
						el as HTMLDivElement,
						backdropOpacity,
						reapplySpan
					);
				}
				if (atlas2dHandlersAttached) return;
				atlas2dHandlersAttached = true;
				const node = el as unknown as {
					on: (e: string, h: (e: unknown) => void) => void;
				};
				node.on('plotly_click', (e: unknown) => {
					const ev = e as { points?: Array<{ customdata?: unknown }> } | null;
					const cd = ev?.points?.[0]?.customdata as
						| { kind?: string; id?: number }
						| undefined;
					if (cd && typeof cd.kind === 'string' && typeof cd.id === 'number') {
						dispatch('pointclick', {
							kind: cd.kind as 'ohbm2026' | 'neuroscape',
							id: cd.id
						});
					}
				});
				node.on('plotly_selected', (e: unknown) => {
					const ev = e as { points?: Array<{ customdata?: unknown }> } | null;
					if (!ev || !ev.points || ev.points.length === 0) return;
					const ohbm: number[] = [];
					const neuro: number[] = [];
					for (const pt of ev.points) {
						const cd = pt.customdata as { kind?: string; id?: number } | undefined;
						if (!cd || typeof cd.id !== 'number') continue;
						if (cd.kind === 'ohbm2026') ohbm.push(cd.id);
						else if (cd.kind === 'neuroscape') neuro.push(cd.id);
					}
					dispatch('lassoselect', { ohbm2026_ids: ohbm, neuroscape_ids: neuro });
				});
				node.on('plotly_deselect', () => dispatch('lassoclear'));
				// Zoom-aware backdrop opacity: every pan/zoom emits a
				// `plotly_relayout` with the new axis range. We restyle
				// the backdrop trace's `marker.opacity` so points scale
				// up as the user zooms in (and back down on zoom out).
				// Cheap — `restyle` against trace index 0 only.
				node.on('plotly_relayout', (e: unknown) => {
					const ev = e as Record<string, unknown> | null;
					if (!ev || !api) return;
					// Plotly emits either expanded keys
					// (`xaxis.range[0]` / `[1]`) or a single
					// `xaxis.range` array depending on the gesture
					// (drag-zoom vs programmatic relayout). Handle both.
					let xMin: unknown = ev['xaxis.range[0]'];
					let xMax: unknown = ev['xaxis.range[1]'];
					const arr = ev['xaxis.range'] as unknown[] | undefined;
					if (typeof xMin !== 'number' && Array.isArray(arr)) {
						xMin = arr[0];
						xMax = arr[1];
					}
					if (typeof xMin === 'number' && typeof xMax === 'number') {
						current2dXSpan = Math.abs(xMax - xMin);
						applyAtlasZoomOpacity(
							api as PlotlyApi,
							el as HTMLDivElement,
							backdropOpacity,
							current2dXSpan
						);
					} else if (ev['xaxis.autorange'] === true) {
						// User double-clicked to reset axes → autorange
						// ON → back to the base opacity (full corpus).
						current2dXSpan = data2dFullSpan;
						applyAtlasZoomOpacity(
							api as PlotlyApi,
							el as HTMLDivElement,
							backdropOpacity,
							data2dFullSpan
						);
					}
				});
			})
			.catch((err: Error) => {
				plotlyError = err.message;
			});
	}

	function renderAtlasChart3D(
		api: PlotlyApi | null,
		el: HTMLDivElement | null,
		backdrop: BackdropPoint[],
		overlay: OverlayPoint[],
		clusters: Map<number, AtlasCluster>,
		showOverlayTrace: boolean,
		opacity: number,
		useShapes: boolean,
		focusKind: 'ohbm2026' | 'neuroscape' | null,
		focusId: number | null,
		t: 'light' | 'dark'
	) {
		if (!api || !el) return;
		const c = themedColors(t);
		// Plain scatter — single backdrop trace + single overlay trace,
		// scalar opacity per trace. No lasso mirror, no dual-trace
		// selected/unselected split. Lassoing on the 2D pane does NOT
		// re-render this chart, which is the only way to keep the
		// 461k-point scatter3d stable without triggering the documented
		// plotly.js#6365 WebGL-context leak. The magenta focus halo
		// below still highlights any single-clicked point.
		const traces: unknown[] = [
			buildAtlasBackdropTrace(backdrop, clusters, opacity, useShapes, true, new Set())
		];
		const overlayTrace = buildAtlasOverlayTrace(
			overlay,
			clusters,
			showOverlayTrace,
			useShapes,
			true,
			new Set()
		);
		if (overlayTrace) traces.push(overlayTrace);
		// Focus halo — magenta-ring marker at the focused point's
		// 3D coordinates so "Show on atlas" gives an obvious visual
		// anchor (without this the visitor lands on the home with
		// only the inline detail panel as the signal).
		const focus3d = atlasFocusCoords(focusKind, focusId, backdrop, overlay, true);
		if (focus3d) {
			// Two-marker halo in 3D to match the 2D pattern. scatter3d
			// marker.size scales differently from scattergl — sizes are
			// in canvas pixels not data units — so the outer "aura"
			// here uses a larger filled translucent sphere + the inner
			// ring stays a sharp magenta stroke for the precise anchor.
			traces.push({
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				x: [focus3d.x],
				y: [focus3d.y],
				z: [focus3d.z ?? 0],
				name: 'focus-aura',
				marker: {
					size: 26,
					color: 'rgba(255,0,255,0.20)',
					line: { color: 'rgba(255,0,255,0.45)', width: 1 },
					symbol: 'circle'
				},
				hoverinfo: 'skip' as const,
				showlegend: false
			});
			traces.push({
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				x: [focus3d.x],
				y: [focus3d.y],
				z: [focus3d.z ?? 0],
				name: 'focus',
				marker: {
					size: 16,
					color: 'rgba(255,0,255,0.35)',
					line: { color: '#ff00ff', width: 5 },
					symbol: 'circle'
				},
				hoverinfo: 'skip' as const,
				showlegend: false
			});
		}
		// On lasso, we DON'T touch the 3D camera — the previous
		// attempt to zoom (explicit axis range) clipped unselected
		// context points against the scene volume edge, and the
		// follow-up attempt (camera.center in data coords) silently
		// made the camera look at empty space because Plotly's
		// `scene.camera.center` is in NORMALISED scene coords (-1..1),
		// not data coords. The opacity split (0.6 selected vs 0.15
		// unselected) is enough on its own to make the selection
		// stand out — the user can orbit manually if they want to
		// inspect it more closely.
		const axisCfg = { visible: false, showbackground: false };
		const uirev = 'atlas-3d';
		let cameraEye: { x: number; y: number; z: number } = { x: 1.6, y: 1.6, z: 0.9 };
		if (chart3dInitialized && currentEye3D) cameraEye = currentEye3D;
		const scene: Record<string, unknown> = {
			xaxis: { ...axisCfg },
			yaxis: { ...axisCfg },
			zaxis: { ...axisCfg },
			bgcolor: c.plot,
			camera: { eye: cameraEye }
		};
		const layout = {
			autosize: true,
			margin: { l: 0, r: 0, t: 0, b: 0 },
			showlegend: false,
			paper_bgcolor: c.paper,
			plot_bgcolor: c.plot,
			font: { color: c.font },
			scene,
			uirevision: uirev
		};
		const config = { responsive: true, displaylogo: false };
		(api as unknown as { react: (...args: unknown[]) => Promise<unknown> })
			.react(el, traces, layout, config)
			.then(() => {
				chart3dInitialized = true;
				if (atlas3dHandlersAttached) {
					ensureRotate();
					return;
				}
				atlas3dHandlersAttached = true;
				const node = el as unknown as {
					on: (e: string, h: (e: unknown) => void) => void;
				};
				node.on('plotly_click', (e: unknown) => {
					const ev = e as { points?: Array<{ customdata?: unknown }> } | null;
					const cd = ev?.points?.[0]?.customdata as
						| { kind?: string; id?: number }
						| undefined;
					if (cd && typeof cd.kind === 'string' && typeof cd.id === 'number') {
						dispatch('pointclick', {
							kind: cd.kind as 'ohbm2026' | 'neuroscape',
							id: cd.id
						});
					}
				});
				// Share the camera-tracking + pause-without-reset logic with
				// OHBM mode — same `currentEye3D` is updated on user orbits.
				node.on('plotly_relayout', (e: unknown) => {
					const ev = e as Record<string, unknown> | null;
					if (!ev) return;
					const flat = ev['scene.camera.eye'] as
						| { x?: number; y?: number; z?: number }
						| undefined;
					const nested = (ev['scene.camera'] as
						| { eye?: { x?: number; y?: number; z?: number } }
						| undefined)?.eye;
					const eye = flat ?? nested;
					if (
						eye &&
						typeof eye.x === 'number' &&
						typeof eye.y === 'number' &&
						typeof eye.z === 'number'
					) {
						currentEye3D = { x: eye.x, y: eye.y, z: eye.z };
					}
				});
				ensureRotate();
			})
			.catch((err: Error) => {
				plotlyError = err.message;
			});
	}

	function renderChart3D(
		api: PlotlyApi | null,
		el: HTMLDivElement | null,
		shard: CellShard | null,
		records: AbstractRecord[],
		selected: Set<number> | null,
		t: 'light' | 'dark',
		topicMap: Map<number, string>,
		focusedId: number | null
	) {
		if (!api || !el || !shard) return;
		const s = buildSeries(shard, records, selected, topicMap);
		// Locate focused abstract index in the visible arrays.
		let focusedIdx3 = -1;
		if (focusedId !== null) {
			let visIdx = 0;
			for (const row of shard.rows) {
				if (row.umap_missing) continue;
				if (row.poster_id === focusedId) {
					focusedIdx3 = visIdx;
					break;
				}
				visIdx += 1;
			}
		}
		// scatter3d only accepts a SCALAR marker.opacity; per-point arrays are
		// silently ignored. Split the data into two traces (selected +
		// unselected), each with its own scalar opacity, so the selection
		// visually dims the unselected points.
		const hasSelection = selected !== null && s.selectedIdx.length > 0;
		const selSet = hasSelection ? new Set(s.selectedIdx) : null;
		const partition = (i: number) => (!selSet || selSet.has(i) ? 'sel' : 'unsel');
		// Collect indices for each partition.
		const traces: unknown[] = [];
		const customdata = s.posters.map((p, i) => [p, s.titles[i], s.communityLabels[i]]);
		function buildTrace(name: string, indices: number[], opacity: number, showColorbar: boolean) {
			if (indices.length === 0) return null;
			return {
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				name,
				x: indices.map((i) => s.xs3[i]),
				y: indices.map((i) => s.ys3[i]),
				z: indices.map((i) => s.zs3[i]),
				marker: {
					size: 3,
					color: indices.map((i) => s.markerColors[i]),
					symbol: indices.map((i) => s.markerSymbols3D[i]),
					opacity,
					showscale: showColorbar,
					line: { width: 0 }
				},
				customdata: indices.map((i) => customdata[i]) as unknown as number[][],
				hovertemplate:
					'<b>%{customdata[0]}</b><br>%{customdata[1]}<br><i>%{customdata[2]}</i><extra></extra>',
				hoverinfo: opacity < 0.3 ? 'skip' : undefined,
				showlegend: false
			};
		}
		if (!hasSelection) {
			const all = s.xs3.map((_: number, i: number) => i);
			const t = buildTrace('all', all, 0.85, false);
			if (t) traces.push(t);
		} else {
			const selIdx: number[] = [];
			const unselIdx: number[] = [];
			for (let i = 0; i < s.xs3.length; i++) {
				if (partition(i) === 'sel') selIdx.push(i);
				else unselIdx.push(i);
			}
			// Draw unselected first so selected layer renders on top.
			const tUnsel = buildTrace('unselected', unselIdx, 0.05, false);
			if (tUnsel) traces.push(tUnsel);
			const tSel = buildTrace('selected', selIdx, 1, false);
			if (tSel) traces.push(tSel);
		}
		// Focused-abstract halo: oversized open marker drawn last (on top).
		if (focusedIdx3 >= 0) {
			traces.push({
				type: 'scatter3d' as const,
				mode: 'markers' as const,
				name: 'focused',
				x: [s.xs3[focusedIdx3]],
				y: [s.ys3[focusedIdx3]],
				z: [s.zs3[focusedIdx3]],
				marker: {
					size: 9,
					color: t === 'dark' ? '#FFFFFF' : '#000000',
					symbol: 'circle-open',
					line: { color: t === 'dark' ? '#FFFFFF' : '#000000', width: 3 }
				},
				hovertemplate:
					'<b>FOCUSED · %{customdata[0]}</b><br>%{customdata[1]}<extra></extra>',
				customdata: [[s.posters[focusedIdx3], s.titles[focusedIdx3]]] as unknown as number[][],
				showlegend: false
			});
		}
		const c = themedColors(t);
		const axisCfg = { visible: false, showbackground: false };
		// Explicitly carry the current camera forward into each react() so
		// Plotly doesn't reset to its default. (`uirevision` should do this
		// automatically per the docs, but in this bundle it doesn't.) We
		// trust `currentEye3D` (updated by the rotation step + by
		// `plotly_relayout` user interactions) over `_fullLayout`, which
		// occasionally lags the user's last gesture in this bundle.
		let cameraEye: { x: number; y: number; z: number } = { x: 1.6, y: 1.6, z: 0.9 };
		if (chart3dInitialized && currentEye3D) {
			cameraEye = currentEye3D;
		}
		const scene: Record<string, unknown> = {
			xaxis: axisCfg,
			yaxis: axisCfg,
			zaxis: axisCfg,
			bgcolor: c.plot,
			camera: { eye: cameraEye }
		};
		const layout = {
			margin: { l: 0, r: 0, t: 0, b: 0 },
			showlegend: false,
			paper_bgcolor: c.paper,
			plot_bgcolor: c.plot,
			font: { color: c.font },
			scene,
			// uirevision pinned constant so camera (rotation, zoom) survives
			// re-renders triggered by selection / theme / cell switches.
			// Per US2 acceptance scenario 2, the lasso selection is by
			// poster_id and should persist across cell switches anyway, so
			// keeping the camera too feels right.
			uirevision: 'umap-3d'
		};
		const config = {
			responsive: true,
			displaylogo: false
		};
		(api as unknown as { react: (...args: unknown[]) => Promise<unknown> })
			.react(el, traces, layout, config)
			.then(() => {
				chart3dInitialized = true;
				if (!handlers3dAttached) {
					handlers3dAttached = true;
					const node = el as unknown as { on: (e: string, h: (e: unknown) => void) => void };
					node.on('plotly_click', (e: unknown) => {
						const ev = e as {
							points?: Array<{ customdata?: [string, string, string] }>;
						} | null;
						const pt = ev?.points?.[0];
						// 3D may have 1 or 2 traces depending on selection — read
						// the poster_id straight off customdata so trace
						// partitioning doesn't affect the click target.
						const posterId = pt?.customdata?.[0];
						if (typeof posterId === 'number') $focusedAbstract = posterId;
					});
					// Capture every camera change (user orbit / zoom / pan, OR our
					// own rotation `relayout`) into `currentEye3D`. The event
					// payload arrives in two shapes depending on the cause:
					//   - mouse interaction: { 'scene.camera': { eye, center, ...} }
					//   - our relayout({ 'scene.camera.eye': ... }):
					//       { 'scene.camera.eye': { x, y, z } }
					node.on('plotly_relayout', (e: unknown) => {
						const ev = e as Record<string, unknown> | null;
						if (!ev) return;
						let eye: { x?: number; y?: number; z?: number } | undefined;
						const flat = ev['scene.camera.eye'] as { x?: number; y?: number; z?: number } | undefined;
						const nested = (ev['scene.camera'] as { eye?: { x?: number; y?: number; z?: number } } | undefined)
							?.eye;
						eye = flat ?? nested;
						if (eye && typeof eye.x === 'number' && typeof eye.y === 'number' && typeof eye.z === 'number') {
							currentEye3D = { x: eye.x, y: eye.y, z: eye.z };
						}
					});
				}
				ensureRotate();
			})
			.catch((err: Error) => {
				plotlyError = err.message;
			});
	}

	// Rotation generation counter — every `ensureRotate` bumps this
	// and captures the current value in its local `step`. When
	// stopRotate is called (or a fresh ensureRotate starts a new
	// generation), the old step's `myGen !== rotateGen` guard makes
	// it bail before scheduling its next rAF.
	//
	// Without this, a race window exists: an in-flight `step()`
	// callback (already past the early-return guard) can unconditionally
	// overwrite `rotateFrame` with its own next-frame id, EVEN AFTER
	// stopRotate cancelled the previous frame. Result: two rotation
	// loops compete, both calling plotly.relayout at 60fps, doubling
	// CPU. Symptom: navigating back to /atlas-root/ after visiting
	// /neuroscape/ leaves the previous rotation chain alive and the
	// new one piles on top.
	let rotateGen = 0;

	function ensureRotate() {
		stopRotate();
		if (!autoRotate || !plotly || !chart3dEl) return;
		// Don't spin the camera while the tab is hidden — wastes CPU
		// for no benefit, and bfcache restores can resume stale loops.
		if (typeof document !== 'undefined' && document.visibilityState === 'hidden') return;
		// Seed the orbit from `currentEye3D` (kept in sync via the
		// `plotly_relayout` listener) so pause → user zoom/orbit → unpause
		// continues from where the user left off instead of snapping back to
		// the factory default.
		let r = 2.2;
		let z = 0.9;
		if (currentEye3D) {
			const r0 = Math.hypot(currentEye3D.x, currentEye3D.y);
			if (r0 > 1e-6) {
				r = r0;
				z = currentEye3D.z;
				rotateAngle = Math.atan2(currentEye3D.y, currentEye3D.x);
			}
		}
		rotateGen += 1;
		const myGen = rotateGen;
		const step = () => {
			if (myGen !== rotateGen) return; // a newer ensureRotate / stopRotate replaced us
			if (!autoRotate || !plotly || !chart3dEl) return;
			rotateAngle += 0.004;
			const eye = {
				x: r * Math.cos(rotateAngle),
				y: r * Math.sin(rotateAngle),
				z
			};
			currentEye3D = eye;
			try {
				(plotly as unknown as { relayout: (el: HTMLDivElement, p: unknown) => Promise<unknown> }).relayout(
					chart3dEl,
					{ 'scene.camera.eye': eye }
				);
			} catch {
				/* no-op */
			}
			if (myGen !== rotateGen) return;
			rotateFrame = requestAnimationFrame(step);
		};
		rotateFrame = requestAnimationFrame(step);
	}

	function stopRotate() {
		rotateGen += 1; // invalidate any in-flight step()s
		if (rotateFrame !== null) {
			cancelAnimationFrame(rotateFrame);
			rotateFrame = null;
		}
	}

	function toggleRotate() {
		autoRotate = !autoRotate;
		if (autoRotate) ensureRotate();
		else stopRotate();
	}
</script>

<section class="umap-panel" data-testid="umap-panel" data-mode={mode}>
	<header class="umap-header">
		<div class="title-block">
			{#if mode === 'ohbm'}
				<h3>UMAP — cell <code>{cellKey}</code></h3>
				<p class="hint">
					Points are coloured + shaped by <em>cluster</em> (community detected for this
					cell, Tol-bright palette × 5 symbols, colour-vision-friendly). Lasso on 2D
					filters the result list; click any point to open its detail panel.
				</p>
			{:else}
				<h3>
					UMAP — {mode === 'atlas'
						? 'cross-conference atlas'
						: 'NeuroScape PubMed atlas'}
				</h3>
				<p class="hint">
					Points are coloured by NeuroScape cluster
					{#if useAtlasShapes}+ shaped by cluster (≤7 clusters){:else}(colour only — {atlasClusters.length}
						clusters){/if}.
					Lasso on the 2D pane filters the result list; click any point to open
					its detail panel.
				</p>
			{/if}
		</div>
		<div class="header-actions">
			{#if mode === 'ohbm' && $lassoSelection}
				<button
					type="button"
					class="clear-lasso"
					on:click={() => ($lassoSelection = null)}
					data-testid="umap-clear-lasso"
				>
					Clear selection ({$lassoSelection.size})
				</button>
			{:else if mode !== 'ohbm' && (lassoOhbmSet.size + lassoNeuroSet.size > 0)}
				<button
					type="button"
					class="clear-lasso"
					on:click={() => dispatch('lassoclear')}
					data-testid="umap-clear-lasso"
				>
					Clear selection ({lassoOhbmSet.size + lassoNeuroSet.size})
				</button>
			{/if}
		</div>
	</header>

	<div class="charts" data-testid="umap-chart-wrap">
		<figure class="chart-card">
			<figcaption>2D <span class="caption-aside">{mobile ? 'tap to filter by community' : 'lasso to filter'}</span></figcaption>
			<div bind:this={chart2dEl} class="chart" data-testid="umap-chart-2d"></div>
		</figure>
		<figure class="chart-card">
			<figcaption>
				3D
				<span class="caption-aside">
					<button
						type="button"
						on:click={toggleRotate}
						class="rotate-btn"
						aria-pressed={autoRotate}
						data-testid="umap-rotate-toggle"
					>
						{autoRotate ? '⏸ pause' : '▶ rotate'}
					</button>
				</span>
			</figcaption>
			<div bind:this={chart3dEl} class="chart chart-3d" data-testid="umap-chart-3d"></div>
		</figure>
	</div>

	{#if plotlyError || cellError}
		<p class="error">Map unavailable: {plotlyError || cellError}</p>
	{:else if !plotly || cellLoading}
		<p class="status">Loading map…</p>
	{/if}

	<!-- Back-compat testid: existing e2e looks for `umap-chart`. -->
	<div data-testid="umap-chart" hidden></div>
</section>

<style>
	.umap-panel {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		min-width: 0;
	}
	.umap-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 0.75rem;
		flex-wrap: wrap;
	}
	.title-block h3 {
		margin: 0;
		font-size: 0.95rem;
		color: var(--text);
		font-weight: 600;
	}
	.title-block code {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.85rem;
		color: var(--accent);
	}
	.hint {
		margin: 0.15rem 0 0;
		font-size: 0.78rem;
		color: var(--text-muted);
	}
	.header-actions {
		display: flex;
		gap: 0.5rem;
	}
	.clear-lasso {
		all: unset;
		cursor: pointer;
		padding: 0.3rem 0.7rem;
		border-radius: 4px;
		font-size: 0.8rem;
		background: var(--warning-bg);
		color: var(--warning-text);
		border: 1px solid var(--warning-border);
	}
	.charts {
		display: grid;
		gap: 0.75rem;
		grid-template-columns: 1fr;
	}
	@media (min-width: 880px) {
		.charts {
			grid-template-columns: 1fr 1fr;
		}
	}
	.chart-card {
		margin: 0;
		display: flex;
		flex-direction: column;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--chart-paper);
		overflow: hidden;
	}
	.chart-card figcaption {
		font-size: 0.78rem;
		color: var(--text-muted);
		padding: 0.4rem 0.6rem;
		border-bottom: 1px solid var(--border);
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
	}
	.caption-aside {
		color: var(--text-faint);
		font-size: 0.75rem;
	}
	.rotate-btn {
		all: unset;
		cursor: pointer;
		font-size: 0.75rem;
		color: var(--accent);
	}
	.rotate-btn:hover {
		text-decoration: underline;
	}
	.chart {
		width: 100%;
		max-width: 100%;
		height: clamp(220px, 50vh, 480px);
		overflow: hidden;
	}
	@media (max-height: 480px) and (orientation: landscape) {
		/* Phone-landscape: 480 px tall or less. Don't let one chart eat the
		   entire viewport — keep ~60% of it for the chart, leave room for
		   the panel header + the surrounding result list. */
		.chart {
			height: 60vh;
		}
	}
	.chart-3d {
		height: clamp(280px, 45vh, 480px);
	}
	.status,
	.error {
		margin: 0;
		font-size: 0.8rem;
		color: var(--text-muted);
		font-style: italic;
	}
	.error {
		color: var(--danger);
	}
</style>
