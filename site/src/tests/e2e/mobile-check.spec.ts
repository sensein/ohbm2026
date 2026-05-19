import { test, chromium, devices } from '@playwright/test';

test.setTimeout(120_000);

const probes = [
  { label: 'iSE-1st-portrait', viewport: { width: 320, height: 568 }, mobile: true },
  { label: 'iSE-2nd-portrait', viewport: { width: 375, height: 667 }, mobile: true },
  { label: 'iSE-1st-landscape', viewport: { width: 568, height: 320 }, mobile: true },
  { label: 'iSE-2nd-landscape', viewport: { width: 667, height: 375 }, mobile: true },
  { label: 'tablet-portrait', viewport: { width: 768, height: 1024 }, mobile: true },
  { label: 'desktop-landscape', viewport: { width: 1440, height: 900 }, mobile: false }
];

// Was hardcoded to the PR-9 preview (long since closed). Default to
// local; honour PLAYWRIGHT_BASE_URL for CI runs against PR preview /
// production. The mobile-check probe is geometry-only, so any deploy
// that renders the same DOM passes. BASE is the FULL URL of the
// conference home (including any per-deploy prefix); we strip the
// trailing slash so `${BASE}/abstract/<id>/` composes cleanly.
const BASE = (
	process.env.PLAYWRIGHT_BASE_URL ||
	process.env.TARGET_BASE ||
	'http://127.0.0.1:4173/ohbm2026'
).replace(/\/$/, '');

test('multi-viewport overflow probe', async () => {
  const browser = await chromium.launch();
  for (const probe of probes) {
    const ctx = await browser.newContext({ viewport: probe.viewport, isMobile: probe.mobile, deviceScaleFactor: probe.mobile ? 2 : 1 });
    const page = await ctx.newPage();
    await page.goto(`${BASE}/`, { waitUntil: 'load' });
    await page.waitForSelector('[data-testid="search-input"]', { timeout: 30000 });
    await page.waitForSelector('[data-testid="result-card"]', { timeout: 30000 });
    await page.waitForTimeout(2000);

    const scroll = await page.evaluate(() => ({
      docW: document.documentElement.scrollWidth,
      viewW: document.documentElement.clientWidth,
      overflow: document.documentElement.scrollWidth - document.documentElement.clientWidth
    }));
    console.log(`${probe.label} (${probe.viewport.width}x${probe.viewport.height}): docW=${scroll.docW} viewW=${scroll.viewW} overflow=${scroll.overflow}`);

    if (scroll.overflow > 0) {
      const widest = await page.evaluate(() => {
        const viewW = document.documentElement.clientWidth;
        const out: any[] = [];
        for (const el of document.querySelectorAll('*')) {
          const r = (el as HTMLElement).getBoundingClientRect();
          if (r.right > viewW + 1 && r.width < 2000) {
            out.push({ tag: el.tagName, tid: (el as HTMLElement).getAttribute('data-testid'), w: Math.round(r.width), right: Math.round(r.right) });
          }
        }
        return out.sort((a,b)=>b.right-a.right).slice(0, 8);
      });
      console.log(`  overflowing on ${probe.label}:`);
      for (const e of widest) console.log(`    <${e.tag}> tid=${e.tid} w=${e.w} right=${e.right}`);
    }
    await page.screenshot({ path: `/tmp/probe-${probe.label}.png`, fullPage: false });

    // Also tap a card to see the detail layout
    const card = page.locator('[data-testid="result-card"]').first();
    const posterId = await card.getAttribute('data-poster-id');
    await card.click();
    await page.waitForSelector('[data-testid="detail-panel"]', { timeout: 8000 }).catch(() => null);
    await page.waitForTimeout(800);
    await page.screenshot({ path: `/tmp/probe-${probe.label}-detail.png`, fullPage: false });

    if (posterId && !probe.mobile) {
      // The abstract permalink lives under `${BASE}/abstract/<id>/`
      // because BASE already terminates at the conference home (FR-104).
      const dp = await ctx.newPage();
      await dp.goto(`${BASE}/abstract/${encodeURIComponent(posterId)}/`, { waitUntil: 'load' });
      await dp.waitForSelector('[data-testid="detail-panel"]', { timeout: 30000 });
      await dp.waitForTimeout(1500);
      await dp.screenshot({ path: `/tmp/probe-${probe.label}-permalink.png`, fullPage: false });
    }
    await ctx.close();
  }
  await browser.close();
});
