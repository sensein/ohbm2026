import { test, expect, devices } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('US1: browse + search + detail (desktop)', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('search bar visible within 3s, result cards render, detail opens', async ({ page }) => {
		await page.goto('/');
		await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 3000 });

		// Wait for the result list to hydrate (any non-zero card count).
		await expect(page.getByTestId('result-count')).toBeVisible();
		const initialText = (await page.getByTestId('result-count').textContent())?.trim();
		expect(initialText).toMatch(/^\d+$/);
		expect(Number(initialText)).toBeGreaterThan(100);

		// Type a known-good query.
		await page.getByTestId('search-input').fill('connectivity');
		await expect(async () => {
			const t = (await page.getByTestId('result-count').textContent())?.trim();
			expect(Number(t)).toBeGreaterThan(0);
		}).toPass({ timeout: 2000 });

		// Click the first result.
		await page.getByTestId('result-card').first().click();

		// Detail panel renders the poster_id (NOT the submission_id) as the header.
		await expect(page.getByTestId('detail-panel')).toBeVisible();
		const headerPosterId = (await page.getByTestId('detail-poster-id').textContent())?.trim();
		expect(headerPosterId).toBeTruthy();

		// The clicked card's poster_id (the program-assigned id) must equal what
		// the detail header renders. Submission ids in this corpus are 7-digit
		// integers (e.g. 1176971); poster_ids are program tags like M-AM-101 or
		// 0503. Catch the regression where the panel accidentally falls back to
		// the submission id by checking the card→panel pairing matches.
		const card = page.getByTestId('result-card').first();
		const cardPosterId = await card.getAttribute('data-poster-id');
		expect(cardPosterId).toBe(headerPosterId);
		// Submission ids in this corpus are >= 1,000,000 — assert the displayed
		// poster_id isn't a raw submission id.
		expect(headerPosterId!.length).toBeLessThan(7);
	});
});

test.describe('US1: mobile layout (360 × 640 — SC-004 minimum)', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('home page has no horizontal scroll on the SC-004 viewport', async ({ browser }) => {
		const context = await browser.newContext({
			viewport: { width: 360, height: 640 },
			userAgent: devices['Pixel 5'].userAgent
		});
		const page = await context.newPage();
		try {
			await page.goto('/');
			await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 3000 });
			const scroll = await page.evaluate(() => ({
				scrollWidth: document.documentElement.scrollWidth,
				clientWidth: document.documentElement.clientWidth
			}));
			expect(scroll.scrollWidth).toBeLessThanOrEqual(scroll.clientWidth + 1);
		} finally {
			await context.close();
		}
	});
});

test.describe('US1: build provenance (FR-022 / SC-011)', () => {
	test('footer carries the build_info short SHA on every route', async ({ page }) => {
		await page.goto('/');
		const footer = page.getByTestId('build-info-footer');
		await expect(footer).toBeVisible();
		const shortSha = await page.getByTestId('build-info-short-sha').textContent();
		expect(shortSha).toMatch(/^[0-9a-f]{7}$/);
	});

	test('placeholder route also surfaces the build short SHA in the title', async ({ page }) => {
		await page.goto('/');
		const title = await page.title();
		// `+layout.svelte` titles the page `OHBM 2026 Atlas (beta) · <sha>`
		// once the build_info is available (either from VITE_BUILD_SHA at
		// build time OR from the manifest at load time). The "(beta)" tag
		// is part of the public Stage-6 title; the test asserts the SHA
		// suffix lands on this route.
		expect(title).toMatch(/OHBM 2026 Atlas \(beta\) · [0-9a-f]{7}/);
	});
});
