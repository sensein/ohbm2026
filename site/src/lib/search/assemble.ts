/**
 * Shared, N-corpus search-result assembly.
 *
 * One algorithm for every surface (ohbm2026 / atlas-root / neuroscape), so
 * search behaves identically and adding a new site is just another
 * `CorpusSource` in the array — not a new hand-rolled merge. atlas-root passes
 * two sources today (NeuroScape backdrop + OHBM overlay); more conferences slot
 * in the same way. The single-corpus surfaces pass one source.
 *
 * The shape is fixed across surfaces:
 *   1. `id:N` short-circuit — exact-id rows across every source, in source order.
 *   2. lexical pass — each source's title index (shared operators + typo
 *      tolerance), merged and ordered by a per-source numeric sort-key tuple
 *      (compared lexicographically), so each corpus keeps its own tiebreak
 *      while still interleaving by exactness.
 *   3. semantic-only append — ranker/KNN hits NOT already in the lexical set,
 *      ordered by ascending distance, appended after the lexical rows (they get
 *      the ✨ badge in the row template).
 *
 * Scoring is parameterised (sort-key callbacks) so this never changes any
 * surface's existing ranking; only the duplicated control flow is removed.
 */
import { searchTitleIndex, type InvertedIndex } from '$lib/filter';
import { parseIdOperator } from '$lib/goto_poster';

export interface CorpusSource<Row> {
	/** Stable corpus key (e.g. 'neuroscape', 'ohbm2026'); namespaces ids so the
	 *  same numeric id in two corpora can't collide in the lexical-dedup set. */
	kind: string;
	/** Title search index over this source's facet-filtered set (or null). */
	index: InvertedIndex | null;
	/** Whether an id is in this source's current facet-filtered set. */
	has: (id: number) => boolean;
	/** Every id in the facet-filtered set — used only for the empty query. */
	allIds: () => Iterable<number>;
	/** Build the render row for an id (null → skip, e.g. id no longer resident).
	 *  `semanticDistance` is non-null only for semantic-only rows. */
	toRow: (id: number, semanticDistance: number | null) => Row | null;
	/** Ascending sort-key tuple for a lexical hit (compared lexicographically
	 *  across all sources). e.g. neuroscape `[-exact, -year, pmid]`. */
	lexicalSortKey: (id: number, exact: number) => number[];
	/** Ascending sort-key tuple for the empty-query (all rows) case. */
	emptySortKey: (id: number) => number[];
	/** id → semantic distance (lower = better) for semantic-only candidates. */
	semanticHits?: Map<number, number>;
}

function cmpKeys(a: number[], b: number[]): number {
	const n = Math.max(a.length, b.length);
	for (let i = 0; i < n; i++) {
		const d = (a[i] ?? 0) - (b[i] ?? 0);
		if (d !== 0) return d;
	}
	return 0;
}

export function assembleResults<Row>(sources: CorpusSource<Row>[], query: string): Row[] {
	const trimmed = (query ?? '').trim();

	// 1. id:N short-circuit — exact-id rows across every source, source order.
	// Uses the shared `parseIdOperator` (the `id:` grammar the OHBM SearchBar +
	// goto-poster use) so id-lookup behaves identically on every surface. A
	// non-numeric / empty payload (`id:foo`, `id:`) yields no rows.
	const idPayload = parseIdOperator(trimmed);
	if (idPayload !== null) {
		const wanted = Number(idPayload);
		if (idPayload.trim() === '' || !Number.isFinite(wanted)) return [];
		const rows: Row[] = [];
		for (const s of sources) {
			if (!s.has(wanted)) continue;
			const r = s.toRow(wanted, null);
			if (r) rows.push(r);
		}
		return rows;
	}

	// 2. lexical pass (or, for the empty query, every row).
	type Scored = { id: number; src: CorpusSource<Row>; key: number[] };
	const scored: Scored[] = [];
	for (const s of sources) {
		if (!trimmed) {
			for (const id of s.allIds()) scored.push({ id, src: s, key: s.emptySortKey(id) });
			continue;
		}
		const res = s.index ? searchTitleIndex(s.index, trimmed) : null;
		if (!res) continue;
		for (const id of res.ids) {
			if (!s.has(id)) continue;
			const exact = res.exactness.get(id) ?? 0;
			scored.push({ id, src: s, key: s.lexicalSortKey(id, exact) });
		}
	}
	scored.sort((a, b) => cmpKeys(a.key, b.key));

	// Only track the lexical id-set when a semantic pass will actually need it
	// (some source has hits) — avoids allocating a Set over the whole corpus on
	// the empty query / no-semantic surfaces.
	const needDedup = sources.some((s) => s.semanticHits && s.semanticHits.size > 0);
	const lexicalRows: Row[] = [];
	const lexicalKeys = needDedup ? new Set<string>() : null;
	for (const e of scored) {
		const r = e.src.toRow(e.id, null);
		if (!r) continue;
		lexicalRows.push(r);
		lexicalKeys?.add(`${e.src.kind}:${e.id}`);
	}

	// 3. semantic-only append — ordered by ascending distance across sources.
	const semantic: Array<{ row: Row; d: number }> = [];
	for (const s of sources) {
		if (!s.semanticHits || s.semanticHits.size === 0) continue;
		for (const [id, d] of s.semanticHits) {
			if (lexicalKeys?.has(`${s.kind}:${id}`)) continue;
			if (!s.has(id)) continue;
			const r = s.toRow(id, d);
			if (r) semantic.push({ row: r, d });
		}
	}
	semantic.sort((a, b) => a.d - b.d);

	return [...lexicalRows, ...semantic.map((s) => s.row)];
}
