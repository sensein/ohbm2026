<!--
  Stage 15 (spec 015-neuroscape-context, FR-010 + FR-011 + FR-012 + T045 + T056):
  the bare-root cross-conference atlas scatter — and the same panel
  is reused on the /neuroscape/ subsite home (overlayPoints empty).

  Renders two traces:
    1. NeuroScape backdrop  — cluster-coloured, small, dim, dense.
    2. OHBM 2026 overlay    — outlined, larger, distinct foreground
                              (omitted when overlayPoints is empty).

  Props:
    - backdropPoints / overlayPoints / clusters: per-row data.
    - showOverlay: visibility of trace 2 (atlas-overlay toggle).
    - backdropOpacity: per-point alpha on trace 1 (density slider).
    - dimensionality: '3d' (default; scatter3d trace) or '2d' (scattergl).

  Performance: opacity + visibility changes are dispatched via
  `Plotly.restyle` so a slider drag doesn't trigger a full
  recompute of the 461K-point scatter. Only data-shape changes
  (point list / cluster table / dimensionality) call `Plotly.react`.
-->
<script lang="ts">
	import { createEventDispatcher, onDestroy, onMount } from 'svelte';

	const dispatch = createEventDispatcher<{
		pointclick: { kind: 'ohbm2026' | 'neuroscape'; id: number };
		lassoselect: { ohbm2026_ids: number[]; neuroscape_ids: number[] };
		lassoclear: void;
	}>();

	type PlotlyApi = typeof import('plotly.js-gl3d-dist-min');

	type BackdropPoint = {
		pubmed_id: number;
		cluster_id: number;
		umap_3d: [number, number, number];
		umap_2d?: [number, number];
		title: string;
		year: number;
	};
	type OverlayPoint = {
		submission_id: number;
		poster_id: number;
		umap_3d: [number, number, number];
		umap_2d?: [number, number];
		title: string;
		nearest_cluster_id: number;
	};
	type ClusterRow = {
		cluster_id: number;
		title: string;
		colour_hex: string;
		palette_tier: 'primary' | 'secondary';
	};

	export let backdropPoints: BackdropPoint[] = [];
	export let overlayPoints: OverlayPoint[] = [];
	export let clusters: ClusterRow[] = [];
	export let showOverlay: boolean = true;
	export let backdropOpacity: number = 0.25;
	export let dimensionality: '2d' | '3d' = '3d';

	let plotEl: HTMLDivElement | null = null;
	let plotly: PlotlyApi | null = null;
	let plotError: string | null = null;
	let plotInitialized = false;
	let plotInitializedFor: '2d' | '3d' | null = null;

	// Auto-rotate state (3D only). The frame loop walks the camera
	// around the scene's vertical axis at ~0.3°/frame (~36 s for a
	// full revolution at 60 fps). Manual user drag pauses rotation
	// via the `plotly_relayout` event so the visitor isn't fighting
	// the auto-rotation when they grab the scene.
	let autoRotate = true;
	let rotateFrame: number | null = null;
	let rotateAngle = 0;
	let relayoutHandlerAttached = false;

	$: clusterColour = (() => {
		const map = new Map<number, string>();
		for (const c of clusters) map.set(c.cluster_id, c.colour_hex);
		return map;
	})();

	$: clusterTitle = (() => {
		const map = new Map<number, string>();
		for (const c of clusters) map.set(c.cluster_id, c.title);
		return map;
	})();

	// Both 2D and 3D use scatter3d so the bundle stays on
	// plotly.js-gl3d-dist-min (which has scatter3d but NOT scattergl
	// — switching modes inside that bundle is the difference between
	// a 461K-point flat scatter3d (z=0, top-down camera) vs the
	// rotatable 3D scatter. Using scattergl would require swapping
	// to plotly.js-dist-min, +1.7 MB to the bundle. The 2D mode reads
	// its own UMAP fit from `umap_2d` so geometry isn't a projection
	// of the 3D one.
	function backdropTrace() {
		const is3d = dimensionality === '3d';
		const x = backdropPoints.map((p) =>
			is3d ? p.umap_3d[0] : (p.umap_2d ?? [0, 0])[0]
		);
		const y = backdropPoints.map((p) =>
			is3d ? p.umap_3d[1] : (p.umap_2d ?? [0, 0])[1]
		);
		const z = is3d
			? backdropPoints.map((p) => p.umap_3d[2])
			: backdropPoints.map(() => 0);
		const colours = backdropPoints.map(
			(p) => clusterColour.get(p.cluster_id) ?? '#9c9c9c'
		);
		const hoverText = backdropPoints.map(
			(p) =>
				`<b>${escape(p.title)}</b><br>${p.year} · ${escape(
					clusterTitle.get(p.cluster_id) ?? `Cluster ${p.cluster_id}`
				)}`
		);
		return {
			type: 'scatter3d' as const,
			mode: 'markers' as const,
			x,
			y,
			z,
			name: 'NeuroScape backdrop',
			marker: {
				size: 2,
				color: colours,
				opacity: backdropOpacity,
				line: { width: 0 }
			},
			hovertemplate: '%{text}<extra></extra>',
			text: hoverText,
			showlegend: false,
			customdata: backdropPoints.map((p) => ({
				kind: 'neuroscape',
				id: p.pubmed_id
			}))
		};
	}

	function overlayTrace() {
		const is3d = dimensionality === '3d';
		const x = overlayPoints.map((p) =>
			is3d ? p.umap_3d[0] : (p.umap_2d ?? [0, 0])[0]
		);
		const y = overlayPoints.map((p) =>
			is3d ? p.umap_3d[1] : (p.umap_2d ?? [0, 0])[1]
		);
		const z = is3d
			? overlayPoints.map((p) => p.umap_3d[2])
			: overlayPoints.map(() => 0);
		const colours = overlayPoints.map(
			(p) => clusterColour.get(p.nearest_cluster_id) ?? '#1f77b4'
		);
		const hoverText = overlayPoints.map(
			(p) =>
				`<b>${escape(p.title)}</b><br>OHBM 2026 poster #${p.poster_id} · near ${escape(
					clusterTitle.get(p.nearest_cluster_id) ?? `Cluster ${p.nearest_cluster_id}`
				)}`
		);
		return {
			type: 'scatter3d' as const,
			mode: 'markers' as const,
			x,
			y,
			z,
			name: 'OHBM 2026 overlay',
			visible: showOverlay,
			marker: {
				size: 5,
				color: colours,
				opacity: 1.0,
				line: { color: '#111111', width: 1.5 }
			},
			hovertemplate: '%{text}<extra></extra>',
			text: hoverText,
			showlegend: false,
			customdata: overlayPoints.map((p) => ({
				kind: 'ohbm2026',
				id: p.poster_id
			}))
		};
	}

	function escape(s: string): string {
		return s
			.replace(/&/g, '&amp;')
			.replace(/</g, '&lt;')
			.replace(/>/g, '&gt;');
	}

	function layoutFor(d: '2d' | '3d') {
		const baseLayout = {
			autosize: true,
			margin: { l: 0, r: 0, t: 0, b: 0 },
			hovermode: 'closest' as const,
			paper_bgcolor: 'rgba(0,0,0,0)',
			showlegend: false
		};
		if (d === '3d') {
			return {
				...baseLayout,
				scene: {
					xaxis: { visible: false, showspikes: false },
					yaxis: { visible: false, showspikes: false },
					zaxis: { visible: false, showspikes: false },
					bgcolor: 'rgba(0,0,0,0)',
					dragmode: 'turntable' as const
				}
			};
		}
		// 2D mode: still scatter3d, but with z=0 + top-down camera +
		// pan-only drag + flat aspect ratio so the scene presents as a
		// flat plot.
		return {
			...baseLayout,
			scene: {
				xaxis: { visible: false, showspikes: false },
				yaxis: { visible: false, showspikes: false },
				zaxis: {
					visible: false,
					showspikes: false,
					range: [-0.5, 0.5]
				},
				bgcolor: 'rgba(0,0,0,0)',
				camera: {
					eye: { x: 0, y: 0, z: 2.0 },
					up: { x: 0, y: 1, z: 0 },
					center: { x: 0, y: 0, z: 0 }
				},
				dragmode: 'pan' as const,
				aspectmode: 'manual' as const,
				aspectratio: { x: 1, y: 1, z: 0.001 }
			}
		};
	}

	const plotConfig = {
		responsive: true,
		displaylogo: false,
		modeBarButtonsToRemove: ['toImage', 'sendDataToCloud'] as string[],
		displayModeBar: false
	};

	async function ensurePlotly() {
		if (plotly || plotError) return;
		try {
			plotly = (await import('plotly.js-gl3d-dist-min')).default as PlotlyApi;
		} catch (err) {
			plotError = `failed to load plotly: ${(err as Error)?.message ?? String(err)}`;
		}
	}

	async function renderPlotFull() {
		if (!plotEl || !plotly) return;
		const data = [backdropTrace()];
		if (overlayPoints.length > 0) data.push(overlayTrace());
		const layout = layoutFor(dimensionality);
		const needsFullInit = !plotInitialized || plotInitializedFor !== dimensionality;
		if (needsFullInit) {
			// Switching dimensionality re-initialises (scatter3d ↔
			// scattergl is a trace-type change). Calling newPlot makes
			// the intent explicit + clears any prior scene state.
			await plotly.newPlot(plotEl, data, layout, plotConfig);
			plotInitialized = true;
			plotInitializedFor = dimensionality;
		} else {
			await plotly.react(plotEl, data, layout, plotConfig);
		}
	}

	async function restyleOpacityOnly() {
		if (!plotEl || !plotly || !plotInitialized) return;
		try {
			await plotly.restyle(plotEl, { 'marker.opacity': backdropOpacity }, [0]);
		} catch {
			await renderPlotFull();
		}
	}

	async function restyleOverlayVisibility() {
		if (!plotEl || !plotly || !plotInitialized) return;
		if (overlayPoints.length === 0) return;
		try {
			await plotly.restyle(plotEl, { visible: showOverlay }, [1]);
		} catch {
			await renderPlotFull();
		}
	}

	// ----- Auto-rotate ------------------------------------------------------

	let lastRotateTickTs = 0;

	function startRotate() {
		if (rotateFrame !== null) return;
		const tick = () => {
			if (!autoRotate || dimensionality !== '3d' || !plotEl || !plotly) {
				rotateFrame = null;
				return;
			}
			rotateAngle += 0.005; // radians per frame
			const r = 1.8;
			const x = r * Math.cos(rotateAngle);
			const y = r * Math.sin(rotateAngle);
			lastRotateTickTs = performance.now();
			void plotly.relayout(plotEl, {
				'scene.camera.eye': { x, y, z: 0.6 }
			});
			rotateFrame = requestAnimationFrame(tick);
		};
		rotateFrame = requestAnimationFrame(tick);
	}

	function stopRotate() {
		if (rotateFrame !== null) {
			cancelAnimationFrame(rotateFrame);
			rotateFrame = null;
		}
	}

	function toggleRotate() {
		autoRotate = !autoRotate;
		if (autoRotate && dimensionality === '3d') startRotate();
		else stopRotate();
	}

	function attachRelayoutHandler() {
		if (relayoutHandlerAttached || !plotEl || !plotly) return;
		// Plotly emits `plotly_relayout` for any camera move including
		// user drags. Distinguish our own auto-rotate emissions (which
		// happen every ~16ms) from a user drag by timing: any relayout
		// that arrives MORE than 100 ms after our last tick must be a
		// user-driven move — pause auto-rotate so the visitor can
		// inspect the scene without fighting us.
		const el = plotEl as unknown as {
			on: (e: string, cb: (data: unknown) => void) => void;
		};
		el.on('plotly_relayout', () => {
			if (!autoRotate) return;
			const gap = performance.now() - lastRotateTickTs;
			if (gap > 100) {
				autoRotate = false;
				stopRotate();
			}
		});
		// T046 — point click dispatches a `pointclick` event with the
		// point's customdata ({kind, id}). The parent (`+page.svelte`
		// atlas-root branch) opens the AtlasRootDetailPanel using this.
		el.on('plotly_click', (raw: unknown) => {
			const data = raw as { points?: Array<{ customdata?: unknown }> };
			const first = data.points?.[0];
			const cd = first?.customdata as { kind?: string; id?: number } | undefined;
			if (cd && typeof cd.kind === 'string' && typeof cd.id === 'number') {
				dispatch('pointclick', { kind: cd.kind as 'ohbm2026' | 'neuroscape', id: cd.id });
			}
		});
		// T047 — lasso/box selection dispatches a `lassoselect` event
		// with all selected customdatas grouped by kind so the parent
		// can show the two-section grouped result list.
		el.on('plotly_selected', (raw: unknown) => {
			const data = raw as { points?: Array<{ customdata?: unknown }> };
			const ohbm: number[] = [];
			const neuro: number[] = [];
			for (const pt of data.points ?? []) {
				const cd = pt.customdata as { kind?: string; id?: number } | undefined;
				if (!cd || typeof cd.id !== 'number') continue;
				if (cd.kind === 'ohbm2026') ohbm.push(cd.id);
				else if (cd.kind === 'neuroscape') neuro.push(cd.id);
			}
			dispatch('lassoselect', { ohbm2026_ids: ohbm, neuroscape_ids: neuro });
		});
		// Clicking on empty plot space deselects; dispatch a clear
		// event so the parent can collapse any lasso result list.
		el.on('plotly_deselect', () => {
			dispatch('lassoclear');
		});
		relayoutHandlerAttached = true;
	}

	onMount(async () => {
		await ensurePlotly();
		await renderPlotFull();
		attachRelayoutHandler();
		if (autoRotate && dimensionality === '3d') startRotate();
	});

	onDestroy(() => {
		stopRotate();
		if (plotly && plotEl) plotly.purge(plotEl);
	});

	// Reactive split: data + dimensionality changes do a full
	// react/newPlot pass; opacity + visibility changes go through the
	// cheap restyle path so a slider drag is fluid.
	$: if (plotly && plotEl && backdropPoints.length >= 0) {
		// Touch every data dep so Svelte tracks them.
		void backdropPoints;
		void overlayPoints;
		void clusters;
		void dimensionality;
		void renderPlotFull();
	}
	// Switching to 2D stops the rotation; switching back to 3D resumes
	// it iff autoRotate is true.
	$: if (dimensionality === '2d') {
		stopRotate();
	} else if (dimensionality === '3d' && autoRotate && plotInitialized) {
		startRotate();
	}
	$: if (plotly && plotEl) {
		void backdropOpacity;
		void restyleOpacityOnly();
	}
	$: if (plotly && plotEl) {
		void showOverlay;
		void restyleOverlayVisibility();
	}
