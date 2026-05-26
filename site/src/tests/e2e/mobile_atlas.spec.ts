/**
 * Stage 15 mobile e2e — verifies the atlas-root + neuroscape pages
 * adapt cleanly to a 360×640 (Pixel 5) viewport:
 *
 *   - Map is HIDDEN by default (the parquet-sized payload doesn't
 *     start downloading until the user opts in).
 *   - Mobile admonition is visible near the top explaining the
 *     "data + battery on cellular" trade-off.
 *   - No horizontal overflow at viewport width.
 *
 * Both atlas-root and neuroscape build at sibling deploys, so the
 * spec navigates from the baseURL (which ends at /ohbm2026/) up to
 * the deploy root + over to the relevant sibling subpath. Skipped
 * for the desktop chromium project so the chromium suite stays
 * focused on its existing assertions.
 */

import { test, expect } from '@playwright/test';

const isMobileProject = (project: { name: string }) => project.name === 'mobile';

test.describe('mobile · atlas-root + neuroscape adapt to small viewport', () => {
	test.beforeEach(async ({ }, testInfo) => {
		test.skip(
			!isMobileProject(testInfo.project),
			'mobile-only spec — runs in the Pixel 5 project'
		);
	});

	for (const subsite of ['atlas-root', 'neuroscape'] as const) {
		// `../` lands on the deploy root (atlas-root build); `../neuroscape/`
		// lands on the NeuroScape PubMed sibling. Both rooted relative to
		// PLAYWRIGHT_BASE_URL which terminates at `/ohbm2026/`.
		const path = subsite === 'atlas-root' ? '../' : '../neuroscape/';
		const label = subsite === 'atlas-root' ? 'atlas-root' : '/neuroscape/';

		test(`${label}: map is hidden by default + admonition visible`, async ({ page }) => {
			await page.goto(path);
			await expect(page.getByTestId('atlas-mobile-warning')).toBeVisible();
			// Map toggle exists but is in the "Show map" state (off).
			const toggle = page.getByTestId('toggle-map');
			await expect(toggle).toBeVisible();
			// Button label flips between "✕ Hide map" (on) and "🗺  Show map"
			// (off). On mobile default we expect the OFF label.
			await expect(toggle).toContainText(/Show map/i);
		});

		test(`${label}: no horizontal page overflow`, async ({ page }) => {
			await page.goto(path);
			await expect(page.getByTestId('atlas-mobile-warning')).toBeVisible();
			// `document.documentElement.scrollWidth` should not exceed the
			// viewport width — a horizontal scrollbar at 360 CSS px would
			// be a layout regression.
			const overflow = await page.evaluate(() => ({
				docWidth: document.documentElement.scrollWidth,
				viewportWidth: window.innerWidth
			}));
			expect(overflow.docWidth).toBeLessThanOrEqual(overflow.viewportWidth + 1);
		});

		test(`${label}: tapping "Show map" loads + renders the UMAP`, async ({ page }) => {
			await page.goto(path);
			await page.getByTestId('atlas-mobile-warning').waitFor({ timeout: 10_000 });
			const toggle = page.getByTestId('toggle-map');
			await toggle.click();
			// Once flipped the button label switches to "Hide map".
			await expect(toggle).toContainText(/Hide map/i);
			// The UmapPanel container should be present after the parquet
			// load + first render. Generous timeout because mobile
			// SwiftShader is slow on big point clouds.
			await expect(page.getByTestId('umap-panel')).toBeVisible({
				timeout: 60_000
			});
		});
	}
});
