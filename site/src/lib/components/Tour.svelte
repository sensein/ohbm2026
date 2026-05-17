<script lang="ts">
	import { onDestroy } from 'svelte';
	import { page } from '$app/stores';
	import { focusedAbstract } from '$lib/stores/selection';
	import { tourStore, tourPhase } from '$lib/stores/tour';

	/**
	 * Shepherd.js wrapper for the US6 guided tour.
	 *
	 * Three route-keyed tour configurations:
	 *
	 *   home    (`/`)                       — search, model, map, lasso (desktop),
	 *                                          facets, click-a-card to open the
	 *                                          related-works detail pane, the
	 *                                          per-card cart icon, then the
	 *                                          "full details" permalink link.
	 *   detail  (`/abstract/<poster_id>/`)  — the two zones (submitter vs.
	 *                                          computed), claims, figures,
	 *                                          related abstracts, cluster
	 *                                          membership, cart action.
	 *   about   (`/about/`)                 — overview, per-stage TL;DR toggles.
	 *
	 * When the user navigates between routes mid-tour, the current shepherd
	 * instance is cancelled — we do NOT auto-continue with a stale step list
	 * pointing at elements that don't exist on the new page.
	 *
	 * Lazy-loaded: shepherd.js + its CSS only load when a tour actually starts.
	 */

	type TourKind = 'home' | 'detail' | 'about' | 'unknown';

	let shepherdInstance: {
		start: () => void;
		cancel: () => void;
		complete: () => void;
	} | null = null;
	let activePathname: string | null = null;

	function detectKind(pathname: string): TourKind {
		// Route detection is base-path-agnostic: we only look at whether the
		// URL contains `/abstract/<id>/` or `/about/`. Anything else is home.
		if (/\/abstract\/[^/]+\/?$/.test(pathname)) return 'detail';
		if (/\/about\/?$/.test(pathname)) return 'about';
		return 'home';
	}

	$: void onPhaseOrPathChange($tourPhase, $page.url.pathname);

	async function onPhaseOrPathChange(p: 'idle' | 'running' | 'dismissed', pathname: string) {
		if (p !== 'running') {
			if (shepherdInstance) {
				shepherdInstance.cancel();
				shepherdInstance = null;
				activePathname = null;
			}
			return;
		}
		// Phase is running. If a shepherd is up but the URL changed, kill it.
		if (shepherdInstance && activePathname !== pathname) {
			shepherdInstance.cancel();
			shepherdInstance = null;
			activePathname = null;
		}
		if (!shepherdInstance) {
			activePathname = pathname;
			await launch(detectKind(pathname));
		}
	}

	async function launch(kind: TourKind) {
		const { default: Shepherd } = await import('shepherd.js');
		await import('shepherd.js/dist/css/shepherd.css');

		const isMobile = typeof window !== 'undefined' && window.innerWidth < 1024;
		const tour = new Shepherd.Tour({
			useModalOverlay: true,
			defaultStepOptions: {
				cancelIcon: { enabled: true },
				classes: 'ohbm-shepherd',
				scrollTo: { behavior: 'smooth', block: 'center' }
			}
		});

		const goNext = (): void => {
			tourStore.next();
			tour.next();
		};
		const goBack = (): void => {
			tourStore.prev();
			tour.back();
		};
		const skip = (): void => {
			tourStore.skip();
			tour.cancel();
		};
		const finish = (): void => {
			tourStore.complete();
			tour.complete();
		};

		const place = (preferred: 'bottom' | 'right' | 'top' | 'left'):
			'bottom' | 'right' | 'top' | 'left' => (isMobile ? 'bottom' : preferred);

		const buttons = (
			isFirst: boolean,
			isLast: boolean
		): Array<{ text: string; classes?: string; action: () => void }> => {
			const out: Array<{ text: string; classes?: string; action: () => void }> = [
				{ text: 'Skip', classes: 'shepherd-button-secondary', action: skip }
			];
			if (!isFirst) out.push({ text: 'Back', classes: 'shepherd-button-secondary', action: goBack });
			out.push(isLast ? { text: 'Done', action: finish } : { text: 'Next', action: goNext });
			return out;
		};

		const steps: Array<{
			id: string;
			title: string;
			text: string;
			attachTo?: { element: string; on: 'bottom' | 'right' | 'top' | 'left' };
			beforeShowPromise?: () => Promise<void> | void;
		}> = [];

		if (kind === 'home') {
			steps.push(
				{
					id: 'home-search',
					title: 'Search',
					text: 'Type a keyword, author, topic, or poster id — typos and accents are tolerated. Semantic search runs in the background, so a query like "memory aging" also surfaces abstracts that never use those exact words.',
					attachTo: { element: '[data-testid="search-input"]', on: place('bottom') }
				},
				{
					id: 'home-model',
					title: 'Pick a lens',
					text: 'Switch the (model × input) pair to view the corpus through a different embedding. Each lens gives the UMAP its own colouring, clusters, and "most similar" lists.',
					attachTo: { element: '[data-testid="model-selector"]', on: place('bottom') }
				},
				{
					id: 'home-map',
					title: 'The map',
					text: 'Every dot is one accepted abstract, coloured + shaped by its cluster. Click a dot to focus that abstract; on desktop, lasso a region to filter the result list. The 3D side can be paused / orbited.',
					attachTo: { element: '[data-testid="toggle-map"]', on: place('bottom') }
				}
			);
			if (!isMobile) {
				steps.push({
					id: 'home-lasso',
					title: 'Lasso on the 2D map',
					text: 'On the 2D map, drag the lasso tool (top-right of the chart toolbar) to select a region. The result list, facets, and 3D map all narrow to that selection — and the focused dot gets a halo.',
					attachTo: { element: '[data-testid="umap-chart-2d"]', on: 'right' }
				});
			}
			steps.push(
				{
					id: 'home-facets',
					title: 'Refine',
					text: 'Filter by cluster, topic, methods, population, and a dozen more facets. Each filter narrows the result list AND dims the map; combine them freely.',
					attachTo: {
						element: isMobile ? '[data-testid="toggle-facets"]' : '[data-testid="facet-sidebar"]',
						on: place(isMobile ? 'bottom' : 'right')
					}
				},
				{
					id: 'home-card',
					title: 'Open an abstract',
					text: 'Click any result card to open its detail pane on the right (or full-screen on mobile). You\'ll see the authors (clickable to filter), AI-extracted claims, cross-cell cluster membership, and the "Most similar" / "Most different" related-works lists aggregated across every map.',
					attachTo: { element: '[data-testid="result-card"]', on: place('right') },
					beforeShowPromise: () => {
						// Auto-focus the first card so the related-works panel actually
						// renders for the next step.
						const card = document.querySelector<HTMLElement>('[data-testid="result-card"]');
						const posterId = card?.getAttribute('data-poster-id');
						if (posterId) focusedAbstract.set(posterId);
					}
				},
				{
					id: 'home-card-cart',
					title: 'Save it for later',
					text: 'Each card has a 🛒 icon. Click it once to save the abstract to your list — the icon flips to a filled cart with a ✓ pip. Keep saving; the 🛒 button in the header shows the running count.',
					attachTo: {
						element: '[data-testid="card-cart-add"], [data-testid="card-cart-remove"]',
						on: place('left')
					}
				},
				{
					id: 'home-permalink',
					title: 'Full-detail (permalink) page',
					text: 'The "full details ↗" link in the detail pane opens a shareable permalink for this abstract. It lays out the submission verbatim on the left (intro / methods / results / conclusion / topics / methods checklist / references) and the AI + algorithmic insights on the right (extracted claims, figure interpretations, cluster membership, related abstracts). A "back to the atlas" link sits at the bottom of the page so you can always return.',
					attachTo: { element: '[data-testid="detail-permalink"]', on: place('left') }
				},
				{
					id: 'home-cart-toggle',
					title: 'Your saved list',
					text: "When you're ready, the 🛒 button in the top bar opens your saved list. From there you can email it to yourself (the mailto body includes a per-poster Open link back to the atlas), copy it to the clipboard, or clear it.",
					attachTo: { element: '[data-testid="toggle-cart"]', on: place('bottom') }
				},
				{
					id: 'home-about',
					title: 'About + methodology',
					text: 'The "About" link in the header opens a page describing how the data + the AI surfaces are produced — a short lay paragraph per stage, plus a "Technical details" toggle that expands code-grounded specifics (algorithms, parameters, file paths, cache keys). Every external citation is HEAD-checked at build time so the references stay live.',
					attachTo: { element: '[data-testid="header-about-link"]', on: place('bottom') }
				},
				{
					id: 'home-feedback',
					title: 'Spot something broken? Have an idea?',
					text: 'The speech-bubble icon next to the theme switch opens a pre-filled GitHub issue (page URL + deploy SHA + user-agent templated in for you). Use it for bug reports, missing features, or "this abstract looks wrong" notes — issues land under the `feedback` label.',
					attachTo: { element: '[data-testid="header-feedback"]', on: place('bottom') }
				}
			);
		} else if (kind === 'detail') {
			steps.push(
				{
					id: 'detail-zone-submitter',
					title: 'Submitter content',
					text: 'The left column is verbatim from the submission: title, authors, body sections (Intro / Methods / Results / Conclusion), Topics + Methods checklist, and curated references.',
					attachTo: { element: '[data-testid="zone-submitter"], .zone-submitter', on: place('right') }
				},
				{
					id: 'detail-zone-computed',
					title: 'Computed insights',
					text: "The right column is everything we computed about this abstract. AI-extracted claims + figure interpretations sit at the top (clearly tagged ✨ AI), followed by the algorithmic cluster membership + related-abstract rails.",
					attachTo: { element: '[data-testid="zone-computed"], .zone-computed', on: place('left') }
				},
				{
					id: 'detail-claims',
					title: 'AI-extracted claims',
					text: 'Each claim is shown with its evidence quote (verified against the source text), an ECO ontology code for the kind of evidence, and the LLM model identifier — so you can decide how much to trust each one.',
					attachTo: { element: '[data-testid="section-claims"]', on: place('left') }
				},
				{
					id: 'detail-related',
					title: 'Related abstracts',
					text: 'Per-cell precomputed neighbours, aggregated across all 15 (model, input) maps. The "×N" badge shows how many maps include this abstract in the focused abstract\'s nearest/farthest 10 — more = more robust similarity.',
					attachTo: { element: '[data-testid="detail-related"]', on: place('left') }
				},
				{
					id: 'detail-clusters',
					title: 'Cluster membership',
					text: 'Each row is one (model, input) cell\'s view of where this abstract sits. Cluster labels are LLM-grouped (✨ AI) and reflect that map\'s own community-detection run.',
					attachTo: { element: '[data-testid="extra-clusters"]', on: place('left') }
				},
				{
					id: 'detail-cart',
					title: 'Save it',
					text: 'The cart icon next to the poster id adds this abstract to your saved list — the same list the 🛒 button in the home-page header surfaces.',
					attachTo: { element: '[data-testid="detail-cart-add"], [data-testid="detail-cart-remove"]', on: place('bottom') }
				},
				{
					id: 'detail-back',
					title: 'Back to the atlas',
					text: 'When you\'re done reading, the link at the bottom returns you to the search + map view with your saved list and any filters still intact.',
					attachTo: { element: '[data-testid="detail-back-to-atlas"]', on: place('top') }
				}
			);
		} else if (kind === 'about') {
			steps.push(
				{
					id: 'about-intro',
					title: 'About this site',
					text: 'A short overview of where the data comes from and how the AI surfaces (figure interpretations, claims, cluster labels) are produced.',
					attachTo: { element: 'header h1', on: place('bottom') }
				},
				{
					id: 'about-stages',
					title: 'Per-stage deep dives',
					text: 'Five collapsible stages walk through the pipeline. Each opens with a lay paragraph; click "Technical details" beneath it to expand a code-grounded breakdown (algorithms, file paths, cache keys, parameters).',
					attachTo: { element: '[data-testid^="about-stage-"]', on: place('right') }
				},
				{
					id: 'about-references',
					title: 'External citations',
					text: 'Every link goes to a real, accessible page. They\'re HEAD-checked at build time — a broken citation blocks the deploy — so the references stay current.',
					attachTo: { element: '.stage-body a[target="_blank"]', on: place('right') }
				}
			);
		} else {
			// Unknown route → just dismiss the tour cleanly.
			tourStore.skip();
			return;
		}

		steps.forEach((s, i) =>
			tour.addStep({ ...s, buttons: buttons(i === 0, i === steps.length - 1) })
		);

		tour.on('cancel', () => tourStore.skip());
		tour.on('complete', () => tourStore.complete());

		shepherdInstance = tour;
		tour.start();
	}

	onDestroy(() => {
		if (shepherdInstance) {
			shepherdInstance.cancel();
			shepherdInstance = null;
		}
	});
</script>

<style global>
	.ohbm-shepherd {
		--shepherd-primary: var(--accent, #2c5fa3);
	}
	.shepherd-element {
		border-radius: 6px;
		max-width: min(28rem, 90vw);
	}
	.shepherd-text {
		font-size: 0.92rem;
		line-height: 1.55;
	}
	.shepherd-button {
		background: var(--accent);
		color: var(--accent-text, white);
		padding: 0.4rem 0.9rem;
		font-size: 0.85rem;
		border-radius: 4px;
		margin-right: 0.4rem;
	}
	.shepherd-button-secondary {
		background: var(--bg-elevated);
		color: var(--text);
		border: 1px solid var(--border);
	}
</style>
