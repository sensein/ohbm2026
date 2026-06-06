/**
 * T064 — US4 facets unit test.
 *
 * The Playwright spec exercises the live UI; this unit test pins the
 * FR-013 nuance (a facet's own counts are computed against the
 * intersection EXCLUDING that facet's selections) against a 4-abstract
 * fixture so a regression in `passesFilters` would fail in milliseconds.
 *
 * The fixture is deliberately small but covers:
 *   - two distinct values in `keywords` (so toggling one option doesn't
 *     zero the other's count)
 *   - facet groups whose values live on the per-record `facets` block AND
 *     groups whose values live on a top-level field (`accepted_for`)
 */

import { describe, expect, it } from 'vitest';
import {
	clearAllFilters,
	recomputeFacets,
	toggleFilter,
	type ActiveFilters
} from '$lib/facets';
import type { AbstractRecord } from '$lib/shards';

function mkAbstract(
	id: number,
	overrides: Partial<AbstractRecord> = {}
): AbstractRecord {
	return {
		poster_id: id,
		title: `Abstract ${id}`,
		accepted_for: 'Poster',
		sections: { introduction: '', methods: '', results: '', conclusion: '', references: '' },
		topics: { primary: '', primary_subcategory: '', secondary: '', secondary_subcategory: '' },
		methods_checklist: [],
		facets: {
			keywords: [],
			methods: [],
			study_type: [],
			population: [],
			field_strength: [],
			processing_packages: [],
			species: [],
			recording_technology: [],
			brain_regions: [],
			brain_networks: []
		},
		author_ids: [],
		reference_dois: [],
		reference_urls: [],
		...overrides
	};
}

const fixture: AbstractRecord[] = [
	mkAbstract(1, {
		accepted_for: 'Poster',
		facets: {
			keywords: ['Memory'],
			methods: ['Functional MRI'],
			study_type: [],
			population: [],
			field_strength: [],
			processing_packages: [],
			species: ['Human'],
			recording_technology: ['fMRI'],
			brain_regions: [],
			brain_networks: []
		}
	}),
	mkAbstract(2, {
		accepted_for: 'Poster',
		facets: {
			keywords: ['Memory', 'Aging'],
			methods: ['EEG'],
			study_type: [],
			population: [],
			field_strength: [],
			processing_packages: [],
			species: ['Human'],
			recording_technology: ['EEG'],
			brain_regions: [],
			brain_networks: []
		}
	}),
	mkAbstract(3, {
		accepted_for: 'Oral',
		facets: {
			keywords: ['Aging'],
			methods: ['Functional MRI'],
			study_type: [],
			population: [],
			field_strength: [],
			processing_packages: [],
			species: ['Mouse'],
			recording_technology: ['Calcium Imaging'],
			brain_regions: [],
			brain_networks: []
		}
	}),
	mkAbstract(4, {
		accepted_for: 'Oral',
		facets: {
			keywords: ['Memory'],
			methods: ['Functional MRI'],
			study_type: [],
			population: [],
			field_strength: [],
			processing_packages: [],
			species: ['Mouse'],
			recording_technology: ['fMRI'],
			brain_regions: [],
			brain_networks: []
		}
	})
];

const NO_FILTERS: ActiveFilters = new Map();

