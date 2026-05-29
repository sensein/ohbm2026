import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

test.describe('US2: UMAP panel + lasso + model selector', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	// The `showMap` store defaults to true (new users land with the map
	// open). Reset it on every test in this file so the "click toggle to
	// open" sequences below test the open transition deterministically.
	test.beforeEach(async ({ context }) => {
		await context.addInitScript(() => {
			try {
				window.localStorage.setItem('ohbm2026.ui.showMap.v1', '0');
			} catch {
				/* private mode / sandboxed about:blank — best effort */
			}
		});
	});

	test('opens map; lazy-loads Plotly; both 2D + 3D charts render side-by-side', async ({
		page
	}) => {
		await page.goto('./');
		await expect(page.getByTestId('result-count')).toBeVisible({ timeout: 15_000 });
		await expect(page.getByTestId('umap-panel')).toHaveCount(0);

		await page.getByTestId('toggle-map').click();
		await expect(page.getByTestId('umap-panel')).toBeVisible();
		await expect(page.getByTestId('umap-chart-2d')).toBeVisible();
		await expect(page.getByTestId('umap-chart-3d')).toBeVisible();

		// Plotly lazy-loads — wait for the 2D pane to render an SVG/canvas.
		await expect
			.poll(
				async () =>
					page
						.locator('[data-testid="umap-chart-2d"] svg, [data-testid="umap-chart-2d"] canvas')
						.count(),
				{ timeout: 15000 }
			)
			.toBeGreaterThan(0);
		// 3D pane renders a WebGL canvas inside `.gl-container`.
		await expect
			.poll(
				async () =>
					page.locator('[data-testid="umap-chart-3d"] canvas').count(),
				{ timeout: 15000 }
			)
			.toBeGreaterThan(0);
	});

	test('rotate toggle pauses / resumes the 3D animation', async ({ page }) => {
		await page.goto('./');
		await page.getByTestId('toggle-map').click();
		await expect(page.getByTestId('umap-chart-3d')).toBeVisible();
		const btn = page.getByTestId('umap-rotate-toggle');
		await expect(btn).toBeVisible();
		// Initial state: rotating (aria-pressed=true, label "⏸ pause").
		await expect(btn).toHaveAttribute('aria-pressed', 'true');
		await btn.click();
		await expect(btn).toHaveAttribute('aria-pressed', 'false');
		await btn.click();
		await expect(btn).toHaveAttribute('aria-pressed', 'true');
	});

	test('lasso selection (simulated) updates the result list count', async ({ page }) => {
		await page.goto('./');
		await page.getByTestId('toggle-map').click();
		await expect(page.getByTestId('umap-chart-2d')).toBeVisible();
		await expect
			.poll(
				async () =>
					page
						.locator('[data-testid="umap-chart-2d"] svg, [data-testid="umap-chart-2d"] canvas')
						.count(),
				{ timeout: 15000 }
			)
			.toBeGreaterThan(0);

		const initialCount = Number(
			(await page.getByTestId('result-count').textContent())?.trim()
		);
		expect(initialCount).toBeGreaterThan(100);

		const ok = await page.evaluate(() => {
			const el = document.querySelector('[data-testid="umap-chart-2d"]') as unknown as {
				emit?: (event: string, payload: unknown) => void;
			} | null;
			if (!el?.emit) return false;
			el.emit('plotly_selected', {
				points: [{ pointIndex: 0 }, { pointIndex: 1 }, { pointIndex: 2 }]
			});
			return true;
		});
		expect(ok).toBe(true);

		const clear = page.getByTestId('umap-clear-lasso');
		await expect(clear).toBeVisible({ timeout: 3000 });
		// 3-point lasso → 3 abstracts selected → result-count drops to 3.
		await expect(page.getByTestId('result-count')).toHaveText('3', { timeout: 3000 });
		await clear.click();
		await expect(clear).toHaveCount(0);
	});
});
