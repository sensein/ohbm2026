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
	function purgeCharts() {
		if (!plotly) return;
		if (chart2dEl) plotly.purge(chart2dEl);
		if (chart3dEl) plotly.purge(chart3dEl);
		handlers2dAttached = false;
		handlers3dAttached = false;
		atlas2dHandlersAttached = false;
		atlas3dHandlersAttached = false;
		chart3dInitialized = false;
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
		// bfcache restore — charts were purged in pagehide, re-render.
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
		// Atlas / neuroscape mode — different data shape, different
		// trace structure (backdrop + overlay rather than per-community).
		// The 2D pane carries the lasso interaction (scattergl has
		// native lasso + selectedpoints). The 3D pane mirrors the
		// lasso highlight via a dual-trace split (scatter3d ignores
		// selectedpoints), but has no lasso tool of its own — its
		// dragmode is the orbit default.
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
			theme
		);
		void renderAtlasChart3D(
			plotly,
			chart3dEl,
			backdropPoints,
			overlayPoints,
			clustersById,
			showOverlay,
			backdropOpacity,
			useAtlasShapes,
			lassoOhbmSet,
			lassoNeuroSet,
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
		// In 2D lasso mode the unselected backdrop stays VISIBLE but
		// dim — gives the visitor context for where the selection
		// lives within the full corpus. Pre-fix unselected was 0.02
		// (almost invisible against a dense backdrop); 0.10 keeps a
		// soft carpet showing through.
		const selectedConfig = selectedIdx.length
			? {
					selectedpoints: selectedIdx,
					selected: { marker: { opacity: 1 } },
					unselected: { marker: { opacity: Math.max(opacity * 2, 0.1) } }
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
		t: 'light' | 'dark'
	) {
		if (!api || !el) return;
		const c = themedColors(t);
		const traces: unknown[] = [
			buildAtlasBackdropTrace(backdrop, clusters, opacity, useShapes, false, neuroLassoSet)
		];
		const overlayTrace = buildAtlasOverlayTrace(
			overlay,
			clusters,
			showOverlayTrace,
			useShapes,
			false,
			ohbmLassoSet
		);
		if (overlayTrace) traces.push(overlayTrace);
		// We DON'T set `selectionrevision`. The earlier attempt to
		// pin it to a fingerprint string (e.g. lasso-size combos)
		// still emitted `unrecognized GUI edit: selections[0].yref`
		// when Plotly tried to merge its preserved internal
		// `selections` polygon into a chart whose trace structure had
		// shifted (the dual-trace lasso split). Letting Plotly default
		// to "no preservation" drops the polygon outline on re-render
		// — acceptable since the lassoed points are still highlighted
		// via `selectedpoints` + the dim-unselected opacity, and the
		// "Clear selection" button in the panel header is the
		// authoritative deselect.
		const layout = {
			autosize: true,
			margin: { l: 0, r: 0, t: 0, b: 0 },
			hovermode: 'closest' as const,
			dragmode: 'lasso' as const,
			paper_bgcolor: c.paper,
			plot_bgcolor: c.plot,
			font: { color: c.font },
			showlegend: false,
			xaxis: { visible: false, scaleanchor: 'y' },
			yaxis: { visible: false },
			uirevision: 'atlas-2d'
		};
		const config = {
			responsive: true,
			displaylogo: false,
			scrollZoom: true
		};
		(api as unknown as { react: (...args: unknown[]) => Promise<unknown> })
			.react(el, traces, layout, config)
			.then(() => {
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
		ohbmLassoSet: Set<number>,
		neuroLassoSet: Set<number>,
		t: 'light' | 'dark'
	) {
		if (!api || !el) return;
		const c = themedColors(t);
		// scatter3d ignores `selectedpoints` + selected/unselected
		// marker styles (unlike scattergl). To get dim-unselected +
		// pop-selected in 3D, we SPLIT each source into two traces
		// with different scalar opacities — Plotly merges them on
		// render. Unselected stays VISIBLE (slightly higher than
		// the default backdrop opacity so the context shows through
		// even with the new selection bbox zoom) and selected pops
		// at medium opacity — NOT fully opaque, which was previously
		// too contrastive against the empty zoomed scene.
		//
		// The 3D pane has NO lasso interaction of its own (scatter3d
		// doesn't support lasso; dragmode stays at the orbit default).
		// It just reflects the lasso state set by the 2D pane.
		const lassoActive = ohbmLassoSet.size + neuroLassoSet.size > 0;
		const traces: unknown[] = [];
		if (lassoActive) {
			const bdrSel: BackdropPoint[] = [];
			const bdrUnsel: BackdropPoint[] = [];
			for (const p of backdrop) {
				(neuroLassoSet.has(p.pubmed_id) ? bdrSel : bdrUnsel).push(p);
			}
			// Backdrop unselected: bump to ~3× the default 0.05 (so 0.15)
			// so the surrounding cluster carpet remains a faint context
			// glow during zoom-to-bbox. Backdrop selected: 0.6 — a clear
			// pop above the carpet, not the previous 0.9 retina-blast.
			traces.push(
				buildAtlasBackdropTrace(bdrUnsel, clusters, Math.max(opacity * 3, 0.15), useShapes, true, new Set())
			);
			traces.push(
				buildAtlasBackdropTrace(bdrSel, clusters, 0.6, useShapes, true, new Set())
			);
			if (showOverlayTrace) {
				const ovrSel: OverlayPoint[] = [];
				const ovrUnsel: OverlayPoint[] = [];
				for (const p of overlay) {
					(ohbmLassoSet.has(p.poster_id) ? ovrSel : ovrUnsel).push(p);
				}
				// Overlay unselected: outlined OHBM markers stay at 0.35
				// (dim but still readable above the backdrop). Selected:
				// 1.0 (full opacity — the OHBM overlay is the main focus
				// when it's been lassoed).
				const ovrUnselTrace = buildAtlasOverlayTrace(
					ovrUnsel,
					clusters,
					true,
					useShapes,
					true,
					new Set()
				);
				if (ovrUnselTrace) {
					(ovrUnselTrace as { marker: { opacity: number } }).marker.opacity = 0.35;
					traces.push(ovrUnselTrace);
				}
				const ovrSelTrace = buildAtlasOverlayTrace(
					ovrSel,
					clusters,
					true,
					useShapes,
					true,
					new Set()
				);
				if (ovrSelTrace) traces.push(ovrSelTrace);
			}
		} else {
			traces.push(
				buildAtlasBackdropTrace(backdrop, clusters, opacity, useShapes, true, new Set())
			);
			const overlayTrace = buildAtlasOverlayTrace(
				overlay,
				clusters,
				showOverlayTrace,
				useShapes,
				true,
				new Set()
			);
			if (overlayTrace) traces.push(overlayTrace);
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
