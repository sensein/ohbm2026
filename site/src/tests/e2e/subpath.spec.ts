/**
 * Spec 009 — Conference subpath rework e2e (T015 / T017 / T019 / T021).
 *
 * Verifies that every OHBM 2026 surface (home, About, abstract permalink)
 * lives under `/ohbm2026/`, that the root URL bounces there, that a
 * fresh-tab direct-load of a deep link inside the subpath renders the
 * detail panel (via the `?spa=` handoff in `+layout.svelte`), and that
 * the deploy SHA stays visible on every route.
 *
 * Skipped when the local data package isn't built (the SvelteKit shell
 * renders a placeholder under those conditions, and no result cards exist
 * to drive the deep-link assertions).
 */

import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';
// The root-redirect island lives at the *origin* root of the deploy
// (CNAME root `/`, or local-preview `127.0.0.1:4173/`). When the suite
// is pointed at a per-PR or sandbox URL like `<origin>/pr-N/`, the
// redirect island sits at `<origin>/pr-N/` — but `browser.newContext`
// with a hardcoded localhost baseURL can't reach it. Those three tests
// need the local preview harness; skip when running against a remote URL.
const REMOTE_BASE_URL = process.env.PLAYWRIGHT_BASE_URL;

test.describe('US1 — subpath canonical', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('home renders at /ohbm2026/', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('result-count')).toBeVisible();
		// Sanity: the URL bar reflects the subpath canonical location.
		expect(page.url()).toMatch(/\/ohbm2026\/?$/);
	});

	test('about renders at /ohbm2026/about/', async ({ page }) => {
		await page.goto('./about/');
		// The About page header is the first <h1> on the route; identify by
		// content to avoid coupling to a brittle testid.
		await expect(page.locator('main h1').first()).toBeVisible({ timeout: 5000 });
		expect(page.url()).toMatch(/\/ohbm2026\/about\/?$/);
	});

	test('abstract permalink renders at /ohbm2026/abstract/<id>/', async ({ page }) => {
		// Pick a known poster_id from the home grid, then direct-navigate to
		// its permalink via the subpath-scoped route.
		await page.goto('./');
		const firstCard = page.getByTestId('result-card').first();
		await firstCard.waitFor({ timeout: 10_000 });
		const posterId = await firstCard.getAttribute('data-poster-id');
		expect(posterId).toBeTruthy();
		await page.goto(`./abstract/${encodeURIComponent(posterId!)}/`);
		await expect(page.getByTestId('detail-poster-id')).toBeVisible({ timeout: 15_000 });
		const headerPosterId = (await page.getByTestId('detail-poster-id').textContent())?.trim();
		expect(headerPosterId).toBe(posterId);
		expect(page.url()).toMatch(/\/ohbm2026\/abstract\/[^/]+\/?$/);
	});
});

test.describe('SC-106 — build_info short SHA visible under the subpath', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('short SHA matches across home / about / permalink', async ({ page }) => {
		// FR-110 / SC-106: the deploy-SHA contract widens from Stage 6's
		// "every route" to "every route under /ohbm2026/". The actual SHA
		// is whatever the local build baked in; we don't assert its
		// content — only that the testid renders a hex string AND is
		// consistent across the three routes.
		await page.goto('./');
		await page.getByTestId('build-info-short-sha').first().waitFor();
		const home = (await page.getByTestId('build-info-short-sha').first().textContent())?.trim();
		expect(home).toMatch(/^[0-9a-f]{7,12}$/);

		await page.goto('./about/');
		await page.getByTestId('build-info-short-sha').first().waitFor();
		const about = (await page.getByTestId('build-info-short-sha').first().textContent())?.trim();
		expect(about).toBe(home);

		// Sample a real poster_id to test the permalink route's SHA too.
		await page.goto('./');
		const card = page.getByTestId('result-card').first();
		await card.waitFor({ timeout: 10_000 });
		const posterId = await card.getAttribute('data-poster-id');
		if (posterId) {
			await page.goto(`./abstract/${encodeURIComponent(posterId)}/`);
			await page.getByTestId('build-info-short-sha').first().waitFor();
			const permalink = (
				await page.getByTestId('build-info-short-sha').first().textContent()
			)?.trim();
			expect(permalink).toBe(home);
		}
	});
});

