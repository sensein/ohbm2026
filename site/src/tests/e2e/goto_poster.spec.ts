import { expect, test } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

/**
 * Stage 14 — `id:` operator in the search bar with autocomplete
 * dropdown. Per `contracts/id-search-mode.md`.
 *
 * The tests run against the deployed preview or `pnpm preview` and
 * SKIP cleanly when no data package is reachable.
 */
test.describe('Stage 14 US1 — `id:` operator navigator mode', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('exact match navigates to the permalink', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		// Snapshot a known available poster id from the first card so the
		// test stays in lockstep with whatever corpus is loaded.
		const posterId = await page.getByTestId('result-card').first().getAttribute('data-poster-id');
		expect(posterId).toBeTruthy();

		await page.getByTestId('search-input').fill(`id:${posterId}`);
		// The listbox renders + collapses to a single match.
		const listbox = page.getByTestId('search-id-listbox');
		await expect(listbox).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('search-id-option')).toHaveCount(1);

		await page.getByTestId('search-input').press('Enter');
		await page.waitForURL(new RegExp(`/abstract/${posterId}/?$`));
	});

	test('prefix `id:12` lists matching ids but never `1012` / `0212`', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').fill('id:12');
		await expect(page.getByTestId('search-id-listbox')).toBeVisible({ timeout: 2000 });

		const visibleIds = await page
			.getByTestId('search-id-option')
			.evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-poster-id'))));

		// Each visible id MUST be in the set whose decimal string starts
		// with "12". Negative-check: id 1012 / 212 must NEVER be present.
		expect(visibleIds.length).toBeGreaterThan(0);
		for (const id of visibleIds) {
			expect(id.toString().startsWith('12')).toBe(true);
		}
		expect(visibleIds).not.toContain(1012);
		expect(visibleIds).not.toContain(212);

		// Listbox capped at 10 visible; overflow footer present when total > 10.
		expect(visibleIds.length).toBeLessThanOrEqual(10);
	});

	test('`id:9999` shows "No matching posters" and Enter is a no-op', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const startUrl = page.url();

		await page.getByTestId('search-input').fill('id:9999');
		await expect(page.getByTestId('search-id-empty')).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('search-id-empty')).toContainText(/no matching posters/i);

		await page.getByTestId('search-input').press('Enter');
		// URL unchanged — no navigation happened.
		expect(page.url()).toBe(startUrl);
	});

	test('`id:` (no digits) shows the "type a poster number" hint', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').fill('id:');
		await expect(page.getByTestId('search-id-hint')).toBeVisible({ timeout: 2000 });
	});

	test('backspacing the `id:` prefix exits navigator mode + result list re-renders', async ({
		page
	}) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').fill('id:12');
		await expect(page.getByTestId('search-id-listbox')).toBeVisible({ timeout: 2000 });

		// Clear the input by selecting all + delete. The dropdown unmounts
		// and the result list re-renders.
		await page.getByTestId('search-input').fill('');
		await expect(page.getByTestId('search-id-listbox')).toBeHidden();
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 2000 });
	});

	test('click on a suggestion `<li>` navigates without keyboard', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const firstId = await page.getByTestId('result-card').first().getAttribute('data-poster-id');

		await page.getByTestId('search-input').fill(`id:${firstId}`);
		await expect(page.getByTestId('search-id-option')).toHaveCount(1);
		await page.getByTestId('search-id-option').first().click();
		await page.waitForURL(new RegExp(`/abstract/${firstId}/?$`));
	});
});

test.describe('Stage 14 US2 — `g` keyboard shortcut', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('`g` from non-input area focuses search bar + inserts `id:`', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		// Click into a non-input area (the page body itself) to ensure
		// nothing is focused, then press `g`.
		await page.locator('body').click({ position: { x: 5, y: 5 } });
		await page.keyboard.press('g');

		await expect(page.getByTestId('search-input')).toBeFocused();
		await expect(page.getByTestId('search-input')).toHaveValue('id:');
	});

	test('`g` while another input is focused passes through as the literal char', async ({
		page
	}) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').focus();
		await page.getByTestId('search-input').fill('');
		await page.keyboard.press('g');
		await expect(page.getByTestId('search-input')).toHaveValue('g');
	});

	test('Escape immediately after `g` restores the prior query', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		// Seed the bar with a normal lexical query.
		await page.getByTestId('search-input').fill('memory');
		await page.locator('body').click({ position: { x: 5, y: 5 } });

		await page.keyboard.press('g');
		await expect(page.getByTestId('search-input')).toHaveValue('id:');

		await page.keyboard.press('Escape');
		await expect(page.getByTestId('search-input')).toHaveValue('memory');
	});

	test('`g` works the same on a permalink page', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const firstId = await page.getByTestId('result-card').first().getAttribute('data-poster-id');

		await page.goto(`./abstract/${firstId}/`);
		await page.locator('body').click({ position: { x: 5, y: 5 } });
		await page.keyboard.press('g');

		await expect(page.getByTestId('search-input')).toBeFocused();
		await expect(page.getByTestId('search-input')).toHaveValue('id:');
	});
});