</script>

<div
	class="atlas-umap-panel"
	data-testid="atlas-umap-panel"
	data-dimensionality={dimensionality}
>
	{#if plotError}
		<div class="error-banner" role="alert" data-testid="atlas-umap-error">
			{plotError}
		</div>
	{:else}
		<div
			class="plot-host"
			bind:this={plotEl}
			data-testid="atlas-umap-plot"
		></div>
		{#if dimensionality === '3d'}
			<button
				type="button"
				class="rotate-toggle"
				on:click={toggleRotate}
				aria-label={autoRotate ? 'Pause rotation' : 'Resume rotation'}
				title={autoRotate ? 'Pause rotation' : 'Resume rotation'}
				data-testid="rotate-toggle"
				data-state={autoRotate ? 'rotating' : 'paused'}
			>
				{autoRotate ? '⏸︎ Pause' : '▶ Rotate'}
			</button>
		{/if}
		<div class="counts" data-testid="atlas-umap-counts" aria-live="polite">
			<span>{backdropPoints.length.toLocaleString()} backdrop pts</span>
			{#if showOverlay && overlayPoints.length > 0}
				<span>·</span>
				<span>{overlayPoints.length.toLocaleString()} OHBM 2026 pts</span>
			{/if}
		</div>
	{/if}
</div>

<style>
	.atlas-umap-panel {
		flex: 1;
		display: flex;
		flex-direction: column;
		min-height: 0;
		position: relative;
	}

	.plot-host {
		flex: 1;
		min-height: 50vh;
	}

	.counts {
		position: absolute;
		bottom: 0.5rem;
		right: 0.75rem;
		display: flex;
		gap: 0.4rem;
		font-size: 0.85rem;
		color: var(--text-muted);
		background: var(--bg-elevated);
		padding: 0.15rem 0.5rem;
		border-radius: 4px;
		font-variant-numeric: tabular-nums;
		pointer-events: none;
	}

	.rotate-toggle {
		position: absolute;
		top: 0.5rem;
		right: 0.75rem;
		font-size: 0.85rem;
		color: var(--text-muted);
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		padding: 0.2rem 0.6rem;
		border-radius: 4px;
		cursor: pointer;
	}
	.rotate-toggle:hover {
		background: var(--bg-subtle);
	}
	.rotate-toggle[data-state='rotating'] {
		color: var(--accent);
	}

	.error-banner {
		padding: 1rem;
		border: 1px solid var(--danger);
		border-radius: 4px;
		background: var(--bg-subtle);
		color: var(--danger);
	}
</style>
