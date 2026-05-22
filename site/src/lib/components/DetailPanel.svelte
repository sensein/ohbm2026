<script lang="ts">
	import { base } from '$app/paths';
	import { goto } from '$app/navigation';
	import { focusedAbstract, authorChips } from '$lib/stores/selection';
	import { cartStore } from '$lib/stores/cart';
	import { standbySummary } from '$lib/standby';
	import {
		PERMALINK_SECTION_KEYS,
		isClampable,
		masterToggleLabel,
		nextStateAfterMasterToggle
	} from '$lib/permalink_section_state';
	import { renderMath } from '$lib/render_math';
	import {
		loadAllCellsWithTopics,
		loadAllNeighbors,
		loadEnrichment,
		type AbstractRecord,
		type AuthorRecord,
		type CellShard,
		type EnrichmentRecord,
		type EnrichmentShard,
		type NeighborsShard,
		type TopicShard
	} from '$lib/shards';

	export let abstract: AbstractRecord | null = null;
	export let authorsById: Map<number, AuthorRecord>;
	export let abstractsById: Map<number, AbstractRecord> = new Map();
	export let dismissable = true;
	/**
	 * In the home page's inline detail pane there isn't room (or attention
	 * budget) for the full abstract — we show only authors (compact, no
	 * affiliations), cross-cell cluster membership, related abstracts, and
	 * AI-extracted claims. The permalink page passes `compact={false}` to
	 * get the full read-everything view.
	 */
	export let compact = false;
	/**
	 * Stage 12 US1b — render mode. `'panel'` (default) is the
	 * in-grid drawer's existing click-to-expand caret behaviour, with
	 * the same 4 verbatim sections (Introduction / Methods / Results /
	 * Conclusion). `'permalink'` switches every left-column verbatim
	 * section to a 3-line CSS `line-clamp` preview with per-section
	 * "Show more" / "Show less" buttons + a column-scoped "Show all" /
	 * "Collapse all" master toggle, and adds the Acknowledgments
	 * section to the iteration (when its corpus value is non-empty).
	 * Set by the permalink page route (`/abstract/<poster_id>/`).
	 */
	export let mode: 'panel' | 'permalink' = 'panel';

	let showAllAuthors = false;
	// Section expansion: each body section starts collapsed; user opens what
	// they want to read. Per-claim and per-figure cards also follow this
	// open/closed pattern so the panel stays a scannable overview.
	let openSections: Record<string, boolean> = {};
	let openClaims: Record<number, boolean> = {};
	let openFigures: Record<number, boolean> = {};

	// Stage 12 US1b — separate state for permalink mode where each
	// section starts in 3-line clamp (NOT hidden) and `expanded[skey]`
	// flips to true when the per-section "Show more" button is
	// clicked. Distinct from `openSections` to avoid semantic
	// confusion (panel-mode default = hidden; permalink-mode default
	// = clamped-but-visible).
	let permalinkExpanded: Record<string, boolean> = {};

	function togglePermalinkSection(key: string) {
		permalinkExpanded = { ...permalinkExpanded, [key]: !permalinkExpanded[key] };
	}

	function togglePermalinkAll() {
		// Derive a Map of clampable section keys + their current state,
		// then flip the whole set via the pure helper.
		const clampableMap = new Map<string, boolean>();
		for (const k of PERMALINK_SECTION_KEYS) {
			const body = abstract?.sections[k as keyof typeof abstract.sections];
			if (isClampable(body as string | undefined)) {
				clampableMap.set(k, !!permalinkExpanded[k]);
			}
		}
		const next = nextStateAfterMasterToggle(clampableMap);
		const merged = { ...permalinkExpanded };
		for (const [k, v] of next) {
			merged[k] = v;
		}
		permalinkExpanded = merged;
	}

	$: clampableExpandedMap = (() => {
		const m = new Map<string, boolean>();
		if (mode !== 'permalink' || !abstract) return m;
		for (const k of PERMALINK_SECTION_KEYS) {
			const body = abstract.sections[k as keyof typeof abstract.sections];
			if (isClampable(body as string | undefined)) {
				m.set(k, !!permalinkExpanded[k]);
			}
		}
		return m;
	})();
	$: masterLabel = masterToggleLabel(clampableExpandedMap);
	$: anyClampable = clampableExpandedMap.size > 0;

	function toggleSection(key: string) {
		openSections = { ...openSections, [key]: !openSections[key] };
	}
	function toggleClaim(i: number) {
		openClaims = { ...openClaims, [i]: !openClaims[i] };
	}
	function toggleFigure(i: number) {
		openFigures = { ...openFigures, [i]: !openFigures[i] };
	}

	// Reset per-section/per-card open state when the focused abstract changes
	// so the next abstract starts in the same collapsed default.
	let prevAbstractId: number | null = null;
	$: if (abstract && abstract.poster_id !== prevAbstractId) {
		prevAbstractId = abstract.poster_id;
		openSections = {};
		openClaims = {};
		openFigures = {};
		// Stage 12 US1b: permalink-mode sections reset to clamped on
		// navigation between abstracts (matches the page-load default).
		permalinkExpanded = {};
	}

	// --- Cross-cell cluster membership -----------------------------------
	// For every (model, input) cell, look up which community this abstract
	// belongs to + the community's label. Lets the user compare what
	// different embeddings consider "this abstract's neighbourhood".
	let allCells: Map<string, { cell: CellShard; topics: TopicShard | null }> | null = null;
	$: void (async () => {
		if (allCells !== null) return;
		allCells = await loadAllCellsWithTopics();
	})();
	type ClusterRow = { cellKey: string; communityId: number; label: string };
	$: clusterMemberships = (() => {
		if (!abstract || !allCells) return [] as ClusterRow[];
		const rows: ClusterRow[] = [];
		for (const [cellKey, { cell, topics }] of allCells) {
			const row = cell.rows.find((r) => r.poster_id === abstract!.poster_id);
			if (!row) continue;
			const topicMap = new Map<number, string>();
			if (topics) {
				for (const t of topics.topics) {
					const label = t.title
						? t.title
						: t.keywords?.length
							? t.keywords.slice(0, 3).join(', ')
							: `cluster ${t.cluster_id}`;
					topicMap.set(t.cluster_id, label);
				}
			}
			rows.push({
				cellKey,
				communityId: row.community_id,
				label: topicMap.get(row.community_id) ?? `community ${row.community_id}`
			});
		}
		rows.sort((a, b) => a.cellKey.localeCompare(b.cellKey));
		return rows;
	})();

	// --- Stage 2.1 enrichment (claims + figure interpretations) ----------
	let enrichmentShard: EnrichmentShard | null = null;
	let enrichmentLoaded = false;
	$: void (async () => {
		if (enrichmentLoaded) return;
		const shard = await loadEnrichment();
		enrichmentShard = shard;
		enrichmentLoaded = true;
	})();
	$: enrichment = (() => {
		if (!abstract || !enrichmentShard) return null;
		const rec = enrichmentShard.records[String(abstract.poster_id)];
		return (rec as EnrichmentRecord | undefined) ?? null;
	})();
	$: claimsModelId = enrichmentShard?.ai_provenance.claims_model_id ?? null;
	$: figuresModelId = enrichmentShard?.ai_provenance.figures_model_id ?? null;

	$: authorList = abstract
		? abstract.author_ids
				.map((id) => authorsById.get(id))
				.filter((a): a is AuthorRecord => a !== undefined)
		: [];
	$: visibleAuthors = showAllAuthors ? authorList : authorList.slice(0, 6);

	function close() {
		$focusedAbstract = null;
	}

	function inCart(posterId: number): boolean {
		return $cartStore.has(posterId);
	}

	// --- Related abstracts: aggregated across ALL cells -----------------
	// The earlier single-cell view biased the "most similar" list toward the
	// active (model, input) embedding. Aggregating over every cell surfaces
	// abstracts that are consistently close (or distant) across multiple
	// embeddings — a stronger signal of true topical similarity. Each row
	// shows the min distance plus the count of cells in which the abstract
	// appeared in the focused record's nearest/farthest 10.
	let allNeighbors: Map<string, NeighborsShard> | null = null;
	let neighborsLoading = false;
	$: void (async () => {
		if (allNeighbors !== null) return;
		neighborsLoading = true;
		allNeighbors = await loadAllNeighbors();
		neighborsLoading = false;
	})();

	type RelatedEntry = {
		abstract: AbstractRecord;
		minDistance: number;
		meanDistance: number;
		cellCount: number;
		cellKeys: string[];
	};

	function aggregateRelated(
		shards: Map<string, NeighborsShard> | null,
		focusedId: number | undefined,
		kind: 'nearest' | 'farthest'
	): RelatedEntry[] {
		if (!shards || focusedId === undefined) return [];
		// poster_id → { distances: [], cellKeys: [] }
		const buckets = new Map<number, { distances: number[]; cellKeys: string[] }>();
		for (const [cellKey, shard] of shards) {
			const row = shard.poster_ids.indexOf(focusedId);
			if (row < 0) continue;
			const ids = kind === 'nearest' ? shard.nearest_ids[row] : shard.farthest_ids[row];
			const dist =
				kind === 'nearest' ? shard.nearest_distances[row] : shard.farthest_distances[row];
			for (let i = 0; i < ids.length; i++) {
				const aid = ids[i];
				const d = dist[i];
				let b = buckets.get(aid);
				if (!b) {
					b = { distances: [], cellKeys: [] };
					buckets.set(aid, b);
				}
				b.distances.push(d);
				b.cellKeys.push(cellKey);
			}
		}
		const out: RelatedEntry[] = [];
		for (const [aid, b] of buckets) {
			const rec = abstractsById.get(aid);
			if (!rec) continue;
			const minD = Math.min(...b.distances);
			const meanD = b.distances.reduce((s, x) => s + x, 0) / b.distances.length;
			out.push({
				abstract: rec,
				minDistance: minD,
				meanDistance: meanD,
				cellCount: b.cellKeys.length,
				cellKeys: b.cellKeys
			});
		}
		// "Closest 5" → sort by min-distance ascending; "Most different" by
		// max-distance descending (negated min for "farthest" mode).
		if (kind === 'nearest') {
			out.sort(
				(a, b) => a.minDistance - b.minDistance || b.cellCount - a.cellCount
			);
		} else {
			// For farthest, use mean for ranking — a single outlier cell shouldn't
			// dominate; we want consistently distant abstracts at the top.
			out.sort(
				(a, b) => b.meanDistance - a.meanDistance || b.cellCount - a.cellCount
			);
		}
		return out;
	}

	$: focusedId = abstract?.poster_id;
	$: nearest = aggregateRelated(allNeighbors, focusedId, 'nearest');
	$: farthest = aggregateRelated(allNeighbors, focusedId, 'farthest');

	function focusRelated(posterId: number) {
		if (posterId) $focusedAbstract = posterId;
	}

	/**
	 * Add the author's name to the active author-chip set and (on the
	 * permalink page) navigate back to the home page so the result list
	 * shows the filter result. Non-destructive: chips coexist with the
	 * search query, facets, and lasso, and can be removed individually.
	 */
	async function searchByAuthor(name: string): Promise<void> {
		if (!name) return;
		authorChips.update((s) => {
			if (s.has(name)) return s;
			const next = new Set(s);
			next.add(name);
			return next;
		});
		if (!compact) {
			await goto(`${base}/`);
		} else if (typeof window !== 'undefined') {
			window.scrollTo({ top: 0, behavior: 'smooth' });
		}
	}

	function leadAuthor(record: AbstractRecord): string {
		const id = record.author_ids[0];
		if (id === undefined) return '';
		return authorsById.get(id)?.name ?? '';
	}
