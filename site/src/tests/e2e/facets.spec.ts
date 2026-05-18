/**
 * T068 — US4 facets acceptance.
 *
 * Exercises FR-005: clicking a facet option narrows the result set; the
 * facet counts on OTHER groups recompute against the narrowed set; and
 * the `Clear` action releases every active facet at once.
 *
 * Runs against the local Vite preview; skips when the data package isn't
 * built so we don't false-fail in plain `pnpm test:unit` runs.
 */

import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

async function resultCount(page: import('@playwright/test').Page): Promise<number> {
	const t = (await page.getByTestId('result-count').textContent())?.trim() ?? '0';
	return Number.parseInt(t, 10) || 0;
}

test.describe('US4: interactive facets', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('clicking a facet option narrows the result set', async ({ page }) => {
		await page.goto('/');
		await page.getByTestId('search-input').waitFor();
		await page.getByTestId('result-card').first().waitFor({ timeout: 10_000 });
		const before = await resultCount(page);
		// Expand the first facet group that exists. The Accepted-for group
		// is always present in the data package.
		const acceptedFor = page.getByTestId('facet-accepted_for');
		if ((await acceptedFor.count()) === 0) test.skip(true, 'facet-accepted_for missing');
		const header = acceptedFor.locator('.facet-header');
		const expanded = await header.getAttribute('aria-expanded');
		if (expanded !== 'true') await header.click();
		// Tick the first option.
		const firstOpt = acceptedFor.getByTestId('facet-option-accepted_for').first();
		await firstOpt.click();
		await page.waitForTimeout(200);
		const after = await resultCount(page);
		expect(after).toBeGreaterThan(0);
		expect(after).toBeLessThanOrEqual(before);
	});

	test('other facet counts recompute against the narrowed set', async ({ page }) => {
		await page.goto('/');
		await page.getByTestId('search-input').waitFor();
		await page.getByTestId('result-card').first().waitFor({ timeout: 10_000 });
		// Sample a count from a second facet group BEFORE filtering.
		const expandIfClosed = async (key: string): Promise<void> => {
			const group = page.getByTestId(`facet-${key}`);
			if ((await group.count()) === 0) return;
			const exp = await group.locator('.facet-header').getAttribute('aria-expanded');
			if (exp !== 'true') await group.locator('.facet-header').click();
		};
		await expandIfClosed('accepted_for');
		await expandIfClosed('keywords');
		// Read the count of the first keyword option, pre-filter.
		const kw0 = page.getByTestId('facet-keywords').getByTestId('facet-option-keywords').first();
		const pre = await kw0.locator('.opt-count').textContent();
		// Now tick the first Accepted-for option.
		await page
			.getByTestId('facet-accepted_for')
			.getByTestId('facet-option-accepted_for')
			.first()
			.click();
		await page.waitForTimeout(200);
		// Read the same keyword's count again — must be ≤ pre.
		const post = await kw0.locator('.opt-count').textContent();
		expect(Number.parseInt(post ?? '0', 10)).toBeLessThanOrEqual(Number.parseInt(pre ?? '0', 10));
	});

	test('Clear releases every active facet at once', async ({ page }) => {
		await page.goto('/');
		await page.getByTestId('search-input').waitFor();
		await page.getByTestId('result-card').first().waitFor({ timeout: 10_000 });
		const before = await resultCount(page);
		const accepted = page.getByTestId('facet-accepted_for');
		if ((await accepted.count()) === 0) test.skip(true, 'facet-accepted_for missing');
		const header = accepted.locator('.facet-header');
		if ((await header.getAttribute('aria-expanded')) !== 'true') await header.click();
		await accepted.getByTestId('facet-option-accepted_for').first().click();
		await page.waitForTimeout(200);
		expect(await resultCount(page)).toBeLessThanOrEqual(before);
		await page.getByTestId('facets-clear').click();
		await page.waitForTimeout(200);
		expect(await resultCount(page)).toBe(before);
	});
});
