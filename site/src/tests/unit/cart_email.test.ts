import { describe, expect, it } from 'vitest';
import {
	buildMailtoLink,
	buildPlainTextList,
	MAX_MAILTO_LENGTH
} from '$lib/cart_email';
import type { AbstractRecord } from '$lib/shards';

function rec(id: number, poster: string, title: string): AbstractRecord {
	return {
		abstract_id: id,
		poster_id: poster,
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

describe('buildMailtoLink', () => {
	it('produces a mailto: URL with the standard subject', () => {
		const url = buildMailtoLink([rec(1, 'M-AM-101', 'Memory in aging')], new Map(), {
			siteUrl: 'https://example.org/atlas'
		});
		expect(url.startsWith('mailto:?subject=')).toBe(true);
		expect(decodeURIComponent(url)).toContain('My OHBM 2026 abstract list');
	});

	it('embeds each abstract as poster_id + title + permalink', () => {
		const items = [rec(1, 'M-AM-101', 'A'), rec(2, 'M-AM-102', 'B')];
		const url = buildMailtoLink(items, new Map(), { siteUrl: 'https://example.org/atlas' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('M-AM-101');
		expect(body).toContain('M-AM-102');
		expect(body).toContain('https://example.org/atlas/abstract/M-AM-101/');
		expect(body).toContain('https://example.org/atlas/abstract/M-AM-102/');
	});

	it('includes lead author when provided', () => {
		const items = [rec(1, 'M-AM-101', 'Memory in aging')];
		const leads = new Map<number, string>([[1, 'José García']]);
		const url = buildMailtoLink(items, leads, { siteUrl: 'https://example.org' });
		const body = decodeURIComponent(url.split('&body=')[1]);
		expect(body).toContain('— José García');
	});

	it('caps the URL length at the mailto budget and inserts a truncation marker', () => {
		// Manufacture 500 fake abstracts; the cap kicks in long before the end.
		const many = Array.from({ length: 500 }, (_, i) =>
			rec(i, `P${i.toString().padStart(4, '0')}`, `Abstract title number ${i} — a longish placeholder so each line eats bytes`)
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
		expect(body).toContain('(0 items):');
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
		const items = [rec(1, 'M-AM-101', 'Memory in aging')];
		const txt = buildPlainTextList(items, new Map(), 'https://example.org');
		expect(txt).toContain('M-AM-101');
		expect(txt).toContain('Memory in aging');
		expect(txt).toContain('https://example.org/abstract/M-AM-101/');
	});
});
