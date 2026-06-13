/**
 * Stage 24 (specs/024-fix-ios-safari-load) — US1 load verification.
 *
 * Contract: contracts/load-verification.md + SC-001/SC-002/SC-003.
 *
 * The `/ohbm2026/` atlas did not load on iPhone Safari (blank screen / endless
 * spinner). This spec drives the REAL WebKit engine on an iPhone descriptor
 * (the `iphone-webkit` Playwright project) and asserts the atlas reaches an
 * interactive state and the core journey (open → search → open an abstract)
 * succeeds. Before the fix this FAILS — the bootstrap never leaves "Loading…".
 *
 * Interactivity is gated on the result list + search box, NOT the UMAP chart:
 * the chart is WebGL and Playwright's headless WebKit has no WebGL (a real
 * iPhone does). On a no-WebGL device the atlas must still load the list/search
 * (FR-001 / T011), so this is also the correct signal there.
 *
 * Run: `pnpm exec playwright test --project=iphone-webkit ios-ohbm-load`
 * (requires `playwright install webkit` + a data package URL wired in
 * `site/.env.local`, baked into the build the preview server serves).
 *
 * Skipped automatically when no data package is wired (UI_DATA_AVAILABLE=0).
 */

import { test, expect, type Page } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';
// SC-002: optional desktop load-to-interactive baseline (ms). When supplied
// (captured from the chromium project run) we assert iphone ≤ baseline + 3 s;
// otherwise we assert an absolute ceiling and log the measured time.
const DESKTOP_BASELINE_MS = process.env.DESKTOP_BASELINE_MS
	? Number.parseInt(process.env.DESKTOP_BASELINE_MS, 10)
	: null;
const ABSOLUTE_INTERACTIVE_CEILING_MS = 60_000; // 25 MB parquet over network + decode

async function resultCount(page: Page): Promise<number> {
	const t = (await page.getByTestId('result-count').textContent())?.trim() ?? '0';
	return Number.parseInt(t, 10) || 0;
}

/** Interactive = search box visible AND the corpus has populated the list.
 *  WebGL-independent, so it holds on headless WebKit and no-WebGL devices. */
async function waitForInteractive(page: Page): Promise<void> {
	await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 5_000 });
	await expect.poll(() => resultCount(page), { timeout: ABSOLUTE_INTERACTIVE_CEILING_MS }).toBeGreaterThan(0);
}

/** Whether the browser can actually create a WebGL context. */
async function hasWebGL(page: Page): Promise<boolean> {
	return page.evaluate(() => {
		try {
			const c = document.createElement('canvas');
			return !!(c.getContext('webgl2') || c.getContext('webgl'));
		} catch {
			return false;
		}
	});
}

test.describe('US1: OHBM atlas loads on iPhone Safari (WebKit)', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');
	test.setTimeout(90_000); // 25 MB parquet over network + decode on WebKit

	test('reaches an interactive state without a blank screen or endless spinner (SC-001/SC-002)', async ({
		page
	}) => {
		const start = Date.now();
		await page.goto('./');
		await waitForInteractive(page);
		// The page is NOT stuck on the spinner and did NOT fall into the error state.
		await expect(page.getByText('Loading…')).toHaveCount(0);
		await expect(page.getByTestId('load-error')).toHaveCount(0);
		const elapsed = Date.now() - start;
		// eslint-disable-next-line no-console
		console.log(`[ios-ohbm-load] load-to-interactive: ${elapsed}ms`);
		if (DESKTOP_BASELINE_MS !== null) {
			expect(elapsed).toBeLessThanOrEqual(DESKTOP_BASELINE_MS + 3_000);
		} else {
			expect(elapsed).toBeLessThanOrEqual(ABSOLUTE_INTERACTIVE_CEILING_MS);
		}
	});

	test('core journey: search returns results and an abstract opens (SC-003)', async ({ page }) => {
		await page.goto('./');
		await waitForInteractive(page);
		await page.getByTestId('search-input').fill('memory');
		await expect
			.poll(async () => page.getByTestId('result-card').count(), { timeout: 10_000 })
			.toBeGreaterThan(0);
		await page.getByTestId('result-card').first().click();
		await expect(page.getByTestId('detail-panel')).toBeVisible({ timeout: 5_000 });
	});

	test('mobile rendering: 3D is deferred (WebGL) or the map degrades gracefully (no WebGL)', async ({
		page
	}) => {
		await page.goto('./');
		await waitForInteractive(page);
		if (await hasWebGL(page)) {
			// Phone WITH WebGL: 2D mounts, 3D is NOT auto-mounted — the opt-in CTA is.
			await expect(page.getByTestId('umap-chart-3d')).toHaveCount(0);
			await expect(page.getByTestId('umap-show-3d')).toBeVisible();
			await page.getByTestId('umap-show-3d').click();
			await expect(page.getByTestId('umap-chart-3d')).toBeVisible({ timeout: 10_000 });
		} else {
			// No WebGL (e.g. headless WebKit): the map degrades to a clear note
			// and the list/search still work (FR-001 / T011) — never a blank pane.
			await expect(page.getByTestId('umap-unavailable')).toBeVisible();
		}
	});
});
