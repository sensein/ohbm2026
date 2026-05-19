import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('FR-001 + SC-005: accepted-only invariant', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('no abstract record in the loaded shard has accepted_for == "Withdrawn"', async ({
		page
	}) => {
		await page.goto('./');
		await expect(page.getByTestId('result-count')).toBeVisible({ timeout: 5000 });
		// After hydration, the home page exposes window.__abstracts for this guard.
		const leak = await page.evaluate(() => {
			const records = (window as unknown as { __abstracts?: Array<{ accepted_for: string }> })
				.__abstracts;
			if (!records) return -1;
			return records.filter((r) => r.accepted_for === 'Withdrawn').length;
		});
		expect(leak).toBe(0);
	});
});
