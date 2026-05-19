import { describe, expect, it } from 'vitest';
import {
	buildMailtoLink,
	buildPlainTextList,
	MAX_MAILTO_LENGTH
} from '$lib/cart_email';
import type { AbstractRecord } from '$lib/shards';

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

	it('caps the URL length at the mailto budget and inserts a truncation marker', () => {
		// Manufacture 500 fake abstracts; the cap kicks in long before the end.
		const many = Array.from({ length: 500 }, (_, i) =>
			rec(i + 1, `Abstract title number ${i} — a longish placeholder so each line eats bytes`)
		);
		const url = buildMailtoLink(many, new Map(), { siteUrl: 'https://example.org/atlas' });
		expect(url.length).toBeLessThanOrEqual(MAX_MAILTO_LENGTH);
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('more items not shown');
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