test.describe('US2 — direct-load deep-link', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('incognito direct-load renders the detail panel for the expected poster', async ({
		browser
	}) => {
		// Fresh context (no cookies, no storage) mimics an incognito tab
		// that's never seen the site before. The path under test goes
		// through the SPA-redirect handoff: gh-pages serves /ohbm2026/404.html
		// (the SvelteKit fallback), `+layout.svelte` reads the URL, and
		// renders the abstract/[id] route. We sample a known poster_id from
		// the home grid (also via a fresh context) so the test stays
		// data-package-version-agnostic.
		const ctx = await browser.newContext();
		const probe = await ctx.newPage();
		await probe.goto('./');
		const card = probe.getByTestId('result-card').first();
		await card.waitFor({ timeout: 10_000 });
		const posterId = await card.getAttribute('data-poster-id');
		await probe.close();
		expect(posterId).toBeTruthy();

		const fresh = await ctx.newPage();
		await fresh.evaluate(() => {
			try {
				localStorage.clear();
				sessionStorage.clear();
			} catch (e) {
				/* ignore */
			}
		}).catch(() => null);
		await fresh.goto(`./abstract/${encodeURIComponent(posterId!)}/`);
		await expect(fresh.getByTestId('detail-poster-id')).toBeVisible({ timeout: 5000 });
		const rendered = (await fresh.getByTestId('detail-poster-id').textContent())?.trim();
		expect(rendered).toBe(posterId);
		await ctx.close();
	});

	test('refresh keeps URL + panel', async ({ page }) => {
		await page.goto('./');
		const card = page.getByTestId('result-card').first();
		await card.waitFor({ timeout: 10_000 });
		const posterId = await card.getAttribute('data-poster-id');
		expect(posterId).toBeTruthy();
		await page.goto(`./abstract/${encodeURIComponent(posterId!)}/`);
		await expect(page.getByTestId('detail-poster-id')).toBeVisible({ timeout: 15_000 });
		const before = page.url();
		await page.reload();
		// A hard reload busts in-memory state and re-fetches the full data
		// package from the (rate-limit-prone) data host before the detail
		// panel can re-render. The default 5s expect timeout is too tight on
		// a cold, throttled fetch — give it the same headroom as the initial
		// data-dependent waits in this file.
		await expect(page.getByTestId('detail-poster-id')).toBeVisible({ timeout: 30_000 });
		expect(page.url()).toBe(before);
	});

	test('unknown poster_id renders "abstract not found" inside the conference shell', async ({
		page
	}) => {
		await page.goto('./abstract/NOT-A-REAL-ID/');
		// The "not found" affordance MUST render inside the SvelteKit shell
		// (NOT the generic gh-pages 404). The shell is identified by the
		// layout-level `header-tour-button` testid which is always present
		// on every route. `search-input` is home-only; the abstract
		// permalink route doesn't render it.
		await expect(page.getByTestId('header-tour-button')).toBeVisible({ timeout: 5000 });
		await expect(page.getByTestId('abstract-not-found')).toBeVisible({ timeout: 5000 });
	});
});

test.describe('US3 — root URL redirects', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');
	test.skip(
		!!REMOTE_BASE_URL,
		'Root-redirect island is origin-rooted; the local preview harness is required to exercise it'
	);

	test('root path bounces to the conference subpath', async ({ browser }) => {
		// Use a fresh context so we can navigate to a URL OUTSIDE the
		// configured baseURL. `useContextOptions` doesn't expose an explicit
		// override here; the safe path is `browser.newContext()` then
		// `page.goto('http://127.0.0.1:4173/')` (absolute, no baseURL prepend).
		const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:4173' });
		const page = await ctx.newPage();
		await page.goto('/');
		// Wait for the meta-refresh + JS replace to settle into /ohbm2026/.
		await expect.poll(async () => page.url(), { timeout: 5000 }).toMatch(
			/\/ohbm2026\/?$/
		);
		// And the SvelteKit shell renders.
		await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 5000 });
		await ctx.close();
	});

	test('query string survives the redirect', async ({ browser }) => {
		const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:4173' });
		const page = await ctx.newPage();
		await page.goto('/?utm_source=test');
		await expect.poll(async () => page.url(), { timeout: 5000 }).toMatch(
			/\/ohbm2026\/\?utm_source=test/
		);
		await ctx.close();
	});

	test('hash survives the redirect', async ({ browser }) => {
		const ctx = await browser.newContext({ baseURL: 'http://127.0.0.1:4173' });
		const page = await ctx.newPage();
		await page.goto('/#anchor');
		await expect.poll(async () => page.url(), { timeout: 5000 }).toMatch(
			/\/ohbm2026\/?#anchor/
		);
		await ctx.close();
	});
});
