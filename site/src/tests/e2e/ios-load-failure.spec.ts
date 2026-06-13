/**
 * Stage 24 (specs/024-fix-ios-safari-load) — US2 failure-visibility.
 *
 * Contract: contracts/error-visibility.md (AC-1/AC-2) + SC-004.
 *
 * When the critical data load fails, the atlas MUST show a readable message —
 * never a blank page or an endless spinner. We force the failure by aborting
 * the data-package fetch, then assert the visible `load-error` placeholder
 * appears and the "Loading…" spinner is gone.
 *
 * Run against the `iphone-webkit` project (but engine-agnostic). Requires a
 * build whose bundle has a data-package URL to attempt (so the abort has
 * something to intercept) — hence gated on UI_DATA_AVAILABLE like the rest.
 */

import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('US2: load failure is visible, not a blank screen', () => {
	test.skip(!DATA_AVAILABLE, 'No data-package URL to intercept in this run');

	test('AC-1: aborting the data fetch shows a readable error, not a spinner (SC-004)', async ({
		page
	}) => {
		// Intercept the parquet data-package request(s) and fail them, simulating
		// an iOS network/abort failure mid-load.
		await page.route(/\.parquet(\?|$)/, (route) => route.abort());
		await page.goto('./');
		// The visible error placeholder appears...
		await expect(page.getByTestId('load-error')).toBeVisible({ timeout: 20_000 });
		// ...and the page is NOT stuck on the spinner.
		await expect(page.getByText('Loading…')).toHaveCount(0);
		// The message is human-readable (non-empty), not a blank panel.
		const msg = (await page.getByTestId('load-error').textContent())?.trim() ?? '';
		expect(msg.length).toBeGreaterThan(0);
	});
});