</script>

{#if abstract}
	<aside class="detail" data-testid="detail-panel" data-poster-id={abstract.poster_id}>
		<header class="detail-header">
			<div class="ids">
				<span
					class="poster-id"
					data-testid="detail-poster-id"
					title="Program-assigned poster id"
				>
					{abstract.poster_id || `(no poster id)`}
				</span>
				<span class="accepted-for">{abstract.accepted_for}</span>
			</div>
			<div class="header-actions">
				{#if abstract.poster_id}
					{@const headerInCart = $cartStore.has(abstract.poster_id)}
					<button
						type="button"
						class="cart-icon detail-cart-icon"
						class:in-cart={headerInCart}
						on:click={() =>
							headerInCart
								? cartStore.remove(abstract.poster_id)
								: cartStore.add(abstract.poster_id)}
						aria-label={headerInCart ? 'Remove from your list' : 'Add to your list'}
						aria-pressed={headerInCart ? 'true' : 'false'}
						title={headerInCart ? 'In your list — click to remove' : 'Add to your list'}
						data-testid={headerInCart ? 'detail-cart-remove' : 'detail-cart-add'}
					>
						{#if headerInCart}
							<svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<circle cx="9" cy="21" r="1.2" />
								<circle cx="18" cy="21" r="1.2" />
								<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7 4.5 3H2zM7 9l1 5h11l1-5z" />
							</svg>
							<span class="check-pip" aria-hidden="true">✓</span>
						{:else}
							<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
								<circle cx="9" cy="21" r="1.2" />
								<circle cx="18" cy="21" r="1.2" />
								<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7" />
							</svg>
						{/if}
					</button>
				{/if}
				{#if abstract.poster_id && compact}
					<a
						class="permalink permalink-top"
						href={`${base}/abstract/${String(abstract.poster_id).padStart(4, '0')}/`}
						data-testid="detail-permalink"
						title="Open the full-detail page for this abstract"
					>
						full details ↗
					</a>
				{/if}
				{#if dismissable}
					<button
						type="button"
						class="close"
						on:click={close}
						aria-label="Close detail panel"
						data-testid="detail-close"
					>
						×
					</button>
				{/if}
			</div>
		</header>

		<h1 class="detail-title" data-testid="detail-title">{abstract.title}</h1>

		<section class="authors" data-testid="detail-authors">
			<h2>Authors <span class="hint-inline">click to filter by author</span></h2>
			{#if compact}
				<p class="author-compact">
					{#each authorList as author, i (author.author_id)}<!--
					-->{#if i > 0}<span class="author-sep">, </span>{/if}<!--
					--><button
							type="button"
							class="author-link"
							on:click={() => searchByAuthor(author.name)}
							title={`Search abstracts by ${author.name}`}
							data-testid="author-search"
						>{author.name}</button><!--
					-->{/each}
				</p>
			{:else}
				<ol class="author-list">
					{#each visibleAuthors as author (author.author_id)}
						<li>
							<button
								type="button"
								class="author-link"
								on:click={() => searchByAuthor(author.name)}
								title={`Search abstracts by ${author.name}`}
								data-testid="author-search"
							>{author.name}</button>
							{#if author.affiliations[0]}
								<span class="author-aff">— {author.affiliations[0]}</span>
							{/if}
						</li>
					{/each}
				</ol>
				{#if authorList.length > 6}
					<button
						type="button"
						class="link"
						on:click={() => (showAllAuthors = !showAllAuthors)}
						data-testid="detail-toggle-authors"
					>
						{showAllAuthors ? 'Show fewer' : `Show all ${authorList.length} authors`}
					</button>
				{/if}
			{/if}
		</section>

		{#if abstract.poster_standby}
			{@const standby = standbySummary(abstract.poster_standby)}
			{#if standby.firstLabel || standby.secondLabel}
				<section class="standby" data-testid="detail-standby" data-zone="submitter">
					<h2>Stand-by times <span class="hint-inline">when this poster is staffed</span></h2>
					<ul class="standby-list">
						{#if standby.firstLabel}
							<li data-testid="standby-first">{standby.firstLabel}</li>
						{/if}
						{#if standby.secondLabel}
							<li data-testid="standby-second">{standby.secondLabel}</li>
						{/if}
					</ul>
					<p class="standby-tz-hint">All times Europe/Paris (venue local).</p>
				</section>
			{/if}
		{/if}


		<!--
			Two-zone layout for the permalink view: submitter content on
			the left, computed + AI insights on the right. The DOM has two
			INDEPENDENT flex-column containers inside a 2-column CSS grid
			so each column's items stack tightly without their row heights
			being yoked to the other column's items. Compact mode (home
			pane) renders a flat linear flow with no zones.
		-->
		<div class="detail-content" class:zoned={!compact}>
			{#if !compact}
				<!-- LEFT zone — submitter-authored content (verbatim) -->
				<div class="zone zone-submitter" data-zone="submitter">
					<div class="zone-header">
						<span class="zone-title">From the submitter</span>
						<span class="zone-sub">verbatim from the submission</span>
					</div>
					{@render bodyBlock()}
					<!--
						FR-011: only Topics + Methods of the submission-form extras render
						here. Other extra-question fields (study_type, population,
						field_strength, processing_packages, …) are stored in `facets` for
						filtering but MUST NOT surface in the detail panel.
					-->
					{@render topicsBlock()}
					{@render methodsBlock()}
					{@render referencesBlock()}
				</div>
				<!-- RIGHT zone — algorithmic + AI-derived -->
				<div class="zone zone-computed" data-zone="computed">
					<div class="zone-header">
						<span class="zone-title">Computed insights</span>
						<span class="zone-sub">
							algorithmic; <span class="ai-pill-inline">✨ AI</span> sections labelled
						</span>
					</div>
					<!-- AI-derived sections first so the most distinctive
						 surfaces (extracted claims + figure interpretations) sit
						 at the top of the computed column; algorithmic context
						 (cluster membership + neighbour rails) follows below. -->
					{@render claimsBlock()}
					{@render figuresBlock()}
					{@render clusterBlock()}
					{@render relatedBlock()}
				</div>
			{:else}
				<!-- Compact mode: linear flow, only the home-pane essentials. -->
				{@render claimsBlock()}
				{@render clusterBlock()}
				{@render relatedBlock()}
			{/if}
		</div><!-- /.detail-content -->

		{#snippet bodyBlock()}
		{#if !compact}
			{#if mode === 'permalink' && anyClampable}
				<!-- Stage 12 US1b: column-scoped master toggle that
				     expands every clampable section at once + flips
				     to "Collapse all" once everything is open. -->
				<button
					type="button"
					class="master-toggle"
					data-testid="master-toggle"
					aria-pressed={masterLabel === 'Collapse all'}
					aria-controls="permalink-verbatim-column"
					on:click={togglePermalinkAll}
				>{masterLabel}</button>
			{/if}
			<div
				id={mode === 'permalink' ? 'permalink-verbatim-column' : undefined}
			>
				{#each (mode === 'permalink'
					? [ ['introduction','Introduction'], ['methods','Methods'], ['results','Results'], ['conclusion','Conclusion'], ['acknowledgments','Acknowledgments'] ] as [keyof typeof abstract.sections, string][]
					: [ ['introduction','Introduction'], ['methods','Methods'], ['results','Results'], ['conclusion','Conclusion'] ] as [keyof typeof abstract.sections, string][]) as [skey, slabel] (skey)}
				{@const sbody = abstract.sections[skey]}
				{#if sbody}
					{#if mode === 'permalink'}
						{@const clampable = isClampable(sbody)}
						{@const expanded = !!permalinkExpanded[skey]}
						<section
							class="section verbatim-section {clampable ? (expanded ? 'section-expanded' : 'section-clamped') : 'section-short'}"
							data-testid={`section-${skey}`}
							data-zone="submitter"
						>
							<h3 class="section-label section-label-permalink">{slabel}</h3>
							<p class="section-body" class:section-body-clamped={clampable && !expanded}>{@html renderMath(sbody)}</p>
							{#if clampable}
								<button
									type="button"
									class="section-toggle"
									data-testid={`section-toggle-${skey}`}
									aria-expanded={expanded}
									on:click={() => togglePermalinkSection(skey)}
								>{expanded ? 'Show less' : 'Show more'}</button>
							{/if}
						</section>
					{:else}
						<section class="section collapsible" data-testid={`section-${skey}`} data-zone="submitter">
							<button
								type="button"
								class="section-header"
								on:click={() => toggleSection(skey)}
								aria-expanded={!!openSections[skey]}
							>
								<span class="caret">{openSections[skey] ? '▾' : '▸'}</span>
								<span class="section-label">{slabel}</span>
							</button>
							{#if openSections[skey]}
								<p class="section-body">{@html renderMath(sbody)}</p>
							{/if}
						</section>
					{/if}
				{/if}
				{/each}
			</div>
		{/if}
		{/snippet}

		{#snippet claimsBlock()}
		{#if enrichment && enrichment.claims.length}
			<section class="section collapsible" data-testid="section-claims" data-zone="computed">
				<button
					type="button"
					class="section-header"
					on:click={() => toggleSection('claims')}
					aria-expanded={!!openSections.claims}
				>
					<span class="caret">{openSections.claims ? '▾' : '▸'}</span>
					<span class="section-label">
						Claims <span class="badge">{enrichment.claims.length}</span>
					</span>
					{#if claimsModelId}
						<span class="ai-pill" title={`AI-extracted by ${claimsModelId}`}>
							✨ AI
						</span>
					{/if}
				</button>
				{#if openSections.claims}
					<ul class="card-list">
						{#each enrichment.claims as claim, i (i)}
							{@const isOpen = !!openClaims[i]}
							<li class="card-item">
								<button
									type="button"
									class="card-header"
									on:click={() => toggleClaim(i)}
									aria-expanded={isOpen}
								>
									<span class="caret">{isOpen ? '▾' : '▸'}</span>
									<span class="card-summary">{claim.claim}</span>
									{#if claim.claim_type}
										<span class="card-tag">{claim.claim_type}</span>
									{/if}
								</button>
								{#if isOpen}
									<div class="card-body">
										{#if claim.evidence}
											<dl class="kv">
												<dt>Evidence</dt>
												<dd>{claim.evidence}</dd>
												{#if claim.evidence_eco_codes?.length}
													<dt>ECO codes</dt>
													<dd>
														<code>{claim.evidence_eco_codes.join(', ')}</code>
													</dd>
												{/if}
												{#if claim.source}
													<dt>Source quote</dt>
													<dd class="quote">
														“{claim.source}”
														{#if claim.source_quote_verified}
															<span class="verified" title="verified against the abstract">✓</span>
														{/if}
													</dd>
												{/if}
											</dl>
										{/if}
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		{/if}
		{/snippet}

		{#snippet figuresBlock()}
		{#if !compact && enrichment && enrichment.figures.length}
			<section class="section collapsible" data-testid="section-figures" data-zone="computed">
				<button
					type="button"
					class="section-header"
					on:click={() => toggleSection('figures')}
					aria-expanded={!!openSections.figures}
				>
					<span class="caret">{openSections.figures ? '▾' : '▸'}</span>
					<span class="section-label">
						Figure interpretations <span class="badge">{enrichment.figures.length}</span>
					</span>
					{#if figuresModelId}
						<span class="ai-pill" title={`AI-interpreted by ${figuresModelId}`}>
							✨ AI
						</span>
					{/if}
				</button>
				{#if openSections.figures}
					<ul class="card-list">
						{#each enrichment.figures as fig, i (i)}
							{@const isOpen = !!openFigures[i]}
							<li class="card-item">
								<button
									type="button"
									class="card-header"
									on:click={() => toggleFigure(i)}
									aria-expanded={isOpen}
								>
									<span class="caret">{isOpen ? '▾' : '▸'}</span>
									<span class="card-summary">
										{fig.question_name || `Figure ${i + 1}`}
									</span>
								</button>
								{#if isOpen}
									<div class="card-body">
										<p class="fig-interpretation">{fig.interpretation}</p>
										<dl class="kv">
											{#if fig.keywords?.length}
												<dt>Keywords</dt>
												<dd>
													<ul class="chips chips-sm">
														{#each fig.keywords as kw (kw)}<li>{kw}</li>{/each}
													</ul>
												</dd>
											{/if}
											{#if fig.ocr_text}
												<dt>OCR text</dt>
												<dd class="ocr"><code>{fig.ocr_text}</code></dd>
											{/if}
											{#if fig.model_quality_estimate}
												<dt>Model quality</dt>
												<dd>{fig.model_quality_estimate}</dd>
											{/if}
										</dl>
									</div>
								{/if}
							</li>
						{/each}
					</ul>
				{/if}
			</section>
		{/if}
		{/snippet}

		{#snippet topicsBlock()}
		{#if !compact && (abstract.topics.primary || abstract.topics.secondary)}
			<section class="extra topics" data-testid="extra-topics" data-zone="submitter">
				<h2>Topics</h2>
				<dl>
					{#if abstract.topics.primary}
						<dt>Primary</dt>
						<dd>
							{abstract.topics.primary}{#if abstract.topics.primary_subcategory}
								<span class="muted"> / {abstract.topics.primary_subcategory}</span>
							{/if}
						</dd>
					{/if}
					{#if abstract.topics.secondary}
						<dt>Secondary</dt>
						<dd>
							{abstract.topics.secondary}{#if abstract.topics.secondary_subcategory}
								<span class="muted"> / {abstract.topics.secondary_subcategory}</span>
							{/if}
						</dd>
					{/if}
				</dl>
			</section>
		{/if}
		{/snippet}

		{#snippet methodsBlock()}
		{#if !compact && abstract.methods_checklist.length}
			<section class="extra methods-checklist" data-testid="extra-methods" data-zone="submitter">
				<h2>Methods</h2>
				<ul class="chips">
					{#each abstract.methods_checklist as m (m)}
						<li>{m}</li>
					{/each}
				</ul>
			</section>
		{/if}
		{/snippet}

		{#snippet clusterBlock()}
		{#if clusterMemberships.length}
			<section class="extra clusters" data-testid="extra-clusters" data-zone="computed">
				<h2>Cluster membership <span class="muted">— per (model × input)</span></h2>
				<!-- tabindex=0 + role="region" + aria-label so the
					 overflow:auto scroll container is reachable by keyboard
					 users (axe scrollable-region-focusable / WCAG 2.1.1). -->
				<!-- Wrap the <ul> in a region-roled <div>; putting role="region"
					 on the <ul> itself strips its implicit list role and axe
					 then flags the child <li>s as "must be in a <ul>/<ol>". -->
				<div
					class="cluster-grid-region"
					tabindex="0"
					role="region"
					aria-label="Cluster membership across all (model × input) cells"
				>
					<ul class="cluster-grid">
						{#each clusterMemberships as row (row.cellKey)}
							<li class="cluster-row">
								<code class="cluster-cell">{row.cellKey}</code>
								<span class="cluster-id">#{row.communityId}</span>
								<span class="cluster-label" title={row.label}>{row.label}</span>
							</li>
						{/each}
					</ul>
				</div>
			</section>
		{/if}
		{/snippet}

		{#snippet relatedBlock()}
		{#if allNeighbors && (nearest.length || farthest.length)}
			<section class="related" data-testid="detail-related" data-zone="computed">
				<h2>
					Related abstracts
					<span class="muted">— across all {allNeighbors.size} maps</span>
				</h2>
				{#if nearest.length}
					<div class="related-block">
						<h3 class="related-heading">
							Most similar
							<span class="hint">closest 5 shown; scroll for more</span>
						</h3>
						<div class="related-scroll" tabindex="0" role="region" aria-label="Most-similar abstracts list">
						<ul class="related-list" data-testid="related-nearest-list">
							{#each nearest as entry, i (entry.abstract.poster_id)}
								{@const inCartNow = $cartStore.has(entry.abstract.poster_id)}
								<li>
									<div class="related-link">
										<button
											type="button"
											class="related-body"
											on:click={() => focusRelated(entry.abstract.poster_id)}
											disabled={!entry.abstract.poster_id}
											data-testid="related-nearest"
										>
											<span class="related-rank">#{i + 1}</span>
											<span class="related-poster-pile">
												<span class="related-poster">{entry.abstract.poster_id ? String(entry.abstract.poster_id).padStart(4, '0') : '—'}</span>
												<span class="related-distance" title="min cosine distance across maps">
													d={entry.minDistance.toFixed(3)}
												</span>
											</span>
											<span class="related-title">{entry.abstract.title}</span>
											<span
												class="related-cells"
												title={`appears in ${entry.cellCount} of ${allNeighbors.size} maps: ${entry.cellKeys.join(', ')}`}
											>
												×{entry.cellCount}
											</span>
										</button>
										<button
											type="button"
											class="related-cart"
											class:in-cart={inCartNow}
											disabled={!entry.abstract.poster_id}
											on:click={() =>
												inCartNow
													? cartStore.remove(entry.abstract.poster_id)
													: cartStore.add(entry.abstract.poster_id)}
											aria-label={inCartNow ? 'Remove from your list' : 'Add to your list'}
											aria-pressed={inCartNow ? 'true' : 'false'}
											title={inCartNow ? 'In your list — click to remove' : 'Add to your list'}
											data-testid={inCartNow ? 'related-cart-remove' : 'related-cart-add'}
										>
											{#if inCartNow}
												<svg
													width="16"
													height="16"
													viewBox="0 0 24 24"
													fill="currentColor"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
													aria-hidden="true"
												>
													<circle cx="9" cy="21" r="1.2" />
													<circle cx="18" cy="21" r="1.2" />
													<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7 4.5 3H2zM7 9l1 5h11l1-5z" />
												</svg>
												<span class="check-pip" aria-hidden="true">✓</span>
											{:else}
												<svg
													width="16"
													height="16"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
													aria-hidden="true"
												>
													<circle cx="9" cy="21" r="1.2" />
													<circle cx="18" cy="21" r="1.2" />
													<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7" />
												</svg>
											{/if}
										</button>
									</div>
								</li>
							{/each}
						</ul>
						</div>
					</div>
				{/if}
				{#if farthest.length}
					<div class="related-block">
						<h3 class="related-heading">
							Most different
							<span class="hint">farthest 5 shown; scroll for more</span>
						</h3>
						<div class="related-scroll" tabindex="0" role="region" aria-label="Most-different abstracts list">
						<ul class="related-list" data-testid="related-farthest-list">
							{#each farthest as entry, i (entry.abstract.poster_id)}
								{@const inCartFar = $cartStore.has(entry.abstract.poster_id)}
								<li>
									<div class="related-link">
										<button
											type="button"
											class="related-body"
											on:click={() => focusRelated(entry.abstract.poster_id)}
											disabled={!entry.abstract.poster_id}
											data-testid="related-farthest"
										>
											<span class="related-rank">#{i + 1}</span>
											<span class="related-poster-pile">
												<span class="related-poster">{entry.abstract.poster_id ? String(entry.abstract.poster_id).padStart(4, '0') : '—'}</span>
												<span class="related-distance" title="mean cosine distance across maps">
													d={entry.meanDistance.toFixed(3)}
												</span>
											</span>
											<span class="related-title">{entry.abstract.title}</span>
											<span
												class="related-cells"
												title={`appears in ${entry.cellCount} of ${allNeighbors.size} maps`}
											>
												×{entry.cellCount}
											</span>
										</button>
										<button
											type="button"
											class="related-cart"
											class:in-cart={inCartFar}
											disabled={!entry.abstract.poster_id}
											on:click={() =>
												inCartFar
													? cartStore.remove(entry.abstract.poster_id)
													: cartStore.add(entry.abstract.poster_id)}
											aria-label={inCartFar ? 'Remove from your list' : 'Add to your list'}
											aria-pressed={inCartFar ? 'true' : 'false'}
											title={inCartFar ? 'In your list — click to remove' : 'Add to your list'}
											data-testid={inCartFar ? 'related-cart-remove-far' : 'related-cart-add-far'}
										>
											{#if inCartFar}
												<svg
													width="16"
													height="16"
													viewBox="0 0 24 24"
													fill="currentColor"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
													aria-hidden="true"
												>
													<circle cx="9" cy="21" r="1.2" />
													<circle cx="18" cy="21" r="1.2" />
													<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7 4.5 3H2zM7 9l1 5h11l1-5z" />
												</svg>
												<span class="check-pip" aria-hidden="true">✓</span>
											{:else}
												<svg
													width="16"
													height="16"
													viewBox="0 0 24 24"
													fill="none"
													stroke="currentColor"
													stroke-width="2"
													stroke-linecap="round"
													stroke-linejoin="round"
													aria-hidden="true"
												>
													<circle cx="9" cy="21" r="1.2" />
													<circle cx="18" cy="21" r="1.2" />
													<path d="M2 3h2.5L5.5 7H21l-2 9H7L5.5 7" />
												</svg>
											{/if}
										</button>
									</div>
								</li>
							{/each}
						</ul>
						</div>
					</div>
				{/if}
			</section>
		{:else if neighborsLoading}
			<section class="related" data-testid="detail-related-loading" data-zone="computed">
				<h2>Related abstracts</h2>
				<p class="muted">Loading neighbors…</p>
			</section>
		{/if}
		{/snippet}

		{#snippet referencesBlock()}
		{#if !compact && (abstract.reference_urls.some(Boolean) || abstract.reference_dois.some(Boolean) || (abstract.reference_titles ?? []).some(Boolean))}
			<section class="references" data-testid="detail-references" data-zone="submitter">
				<h2>References</h2>
				<ol>
					{#each abstract.reference_urls as url, i (url + i)}
						{@const doi = abstract.reference_dois[i] || ''}
						{@const title = (abstract.reference_titles ?? [])[i] || ''}
						{@const linkUrl = url || (doi ? `https://doi.org/${doi}` : '')}
						<li>
							{#if linkUrl}
								<a href={linkUrl} target="_blank" rel="noopener noreferrer">
									{title || doi || linkUrl}
								</a>
								{#if title && doi}
									<span class="ref-doi" title="DOI">{doi}</span>
								{/if}
							{:else if title}
								<span>{title}</span>
							{/if}
						</li>
					{/each}
				</ol>
			</section>
		{/if}
		{/snippet}

		<footer class="detail-footer">
			{#if !compact}
				<!-- Permalink page: the last thing on the panel is a way back
					 to the main atlas. (Cart action moved to the header next to
					 the poster id; the permalink button itself only renders in
					 compact / home-pane mode.) -->
				<a class="back-to-atlas" href={`${base}/`} data-testid="detail-back-to-atlas">
					← back to the atlas
				</a>
			{/if}
		</footer>
	</aside>
{/if}

<style>
	/* Two-zone layout. `.detail-content` is the post-header container. In
	   compact (home pane) mode + on mobile (< 980 px), sections stack
	   linearly. On landscape desktop the wrapper becomes a 2-column CSS
	   grid containing TWO independent flex-column zones (`.zone`); each
	   zone packs its own sections tightly, so the columns don't yoke
	   each other's row heights. */
	.detail-content {
		display: flex;
		flex-direction: column;
		gap: 0.6rem;
	}
	.zone {
		display: contents; /* mobile / compact: don't introduce extra boxes */
	}
	.zone-header {
		display: none; /* hidden on mobile / compact */
	}
	@media (min-width: 980px) {
		.detail-content.zoned {
			display: grid;
			grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
			column-gap: 1.5rem;
			align-items: start;
		}
		.detail-content.zoned > .zone {
			display: flex;
			flex-direction: column;
			gap: 0.55rem;
			min-width: 0;
			align-self: start;
		}
		.detail-content.zoned > .zone-computed {
			padding-left: 0.5rem;
			border-left: 1px solid var(--border);
			margin-left: -0.5rem;
		}
		.detail-content.zoned > .zone > .zone-header {
			display: flex;
			flex-direction: column;
			gap: 0.1rem;
			margin-bottom: 0.2rem;
			padding-bottom: 0.4rem;
			border-bottom: 1.5px solid var(--border-strong);
		}
	}
	.zone-title {
		font-size: 0.85rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text);
	}
	.zone-sub {
		font-size: 0.75rem;
		color: var(--text-muted);
	}
	.ai-pill-inline {
		display: inline-block;
		font-size: 0.65rem;
		font-weight: 600;
		color: var(--accent-soft-text);
		background: var(--accent-soft-bg);
		padding: 0 0.4rem;
		border-radius: 999px;
		letter-spacing: 0.04em;
		vertical-align: middle;
	}
	.author-link {
		all: unset;
		cursor: pointer;
		color: var(--accent);
		border-bottom: 1px dotted transparent;
	}
	.author-link:hover {
		border-bottom-color: var(--accent);
	}
	.author-sep {
		color: var(--text-faint);
	}
	.hint-inline {
		font-size: 0.7rem;
		text-transform: none;
		letter-spacing: 0;
		color: var(--text-faint);
		font-weight: 400;
		margin-left: 0.4rem;
	}
	.standby {
		margin: 0.4rem 0 0.6rem;
	}
	.standby-list {
		list-style: none;
		padding: 0;
		margin: 0.2rem 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.standby-list li {
		background: var(--chip-bg, rgba(0, 0, 0, 0.05));
		border: 1px solid var(--border);
		border-radius: 0.4rem;
		padding: 0.2rem 0.55rem;
		font-size: 0.82rem;
		white-space: nowrap;
	}
	.standby-tz-hint {
		margin: 0.15rem 0 0;
		font-size: 0.7rem;
		color: var(--text-faint);
	}

	.detail {
		background: var(--bg-elevated);
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 1rem;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		min-width: 0;
	}
	.detail-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
	}
	.header-actions {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.permalink-top {
		font-size: 0.78rem;
		color: var(--accent);
		text-decoration: none;
		padding: 0.2rem 0.45rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-sunken);
		white-space: nowrap;
	}
	.permalink-top:hover {
		background: var(--accent-soft-bg);
		text-decoration: none;
	}
	.author-compact {
		margin: 0;
		font-size: 0.85rem;
		line-height: 1.45;
		color: var(--text);
	}
	.ids {
		display: flex;
		gap: 0.5rem;
		align-items: baseline;
	}
	.poster-id {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-weight: 700;
		font-size: 1rem;
		color: var(--accent);
	}
	.accepted-for {
		font-size: 0.75rem;
		color: var(--text-muted);
		text-transform: uppercase;
		letter-spacing: 0.04em;
	}
	.close {
		all: unset;
		cursor: pointer;
		font-size: 1.5rem;
		color: var(--text-muted);
		padding: 0 0.25rem;
	}
	.close:hover {
		color: var(--text);
	}
	.detail-title {
		font-size: 1.2rem;
		margin: 0;
		line-height: 1.3;
		color: var(--text);
	}
	h2 {
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		margin: 0 0 0.25rem;
	}
	.section p,
	.detail dd {
		margin: 0;
		font-size: 0.95rem;
		line-height: 1.55;
		color: var(--text);
	}
	.section-body {
		white-space: pre-wrap;
		padding: 0.4rem 0 0.2rem 1.3rem;
	}

	/* Stage 12 US1b — permalink-mode brief-preview + show-more. */
	.verbatim-section {
		border-top: 1px solid var(--border);
		padding-top: 0.6rem;
		padding-bottom: 0.4rem;
	}
	.section-label-permalink {
		margin: 0 0 0.3rem;
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-weight: 600;
	}
	.section-body-clamped {
		display: -webkit-box;
		-webkit-line-clamp: 3;
		-webkit-box-orient: vertical;
		line-clamp: 3;
		overflow: hidden;
	}
	.section-toggle {
		all: unset;
		cursor: pointer;
		margin-top: 0.3rem;
		font-size: 0.8rem;
		color: var(--accent, #2c5fa3);
		font-weight: 600;
	}
	.section-toggle:hover {
		text-decoration: underline;
	}
	.section-toggle:focus-visible {
		outline: 2px solid var(--accent, #2c5fa3);
		outline-offset: 2px;
	}
	.master-toggle {
		all: unset;
		cursor: pointer;
		display: inline-block;
		margin: 0.4rem 0 0.6rem;
		padding: 0.3rem 0.7rem;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-sunken, #f4f4f4);
		font-size: 0.85rem;
		font-weight: 600;
		color: var(--text);
	}
	.master-toggle:hover {
		background: var(--bg-hover, #e8e8e8);
	}
	.master-toggle:focus-visible {
		outline: 2px solid var(--accent, #2c5fa3);
		outline-offset: 2px;
	}

	.collapsible {
		border-top: 1px solid var(--border);
		padding-top: 0.4rem;
	}
	.section-header {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: center;
		gap: 0.4rem;
		width: 100%;
		font-size: 0.85rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-muted);
		font-weight: 600;
	}
	.section-header:hover {
		color: var(--text);
	}
	.section-header .caret {
		font-size: 0.7rem;
		color: var(--text-muted);
		width: 0.7rem;
	}
	.section-label {
		flex: 1;
	}
	.badge {
		display: inline-block;
		background: var(--bg-sunken);
		color: var(--text-muted);
		font-size: 0.7rem;
		padding: 0.05rem 0.4rem;
		border-radius: 999px;
		margin-left: 0.3rem;
		text-transform: none;
		letter-spacing: 0;
		font-weight: 500;
	}
	.ai-pill {
		font-size: 0.65rem;
		font-weight: 600;
		color: var(--accent-soft-text);
		background: var(--accent-soft-bg);
		padding: 0.1rem 0.4rem;
		border-radius: 999px;
		letter-spacing: 0.04em;
		text-transform: none;
		flex-shrink: 0;
	}
	.card-list {
		list-style: none;
		padding: 0 0 0.25rem 1.3rem;
		margin: 0.3rem 0 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.card-item {
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg-elevated);
	}
	.card-header {
		all: unset;
		cursor: pointer;
		display: flex;
		align-items: flex-start;
		gap: 0.4rem;
		padding: 0.4rem 0.55rem;
		font-size: 0.85rem;
		line-height: 1.35;
		color: var(--text);
		width: 100%;
		box-sizing: border-box;
	}
	.card-header:hover {
		background: var(--bg-sunken);
	}
	.card-header .caret {
		font-size: 0.65rem;
		color: var(--text-muted);
		width: 0.7rem;
		margin-top: 0.2rem;
	}
	.card-summary {
		flex: 1;
		min-width: 0;
		word-break: break-word;
	}
	.card-tag {
		font-size: 0.65rem;
		text-transform: uppercase;
		color: var(--text-muted);
		background: var(--bg-sunken);
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		letter-spacing: 0.04em;
		flex-shrink: 0;
	}
	.card-body {
		padding: 0 0.55rem 0.55rem 1.55rem;
		font-size: 0.83rem;
		color: var(--text);
	}
	.kv {
		grid-template-columns: max-content 1fr;
		gap: 0.2rem 0.6rem;
		font-size: 0.82rem;
	}
	.kv dt {
		color: var(--text-muted);
		font-weight: 500;
	}
	.kv dd code {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.8rem;
		color: var(--text);
		background: var(--bg-sunken);
		padding: 0 0.3rem;
		border-radius: 3px;
	}
	.quote {
		font-style: italic;
		color: var(--text-muted);
	}
	.verified {
		color: var(--success);
		font-weight: 700;
		margin-left: 0.2rem;
	}
	.chips-sm li {
		font-size: 0.72rem;
		padding: 0.1rem 0.4rem;
	}
	.fig-interpretation {
		margin: 0 0 0.4rem;
		font-size: 0.85rem;
		line-height: 1.5;
		color: var(--text);
	}
	.ocr code {
		white-space: pre-wrap;
		display: block;
		padding: 0.3rem 0.5rem;
		font-size: 0.75rem;
	}
	.author-list {
		margin: 0;
		padding-left: 1.25rem;
		font-size: 0.9rem;
	}
	.author-aff {
		color: var(--text-muted);
	}
	.link {
		all: unset;
		color: var(--accent);
		cursor: pointer;
		font-size: 0.85rem;
		margin-top: 0.25rem;
	}
	.link:hover {
		text-decoration: underline;
	}
	dl {
		margin: 0;
		display: grid;
		grid-template-columns: max-content 1fr;
		gap: 0.25rem 0.75rem;
		font-size: 0.9rem;
	}
	dt {
		color: var(--text-muted);
		font-weight: 500;
	}
	dd {
		margin: 0;
	}
	.muted {
		color: var(--text-faint);
	}
	.chips {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-wrap: wrap;
		gap: 0.4rem;
	}
	.cluster-grid-region {
		max-height: 14rem;
		overflow-y: auto;
		padding-right: 0.3rem;
	}
	.cluster-grid {
		list-style: none;
		padding: 0;
		margin: 0;
		display: grid;
		grid-template-columns: 1fr;
		gap: 0.2rem;
	}
	.cluster-row {
		display: grid;
		grid-template-columns: minmax(8rem, max-content) 2.5rem 1fr;
		gap: 0.5rem;
		align-items: baseline;
		padding: 0.25rem 0.4rem;
		border-bottom: 1px solid var(--border);
		font-size: 0.8rem;
	}
	.cluster-row:last-child {
		border-bottom: none;
	}
	.cluster-cell {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.75rem;
		color: var(--accent);
		background: var(--bg-sunken);
		padding: 0 0.3rem;
		border-radius: 3px;
	}
	.cluster-id {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-faint);
	}
	.cluster-label {
		color: var(--text);
		min-width: 0;
		word-break: break-word;
	}
	.chips li {
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
		padding: 0.2rem 0.5rem;
		border-radius: 999px;
		font-size: 0.8rem;
	}
	.references ol {
		margin: 0;
		padding-left: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		font-size: 0.85rem;
	}
	.references a {
		color: var(--accent);
		word-break: normal;
	}
	.references a:hover {
		text-decoration: underline;
	}
	.ref-doi {
		color: var(--text-muted);
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.78rem;
		margin-left: 0.5rem;
	}
	.detail-footer {
		display: flex;
		gap: 0.75rem;
		align-items: center;
		justify-content: flex-start;
		border-top: 1px solid var(--border);
		padding-top: 0.5rem;
	}
	.back-to-atlas {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.35rem 0.6rem;
		border-radius: 4px;
		border: 1px solid var(--border);
		background: var(--bg-sunken);
	}
	.back-to-atlas:hover {
		background: var(--accent-soft-bg);
		text-decoration: none;
	}
	.cart-icon.detail-cart-icon {
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		border-radius: 4px;
		color: var(--text-faint);
		cursor: pointer;
	}
	.cart-icon.detail-cart-icon:hover {
		background: var(--accent-soft-bg);
		color: var(--accent);
	}
	.cart-icon.detail-cart-icon.in-cart {
		color: var(--accent);
	}
	.cart-icon.detail-cart-icon .check-pip {
		position: absolute;
		bottom: 0px;
		right: 0px;
		background: var(--success);
		color: var(--bg-elevated);
		border-radius: 999px;
		width: 0.9rem;
		height: 0.9rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 0.65rem;
		font-weight: 700;
		line-height: 1;
		border: 1.5px solid var(--bg-elevated);
	}
	.permalink {
		font-size: 0.85rem;
		color: var(--text-muted);
		text-decoration: none;
	}
	.permalink:hover {
		color: var(--accent);
		text-decoration: underline;
	}
	.related h2 {
		display: flex;
		gap: 0.4rem;
		align-items: baseline;
	}
	.related h2 code {
		font-size: 0.7rem;
		text-transform: none;
		letter-spacing: 0;
		font-weight: 400;
	}
	.related-block {
		margin-top: 0.4rem;
	}
	.related-heading {
		margin: 0 0 0.25rem;
		font-size: 0.78rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--text-faint);
		font-weight: 600;
	}
	.related-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}
	.related-link {
		display: flex;
		align-items: stretch;
		border-radius: 4px;
		border: 1px solid transparent;
	}
	.related-link:hover {
		background: var(--bg-sunken);
		border-color: var(--border);
	}
	.related-body {
		all: unset;
		flex: 1;
		min-width: 0;
		cursor: pointer;
		display: grid;
		/* rank · (poster + distance stacked) · title (wraps, full) · cellCount */
		grid-template-columns: 2rem minmax(4.5rem, 6rem) 1fr auto;
		gap: 0.5rem;
		align-items: start;
		padding: 0.4rem 0.5rem;
		font-size: 0.85rem;
		color: var(--text);
	}
	.related-cart {
		all: unset;
		cursor: pointer;
		position: relative;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		flex-shrink: 0;
		color: var(--text-faint);
		border-left: 1px solid var(--border);
	}
	.related-cart:hover {
		background: var(--accent-soft-bg);
		color: var(--accent);
	}
	.related-cart.in-cart {
		color: var(--accent);
	}
	.related-cart .check-pip {
		position: absolute;
		bottom: 0.2rem;
		right: 0.2rem;
		background: var(--success);
		color: var(--bg-elevated);
		border-radius: 999px;
		width: 0.8rem;
		height: 0.8rem;
		display: inline-flex;
		align-items: center;
		justify-content: center;
		font-size: 0.55rem;
		font-weight: 700;
		line-height: 1;
		border: 1.2px solid var(--bg-elevated);
	}
	.related-cart:disabled {
		opacity: 0.3;
		cursor: not-allowed;
	}
	.related-poster-pile {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		align-items: flex-start;
	}
	.related-scroll {
		max-height: 14rem; /* ~5 rows; rest reachable by scroll */
		overflow-y: auto;
		padding-right: 0.3rem;
	}
	.related-cells {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.7rem;
		color: var(--text-faint);
		cursor: help;
	}
	.related-heading .hint {
		font-size: 0.7rem;
		text-transform: none;
		letter-spacing: 0;
		color: var(--text-faint);
		font-weight: 400;
		margin-left: 0.4rem;
	}
	.related-body:disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}
	.related-rank {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-faint);
	}
	.related-poster {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.8rem;
		color: var(--accent);
		font-weight: 600;
	}
	.related-title {
		color: var(--text);
		line-height: 1.3;
		word-break: break-word;
		min-width: 0;
	}
	.related-distance {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-muted);
	}
</style>
