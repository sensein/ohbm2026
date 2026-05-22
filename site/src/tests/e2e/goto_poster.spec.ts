import { expect, test } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

/**
 * Stage 14 — `id:` operator in the search bar with autocomplete
 * dropdown. Per the 2026-05-22 clarification, selecting an id FILTERS
 * the result list to that one abstract — it does NOT navigate to the
 * permalink page. The user then clicks the card to drill in.
 */
test.describe('Stage 14 US1 — `id:` operator narrows the result list', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('exact id filters the result list to one card', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		// Snapshot a known available poster id from the first card.
		const posterId = await page.getByTestId('result-card').first().getAttribute('data-poster-id');
		expect(posterId).toBeTruthy();
		const startUrl = page.url();

		await page.getByTestId('search-input').fill(`id:${posterId}`);
		await expect(page.getByTestId('search-id-listbox')).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('search-id-option')).toHaveCount(1);

		await page.getByTestId('search-input').press('Enter');

		// URL UNCHANGED — Enter narrows the list, doesn't navigate.
		expect(page.url()).toBe(startUrl);

		// Result list shows exactly 1 card, matching the chosen id.
		await expect(page.getByTestId('result-card')).toHaveCount(1, { timeout: 2000 });
		expect(
			await page.getByTestId('result-card').first().getAttribute('data-poster-id')
		).toBe(posterId);
	});

	test('prefix `id:12` lists matching ids but never `1012` / `0212`', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').fill('id:12');
		await expect(page.getByTestId('search-id-listbox')).toBeVisible({ timeout: 2000 });

		const visibleIds = await page
			.getByTestId('search-id-option')
			.evaluateAll((els) => els.map((e) => Number(e.getAttribute('data-poster-id'))));

		expect(visibleIds.length).toBeGreaterThan(0);
		for (const id of visibleIds) {
			expect(id.toString().startsWith('12')).toBe(true);
		}
		expect(visibleIds).not.toContain(1012);
		expect(visibleIds).not.toContain(212);
		expect(visibleIds.length).toBeLessThanOrEqual(10);
	});

	test('`id:9999` shows "No matching posters" + result list is empty', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const startUrl = page.url();

		await page.getByTestId('search-input').fill('id:9999');
		await expect(page.getByTestId('search-id-empty')).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('search-id-empty')).toContainText(/no matching posters/i);

		// Result list filters down to zero cards.
		await expect(page.getByTestId('result-card')).toHaveCount(0);

		// Enter is a no-op when nothing is selectable.
		await page.getByTestId('search-input').press('Enter');
		expect(page.url()).toBe(startUrl);
	});

	test('`id:` (no digits) shows hint + filters list to zero cards', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

		await page.getByTestId('search-input').fill('id:');
		await expect(page.getByTestId('search-id-hint')).toBeVisible({ timeout: 2000 });
		await expect(page.getByTestId('result-card')).toHaveCount(0);
	});

	test('backspacing the `id:` prefix restores the unfiltered result list', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const startingCount = await page.getByTestId('result-card').count();

		await page.getByTestId('search-input').fill('id:12');
		await expect(page.getByTestId('search-id-listbox')).toBeVisible({ timeout: 2000 });

		// Clear → exits navigator mode → result list returns.
		await page.getByTestId('search-input').fill('');
		await expect(page.getByTestId('search-id-listbox')).toBeHidden();
		// At minimum the original first card reappears.
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 2000 });
		// And the count returns to the unfiltered total (allow some
		// jitter — the search-result list may render lazily).
		const restoredCount = await page.getByTestId('result-card').count();
		expect(restoredCount).toBe(startingCount);
	});

	test('click on a suggestion filters the list to that single card', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const firstId = await page.getByTestId('result-card').first().getAttribute('data-poster-id');
		const startUrl = page.url();

		await page.getByTestId('search-input').fill(`id:${firstId}`);
		await expect(page.getByTestId('search-id-option')).toHaveCount(1);
		await page.getByTestId('search-id-option').first().click();

		// URL stays on home — no navigation.
		expect(page.url()).toBe(startUrl);
		// Search bar value commits to the exact id.
		await expect(page.getByTestId('search-input')).toHaveValue(`id:${firstId}`);
		// Listbox dismisses; result list shows the single card.
		await expect(page.getByTestId('search-id-listbox')).toBeHidden();
		await expect(page.getByTestId('result-card')).toHaveCount(1);
	});
});

test.describe('Stage 14 US2 — `g` keyboard shortcut', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('`g` from non-input area focuses search bar + inserts `id:`', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });

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
