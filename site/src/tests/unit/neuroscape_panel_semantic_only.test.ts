/**
 * Spec 019 regression — a phrase query with ZERO lexical matches must
 * still surface its KNN-expanded semantic-only rows in the NeuroScape
 * browse panel.
 *
 * The bug: NeuroscapeBrowsePanel.filtered short-circuited with `return []`
 * the moment `searchTitleIndex` found no adjacent-token title for an exact
 * phrase like "corpus callosum disorders". That early return ran BEFORE the
 * semantic-augmentation block, so the (valid, non-empty) `semanticHits` map
 * was discarded — the user saw 0 results for a quoted multi-word query even
 * though the KNN fallback had produced hits. The fix lets a zero-row lexical
 * result fall through to the semantic merge.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import NeuroscapeBrowsePanel from '$lib/components/NeuroscapeBrowsePanel.svelte';
import { buildTitleIndex } from '$lib/filter';

type Article = {
	pubmed_id: number;
	title: string;
	year: number;
	cluster_id: number;
};

// No single title contains the adjacent phrase "corpus callosum disorders",
// so an exact-phrase query yields zero lexical hits.
const articles: Article[] = [
	{ pubmed_id: 1, title: 'Corpus callosum development in children', year: 2020, cluster_id: 0 },
	{ pubmed_id: 2, title: 'Agenesis of the corpus callosum', year: 2019, cluster_id: 0 },
	{ pubmed_id: 3, title: 'White matter integrity and behaviour', year: 2021, cluster_id: 1 }
];
const searchIndex = buildTitleIndex(
	articles,
	(a) => a.pubmed_id,
	(a) => a.title
);
const clustersById = new Map([
	[0, { cluster_id: 0, title: 'Callosal', colour_hex: '#abc' }],
	[1, { cluster_id: 1, title: 'White matter', colour_hex: '#def' }]
]);

describe('NeuroscapeBrowsePanel — semantic-only survives zero lexical hits', () => {
	beforeEach(() => cleanup());

	it('renders KNN semantic rows for an exact phrase with no adjacent-token title', () => {
		const { getAllByTestId, queryAllByTestId } = render(NeuroscapeBrowsePanel, {
			articles,
			clustersById,
			query: '"corpus callosum disorders"',
			searchIndex,
			// KNN fallback surfaced article 3 as a semantic-only candidate.
			semanticHits: new Map<number, number>([[3, 0.12]])
		});
		const rows = getAllByTestId('neuroscape-result-row');
		expect(rows.length).toBe(1);
		expect(queryAllByTestId('semantic-only-badge').length).toBe(1);
	});

	it('still returns empty when BOTH lexical and semantic are empty', () => {
		const { queryAllByTestId } = render(NeuroscapeBrowsePanel, {
			articles,
			clustersById,
			query: '"corpus callosum disorders"',
			searchIndex,
			semanticHits: new Map<number, number>()
		});
		expect(queryAllByTestId('neuroscape-result-row').length).toBe(0);
	});
});
