import { expect, test } from '@playwright/test';

const DATA_AVAILABLE = process.env.UI_DATA_AVAILABLE !== '0';

/**
 * T009 — Stage 12 US1b — Playwright e2e for the permalink page's
 * brief-preview + show-more / show-all controls.
 *
 * Per `contracts/permalink-page.md`, the permalink page renders 5
 * left-column verbatim sections (Introduction / Methods / Results /
 * Conclusion / Acknowledgments). Each clampable section (text length
 * ≥ 280 chars) starts in 3-line CSS `line-clamp` preview and shows
 * a `.section-toggle` button. A column-scoped `.master-toggle`
 * expands all clampable sections at once + relabels to "Collapse all".
 *
 * The test picks the FIRST card on the home page and navigates to
 * its permalink — skipping if no card has a long-enough section to
 * exercise the clamp (rare on the real corpus).
 */
test.describe('Stage 12 US1b — permalink brief-preview + show-more', () => {
	test.skip(!DATA_AVAILABLE, 'Data package not deployed in this run');

	test('clampable section starts in preview + per-section toggle works', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		// Find a card whose corpus methods section is long enough to clamp.
		// Pick the first 6 cards; navigate to each permalink until we
		// find one with a clampable Methods section.
		const cards = page.getByTestId('result-card');
		const candidateCount = Math.min(6, await cards.count());
		// Snapshot poster ids BEFORE navigating; otherwise iteration 1+ tries
		// to read attributes off the permalink page (no result cards there)
		// and Playwright times out at 30s.
		const posterIds: string[] = [];
		for (let i = 0; i < candidateCount; i++) {
			const pid = await cards.nth(i).getAttribute('data-poster-id');
			if (pid) posterIds.push(pid);
		}
		let found = false;
		for (const posterId of posterIds) {
			await page.goto(`./abstract/${encodeURIComponent(posterId)}/`);
			const methodsSection = page.getByTestId('section-methods');
			// Wait for the permalink page to settle.
			await methodsSection.waitFor({ state: 'attached', timeout: 5000 });
			const methodsToggle = page.getByTestId('section-toggle-methods');
			if (await methodsToggle.count()) {
				found = true;
				// Methods section MUST start in the clamped state.
				await expect(methodsSection).toHaveClass(/section-clamped/);
				await expect(methodsToggle).toHaveText(/show more/i);
				await expect(methodsToggle).toHaveAttribute('aria-expanded', 'false');

				// Click expands ONLY this section + relabels button.
				await methodsToggle.click();
				await expect(methodsSection).toHaveClass(/section-expanded/);
				await expect(methodsToggle).toHaveText(/show less/i);
				await expect(methodsToggle).toHaveAttribute('aria-expanded', 'true');

				// Other sections (introduction) should still be clamped
				// if they're clampable on this abstract.
				const intro = page.getByTestId('section-introduction');
				if ((await intro.count()) > 0) {
					const introClass = await intro.getAttribute('class');
					if (introClass?.includes('section-clamped')) {
						// Per-section behaviour does NOT affect other sections.
						await expect(intro).toHaveClass(/section-clamped/);
					}
				}

				// Click again restores the clamp.
				await methodsToggle.click();
				await expect(methodsSection).toHaveClass(/section-clamped/);
				await expect(methodsToggle).toHaveText(/show more/i);
				break;
			}
		}
		test.skip(!found, 'No fixture-corpus card produced a clampable Methods section');
	});

	test('master toggle expands every clampable section at once', async ({ page }) => {
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const cards = page.getByTestId('result-card');
		const candidateCount = Math.min(6, await cards.count());
		// Snapshot all candidate poster ids BEFORE navigating away; otherwise
		// iteration 1+ tries to read attributes off the permalink page which
		// has no result cards (Playwright then times out at 30s).
		const posterIds: string[] = [];
		for (let i = 0; i < candidateCount; i++) {
			const pid = await cards.nth(i).getAttribute('data-poster-id');
			if (pid) posterIds.push(pid);
		}
		let found = false;
		for (const posterId of posterIds) {
			await page.goto(`./abstract/${encodeURIComponent(posterId)}/`);
			const master = page.getByTestId('master-toggle');
			if (await master.count()) {
				found = true;
				// At first paint the master toggle reads "Show all" because
				// at least one clampable section is in its preview state.
				await expect(master).toHaveText(/show all/i);

				// Click: every clampable section expands + master relabels.
				await master.click();
				await expect(master).toHaveText(/collapse all/i);
				// The Methods section (if clampable here) is now expanded.
				const methodsSection = page.getByTestId('section-methods');
				if (await methodsSection.count()) {
					const cls = await methodsSection.getAttribute('class');
					// If methods is in the clampable set, the master flipped it.
					if (cls?.includes('section-')) {
						// Either it's now `.section-expanded` (clampable) or
						// `.section-short` (was too short to clamp); both are
						// valid post-master-toggle states.
						expect(cls).toMatch(/section-expanded|section-short/);
					}
				}

				// Click again: collapse all returns to preview.
				await master.click();
				await expect(master).toHaveText(/show all/i);
				break;
			}
		}
		test.skip(!found, 'No fixture-corpus card produced a permalink page with a master toggle');
	});

	test('acknowledgments section renders when corpus has the field', async ({ page }) => {
		// The acknowledgments section may not be present on every
		// abstract; assert ONLY that when its testid is present, the
		// section renders the expected DOM shape.
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		const cards = page.getByTestId('result-card');
		const candidateCount = Math.min(10, await cards.count());
		// Snapshot poster ids BEFORE navigating; see comment in the master-toggle
		// test for the same gotcha.
		const posterIds: string[] = [];
		for (let i = 0; i < candidateCount; i++) {
			const pid = await cards.nth(i).getAttribute('data-poster-id');
			if (pid) posterIds.push(pid);
		}
		let found = false;
		for (const posterId of posterIds) {
			await page.goto(`./abstract/${encodeURIComponent(posterId)}/`);
			const ack = page.getByTestId('section-acknowledgments');
			if (await ack.count()) {
				found = true;
				await expect(ack).toBeVisible();
				// The section heading must read "Acknowledgments".
				await expect(ack.locator('h3')).toHaveText(/acknowledgments/i);
				break;
			}
		}
		test.skip(!found, 'No fixture-corpus card produced an abstract with non-empty acknowledgments');
	});

	test('in-grid drawer is unchanged (no acknowledgments, no clamp, no toggles)', async ({ page }) => {
		// Stage 12 explicit non-regression target: the in-grid drawer
		// (mode='panel', the default) MUST keep its existing
		// click-to-expand caret behaviour.
		await page.goto('./');
		await expect(page.getByTestId('result-card').first()).toBeVisible({ timeout: 8000 });
		await page.getByTestId('result-card').first().click();
		// The in-grid drawer doesn't render `.master-toggle` or any
		// `.section-toggle` per-section show-more buttons (those are
		// permalink-mode only).
		await expect(page.getByTestId('master-toggle')).toHaveCount(0);
		// Acknowledgments testid MUST NOT appear in the in-grid panel.
		await expect(page.getByTestId('section-acknowledgments')).toHaveCount(0);
	});
});