describe('recomputeFacets', () => {
	it('counts every value across the full corpus when no filters are active', () => {
		const counts = recomputeFacets(fixture, NO_FILTERS, null);
		const kw = counts.get('keywords') ?? [];
		const byValue = Object.fromEntries(kw.map((o) => [o.value, o.count]));
		expect(byValue.Memory).toBe(3);
		expect(byValue.Aging).toBe(2);
		const species = counts.get('species') ?? [];
		expect(Object.fromEntries(species.map((o) => [o.value, o.count]))).toEqual({
			Human: 2,
			Mouse: 2
		});
	});

	it('honours the preFilteredIds intersection', () => {
		// Restrict to abstracts {1, 2} — both have "Human", neither has "Mouse".
		const only12 = new Set([1, 2]);
		const counts = recomputeFacets(fixture, NO_FILTERS, only12);
		const species = Object.fromEntries(
			(counts.get('species') ?? []).map((o) => [o.value, o.count])
		);
		expect(species.Human).toBe(2);
		expect(species.Mouse ?? 0).toBe(0);
	});

	it('FR-013: selecting an option in facet F does NOT zero the other options in F', () => {
		// Tick keywords=Memory. The keywords facet should still show Aging at
		// its FULL count (2) because the keywords facet computes against the
		// intersection EXCLUDING its own selections.
		let filters = toggleFilter(NO_FILTERS, 'keywords', 'Memory');
		const counts = recomputeFacets(fixture, filters, null);
		const kw = Object.fromEntries(
			(counts.get('keywords') ?? []).map((o) => [o.value, o.count])
		);
		expect(kw.Memory).toBe(3); // the ticked option itself stays at its corpus count
		expect(kw.Aging).toBe(2); // and so does the unticked sibling — NOT 1
		// But OTHER facets DO narrow against the keyword filter:
		const accepted = Object.fromEntries(
			(counts.get('accepted_for') ?? []).map((o) => [o.value, o.count])
		);
		// Memory ∈ {1, 2, 4}; among those: 2 Poster, 1 Oral.
		expect(accepted.Poster).toBe(2);
		expect(accepted.Oral).toBe(1);
		// And ticking a second keyword (Aging) UNIONs within the facet, so
		// the keywords facet shouldn't shrink either:
		filters = toggleFilter(filters, 'keywords', 'Aging');
		const counts2 = recomputeFacets(fixture, filters, null);
		const kw2 = Object.fromEntries(
			(counts2.get('keywords') ?? []).map((o) => [o.value, o.count])
		);
		expect(kw2.Memory).toBe(3);
		expect(kw2.Aging).toBe(2);
	});

	it('clearAllFilters returns an empty Map (same shape as initial state)', () => {
		const empty = clearAllFilters();
		expect(empty.size).toBe(0);
		// recomputeFacets with the empty map === recomputeFacets with no filters.
		// Vitest's `toEqual` walks Map<K,V> natively and gives a structural
		// diff on failure — much more useful than the prior `JSON.stringify`
		// stringification (which also fails on undefined/NaN values).
		const a = recomputeFacets(fixture, empty, null);
		const b = recomputeFacets(fixture, NO_FILTERS, null);
		expect(a).toEqual(b);
	});
});

// Stage 23 (spec 023) — the four research-classification dimensions behave as
// peer multi-valued facets: counted across the corpus, OR-membership within a
// dimension, and narrowing other facets when selected.
describe('research-classification dimensions as facets', () => {
	const dims: AbstractRecord[] = [
		mkAbstract(11, {
			facets: {
				keywords: [], methods: [], study_type: [], population: [],
				field_strength: [], processing_packages: [], species: [],
				recording_technology: [], brain_regions: [], brain_networks: [],
				focus: ['Translational', 'Clinical'],
				research_modality: ['Computational'],
				theory_scope: ['Domain Framework'],
				epistemic_basis: ['Data-driven']
			} as AbstractRecord['facets']
		}),
		mkAbstract(12, {
			facets: {
				keywords: [], methods: [], study_type: [], population: [],
				field_strength: [], processing_packages: [], species: [],
				recording_technology: [], brain_regions: [], brain_networks: [],
				focus: ['Fundamental'],
				research_modality: ['Experimental'],
				theory_scope: [],
				epistemic_basis: ['Hypothesis-driven']
			} as AbstractRecord['facets']
		})
	];

	it('counts each dimension option across the corpus', () => {
		const counts = recomputeFacets(dims, NO_FILTERS, null);
		const focus = Object.fromEntries((counts.get('focus') ?? []).map((o) => [o.value, o.count]));
		expect(focus).toEqual({ Translational: 1, Clinical: 1, Fundamental: 1 });
		const eb = Object.fromEntries((counts.get('epistemic_basis') ?? []).map((o) => [o.value, o.count]));
		expect(eb).toEqual({ 'Data-driven': 1, 'Hypothesis-driven': 1 });
	});

	it('filters with OR-membership within a dimension (multi-label match)', () => {
		// Abstract 11 has focus = [Translational, Clinical]; filtering Clinical
		// must include it.
		const filters = toggleFilter(NO_FILTERS, 'focus', 'Clinical');
		const counts = recomputeFacets(dims, filters, null);
		// Other facets narrow to the Clinical-focus subset (just abstract 11):
		const eb = Object.fromEntries((counts.get('epistemic_basis') ?? []).map((o) => [o.value, o.count]));
		expect(eb).toEqual({ 'Data-driven': 1 });
	});
});

// Stage 23 — AI_FACET_KEYS marks exactly the four AI-computed dimensions
// (drives the sidebar ✨ AI pill + collapse-by-default).
describe('AI_FACET_KEYS', () => {
	it('contains exactly the four research-classification dimensions', async () => {
		const { AI_FACET_KEYS } = await import('$lib/facets');
		expect([...AI_FACET_KEYS].sort()).toEqual(
			['epistemic_basis', 'focus', 'research_modality', 'theory_scope']
		);
	});
});
