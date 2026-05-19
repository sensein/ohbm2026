/**
 * T071 — US5 cart acceptance.
 *
 * Exercises FR-006 + SC-009:
 *   - Adding an abstract via the result card's cart icon makes it appear in
 *     the cart drawer.
 *   - The cart survives a full page reload (localStorage-backed store).
 *   - Removing from the drawer (and from the result card) zeroes the count.
 *   - `cart-email` opens a `mailto:` URL whose body contains the cart's
 *     poster_ids.
 */

import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('US5: saved-list cart + email export', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('add via card icon, reload, drawer still shows the item', async ({ page }) => {
		await page.goto('./');
		await page.getByTestId('search-input').waitFor();
		const card = page.getByTestId('result-card').first();
		await card.waitFor({ timeout: 10_000 });
		const posterId = await card.getAttribute('data-poster-id');
		expect(posterId).toBeTruthy();
		// The card-level add button is a sibling of `.card-body` (the
		// element that carries `result-card`); both live under `<li.card>`,
		// so we scope the cart-add lookup to the parent <li>.
		await card.locator('xpath=..').getByTestId('card-cart-add').click();
		// Open the cart drawer and let Playwright auto-wait for the first
		// item — web-first assertions retry until the UI converges, no
		// hand-rolled `waitForTimeout` needed.
		await page.getByTestId('toggle-cart').click();
		await expect(page.getByTestId('cart-drawer')).toBeVisible();
		await expect(page.getByTestId('cart-item').first()).toBeVisible();
		// Reload — the cart store hydrates from localStorage on mount.
		await page.reload();
		await page.getByTestId('toggle-cart').click();
		await expect(page.getByTestId('cart-drawer')).toBeVisible();
		await expect(page.getByTestId('cart-item').first()).toBeVisible();
	});

	test('clear empties the cart', async ({ page }) => {
		await page.goto('./');
		await page.getByTestId('search-input').waitFor();
		await page
			.getByTestId('result-card')
			.first()
			.locator('xpath=..')
			.getByTestId('card-cart-add')
			.click();
		await page.getByTestId('toggle-cart').click();
		await expect(page.getByTestId('cart-drawer')).toBeVisible();
		await expect(page.getByTestId('cart-item').first()).toBeVisible();
		await page.getByTestId('cart-clear').click();
		await expect(page.getByTestId('cart-item')).toHaveCount(0);
	});

	test('email-my-list opens a mailto: URL with the poster_ids', async ({ page }) => {
		await page.goto('./');
		await page.getByTestId('search-input').waitFor();
		const card = page.getByTestId('result-card').first();
		await card.waitFor({ timeout: 10_000 });
		const posterId = (await card.getAttribute('data-poster-id')) ?? '';
		await card.locator('xpath=..').getByTestId('card-cart-add').click();
		await page.getByTestId('toggle-cart').click();
		// Wait for at least one cart item to render — the email anchor's
		// href is recomputed reactively from the cart contents.
		await expect(page.getByTestId('cart-item').first()).toBeVisible();
		// We never actually NAVIGATE the mailto: link (that'd open the user's
		// mail client). The anchor's `href` is the source of truth — read it.
		const emailLink = page.getByTestId('cart-email');
		const href = await emailLink.getAttribute('href');
		expect(href).toMatch(/^mailto:/);
		// The body parameter should mention the poster_id we just added.
		const decoded = decodeURIComponent(href ?? '');
		expect(decoded).toContain(posterId);
		// Stage 9 (spec 009-conference-subpath FR-102 + T016): the embedded
		// permalink MUST live under the conference subpath, not at the bare
		// `/abstract/<id>` root. Guards against a regression where the
		// permalink composer drops the SvelteKit `base`.
		expect(decoded).toContain('/ohbm2026/abstract/');
	});
});
