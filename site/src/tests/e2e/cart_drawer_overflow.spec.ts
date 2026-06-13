/**
 * Spec 025 — cart drawer must not overflow the viewport.
 *
 * Reported (Stage 24 follow-up): on atlas-root in Chrome/Edge the cart drawer
 * opened but its action buttons were not on screen — the drawer was taller than
 * the viewport and the footer was pushed below the fold. Root cause: the
 * scrollable item list (`.items`) lacked `min-height: 0`, so in a flex column
 * its default `min-height: auto` kept it at full content height (overflowing the
 * fixed-height drawer and pushing the footer off-screen) instead of scrolling.
 *
 * The CartDrawer is a single shared component across all subsites, so this is
 * exercised on the default (ohbm2026) baseURL with a deliberately SHORT viewport
 * and a large seeded cart. Before the fix the footer Clear button is below the
 * fold; after, it stays in the viewport and the item list scrolls.
 */

import { test, expect } from '@playwright/test';

// Short viewport so a modest cart overflows; cart is localStorage-backed via the
// `?cart=` deep link, so this does not depend on the data package.
test.use({ viewport: { width: 420, height: 560 } });

const MANY = Array.from({ length: 40 }, (_, i) => i + 1).join(',');

test('cart drawer footer stays on-screen with a full cart (no overflow)', async ({ page }) => {
	await page.goto(`./?cart=ohbm2026:${MANY}`);
	await expect(page.getByTestId('header-cart')).toBeVisible({ timeout: 20_000 });
	// Dismiss the first-visit analytics consent banner so it doesn't overlay the
	// drawer's footer buttons (it intercepts pointer events on a fresh context).
	const consent = page.getByTestId('consent-decline');
	if (await consent.isVisible().catch(() => false)) {
		await consent.click();
		await expect(page.getByTestId('consent-banner')).toHaveCount(0, { timeout: 5_000 });
	}

	await page.getByTestId('header-cart').click();
	await expect(page.getByTestId('cart-drawer')).toBeVisible({ timeout: 5_000 });

	// Enough rows to exceed the short viewport.
	await expect.poll(() => page.getByTestId('cart-item').count(), { timeout: 5_000 }).toBeGreaterThan(10);

	// The footer action buttons MUST be FULLY within the viewport (ratio: 1) —
	// the bug pushed them entirely below the fold.
	await expect(page.getByTestId('cart-clear')).toBeInViewport({ ratio: 1 });
	await expect(page.getByTestId('cart-copy')).toBeInViewport({ ratio: 1 });

	// And the Clear button is actually clickable (responds).
	await page.getByTestId('cart-clear').click();
	await expect.poll(() => page.getByTestId('cart-item').count(), { timeout: 4_000 }).toBe(0);
});
