/**
 * Stage 15 (spec 015-neuroscape-context, T035) — bare-root atlas
 * landing-page smoke + interaction tests.
 *
 * The existing Playwright config's `baseURL` targets the OHBM 2026
 * subpath (`<host>/ohbm2026/`). The atlas-root build lives at the
 * bare origin (one level up), so this spec uses `goto('/')` —
 * Playwright resolves a leading-slash path against the origin only,
 * stripping the baseURL's path component.
 *
 * Gated by `ATLAS_ROOT_E2E=1` so the spec doesn't run in the
 * existing OHBM-2026-only e2e job (which still serves a redirect
 * island at the bare root). The deploy workflow (T049/T050) will
 * flip the gate on once the atlas-root build is staged at the
 * root in PR previews.
 *
 * Three sub-suites:
 *  - smoke: assertions for the chrome/toggle/links that DO exist
 *    after the US1 slice 1 commit (T038–T044, T048).
 *  - scatter interactions: assertions for hover/click/lasso that
 *    require T045 (UmapPanel atlas-root adapter). Marked
 *    `test.skip` until T045 ships.
 *  - drift assertion: requires T043 (cross-parquet drift check in
 *    `loader.ts`). Marked `test.skip` until T043 ships.
 */

import { test, expect } from '@playwright/test';

const ATLAS_ROOT_E2E = process.env.ATLAS_ROOT_E2E === '1';

test.describe('US1: atlas-root landing-page smoke', () => {
	test.skip(!ATLAS_ROOT_E2E, 'Set ATLAS_ROOT_E2E=1 to run atlas-root specs (requires the atlas-root build to be staged at the bare root — see specs/015-neuroscape-context/contracts/atlas-root-ui.md).');

	test('bare root is NOT a meta-refresh redirect', async ({ page }) => {
		const response = await page.goto('/');
		expect(response?.status()).toBe(200);
		// FR-008: the new landing page replaces the Stage-9 meta-refresh
		// redirect. The HTML must NOT contain a <meta http-equiv="refresh">
		// directive.
		const html = await page.content();
		expect(html).not.toMatch(/<meta[^>]*http-equiv\s*=\s*["']refresh["']/i);
	});

	test('SiteHeader + AtlasSubsiteNav render with both outbound subsite links', async ({ page }) => {
		await page.goto('/');
		// SiteHeader (the unified site chrome) is present on every
		// subsite build; AtlasSubsiteNav (the hub-and-spoke nav strip)
		// is only mounted on atlas-root.
		await expect(page.getByTestId('site-header')).toBeVisible();
		await expect(page.getByTestId('atlas-subsite-nav')).toBeVisible();
		const ohbmLink = page.getByTestId('nav-ohbm2026');
		const neuroLink = page.getByTestId('nav-neuroscape');
		await expect(ohbmLink).toBeVisible();
		await expect(neuroLink).toBeVisible();
		// FR-014: the two outbound links target /ohbm2026/ and /neuroscape/.
		const ohbmHref = await ohbmLink.getAttribute('href');
		const neuroHref = await neuroLink.getAttribute('href');
		expect(ohbmHref).toMatch(/(^|\/)ohbm2026\/?$/);
		expect(neuroHref).toMatch(/(^|\/)neuroscape\/?$/);
		// rel="external" so SvelteKit treats them as cross-deployment.
		expect(await ohbmLink.getAttribute('rel')).toBe('external');
		expect(await neuroLink.getAttribute('rel')).toBe('external');
	});

	test('AtlasOverlayToggle defaults to on + flips to off on click', async ({ page }) => {
		await page.goto('/');
		const toggle = page.getByTestId('atlas-overlay-toggle');
		await expect(toggle).toBeVisible();
		// FR-009: default is "on".
		await expect(toggle).toHaveAttribute('data-state', 'on');
		// Clicking the underlying checkbox flips it.
		const checkbox = toggle.locator('input[type="checkbox"]');
		await checkbox.click();
		await expect(toggle).toHaveAttribute('data-state', 'off');
		// localStorage persists the choice — verify by re-navigating
		// and reading the toggle state on a fresh load.
		await page.reload();
		await expect(page.getByTestId('atlas-overlay-toggle')).toHaveAttribute('data-state', 'off');
		// Flip back and confirm again.
		await page.getByTestId('atlas-overlay-toggle').locator('input').click();
		await expect(page.getByTestId('atlas-overlay-toggle')).toHaveAttribute('data-state', 'on');
	});

	test('BackdropDensitySlider visible with the documented default', async ({ page }) => {
		await page.goto('/');
		const slider = page.getByTestId('backdrop-density-slider');
		await expect(slider).toBeVisible();
		// FR-013 + contracts/atlas-root-ui.md: default 0.25 (not persisted).
		const value = await page.getByTestId('backdrop-density-value').textContent();
		expect(value?.trim()).toBe('0.25');
	});

	test('Stage-15 atlas-root page title is the cross-conference label', async ({ page }) => {
		await page.goto('/');
		// Layout swaps the OHBM-2026-only title for the cross-conference
		// landing-page label when SITE_MODE === 'atlas-root'.
		await expect(page).toHaveTitle(/Abstract Atlas/);
		await expect(page).not.toHaveTitle(/OHBM 2026 Atlas/);
	});
});

test.describe('US1: atlas-root scatter interactions (T045 dependent)', () => {
	test.skip(!ATLAS_ROOT_E2E, 'Set ATLAS_ROOT_E2E=1 to run atlas-root specs.');
	test.skip(true, 'Pending T045 — UmapPanel atlas-root adapter.');

	test('toggling overlay off hides OHBM 2026 points but keeps backdrop + legend', async () => {
		// Will be enabled once T045 lands the WebGL adapter.
	});

	test('hovering a NeuroScape point shows the documented tooltip', async () => {
		// Pending T045.
	});

	test('hovering an OHBM 2026 point shows the documented tooltip', async () => {
		// Pending T045.
	});

	test('clicking a NeuroScape point opens the DetailPanel with the right deep-link CTA', async () => {
		// Pending T045 + T046.
	});

	test('clicking an OHBM 2026 point opens the DetailPanel with the right deep-link CTA', async () => {
		// Pending T045 + T046.
	});

	test('lassoing a region produces a grouped result list with summed counts', async () => {
		// Pending T045 + T047.
	});
});

test.describe('US1: cross-parquet drift assertion (T043 dependent)', () => {
	test.skip(!ATLAS_ROOT_E2E, 'Set ATLAS_ROOT_E2E=1 to run atlas-root specs.');
	test.skip(true, 'Pending T043 — loader.ts drift assertion against sibling state-keys.');

	test('mismatched sibling state-keys surface a visible error banner', async () => {
		// Pending T043; will inject a mock loader response with mismatched
		// sibling state-keys and assert the drift error component renders.
	});
});
