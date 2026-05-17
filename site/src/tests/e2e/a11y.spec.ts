/**
 * T091 — axe-core accessibility audit.
 *
 * Walks the three primary surfaces (home / detail-permalink / about) at
 * desktop landscape and reports any axe-core violations at WCAG 2.1 A/AA
 * severities (`serious` + `critical`). Soft-fails informational issues —
 * the goal is to flag broken affordances, not perfect every contrast ratio.
 *
 * Run against the live production site:
 *   TARGET_BASE=https://abstractatlas.brainkb.org pnpm exec playwright test a11y
 *
 * Run against the PR preview:
 *   TARGET_BASE=https://abstractatlas.brainkb.org/pr-9 pnpm exec playwright test a11y
 */

import AxeBuilder from '@axe-core/playwright';
import { test, expect, chromium } from '@playwright/test';

test.setTimeout(180_000);

const BASE = process.env.TARGET_BASE || 'https://abstractatlas.brainkb.org';

async function auditRoute(
	pathSuffix: string,
	label: string,
	waitFor: string = 'main'
): Promise<void> {
	const browser = await chromium.launch();
	const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await ctx.newPage();
	const url = `${BASE.replace(/\/$/, '')}${pathSuffix}`;
	await page.goto(url, { waitUntil: 'load' });
	await page.waitForSelector(waitFor, { timeout: 30000 });
	await page.waitForTimeout(2500); // let hydration + data-package fetch settle

	const results = await new AxeBuilder({ page })
		.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
		.analyze();

	const critical = results.violations.filter((v) => v.impact === 'critical');
	const serious = results.violations.filter((v) => v.impact === 'serious');
	const moderate = results.violations.filter((v) => v.impact === 'moderate');
	const minor = results.violations.filter((v) => v.impact === 'minor');

	console.log(
		`[${label}] axe results: ${critical.length} critical, ${serious.length} serious, ${moderate.length} moderate, ${minor.length} minor`
	);
	for (const v of [...critical, ...serious]) {
		console.log(`  · ${v.impact?.toUpperCase()} (${v.id}) — ${v.help}`);
		for (const node of v.nodes.slice(0, 3)) {
			console.log(`      target: ${node.target}`);
		}
	}
	for (const v of moderate.slice(0, 3)) {
		console.log(`  · MODERATE (${v.id}) — ${v.help}`);
	}
	await browser.close();
	// Critical / serious fail the test; moderate / minor are logged only.
	expect(critical, `critical a11y issues on ${label}`).toEqual([]);
	expect(serious, `serious a11y issues on ${label}`).toEqual([]);
}

test('axe — home page', async () => {
	await auditRoute('/', 'home', '[data-testid="search-input"]');
});

test('axe — about page', async () => {
	await auditRoute('/about/', 'about', 'main');
});

test('axe — abstract permalink page', async () => {
	const browser = await chromium.launch();
	const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
	const page = await ctx.newPage();
	await page.goto(`${BASE.replace(/\/$/, '')}/`, { waitUntil: 'load' });
	await page.waitForSelector('[data-testid="result-card"]', { timeout: 30000 });
	const posterId = await page.locator('[data-testid="result-card"]').first().getAttribute('data-poster-id');
	await browser.close();
	if (!posterId) {
		test.skip();
		return;
	}
	await auditRoute(
		`/abstract/${encodeURIComponent(posterId)}/`,
		`permalink-${posterId}`,
		'[data-testid="detail-panel"]'
	);
});
