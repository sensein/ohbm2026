/**
 * Shared e2e helpers.
 *
 * `waitForHomeReady` is the standard "page is fully hydrated and the
 * result list has stopped re-rendering" gate that every spec which
 * types into search / clicks a result card / asserts a result-count
 * delta should call right after `page.goto('./')` on the home route.
 *
 * UMAP is the heaviest async asset on the home page (lazy-loaded
 * Plotly chunk + WebGL canvas), so once its testid is visible the
 * main thread is idle and the result list has stopped flickering.
 * Without this gate, fast paths through `goto → fill('connectivity')
 * → click first card` race with hydration and can capture a card
 * that's replaced microseconds later — see browse.spec.ts:8 for the
 * regression this was added to absorb.
 */
import { expect, type Page } from '@playwright/test';

export async function waitForHomeReady(page: Page, timeoutMs = 15000): Promise<void> {
	await expect(page.getByTestId('search-input')).toBeVisible({ timeout: 3000 });
	await expect(page.getByTestId('umap-chart-2d')).toBeVisible({ timeout: timeoutMs });
}
