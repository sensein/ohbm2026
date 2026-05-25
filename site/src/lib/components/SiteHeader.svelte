<!--
  Stage 15 — unified header across all three sibling subsites.
  Replaces the OHBM-only inline header in `+layout.svelte` AND the
  Stage-15 `LandingPageHeader` previously rendered by `+page.svelte`
  for atlas-root + neuroscape modes. Same shape on every site:

      [⌂ home] Site Title [beta] · subtitle      Tour  About  Chat  Theme

  Hub-and-spoke navigation: the home icon is shown on the two
  subsite builds (ohbm2026 + neuroscape) and links back to the
  cross-conference root. The root itself doesn't show a home icon
  because it IS home. Subsite-to-subsite links are intentionally
  absent — visitors round-trip through the root, which lets new
  subsites land without rewiring every existing sibling.

  Title text, subtitle, About route, and the home-link tooltip are
  derived from `$lib/site_mode` so each build automatically labels
  itself; no per-site duplication.
-->
<script lang="ts">
	import { base } from '$app/paths';
	import { SITE_MODE } from '$lib/site_mode';
	import ThemeToggle from '$lib/components/ThemeToggle.svelte';
	import { tourStore } from '$lib/stores/tour';

	export let feedbackUrl: string = '#';

	// Strip the per-mode suffix off `base` so a "home" link from
	// /ohbm2026/ resolves to /, not /ohbm2026/. See
	// LandingPageHeader's history for the same dance.
	function rootBase(): string {
		if (SITE_MODE === 'ohbm2026' && base.endsWith('/ohbm2026'))
			return base.slice(0, -'/ohbm2026'.length);
		if (SITE_MODE === 'neuroscape' && base.endsWith('/neuroscape'))
			return base.slice(0, -'/neuroscape'.length);
		return base;
	}
	const ROOT = rootBase();
	const HOME_HREF = ROOT || '/';

	$: TITLE =
		SITE_MODE === 'atlas-root'
			? 'Abstract Atlas'
			: SITE_MODE === 'neuroscape'
				? 'NeuroScape PubMed Atlas'
				: 'OHBM 2026 Atlas';

	$: SUBTITLE =
		SITE_MODE === 'atlas-root'
			? 'OHBM 2026 abstracts overlaid on the NeuroScape PubMed neuroscience landscape'
			: SITE_MODE === 'neuroscape'
				? 'Browse, search, and explore the NeuroScape PubMed 1999–2023 corpus'
				: 'Browse, search, and explore the 2026 accepted abstracts';

	// About route — each build has its own `/about/` so the link
	// stays in-app for normal SvelteKit navigation. The page content
	// itself branches on SITE_MODE to give each site an appropriate
	// intro before falling into the shared pipeline writeup.
	const ABOUT_HREF = `${base}/about/`;
</script>

<header data-testid="site-header" data-mode={SITE_MODE}>
	<div class="header-row">
		<div class="header-text">
			<h1>
				{#if SITE_MODE !== 'atlas-root'}
					<!-- Home icon — back to the cross-conference root. rel="external"
					     tells SvelteKit the link points at a SIBLING deployment
					     (a separately-built bundle), not an in-app route. -->
					<a
						class="home-link"
						href={HOME_HREF}
						rel="external"
						title="Abstract Atlas — cross-conference landing"
						aria-label="Abstract Atlas — cross-conference landing"
						data-testid="header-home"
					>
						<svg
							width="18"
							height="18"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
							aria-hidden="true"
						>
							<path d="M3 9.5L12 2l9 7.5V21a1 1 0 0 1-1 1h-5v-7h-6v7H4a1 1 0 0 1-1-1z" />
						</svg>
					</a>
				{/if}
				<span class="title-text">{TITLE}</span>
				<span class="beta-tag">beta</span>
			</h1>
			<p class="subtitle">{SUBTITLE}</p>
		</div>
		<div class="header-controls">
			<button
				type="button"
				class="header-link header-tour"
				on:click={() => tourStore.start()}
				title="Take the guided tour"
				data-testid="header-tour-button"
			>
				Tour
			</button>
			<a class="header-link" href={ABOUT_HREF} data-testid="header-about-link">
				About
			</a>
			<a
				class="header-feedback"
				target="_blank"
				rel="noopener noreferrer"
				title="Report a bug or request a feature"
				aria-label="Report a bug or request a feature on GitHub"
				data-testid="header-feedback"
				href={feedbackUrl}
			>
				<!-- Lucide-style "message-square-warning" — comment bubble + ! -->
				<svg
					width="20"
					height="20"
					viewBox="0 0 24 24"
					fill="none"
					stroke="currentColor"
					stroke-width="2"
					stroke-linecap="round"
					stroke-linejoin="round"
					aria-hidden="true"
				>
					<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z" />
					<line x1="12" y1="8" x2="12" y2="12" />
					<line x1="12" y1="16" x2="12.01" y2="16" />
				</svg>
			</a>
			<ThemeToggle />
		</div>
	</div>
</header>

<style>
	header {
		padding: 1.25rem clamp(1rem, 2vw, 2rem) 0.75rem;
		width: 100%;
		box-sizing: border-box;
		border-bottom: 1px solid var(--border);
		background: var(--bg);
		color: var(--text);
	}
	.header-row {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}
	.header-text {
		min-width: 0;
	}
	h1 {
		margin: 0 0 0.25rem;
		font-size: 1.5rem;
		font-weight: 600;
		color: var(--text);
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
	}
	.home-link {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 1.75rem;
		height: 1.75rem;
		color: var(--text-muted);
		border-radius: 4px;
		text-decoration: none;
	}
	.home-link:hover {
		color: var(--accent);
		background: var(--accent-soft-bg);
	}
	.title-text {
		letter-spacing: -0.01em;
	}
	.beta-tag {
		font-size: 0.6rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.08em;
		color: var(--accent-text, white);
		background: var(--accent);
		padding: 0.1rem 0.4rem;
		border-radius: 4px;
		vertical-align: middle;
	}
	.subtitle {
		margin: 0;
		color: var(--text-muted);
		font-size: 0.9rem;
	}
	.header-controls {
		display: flex;
		align-items: center;
		gap: 0.6rem;
	}
	.header-link {
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	.header-link:hover {
		background: var(--accent-soft-bg);
	}
	button.header-link {
		all: unset;
		cursor: pointer;
		color: var(--accent);
		text-decoration: none;
		font-size: 0.9rem;
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
	}
	button.header-link:hover {
		background: var(--accent-soft-bg);
	}
	.header-feedback {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		width: 2rem;
		height: 2rem;
		color: var(--text-muted);
		border-radius: 4px;
		text-decoration: none;
	}
	.header-feedback:hover {
		color: var(--accent);
		background: var(--accent-soft-bg);
	}

	@media (max-width: 600px) {
		.header-row {
			flex-direction: column;
			align-items: flex-start;
			gap: 0.5rem;
		}
	}
</style>
