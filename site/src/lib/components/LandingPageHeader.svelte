<!--
  Stage 15 (spec 015-neuroscape-context, FR-014 + T039):
  bare-root cross-conference atlas landing-page header.

  Brand text on the left + two outbound subsite links in the
  center. Visible only when SITE_MODE === 'atlas-root'; in
  ohbm2026 / neuroscape modes the existing header chrome stays.
-->
<script lang="ts">
	import { base } from '$app/paths';

	// The atlas-root build sets BASE_PATH='' so `base` resolves to ''.
	// In production the gh-pages publish-tree puts ohbm2026/ and
	// neuroscape/ at sibling paths relative to the bare root. For
	// PR previews they live under `/pr-<N>/{,ohbm2026/,neuroscape/}`,
	// which means relative `./ohbm2026/` works in both production
	// AND previews.
	const OHBM2026_HREF = `${base}/ohbm2026/`;
	const NEUROSCAPE_HREF = `${base}/neuroscape/`;
</script>

<header class="landing-header" data-testid="landing-page-header">
	<a class="brand" href={base || '/'}>abstractatlas</a>
	<nav class="nav-links" aria-label="Sibling subsites">
		<!-- rel="external" tells SvelteKit's prerenderer + link-
		     interceptor that these point at a SIBLING SvelteKit
		     deployment (a separately-built bundle under /ohbm2026/
		     and /neuroscape/), NOT an in-app route. Without it the
		     atlas-root prerender step would fail because no
		     /ohbm2026/ route exists inside this bundle. -->
		<a class="nav-link" href={OHBM2026_HREF} rel="external" data-testid="nav-ohbm2026"
			>Browse OHBM 2026 abstracts <span class="arrow">→</span></a
		>
		<a class="nav-link" href={NEUROSCAPE_HREF} rel="external" data-testid="nav-neuroscape"
			>Browse the NeuroScape PubMed atlas <span class="arrow">→</span></a
		>
	</nav>
</header>

<style>
	.landing-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 1.5rem;
		padding: 0.75rem 1.25rem;
		border-bottom: 1px solid var(--color-border, rgba(0, 0, 0, 0.1));
		background: var(--color-surface, #ffffff);
		min-height: 3rem;
	}

	.brand {
		font-weight: 600;
		font-size: 1.1rem;
		letter-spacing: -0.01em;
		color: var(--color-text, #111);
		text-decoration: none;
	}

	.nav-links {
		display: flex;
		gap: 1.25rem;
		align-items: center;
	}

	.nav-link {
		color: var(--color-text, #111);
		text-decoration: none;
		font-size: 0.95rem;
		padding: 0.35rem 0.6rem;
		border-radius: 4px;
	}

	.nav-link:hover {
		background: var(--color-surface-hover, rgba(0, 0, 0, 0.04));
	}

	.arrow {
		display: inline-block;
		margin-left: 0.25em;
	}

	@media (max-width: 600px) {
		.landing-header {
			flex-direction: column;
			align-items: flex-start;
			gap: 0.5rem;
		}
		.nav-links {
			flex-direction: column;
			gap: 0.25rem;
			align-items: flex-start;
		}
	}
</style>
