/**
 * atlas-root / neuroscape selection resolver.
 *
 * Spec 019 follow-up. Turning a clicked (kind, id) — from a result row OR a
 * scatter point — into the inline detail-panel selection. The neuroscape id
 * MUST be looked up against the FULL corpus, not the rendered LOD sample:
 * the result list shows the whole corpus, so a clicked row is usually a
 * point that isn't in the on-screen sample. Looking it up in the sample map
 * returned undefined and the panel silently never opened (the regression
 * this guards).
 */

export type OverlayLite = {
	title: string;
	poster_id: number;
	nearest_cluster_id: number;
};

export type NeuroLite = {
	title: string;
	pubmed_id: number;
	year: number;
	cluster_id: number;
};

export type AtlasSelection =
	| {
			kind: 'ohbm2026';
			title: string;
			poster_id: number;
			nearest_cluster_id: number;
			permalink: string;
	  }
	| {
			kind: 'neuroscape';
			title: string;
			pubmed_id: number;
			year: number;
			cluster_id: number;
			permalink: string;
	  };

/**
 * Resolve a clicked `(kind, id)` to a detail-panel selection, or `null` when
 * the id is found in neither lookup (caller leaves the current panel as-is).
 * `getNeuro` should consult the full corpus first (with a sample fallback),
 * so a result not in the rendered LOD sample still resolves.
 */
export function resolveAtlasSelection(
	kind: 'ohbm2026' | 'neuroscape',
	id: number,
	getOverlay: (id: number) => OverlayLite | undefined,
	getNeuro: (id: number) => NeuroLite | undefined,
	permalinkFor: (kind: 'ohbm2026' | 'neuroscape', id: number) => string
): AtlasSelection | null {
	if (kind === 'ohbm2026') {
		const p = getOverlay(id);
		if (!p) return null;
		return {
			kind: 'ohbm2026',
			title: p.title,
			poster_id: p.poster_id,
			nearest_cluster_id: p.nearest_cluster_id,
			permalink: permalinkFor('ohbm2026', p.poster_id)
		};
	}
	const p = getNeuro(id);
	if (!p) return null;
	return {
		kind: 'neuroscape',
		title: p.title,
		pubmed_id: p.pubmed_id,
		year: p.year,
		cluster_id: p.cluster_id,
		permalink: permalinkFor('neuroscape', p.pubmed_id)
	};
}
