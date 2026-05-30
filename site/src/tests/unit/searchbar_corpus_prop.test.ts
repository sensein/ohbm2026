/**
 * Spec 019 / T007 — regression gate for the SearchBar corpus-prop
 * parameterisation (FR-025).
 *
 * The goal: prove the foundational change in T006 (adding `corpus`
 * + `placeholderOverride` props) does NOT alter the existing
 * `/ohbm2026/` SearchBar behaviour. The corpus prop's mechanism is
 * also exercised here against the autocomplete data path so the rest
 * of the spec can rely on it without re-testing.
 *
 * Mounts the real Svelte component via @testing-library/svelte
 * (installed for spec 019 — first Svelte component test in the
 * project).
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import SearchBar from '$lib/components/SearchBar.svelte';
import { filterSuggestions } from '$lib/goto_poster';
import type { AbstractRecord } from '$lib/shards';

const OHBM_PLACEHOLDER =
	'Search… try "phrase", -exclude, word OR word, id:1234 (typos OK)';

describe('SearchBar corpus prop defaults (T007)', () => {
	beforeEach(() => cleanup());

	it('un-parameterised mount preserves the OHBM placeholder byte-identically', () => {
		// Mount without passing corpus or placeholderOverride. The
		// default props MUST produce the pre-spec-019 placeholder.
		const { getByTestId } = render(SearchBar);
		const input = getByTestId('search-input') as HTMLInputElement;
		expect(input.placeholder).toBe(OHBM_PLACEHOLDER);
	});

	it('explicit corpus="ohbm2026" mount produces the same placeholder as the un-parameterised mount', () => {
		const { getByTestId } = render(SearchBar, { corpus: 'ohbm2026' });
		const input = getByTestId('search-input') as HTMLInputElement;
		expect(input.placeholder).toBe(OHBM_PLACEHOLDER);
	});

	it('placeholderOverride prop, when non-null, replaces the OHBM default', () => {
		const customPlaceholder = 'Search across OHBM 2026 + NeuroScape…';
		const { getByTestId } = render(SearchBar, {
			corpus: 'atlas-root',
			placeholderOverride: customPlaceholder
		});
		const input = getByTestId('search-input') as HTMLInputElement;
		expect(input.placeholder).toBe(customPlaceholder);
	});

	it('placeholderOverride=null on a non-ohbm corpus still falls back to the OHBM default', () => {
		// Defensive: a NeuroScape mount that forgets to pass an
		// override MUST NOT silently render a NeuroScape-specific
		// placeholder we never added.
		const { getByTestId } = render(SearchBar, {
			corpus: 'neuroscape',
			placeholderOverride: null
		});
		const input = getByTestId('search-input') as HTMLInputElement;
		expect(input.placeholder).toBe(OHBM_PLACEHOLDER);
	});

	it('the search input test-id is the same across all three corpus values', () => {
		// Cross-corpus stability of `data-testid="search-input"` is what
		// lets existing /ohbm2026/ e2e selectors work unchanged on the
		// new surfaces (contracts/atlas-root-search-ui.md §1).
		for (const corpus of ['ohbm2026', 'neuroscape', 'atlas-root'] as const) {
			cleanup();
			const { getByTestId } = render(SearchBar, { corpus });
			expect(getByTestId('search-input')).toBeTruthy();
		}
	});
});

describe('filterSuggestions is corpus-agnostic (T007 / FR-025 mechanism)', () => {
	// The mechanism that makes the SAME SearchBar component drive all
	// three corpora is that filterSuggestions accepts ANY numeric-keyed
	// Map<number, RecordLike> — the dropdown doesn't care whether the
	// number is a poster_id or a pubmed_id.

	type RecordLike = { poster_id: number; title: string };

	it('autocompletes against an OHBM-shaped poster_id map', () => {
		const ohbmMap = new Map<number, RecordLike>([
			[1234, { poster_id: 1234, title: 'OHBM abstract' }],
			[1235, { poster_id: 1235, title: 'Another OHBM' }]
		]);
		const result = filterSuggestions(
			'123',
			ohbmMap as unknown as Map<number, AbstractRecord>
		);
		expect(result.total).toBe(2);
		expect(result.visible.map((v) => v.posterId).sort()).toEqual([1234, 1235]);
	});

	it('autocompletes against a NeuroScape-shaped pubmed_id map (same code path)', () => {
		const neuroMap = new Map<number, RecordLike>([
			[12345678, { poster_id: 12345678, title: 'PubMed article A' }],
			[87654321, { poster_id: 87654321, title: 'PubMed article B' }]
		]);
		const result = filterSuggestions(
			'12345',
			neuroMap as unknown as Map<number, AbstractRecord>
		);
		expect(result.total).toBe(1);
		expect(result.visible[0].posterId).toBe(12345678);
	});
});
