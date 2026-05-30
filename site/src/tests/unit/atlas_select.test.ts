/**
 * Spec 019 follow-up — atlas-root result/point selection resolver.
 *
 * Regression guard for the bug where clicking a result row on atlas-root
 * did nothing: the result list is the FULL corpus, but the click handler
 * resolved the id against the rendered LOD *sample*, so any row not in the
 * sample returned undefined and the detail panel never opened. The
 * resolver must look the neuroscape id up in the full corpus (with a
 * sample fallback) so EVERY result row opens the panel.
 */

import { describe, expect, it } from 'vitest';
import { resolveAtlasSelection } from '$lib/atlas/select';

const permalinkFor = (kind: 'ohbm2026' | 'neuroscape', id: number) => `/${kind}/abstract/${id}/`;

describe('resolveAtlasSelection', () => {
	it('resolves a neuroscape id that is in the FULL corpus but NOT the LOD sample', () => {
		// The regression: full corpus has the point, the rendered sample does not.
		const full = new Map([
			[100, { pubmed_id: 100, title: 'Memory consolidation', year: 2020, cluster_id: 3 }]
		]);
		const sample = new Map(); // empty — point isn't rendered
		const sel = resolveAtlasSelection(
			'neuroscape',
			100,
			() => undefined, // overlay
			(id) => full.get(id) ?? sample.get(id),
			permalinkFor
		);
		expect(sel).not.toBeNull();
		expect(sel).toMatchObject({
			kind: 'neuroscape',
			pubmed_id: 100,
			title: 'Memory consolidation',
			year: 2020,
			cluster_id: 3,
			permalink: '/neuroscape/abstract/100/'
		});
	});

	it('resolves an ohbm2026 id from the overlay', () => {
		const overlay = new Map([
			[201, { title: 'OHBM poster', poster_id: 201, nearest_cluster_id: 5 }]
		]);
		const sel = resolveAtlasSelection(
			'ohbm2026',
			201,
			(id) => overlay.get(id),
			() => undefined,
			permalinkFor
		);
		expect(sel).toMatchObject({
			kind: 'ohbm2026',
			poster_id: 201,
			nearest_cluster_id: 5,
			permalink: '/ohbm2026/abstract/201/'
		});
	});

	it('returns null (no panel change) when the id is found in neither lookup', () => {
		expect(
			resolveAtlasSelection('neuroscape', 999, () => undefined, () => undefined, permalinkFor)
		).toBeNull();
		expect(
			resolveAtlasSelection('ohbm2026', 999, () => undefined, () => undefined, permalinkFor)
		).toBeNull();
	});
});
