<script lang="ts">
	import { onMount, onDestroy } from 'svelte';
	import { selectedCell, lassoSelection, focusedAbstract } from '$lib/stores/selection';
	import { effectiveTheme } from '$lib/stores/theme';
	import { loadCell, loadTopics, type CellShard, type TopicShard } from '$lib/shards';
	import type { AbstractRecord } from '$lib/shards';

	export let abstracts: AbstractRecord[] = [];
	/**
	 * Set of abstract_ids the rest of the app considers "currently selected"
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

	type PlotlyApi = typeof import('plotly.js-gl3d-dist-min');

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

	$: cellKey = `${$selectedCell.model}_${$selectedCell.input}`;

	function onResize() {
		viewportWidth = window.innerWidth;
		mobile = viewportWidth < mobileBreakpoint;
		if (plotly) {
			if (chart2dEl) plotly.Plots.resize(chart2dEl);
			if (chart3dEl) plotly.Plots.resize(chart3dEl);
		}
	}

	onMount(async () => {
		window.addEventListener('resize', onResize);
		await ensurePlotly();
	});

	onDestroy(() => {
		if (typeof window !== 'undefined') {
			window.removeEventListener('resize', onResize);
		}
		stopRotate();
		if (plotly) {
			if (chart2dEl) plotly.purge(chart2dEl);
			if (chart3dEl) plotly.purge(chart3dEl);
		}
	});

	async function ensurePlotly() {
		if (plotly || plotlyLoading) return;
		plotlyLoading = true;
		try {
			plotly = (await import('plotly.js-gl3d-dist-min')).default as PlotlyApi;
		} catch (err) {
			plotlyError = (err as Error).message;
		} finally {
			plotlyLoading = false;
		}
	}

	$: void (async () => {
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
	$: void renderChart2D(plotly, chart2dEl, cellShard, abstracts, selection, mobile, theme, topicByCluster);
	$: void renderChart3D(plotly, chart3dEl, cellShard, abstracts, selection, theme, topicByCluster);

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
		const posters: string[] = [];
		const titles: string[] = [];
		const communityLabels: string[] = [];
		const colors: number[] = [];
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
			colors.push(row.community_id);
			idx2dByAbstract.set(row.abstract_id, xs2.length - 1);
			if (selected !== null && selected.has(row.abstract_id)) selectedIdx.push(xs2.length - 1);
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
			colors,
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
		topicMap: Map<number, string>
	) {
		if (!api || !el || !shard) return;
		const s = buildSeries(shard, records, selected, topicMap);
		const t1 = {
			type: 'scatter' as const,
			mode: 'markers' as const,
			x: s.xs2,
			y: s.ys2,
			marker: {
				size: 6,
				color: s.colors,
				colorscale: 'Viridis',
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
			.react(el, [t1], layout, config)
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
						visibleIds.push(row.abstract_id);
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
							if (!r.umap_missing && r.community_id === commId) ids.add(r.abstract_id);
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

	function renderChart3D(
		api: PlotlyApi | null,
		el: HTMLDivElement | null,
		shard: CellShard | null,
		records: AbstractRecord[],
		selected: Set<number> | null,
		t: 'light' | 'dark',
		topicMap: Map<number, string>
	) {
		if (!api || !el || !shard) return;
		const s = buildSeries(shard, records, selected, topicMap);
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
		// Find the global color range so both traces share the same scale.
		const cmin = Math.min(...s.colors);
		const cmax = Math.max(...s.colors);
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
					color: indices.map((i) => s.colors[i]),
					colorscale: 'Viridis',
					cmin,
					cmax,
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
		const c = themedColors(t);
		const axisCfg = { visible: false, showbackground: false };
		// Explicitly carry the current camera forward into each react() so
		// Plotly doesn't reset to its default. (`uirevision` should do this
		// automatically per the docs, but in this bundle it doesn't.) The
		// rotation animation uses `relayout` to update camera between
		// react() calls; we read whatever camera is current and pass it back.
		let cameraEye: { x: number; y: number; z: number } = { x: 1.6, y: 1.6, z: 0.9 };
		if (chart3dInitialized) {
			const flLayout = (el as unknown as { _fullLayout?: { scene?: { camera?: { eye?: { x: number; y: number; z: number } } } } })
				._fullLayout;
			const eye = flLayout?.scene?.camera?.eye;
			if (eye && typeof eye.x === 'number') {
				cameraEye = { x: eye.x, y: eye.y, z: eye.z };
			}
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
			// abstract_id and should persist across cell switches anyway, so
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
						if (posterId) $focusedAbstract = posterId;
					});
				}
				ensureRotate();
			})
			.catch((err: Error) => {
				plotlyError = err.message;
			});
	}

	function ensureRotate() {
		stopRotate();
		if (!autoRotate || !plotly || !chart3dEl) return;
		// Seed the orbit from the user's CURRENT camera so that pausing,
		// zooming/orbiting, then unpausing continues from where they left off
		// instead of snapping back to the hard-coded default (r=2.2, z=0.9).
		let r = 2.2;
		let z = 0.9;
		const flLayout = (
			chart3dEl as unknown as {
				_fullLayout?: { scene?: { camera?: { eye?: { x: number; y: number; z: number } } } };
			}
		)._fullLayout;
		const eye0 = flLayout?.scene?.camera?.eye;
		if (eye0 && typeof eye0.x === 'number') {
			const r0 = Math.hypot(eye0.x, eye0.y);
			if (r0 > 1e-6) {
				r = r0;
				z = eye0.z;
				rotateAngle = Math.atan2(eye0.y, eye0.x);
			}
		}
		const step = () => {
			if (!autoRotate || !plotly || !chart3dEl) return;
			rotateAngle += 0.004;
			const eye = {
				x: r * Math.cos(rotateAngle),
				y: r * Math.sin(rotateAngle),
				z
			};
			try {
				(plotly as unknown as { relayout: (el: HTMLDivElement, p: unknown) => Promise<unknown> }).relayout(
					chart3dEl,
					{ 'scene.camera.eye': eye }
				);
			} catch {
				/* no-op */
			}
			rotateFrame = requestAnimationFrame(step);
		};
		rotateFrame = requestAnimationFrame(step);
	}

	function stopRotate() {
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

<section class="umap-panel" data-testid="umap-panel">
	<header class="umap-header">
		<div class="title-block">
			<h3>UMAP — cell <code>{cellKey}</code></h3>
			<p class="hint">
				Points are coloured by <em>cluster</em> (community detected for this cell).
				Lasso on 2D filters the result list; click any point to open its detail panel.
			</p>
		</div>
		<div class="header-actions">
			{#if $lassoSelection}
				<button
					type="button"
					class="clear-lasso"
					on:click={() => ($lassoSelection = null)}
					data-testid="umap-clear-lasso"
				>
					Clear selection ({$lassoSelection.size})
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
		height: clamp(280px, 45vh, 480px);
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
