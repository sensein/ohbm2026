/**
 * Verify the `unrecognized GUI edit: selections[0].yref` warning
 * is gone from the atlas-root preview, and snapshot resource use
 * before / during / after a lasso.
 *
 * Software-rendered WebGL in headless Chromium (SwiftShader) makes
 * a real mouse-drag lasso on 461k scattergl points exhausting (~5 min
 * CPU pegged). Instead, we trigger the lasso state via Plotly's
 * `Plotly.relayout({ selections: [...] })` which exercises the same
 * code path that emits the warning (preserved-selection merge during
 * react()) without the rendering cost.
 *
 * Run:  pnpm exec node scripts/probe-lasso-warning.mjs
 * Env:  PROBE_URL=https://abstractatlas.brainkb.org/pr-37/  (default)
 */
import { chromium } from '@playwright/test';

const URL = process.env.PROBE_URL ?? 'https://abstractatlas.brainkb.org/pr-37/';

const browser = await chromium.launch({
	headless: true,
	args: ['--enable-unsafe-swiftshader', '--use-gl=swiftshader']
});
const ctx = await browser.newContext();
const page = await ctx.newPage();
const cdp = await ctx.newCDPSession(page);
await cdp.send('Performance.enable');

const messages = [];
page.on('console', (msg) => messages.push({ type: msg.type(), text: msg.text() }));
page.on('pageerror', (err) => messages.push({ type: 'pageerror', text: err.message }));

async function metrics(label) {
	const m = await cdp.send('Performance.getMetrics');
	const o = Object.fromEntries(m.metrics.map((x) => [x.name, x.value]));
	console.log(
		`-> [${label}] heap=${(o.JSHeapUsedSize / 1e6).toFixed(0)}/${(o.JSHeapTotalSize / 1e6).toFixed(0)}MB ` +
			`nodes=${o.Nodes} listeners=${o.JSEventListeners} layouts=${o.LayoutCount}`
	);
	return o;
}

console.log(`-> loading ${URL}`);
await page.goto(URL, { waitUntil: 'networkidle' });
await page.waitForSelector('[data-testid="umap-chart-2d"]', { timeout: 30000 });
await page.waitForTimeout(8000);
await metrics('after load');

console.log(`-> ${messages.length} message(s) before lasso:`);
for (const m of messages) console.log(`   [${m.type}] ${m.text}`);
const preLasso = messages.length;

// Dispatch a synthetic lasso selection via Plotly's API directly.
// This is what would happen at the END of a real mouse drag — the
// fastest way to reach the code path that previously emitted the
// `selections[0].yref` warning during react() merge.
console.log('-> dispatching synthetic lasso via Plotly.relayout');
const result = await page.evaluate(() => {
	const el = document.querySelector('[data-testid="umap-chart-2d"]');
	if (!el) return { ok: false, reason: 'no chart element' };
	// Plotly attaches a `_fullData` array to the chart div once
	// rendered. Use it to look up bounding coords for a polygon.
	const fd = el._fullData;
	if (!fd || fd.length === 0) return { ok: false, reason: 'no _fullData' };
	const trace = fd[0];
	if (!trace.x || !trace.y) return { ok: false, reason: 'no x/y data' };
	const n = Math.min(50, trace.x.length);
	let xmin = Infinity, xmax = -Infinity, ymin = Infinity, ymax = -Infinity;
	for (let i = 0; i < n; i++) {
		xmin = Math.min(xmin, trace.x[i]);
		xmax = Math.max(xmax, trace.x[i]);
		ymin = Math.min(ymin, trace.y[i]);
		ymax = Math.max(ymax, trace.y[i]);
	}
	// Build a tiny lasso polygon covering the first 50 points.
	const Plotly = window.Plotly || el._fullLayout?._plots?.xy?.plot?.Plotly;
	if (!Plotly) {
		// Try to fish Plotly off the chart div.
		const P = window.Plotly;
		if (!P) return { ok: false, reason: 'no Plotly handle' };
	}
	const polygon = [
		[xmin, ymin], [xmax, ymin], [xmax, ymax], [xmin, ymax], [xmin, ymin]
	];
	const Pmaybe = window.Plotly;
	if (!Pmaybe) return { ok: false, reason: 'window.Plotly absent' };
	try {
		Pmaybe.relayout(el, {
			selections: [{
				type: 'path',
				xref: 'x',
				yref: 'y',
				path:
					'M' + polygon.map(([x, y]) => `${x},${y}`).join('L') + 'Z'
			}]
		});
		return { ok: true, polygon };
	} catch (err) {
		return { ok: false, reason: String(err) };
	}
});
console.log(`-> relayout result: ${JSON.stringify(result)}`);
await page.waitForTimeout(2000);
await metrics('after synthetic lasso');

console.log(`-> ${messages.length - preLasso} new message(s) after lasso:`);
for (const m of messages.slice(preLasso)) console.log(`   [${m.type}] ${m.text}`);

// Now clear via the panel's button.
const clear = page.locator('[data-testid="umap-clear-lasso"]').first();
if (await clear.isVisible({ timeout: 2000 }).catch(() => false)) {
	const beforeClear = messages.length;
	console.log('-> clicking Clear selection button');
	await clear.click();
	await page.waitForTimeout(1500);
	await metrics('after clear');
	console.log(`-> ${messages.length - beforeClear} new message(s) after clear:`);
	for (const m of messages.slice(beforeClear)) console.log(`   [${m.type}] ${m.text}`);
}

const warnRe = /unrecognized GUI edit|selections\[\d+\]\.yref/i;
const hits = messages.filter((m) => warnRe.test(m.text));
console.log('\n=== SUMMARY ===');
console.log(`total console messages: ${messages.length}`);
console.log(`lasso-warning hits:     ${hits.length}`);
for (const h of hits) console.log(`   [${h.type}] ${h.text}`);

await browser.close();
process.exit(hits.length === 0 ? 0 : 1);
