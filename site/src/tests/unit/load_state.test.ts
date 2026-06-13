/**
 * Stage 24 (specs/024-fix-ios-safari-load) — bootstrap load-state machine.
 *
 * Contract: contracts/error-visibility.md (rules 2–4) + data-model.md
 * `AppLoadState`. The bootstrap must reach `ready` on success and
 * `failed(reason)` (non-empty reason) on a rejected critical await — so the
 * render can always leave the spinner (Constitution VI: fail loudly). A
 * non-critical failure (e.g. semantic-worker warm) must NOT force `failed`.
 */

import { describe, expect, it } from 'vitest';
import { describeLoadError, settleCriticalLoad } from '$lib/load/load_state';

describe('describeLoadError', () => {
	it('uses an Error message', () => {
		expect(describeLoadError(new Error('boom'))).toBe('boom');
	});
	it('uses a non-empty string', () => {
		expect(describeLoadError('  network down  ')).toBe('network down');
	});
	it('falls back to a human-readable default for empty / non-error values', () => {
		expect(describeLoadError(new Error(''))).toBe('The atlas data could not be loaded.');
		expect(describeLoadError(undefined)).toBe('The atlas data could not be loaded.');
		expect(describeLoadError({})).toBe('The atlas data could not be loaded.');
	});
});

describe('settleCriticalLoad', () => {
	it('reaches ready when the critical load resolves', async () => {
		const outcome = await settleCriticalLoad(async () => {});
		expect(outcome).toEqual({ ready: true });
	});

	it('reaches failed(reason) when a critical await rejects', async () => {
		const outcome = await settleCriticalLoad(async () => {
			throw new Error('manifest fetch failed');
		});
		expect(outcome.ready).toBe(false);
		if (!outcome.ready) expect(outcome.reason).toBe('manifest fetch failed');
	});

	it('never rejects, so the caller can always leave the loading state', async () => {
		await expect(
			settleCriticalLoad(async () => {
				throw 'kaboom';
			})
		).resolves.toEqual({ ready: false, reason: 'kaboom' });
	});

	it('a non-critical (fire-and-forget) rejection does not affect the critical outcome', async () => {
		// Simulates the semantic-worker warm: kicked off but NOT awaited inside
		// the critical load, so its rejection cannot blank the page.
		const outcome = await settleCriticalLoad(async () => {
			void Promise.reject(new Error('semantic worker unavailable')).catch(() => {});
		});
		expect(outcome).toEqual({ ready: true });
	});
});
