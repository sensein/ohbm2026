import { test, expect } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

/**
 * T036a / FR-011 — the detail panel surfaces **only** the Topics + Methods
 * extra-question fields. Other submission-form extras (study_type,
 * population, field_strength, processing_packages, species, etc.) live in
 * `facets` for filtering but MUST NOT render in the detail panel.
 *
 * Negative test: scan the panel's DOM for any leakage of the other facet
 * keys. The fixture-style assertion here scans the live corpus instead of a
 * synthetic abstract — that catches both component bugs and accidental
 * shard-schema regressions.
 */
test.describe('FR-011 — detail panel renders only Topics + Methods extras', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('opening any abstract shows topics + methods + no other facet keys as headings', async ({
		page
	}) => {
		// The home-page inline detail pane renders DetailPanel with
		// `compact={true}` and hides topics / methods / sections by design.
		// FR-011 applies to the FULL detail view, which lives at the
		// permalink route — navigate there for the assertion.
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 5000 });
		const firstCard = page.getByTestId('result-card').first();
		const posterId = await firstCard.getAttribute('data-poster-id');
		await page.goto(`./abstract/${encodeURIComponent(posterId!)}/`);
		await expect(page.getByTestId('detail-panel')).toBeVisible();

		// Allowed extra-question sections — at least one must be visible.
		const topicsCount = await page.getByTestId('extra-topics').count();
		const methodsCount = await page.getByTestId('extra-methods').count();
		expect(topicsCount + methodsCount).toBeGreaterThan(0);

		// Forbidden extra-question keys must NOT appear as testid'd blocks.
		const forbidden = [
			'extra-study_type',
			'extra-population',
			'extra-field_strength',
			'extra-processing_packages',
			'extra-species',
			'extra-recording_technology',
			'extra-brain_regions',
			'extra-brain_networks',
			'extra-keywords'
		];
		for (const key of forbidden) {
			await expect(page.getByTestId(key)).toHaveCount(0);
		}

		// Defensive: every <h2> in the detail panel must start with an
		// allowed lead word. Each h2 can carry trailing helper text in a
		// <span class="hint-inline"> or <span class="muted"> ("Authors
		// click to filter by author", "Cluster membership — per (model
		// × input)"), so we substring-match the lead.
		const headings = await page.getByTestId('detail-panel').locator('h2').allTextContents();
		const allowedLeads = [
			'Authors',
			'Introduction',
			'Methods',
			'Results',
			'Conclusion',
			'Topics',
			'References',
			'Cluster membership',
			'Related abstracts'
		];
		for (const h of headings) {
			const trimmed = h.trim();
			const ok = allowedLeads.some((lead) => trimmed.startsWith(lead));
			expect(ok, `heading "${trimmed}" not in allowedLeads`).toBe(true);
		}
	});
});
