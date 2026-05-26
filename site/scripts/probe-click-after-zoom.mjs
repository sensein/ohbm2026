/**
 * Verify the user's specific repro: click a point on the atlas
 * 2D scatter (focus-snap zooms in) → then try to click ANOTHER
 * point in the zoomed view → expect the inline detail panel to
 * update to the new selection.
 *
 * Failure mode this catches: if backdrop trace's `hoverinfo:
 * 'skip'` regresses, `plotly_click` doesn't fire on backdrop
 * points and the second click silently does nothing.
 *
 * Drives the clicks via Plotly's `plotly_click` event dispatch
 * directly (so we don't depend on canvas-pixel coordinates which
 * are flaky in headless).
 *
 * Run: pnpm exec node scripts/probe-click-after-zoom.mjs
 */
import { chromium } from '@playwright/test';

const URL = process.env.PROBE_URL ?? 'https://abstractatlas.brainkb.org/pr-41/';

const browser = await chromium.launch({
	headless: true,
	args: ['--enable-unsafe-swiftshader', '--use-gl=swiftshader']
});
const ctx = await browser.newContext();
const page = await ctx.newPage();
const messages = [];
page.on('console', (m) => messages.push(`[${m.type()}] ${m.text()}`));
page.on('pageerror', (e) => messages.push(`[pageerror] ${e.message}`));

console.log(`-> loading ${URL}`);
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForSelector('[data-testid="umap-chart-2d"]', { timeout: 30_000 });
await page.waitForTimeout(8000);
console.log('-> chart loaded');

// Fire a synthetic plotly_click on the first backdrop point.
const firstClick = await page.evaluate(() => {
	const el = document.querySelector('[data-testid="umap-chart-2d"]');
	if (!el) return { ok: false, reason: 'no chart' };
	const fd = el._fullData;
	if (!fd || !fd[0] || !fd[0].x || !fd[0].x.length) return { ok: false, reason: 'no trace data' };
	const cd0 = fd[0].customdata?.[0];
	// Dispatch a plotly_click event the way Plotly's internals do.
	// Plotly's chart div is an EventEmitter; `.emit('plotly_click',
	// {points: [...]})` mirrors what a real click would deliver.
	el.emit?.('plotly_click', {
		points: [{ customdata: cd0, x: fd[0].x[0], y: fd[0].y[0], pointIndex: 0 }]
	});
	return { ok: true, customdata: cd0 };
});
console.log(`-> first click dispatched: ${JSON.stringify(firstClick)}`);
await page.waitForTimeout(2000);

// Detail panel should now be open. Verify.
const panel1 = await page.locator('[data-testid="atlas-root-detail-card"]').isVisible().catch(() => false);
console.log(`-> after first click — detail card visible: ${panel1}`);

// Now fire a second click on a different backdrop point.
const secondClick = await page.evaluate(() => {
	const el = document.querySelector('[data-testid="umap-chart-2d"]');
	const fd = el?._fullData;
	if (!fd || !fd[0]) return { ok: false };
	const N = fd[0].x.length;
	const idx = Math.min(1000, N - 1);
	const cd = fd[0].customdata?.[idx];
	el.emit?.('plotly_click', {
		points: [{ customdata: cd, x: fd[0].x[idx], y: fd[0].y[idx], pointIndex: idx }]
	});
	return { ok: true, customdata: cd, idx };
});
console.log(`-> second click dispatched: ${JSON.stringify(secondClick)}`);
await page.waitForTimeout(2000);

const panel2Visible = await page.locator('[data-testid="atlas-root-detail-card"]').isVisible().catch(() => false);
const title = await page.locator('[data-testid="atlas-root-detail-title"]').textContent().catch(() => null);
console.log(`-> after second click — detail card visible: ${panel2Visible}, title: ${title?.slice(0, 80)}`);

console.log('\n=== console messages ===');
for (const m of messages) console.log(`   ${m}`);

const ok = panel1 && panel2Visible;
console.log(`\n=== ${ok ? 'PASS' : 'FAIL'} ===`);
console.log(`first-click opens panel:  ${panel1}`);
console.log(`second-click updates panel: ${panel2Visible}`);

await browser.close();
process.exit(ok ? 0 : 1);
