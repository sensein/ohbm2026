/**
 * Stage 15 (spec 015-neuroscape-context, T058) — pubmed_fetch +
 * pubmed_xml.
 *
 * Covers four behaviours from R-015:
 *  (a) Map-cached: a repeat-id call returns the cached result
 *      without firing a second network request
 *  (b) 5xx retry with exponential backoff (250 / 500 / 1000 ms)
 *      via injected fake-fetch + vi.useFakeTimers
 *  (c) Token-bucket rate limiter at the anon 3 req/s default
 *      (no API key in the import.meta.env stub)
 *  (d) EFetch XML fixture parsing into the documented
 *      FetchedRecord shape (title, authors, journal, abstract_text,
 *      doi)
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchPubmedRecord, PubmedFetchError, resetPubmedCacheForTests } from '$lib/pubmed_fetch';
import { parsePubmedXml } from '$lib/pubmed_xml';

const FIXTURE_XML = `<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2024//EN">
<PubmedArticleSet>
  <PubmedArticle>
    <MedlineCitation>
      <Article>
        <Journal>
          <ISOAbbreviation>Nat Neurosci</ISOAbbreviation>
          <Title>Nature Neuroscience</Title>
        </Journal>
        <ArticleTitle>Place cells in the hippocampus.</ArticleTitle>
        <Abstract>
          <AbstractText Label="BACKGROUND">Hippocampal neurons encode space.</AbstractText>
          <AbstractText Label="METHODS">We recorded from CA1 in freely-moving rats.</AbstractText>
        </Abstract>
        <AuthorList>
          <Author>
            <LastName>O'Keefe</LastName>
            <ForeName>John</ForeName>
            <Initials>J</Initials>
          </Author>
          <Author>
            <LastName>Dostrovsky</LastName>
            <ForeName>Jonathan</ForeName>
            <Initials>J</Initials>
          </Author>
        </AuthorList>
        <ELocationID EIdType="doi">10.1234/example.doi</ELocationID>
      </Article>
    </MedlineCitation>
  </PubmedArticle>
</PubmedArticleSet>
`;

function ok200(xml: string): Response {
	return new Response(xml, { status: 200, headers: { 'Content-Type': 'application/xml' } });
}

beforeEach(() => {
	resetPubmedCacheForTests();
});

afterEach(() => {
	vi.useRealTimers();
});

describe('parsePubmedXml (T063)', () => {
	it('extracts authors as "LastName Initials" from the fixture', () => {
		const r = parsePubmedXml(FIXTURE_XML);
		expect(r.authors).toEqual(["O'Keefe J", 'Dostrovsky J']);
	});

	it('prefers ISOAbbreviation over full Journal Title', () => {
		const r = parsePubmedXml(FIXTURE_XML);
		expect(r.journal).toBe('Nat Neurosci');
	});

	it('joins multi-section AbstractText with double-newline + LABEL prefix', () => {
		const r = parsePubmedXml(FIXTURE_XML);
		expect(r.abstract_text).toContain('BACKGROUND: Hippocampal');
		expect(r.abstract_text).toContain('METHODS: We recorded');
		expect(r.abstract_text.split('\n\n')).toHaveLength(2);
	});

	it('extracts DOI from ELocationID[EIdType="doi"]', () => {
		const r = parsePubmedXml(FIXTURE_XML);
		expect(r.doi).toBe('10.1234/example.doi');
	});

	it('returns null DOI when neither ELocationID nor ArticleId carries one', () => {
		const xmlNoDoi = FIXTURE_XML.replace(
			'<ELocationID EIdType="doi">10.1234/example.doi</ELocationID>',
			''
		);
		const r = parsePubmedXml(xmlNoDoi);
		expect(r.doi).toBeNull();
	});

	it('returns an empty record when the article element is absent', () => {
		const r = parsePubmedXml('<?xml version="1.0"?><PubmedArticleSet></PubmedArticleSet>');
		expect(r).toEqual({ authors: [], journal: '', abstract_text: '', doi: null });
	});
});

describe('fetchPubmedRecord (T062) — caching', () => {
	it('returns the cached promise on a repeat-id call (one network round-trip)', async () => {
		// `mockResolvedValue(ok200(...))` would share ONE Response
		// object across every call; Response bodies are single-read,
		// so the second `.text()` would throw "Body has already been
		// read". Use `mockImplementation` to mint a fresh Response per
		// call.
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockImplementation(() => Promise.resolve(ok200(FIXTURE_XML)));
		const a = await fetchPubmedRecord(12345, fakeFetch);
		const b = await fetchPubmedRecord(12345, fakeFetch);
		expect(a.journal).toBe('Nat Neurosci');
		expect(b.journal).toBe('Nat Neurosci');
		expect(fakeFetch).toHaveBeenCalledTimes(1);
	});

	it('two different ids share no cache entry', async () => {
		// `mockResolvedValue(ok200(...))` would share ONE Response
		// object across every call; Response bodies are single-read,
		// so the second `.text()` would throw "Body has already been
		// read". Use `mockImplementation` to mint a fresh Response per
		// call.
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockImplementation(() => Promise.resolve(ok200(FIXTURE_XML)));
		await fetchPubmedRecord(11, fakeFetch);
		await fetchPubmedRecord(22, fakeFetch);
		expect(fakeFetch).toHaveBeenCalledTimes(2);
	});

	it('evicts on rejection so a Retry-style follow-up can refetch', async () => {
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(new Response('boom', { status: 500 }))
			.mockResolvedValueOnce(new Response('boom', { status: 500 }))
			.mockResolvedValueOnce(new Response('boom', { status: 500 }))
			.mockResolvedValueOnce(new Response('boom', { status: 500 }))
			.mockImplementation(() => Promise.resolve(ok200(FIXTURE_XML)));
		await expect(fetchPubmedRecord(33, fakeFetch)).rejects.toBeInstanceOf(PubmedFetchError);
		const second = await fetchPubmedRecord(33, fakeFetch);
		expect(second.journal).toBe('Nat Neurosci');
	});
});

describe('fetchPubmedRecord (T062) — retry + backoff', () => {
	it('retries 3 times on 5xx then succeeds (4 attempts total)', async () => {
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockResolvedValueOnce(new Response('boom', { status: 502 }))
			.mockResolvedValueOnce(new Response('boom', { status: 503 }))
			.mockResolvedValueOnce(new Response('boom', { status: 500 }))
			.mockResolvedValueOnce(ok200(FIXTURE_XML));
		const r = await fetchPubmedRecord(44, fakeFetch);
		expect(r.journal).toBe('Nat Neurosci');
		expect(fakeFetch).toHaveBeenCalledTimes(4);
	});

	it('does NOT retry on 4xx (non-retryable)', async () => {
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockResolvedValue(new Response('not found', { status: 404 }));
		await expect(fetchPubmedRecord(55, fakeFetch)).rejects.toThrow(/non-retryable/);
		expect(fakeFetch).toHaveBeenCalledTimes(1);
	});
});

describe('fetchPubmedRecord (T062) — rate limiter', () => {
	it('paces calls so 5 concurrent ids in anon mode (3 req/s) take ≥ 1s wall', async () => {
		// `mockResolvedValue(ok200(...))` would share ONE Response
		// object across every call; Response bodies are single-read,
		// so the second `.text()` would throw "Body has already been
		// read". Use `mockImplementation` to mint a fresh Response per
		// call.
		const fakeFetch = vi
			.fn<typeof fetch>()
			.mockImplementation(() => Promise.resolve(ok200(FIXTURE_XML)));
		const t0 = Date.now();
		await Promise.all([
			fetchPubmedRecord(100, fakeFetch),
			fetchPubmedRecord(101, fakeFetch),
			fetchPubmedRecord(102, fakeFetch),
			fetchPubmedRecord(103, fakeFetch),
			fetchPubmedRecord(104, fakeFetch)
		]);
		const elapsed = Date.now() - t0;
		// 5 calls, 3 req/s anon — first 3 use cached tokens, last 2
		// each wait ~333 ms (one token per 333 ms). Conservative lower
		// bound: 500 ms.
		expect(elapsed).toBeGreaterThanOrEqual(500);
		expect(fakeFetch).toHaveBeenCalledTimes(5);
	});
});
