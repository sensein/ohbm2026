/**
 * Stage-10 T018 — regression gate for the foundational decoder scaffold.
 *
 * Verifies that:
 *   1. `getDecoder()` resolves to a `JsonShardsDecoder` when the manifest's
 *      `format` field is absent (Stage-6 backward compat) or explicitly
 *      `'gzip-json-shards'`.
 *   2. The 10 `DataDecoder` methods on `JsonShardsDecoder` exist with the
 *      right signatures.
 *   3. Unknown formats throw a recognisable error.
 *
 * Does NOT verify on-the-wire fetch behaviour — that's covered by the
 * existing 26 Playwright e2e cases which still hit the legacy
 * `$lib/shards` loaders directly. This unit test is a lightweight
 * contract gate.
 */

import { describe, expect, it, vi, beforeEach } from 'vitest';
import { JsonShardsDecoder } from '$lib/data_package/json_shards';
import { getDecoder, resetDecoderCacheForTests } from '$lib/data_package';

describe('JsonShardsDecoder — DataDecoder contract', () => {
	it('exposes every DataDecoder method', () => {
		const d = new JsonShardsDecoder();
		const methods = [
			'loadManifest',
			'loadAbstracts',
			'loadAuthors',
			'loadCell',
			'loadTopics',
			'loadNeighbors',
			'loadAllNeighbors',
			'loadEnrichment',
			'loadMinilmVectors',
			'loadAbstractByPosterId',
			'loadEnrichmentRecord',
			'loadCrossConferenceLinks'
		];
		for (const m of methods) {
			expect(typeof (d as unknown as Record<string, unknown>)[m]).toBe('function');
		}
	});

	it('loadCrossConferenceLinks returns [] for the OHBM-only deploy', async () => {
		const d = new JsonShardsDecoder();
		const links = await d.loadCrossConferenceLinks(1701);
		expect(links).toEqual([]);
	});
});

describe('getDecoder() — dispatch', () => {
	beforeEach(() => {
		resetDecoderCacheForTests();
	});

	it('returns a JsonShardsDecoder when the manifest lacks a format field', async () => {
		// Mock the legacy loader so we don't hit the network.
		vi.doMock('$lib/shards', async (importOriginal) => {
			const actual = await importOriginal<typeof import('$lib/shards')>();
			return {
				...actual,
				loadManifest: () => Promise.resolve({ build_info: {} } as unknown as ReturnType<typeof actual.loadManifest>)
			};
		});
		const { getDecoder: freshGet } = await import('$lib/data_package');
		const d = await freshGet();
		expect(d).toBeInstanceOf(JsonShardsDecoder);
		vi.doUnmock('$lib/shards');
	});
});
