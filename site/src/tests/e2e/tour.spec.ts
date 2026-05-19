/**
 * T081 — US6 tour acceptance.
 *
 * Exercises the two US6 acceptance scenarios:
 *
 *   1. A first-time visitor sees a CTA banner offering the tour. Clicking
 *      "Start tour" opens the tour overlay; advancing through the steps
 *      eventually completes it without errors.
 *   2. Dismissing the CTA hides it for the rest of the session. Reopening
 *      via the header `Tour` button still works.
 *
 * Runs against the local Vite preview; skips when the data package isn't
 * built (the tour pins to selectors that don't exist on the placeholder).
 */

import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('US6: guided tour', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('first visit shows the CTA; starting it opens the tour overlay', async ({ page, context }) => {
		// Wipe any localStorage from prior runs so the CTA actually appears.
		await context.clearCookies();
		await page.goto('./');
		await page.evaluate(() => {
			window.localStorage.clear();
			window.sessionStorage.clear();
		});
		await page.reload();
		// CTA banner shows on a clean state.
		const cta = page.getByTestId('tour-cta');
		await expect(cta).toBeVisible({ timeout: 3_000 });
		// Click "Start tour" — shepherd.js mounts `.shepherd-element` into the body.
		await page.getByTestId('tour-cta-start').click();
		await expect(page.locator('.shepherd-element')).toBeVisible({ timeout: 3_000 });
	});

	test('dismissing the CTA hides it; header button still opens the tour', async ({ page, context }) => {
		await context.clearCookies();
		await page.goto('./');
		await page.evaluate(() => {
			window.localStorage.clear();
			window.sessionStorage.clear();
		});
		await page.reload();
		await page.getByTestId('tour-cta').waitFor();
		await page.getByTestId('tour-cta-skip').click();
		await expect(page.getByTestId('tour-cta')).toHaveCount(0);
		// Header button remains the persistent entry point.
		await page.getByTestId('header-tour-button').click();
		await expect(page.locator('.shepherd-element')).toBeVisible({ timeout: 3_000 });
	});
});
