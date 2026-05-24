<!--
  Stage 15 (spec 015-neuroscape-context, FR-010 + FR-011 + T045):
  the bare-root cross-conference atlas scatter.

  Renders two plotly scatter3d traces from atlas.parquet:

    1. NeuroScape backdrop  — cluster-coloured, small, dim, dense.
    2. OHBM 2026 overlay    — outlined, larger, distinct foreground.

  The atlas-overlay binary toggle controls trace #2's visibility;
  the backdrop density slider controls trace #1's per-point alpha.

  Click / lasso interactions are stubbed for now — T046 lands the
  DetailPanel branch and T047 the grouped lasso result list.

  Reuses the existing plotly.js-gl3d-dist-min import that
  UmapPanel.svelte already pulls in; no new browser dependency.
  Distinct file from UmapPanel.svelte so the OHBM-2026 build
  (which doesn't import this component) is byte-identical (FR-022).
-->
<script lang="ts">
	import { onDestroy, onMount } from 'svelte';

	type PlotlyApi = typeof import('plotly.js-gl3d-dist-min');

	// Local prop types — kept private to this component. The parent
	// (+page.svelte) declares its own type aliases of the same shape.
	type BackdropPoint = {
		pubmed_id: number;
		cluster_id: number;
		umap_3d: [number, number, number];
		title: string;
		year: number;
	};
	type OverlayPoint = {
		submission_id: number;
		poster_id: number;
		umap_3d: [number, number, number];
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

	/** Bound to the atlasOverlay store by the parent. */
	export let showOverlay: boolean = true;

	/** 0.05–1.0, bound to BackdropDensitySlider's value by the parent. */
	export let backdropOpacity: number = 0.25;

	let plotEl: HTMLDivElement | null = null;
	let plotly: PlotlyApi | null = null;
	let plotError: string | null = null;
	let plotInitialized = false;

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

	function backdropTrace() {
		const x = backdropPoints.map((p) => p.umap_3d[0]);
		const y = backdropPoints.map((p) => p.umap_3d[1]);
		const z = backdropPoints.map((p) => p.umap_3d[2]);
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
		const x = overlayPoints.map((p) => p.umap_3d[0]);
		const y = overlayPoints.map((p) => p.umap_3d[1]);
		const z = overlayPoints.map((p) => p.umap_3d[2]);
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

	const layout = {
		autosize: true,
		margin: { l: 0, r: 0, t: 0, b: 0 },
		hovermode: 'closest' as const,
		scene: {
			xaxis: { visible: false, showspikes: false },
			yaxis: { visible: false, showspikes: false },
			zaxis: { visible: false, showspikes: false },
			bgcolor: 'rgba(0,0,0,0)'
		},
		paper_bgcolor: 'rgba(0,0,0,0)',
		showlegend: false
	};

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

	async function renderPlot() {
		if (!plotEl || !plotly) return;
		const data = [backdropTrace(), overlayTrace()];
		if (!plotInitialized) {
			await plotly.newPlot(plotEl, data, layout, plotConfig);
			plotInitialized = true;
		} else {
			await plotly.react(plotEl, data, layout, plotConfig);
		}
	}

	onMount(async () => {
		await ensurePlotly();
		await renderPlot();
	});

	onDestroy(() => {
		if (plotly && plotEl) plotly.purge(plotEl);
	});

	// Re-render whenever inputs change.
	$: if (plotly && plotEl && (backdropPoints || overlayPoints || clusters)) {
		void renderPlot();
	}
	$: if (plotly && plotEl) {
		// showOverlay + backdropOpacity changes trigger a re-render
		// via the reactive `backdropTrace()` / `overlayTrace()` calls
		// above; we re-invoke renderPlot here so Plotly's React-style
		// update path runs.
		void renderPlot();
		void showOverlay;
		void backdropOpacity;
	}
</script>

<div class="atlas-umap-panel" data-testid="atlas-umap-panel">
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
		<div class="counts" data-testid="atlas-umap-counts" aria-live="polite">
			<span>{backdropPoints.length.toLocaleString()} backdrop pts</span>
			{#if showOverlay}
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
		color: var(--color-text-muted, #666);
		background: var(--color-surface, rgba(255, 255, 255, 0.75));
		padding: 0.15rem 0.5rem;
		border-radius: 4px;
		font-variant-numeric: tabular-nums;
		pointer-events: none;
	}

	.error-banner {
		padding: 1rem;
		border: 1px solid var(--color-error, #c00);
		border-radius: 4px;
		background: var(--color-error-bg, rgba(192, 0, 0, 0.08));
		color: var(--color-error, #c00);
	}
</style>
