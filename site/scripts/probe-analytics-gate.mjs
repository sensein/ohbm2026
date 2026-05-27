/**
 * Verify the PR-preview gate from PR #45. On a PR preview URL,
 * gtag MUST NOT load and the consent banner MUST NOT appear,
 * regardless of trailing-slash presence (Gemini #45 fix).
 *
 * Run: pnpm exec node scripts/probe-analytics-gate.mjs
 *      (override target via PROBE_PREVIEW_BASE env var)
 */
import { chromium } from '@playwright/test';

const PREVIEW_BASE = process.env.PROBE_PREVIEW_BASE ?? 'https://abstractatlas.brainkb.org/pr-45';

const browser = await chromium.launch({
	headless: true,
	args: ['--enable-unsafe-swiftshader', '--use-gl=swiftshader']
});

// Both forms must be gated — with AND without trailing slash. The
// post-fix regex is `/^\/pr-\d+(\/|$)/`; the pre-fix regex was
// `/^\/pr-\d+\//` and would have failed the no-slash form.
const SCENARIOS = [
	{ name: 'preview path /pr-45/', url: `${PREVIEW_BASE}/` },
	{ name: 'preview path /pr-45 (NO trailing slash)', url: `${PREVIEW_BASE}` }
];

let pass = 0;
let fail = 0;

for (const sc of SCENARIOS) {
	const ctx = await browser.newContext();
	const page = await ctx.newPage();

	const gtagRequests = [];
	page.on('request', (r) => {
		const u = r.url();
		if (u.includes('googletagmanager.com') || u.includes('google-analytics.com')) {
			gtagRequests.push(u);
		}
	});

	let nav_status = null;
	try {
		const resp = await page.goto(sc.url, { waitUntil: 'networkidle', timeout: 30_000 });
		nav_status = resp?.status() ?? null;
	} catch (err) {
		console.log(`✗ ${sc.name}\n   navigation failed: ${err.message}`);
		fail += 1;
		await ctx.close();
		continue;
	}

	// Wait a beat past 'networkidle' so any deferred analytics fetch
	// has a chance to fire.
	await page.waitForTimeout(2000);

	const consentState = await page.evaluate(
		() => /** @type {{ __ohbmAnalyticsConsent?: string }} */ (window).__ohbmAnalyticsConsent ?? null
	);
	const bannerVisible = await page
		.locator('[data-testid="consent-banner"]')
		.isVisible()
		.catch(() => false);

	const gtagOk = gtagRequests.length === 0;
	const bannerOk = bannerVisible === false;
	const stateOk = consentState === 'pr-preview';
	const ok = gtagOk && bannerOk && stateOk;

	console.log(`${ok ? '✓' : '✗'} ${sc.name}`);
	console.log(
		`   url=${sc.url}  http=${nav_status}  consentState=${consentState} (expected pr-preview)`
	);
	console.log(
		`   gtagRequests=${gtagRequests.length} (expected 0)  bannerVisible=${bannerVisible} (expected false)`
	);
	if (!gtagOk) {
		console.log(`   gtag urls: ${gtagRequests.slice(0, 3).join(', ')}`);
	}

	if (ok) pass += 1;
	else fail += 1;

	await ctx.close();
}

console.log('');
console.log(`=== ${pass}/${pass + fail} scenarios passed ===`);
await browser.close();
process.exit(fail === 0 ? 0 : 1);
