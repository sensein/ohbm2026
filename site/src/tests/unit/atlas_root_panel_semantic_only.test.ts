/**
 * Spec 019 regression — atlas-root cross-conference search must render the
 * same ✨ d= semantic-only badge as /ohbm2026/ ResultList and the
 * NeuroscapeBrowsePanel (consistency directive: "search patterns should
 * re-use the ohbm syntax and be consistent across the sites").
 *
 * The bug: AtlasRootBrowsePanel computed a per-row KNN distance for its
 * semantic-only NeuroScape rows but dropped it (`semanticRows.map((s) =>
 * s.row)`), and the row template rendered no badge. So the root search
 * surfaced semantic hits with no ✨ marker and no distance — unlike every
 * other surface. The fix carries the distance onto the row and renders the
 * shared badge.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import { render, cleanup } from '@testing-library/svelte';
import AtlasRootBrowsePanel from '$lib/components/AtlasRootBrowsePanel.svelte';
import { buildTitleIndex } from '$lib/filter';

type BackdropPoint = {
	pubmed_id: number;
	title: string;
	year: number;
	cluster_id: number;
};

// No single title contains the adjacent phrase "corpus callosum disorders",
// so an exact-phrase query yields zero lexical hits and only the KNN-expanded
// semantic candidate (pubmed 3) should surface — with the badge.
const backdropPoints: BackdropPoint[] = [
	{ pubmed_id: 1, title: 'Corpus callosum development in children', year: 2020, cluster_id: 0 },
	{ pubmed_id: 2, title: 'Agenesis of the corpus callosum', year: 2019, cluster_id: 0 },
	{ pubmed_id: 3, title: 'White matter integrity and behaviour', year: 2021, cluster_id: 1 }
];
const searchIndex = buildTitleIndex(
	backdropPoints,
	(a) => a.pubmed_id,
	(a) => a.title
);
const clustersById = new Map([
	[0, { cluster_id: 0, title: 'Callosal', colour_hex: '#abc' }],
	[1, { cluster_id: 1, title: 'White matter', colour_hex: '#def' }]
]);
const permalinkFor = (kind: 'ohbm2026' | 'neuroscape', id: number) => `/${kind}/abstract/${id}/`;

describe('AtlasRootBrowsePanel — semantic-only badge (cross-site consistency)', () => {
	beforeEach(() => cleanup());

	it('renders the ✨ d= badge for a KNN semantic-only row carrying its distance', () => {
		const { getAllByTestId, queryAllByTestId } = render(AtlasRootBrowsePanel, {
			backdropPoints,
			overlayPoints: [],
			clustersById,
			permalinkFor,
			query: '"corpus callosum disorders"',
			searchIndex,
			semanticHits: new Map<number, number>([[3, 0.123]])
		});
		const rows = getAllByTestId('atlas-root-result-row-neuroscape');
		expect(rows.length).toBe(1);
		const badges = queryAllByTestId('semantic-only-badge');
		expect(badges.length).toBe(1);
		expect(badges[0].textContent).toContain('0.123');
	});

	it('renders no semantic badge when there are no semantic hits', () => {
		const { queryAllByTestId } = render(AtlasRootBrowsePanel, {
			backdropPoints,
			overlayPoints: [],
			clustersById,
			permalinkFor,
			query: '"corpus callosum disorders"',
			searchIndex,
			semanticHits: new Map<number, number>()
		});
		expect(queryAllByTestId('semantic-only-badge').length).toBe(0);
	});
});
