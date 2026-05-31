import { describe, expect, it } from 'vitest';
import {
	buildMailtoLink,
	buildPlainTextList,
	buildUnifiedMailtoLink,
	buildUnifiedPlainTextList,
	buildUnifiedCartRestoreUrl,
	MAX_MAILTO_LENGTH,
	type UnifiedCartRow
} from '$lib/cart_email';
import type { AbstractRecord } from '$lib/shards';

function urow(kind: 'ohbm2026' | 'neuroscape', id: number, title = 'Untitled'): UnifiedCartRow {
	return { kind, id, title, subline: '' };
}

function rec(posterId: number, title: string): AbstractRecord {
	return {
		poster_id: posterId,
		title,
		accepted_for: 'Poster',
		sections: { introduction: '', methods: '', results: '', conclusion: '', references: '' },
		topics: { primary: '', primary_subcategory: '', secondary: '', secondary_subcategory: '' },
		methods_checklist: [],
		facets: {},
		author_ids: [],
		reference_dois: [],
		reference_urls: [],
		reference_titles: []
	};
}

function pad(id: number): string {
	return String(id).padStart(4, '0');
}

describe('buildMailtoLink', () => {
	it('produces a mailto: URL with the standard subject', () => {
		const url = buildMailtoLink([rec(101, 'Memory in aging')], new Map(), {
			siteUrl: 'https://example.org/atlas'
		});
		expect(url.startsWith('mailto:?subject=')).toBe(true);
		expect(decodeURIComponent(url)).toContain('My OHBM 2026 abstract list');
	});

	it('embeds each abstract as poster_id + title + permalink', () => {
		const items = [rec(101, 'A'), rec(102, 'B')];
		const url = buildMailtoLink(items, new Map(), { siteUrl: 'https://example.org/atlas' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain(pad(101));
		expect(body).toContain(pad(102));
		expect(body).toContain(`https://example.org/atlas/abstract/${pad(101)}/`);
		expect(body).toContain(`https://example.org/atlas/abstract/${pad(102)}/`);
	});

	it('includes lead author when provided', () => {
		const items = [rec(101, 'Memory in aging')];
		const leads = new Map<number, string>([[101, 'José García']]);
		const url = buildMailtoLink(items, leads, { siteUrl: 'https://example.org' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('— José García');
	});

	it('falls back to compact body when full body would exceed the URL budget', () => {
		// 500 abstracts → full body (with item-list and 500-id restore
		// URL) would blow past MAX_MAILTO_LENGTH; expect compact form.
		const many = Array.from({ length: 500 }, (_, i) =>
			rec(i + 1, `Abstract title number ${i} — a longish placeholder so each line eats bytes`)
		);
		const url = buildMailtoLink(many, new Map(), { siteUrl: 'https://example.org/atlas' });
		// Total URL stays under the budget.
		expect(url.length).toBeLessThanOrEqual(MAX_MAILTO_LENGTH);
		const body = decodeURIComponent(url.split('&body=')[1]);
		// Restore URL is still present.
		expect(body).toMatch(/\?cart=\d{4}(,\d{4})+/);
		// Per-item list is NOT — compact body, no "1. [0001] Title" lines.
		expect(body).not.toMatch(/^1\. \[/m);
		// Compact body steers the user to the Copy button.
		expect(body).toContain('Copy');
	});

	it('includes the full item list when the cart fits in the URL budget', () => {
		// 20-item cart with short titles fits comfortably inside
		// MAX_MAILTO_LENGTH so the body retains every entry.
		const small = Array.from({ length: 20 }, (_, i) => rec(i + 1, `Title ${i}`));
		const url = buildMailtoLink(small, new Map(), { siteUrl: 'https://example.org' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).not.toContain('more items not shown');
		// First and last item numbers both present.
		expect(body).toMatch(/^1\. \[/m);
		expect(body).toMatch(/^20\. \[/m);
		expect(url.length).toBeLessThanOrEqual(MAX_MAILTO_LENGTH);
	});

	it('handles an empty cart gracefully', () => {
		const url = buildMailtoLink([], new Map(), { siteUrl: 'https://example.org' });
		expect(url.startsWith('mailto:?')).toBe(true);
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('(0 items)');
	});

	it('puts each item on its own numbered block with a labelled Open link', () => {
		const items = [rec(101, 'Memory in aging'), rec(102, 'Vision')];
		const url = buildMailtoLink(items, new Map(), { siteUrl: 'https://example.org/atlas' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain(`1. [${pad(101)}] Memory in aging`);
		expect(body).toContain(`2. [${pad(102)}] Vision`);
		expect(body).toContain(`→ Open: https://example.org/atlas/abstract/${pad(101)}/`);
		expect(body).toContain(`→ Open: https://example.org/atlas/abstract/${pad(102)}/`);
		expect(body).toContain('Browse the rest at https://example.org/atlas/');
	});

	it('respects custom subject', () => {
		const url = buildMailtoLink([], new Map(), {
			siteUrl: 'https://example.org',
			subject: 'Hand-picked for you'
		});
		expect(url).toContain('subject=Hand-picked%20for%20you');
	});
});

describe('buildPlainTextList', () => {
	it('produces a clipboard-friendly plain-text rendering', () => {
		const items = [rec(101, 'Memory in aging')];
		const txt = buildPlainTextList(items, new Map(), 'https://example.org');
		expect(txt).toContain(pad(101));
		expect(txt).toContain('Memory in aging');
		expect(txt).toContain(`https://example.org/abstract/${pad(101)}/`);
	});
});

describe('buildUnifiedCartRestoreUrl — grouped, extensible kind:id format', () => {
	it('groups ids by kind, one prefix per kind, groups joined by +', () => {
		const url = buildUnifiedCartRestoreUrl(
			[
				urow('ohbm2026', 42, 'a'),
				urow('neuroscape', 123, 'b'),
				urow('ohbm2026', 101, 'c'),
				urow('neuroscape', 456, 'd')
			],
			'https://example.org/'
		);
		// Each kind appears ONCE (not repeated per item); ids comma-joined.
		expect(url).toBe('https://example.org/?cart=ohbm2026:42,101+neuroscape:123,456');
	});

	it('emits a single group when the cart is one kind', () => {
		expect(buildUnifiedCartRestoreUrl([urow('neuroscape', 9)], 'https://x.org')).toBe(
			'https://x.org/?cart=neuroscape:9'
		);
	});

	it('deduplicates repeated ids per kind so the URL stays compact', () => {
		const url = buildUnifiedCartRestoreUrl(
			[urow('ohbm2026', 42), urow('ohbm2026', 42), urow('neuroscape', 7), urow('ohbm2026', 101)],
			'https://x.org'
		);
		expect(url).toBe('https://x.org/?cart=ohbm2026:42,101+neuroscape:7');
	});

	it('drops non-positive / non-finite ids and returns the bare root for an empty cart', () => {
		expect(buildUnifiedCartRestoreUrl([], 'https://x.org/')).toBe('https://x.org/');
		expect(
			buildUnifiedCartRestoreUrl([urow('ohbm2026', 0), urow('ohbm2026', 7)], 'https://x.org')
		).toBe('https://x.org/?cart=ohbm2026:7');
	});
});

describe('buildUnifiedMailtoLink — restore link + greedy tail-trim', () => {
	function urows(kind: 'ohbm2026' | 'neuroscape', n: number, base = 100): UnifiedCartRow[] {
		return Array.from({ length: n }, (_, i) =>
			urow(kind, base + i, `A reasonably long neuroscience abstract title number ${i} about memory`)
		);
	}

	it('always embeds the grouped ★ restore link (recoverable even when trimmed)', () => {
		const big = urows('neuroscape', 400);
		const url = buildUnifiedMailtoLink(big, 'https://example.org');
		expect(url.length).toBeLessThanOrEqual(MAX_MAILTO_LENGTH);
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('restores the cart');
		expect(body).toMatch(/\?cart=neuroscape:\d+(,\d+)+/);
		// Body was trimmed but NOT emptied of the restore affordance.
		expect(body).toContain('more item');
	});

	it('keeps as many per-item rows as fit, trimming from the tail (not drop-all)', () => {
		const big = urows('neuroscape', 400);
		const url = buildUnifiedMailtoLink(big, 'https://example.org');
		const body = decodeURIComponent(url.split('&body=')[1]);
		// At least the first item survives (greedy-fit), unlike the old
		// all-or-nothing compact form.
		expect(body).toContain('1. [NeuroScape · PMID 100]');
		expect(body).toContain('→ Open: https://example.org/neuroscape/abstract/100/');
	});

	it('includes the full list (no "more" marker) when it fits the budget', () => {
		const small = [urow('ohbm2026', 42, 'Memory'), urow('neuroscape', 123, 'Vision')];
		const url = buildUnifiedMailtoLink(small, 'https://example.org');
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).not.toContain('more item');
		expect(body).toContain('1. [OHBM 2026 · 0042] Memory');
		expect(body).toContain('2. [NeuroScape · PMID 123] Vision');
		expect(body).toContain('?cart=ohbm2026:42+neuroscape:123');
	});
});

describe('buildUnifiedPlainTextList', () => {
	it('leads with the restore link and lists every item', () => {
		const txt = buildUnifiedPlainTextList(
			[urow('ohbm2026', 42, 'Memory'), urow('neuroscape', 123, 'Vision')],
			'https://example.org'
		);
		expect(txt).toContain('?cart=ohbm2026:42+neuroscape:123');
		expect(txt).toContain('1. [OHBM 2026 · 0042] Memory');
		expect(txt).toContain('2. [NeuroScape · PMID 123] Vision');
		expect(txt).toContain('Browse the atlas at https://example.org/');
	});
});
