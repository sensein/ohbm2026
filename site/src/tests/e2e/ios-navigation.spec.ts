/**
 * Stage 24 (specs/024-fix-ios-safari-load) — navigation-crash regression.
 *
 * The ORIGINAL reported bug: on iPhone Safari the atlas CRASHED under any form
 * of navigation. Root cause is WebGL-context churn — every route change / map
 * toggle / 3D mount allocates scatter contexts, and iOS WebKit's tight
 * per-origin context cap crashes the tab when they aren't released fast enough.
 *
 * This spec stresses the context-churning navigation paths on the real WebKit
 * engine (iphone-webkit project) and asserts the tab never crashes and stays
 * responsive. It is the direct regression test for the reported failure.
 *
 * Run on the deployed preview origin (where the data host CORS resolves):
 *   PLAYWRIGHT_BASE_URL=https://abstractatlas.brainkb.org/pr-N/ohbm2026/ \
 *     pnpm exec playwright test --project=iphone-webkit ios-navigation
 */

import { test, expect, type Page } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

async function resultCount(page: Page): Promise<number> {
	const t = (await page.getByTestId('result-count').textContent())?.trim() ?? '0';
	return Number.parseInt(t, 10) || 0;
}
async function waitForInteractive(page: Page): Promise<void> {
	await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 5_000 });
	await expect.poll(() => resultCount(page), { timeout: 60_000 }).toBeGreaterThan(0);
}

test.describe('iPhone Safari: no crash under navigation (WebKit)', () => {
	test.skip(!DATA_AVAILABLE, 'No data package wired in this run');
	test.setTimeout(180_000);

	test('survives repeated map toggles, 3D mount/unmount, and route navigation', async ({
		page
	}) => {
		let crashed = false;
		page.on('crash', () => {
			crashed = true;
		});

		await page.goto('./');
		await waitForInteractive(page);

		const base = page.url().replace(/\?.*$/, '');
		const posterId = await page.evaluate(
			() =>
				(window as unknown as { __abstracts?: { poster_id: number }[] }).__abstracts?.[0]
					?.poster_id ?? null
		);
		// SvelteKit polls _app/version.json on navigation; on the gh-pages preview
		// that fetch can surface a benign access-control pageerror that is NOT a
		// crash. Only `page.on('crash')` counts as the failure we're guarding.

		// 1) Map toggle churn — the prime context-allocation path. Hide/show
		//    unmounts/remounts UmapPanel (its WebGL context must be released each
		//    time, or contexts accumulate → crash).
		for (let i = 0; i < 4; i++) {
			await page.getByTestId('toggle-map').click(); // hide
			await expect(page.getByTestId('umap-chart-2d')).toHaveCount(0, { timeout: 5_000 });
			await page.getByTestId('toggle-map').click(); // show
			await expect(page.getByTestId('umap-chart-2d')).toBeVisible({ timeout: 10_000 });
			expect(crashed, `tab crashed after map toggle ${i}`).toBe(false);
		}

		// 2) 3D mount/unmount churn (mobile defers 3D behind the opt-in toggle).
		const show3d = page.getByTestId('umap-show-3d');
		if ((await show3d.count()) > 0) {
			for (let i = 0; i < 3; i++) {
				await show3d.click();
				await expect(page.getByTestId('umap-chart-3d')).toBeVisible({ timeout: 10_000 });
				await page.getByTestId('umap-hide-3d').click();
				await expect(page.getByTestId('umap-chart-3d')).toHaveCount(0, { timeout: 5_000 });
				expect(crashed, `tab crashed after 3D toggle ${i}`).toBe(false);
			}
		}

		// 3) In-app navigation to the About route and back to home, exercising a
		//    real route change (home +page → about +page → home +page re-mount).
		await page.getByTestId('header-about-link').click();
		await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 15_000 });
		expect(crashed, 'tab crashed navigating to About').toBe(false);

		// 4) Deep-link route navigation: load an abstract permalink directly.
		if (posterId !== null) {
			await page.goto(`${base}abstract/${posterId}/`);
			await expect(page.getByTestId('detail-panel')).toBeVisible({ timeout: 15_000 });
			expect(crashed, 'tab crashed on abstract permalink nav').toBe(false);
		}

		// 5) Back to the home route — scatter re-mounts (fresh WebGL context).
		await page.goto(base);
		await waitForInteractive(page);
		await expect(page.getByTestId('umap-chart-2d')).toBeVisible({ timeout: 30_000 });

		expect(crashed, 'tab crashed during the navigation stress flow').toBe(false);
	});
});
