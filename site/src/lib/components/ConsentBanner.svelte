<!--
  Cookie/consent banner for the Google Analytics tag added in PR #45.
  Renders ONLY when `window.__ohbmAnalyticsConsent === 'pending'`. All
  other states (granted/denied/blocked-dnt/blocked-gpc/pr-preview/
  no-analytics) suppress the banner entirely — DNT or GPC users are
  never asked, and visitors who already chose don't see it again.

  On accept: persists `granted` to localStorage and calls
  `gtag('consent', 'update', { analytics_storage: 'granted' })` so the
  already-loaded gtag library starts honouring analytics requests
  without a page reload. On decline: persists `denied`; gtag stays in
  its default-denied state.
-->
<script lang="ts">
	import { onMount } from 'svelte';

	type ConsentState =
		| 'pending'
		| 'granted'
		| 'denied'
		| 'blocked-dnt'
		| 'blocked-gpc'
		| 'pr-preview'
		| 'blocked-error'
		| 'no-analytics';

	const STORAGE_KEY = 'ohbm2026.analytics.consent.v1';

	let state: ConsentState = 'no-analytics';

	onMount(() => {
		const s = (window as unknown as { __ohbmAnalyticsConsent?: ConsentState })
			.__ohbmAnalyticsConsent;
		if (s) state = s;
	});

	function persist(choice: 'granted' | 'denied') {
		try {
			localStorage.setItem(STORAGE_KEY, choice);
		} catch {
			// quota exceeded / privacy-mode storage — the in-memory
			// state still flips so the banner closes for this session;
			// it'll just re-appear on next visit.
		}
		(window as unknown as { __ohbmAnalyticsConsent?: ConsentState }).__ohbmAnalyticsConsent =
			choice;
		state = choice;
	}

	function accept() {
		persist('granted');
		const g = (window as unknown as { gtag?: (...args: unknown[]) => void }).gtag;
		if (typeof g === 'function') {
			g('consent', 'update', { analytics_storage: 'granted' });
		}
	}

	function decline() {
		persist('denied');
	}
</script>

{#if state === 'pending'}
	<div class="consent-banner" role="dialog" aria-label="Analytics consent" data-testid="consent-banner">
		<div class="consent-body">
			<p class="consent-text">
				Abstract Atlas uses <strong>Google Analytics</strong> to understand which features
				visitors find useful. IP addresses are anonymised; no personal information is
				collected.
			</p>
		</div>
		<div class="consent-actions">
			<button
				type="button"
				class="consent-btn decline"
				on:click={decline}
				data-testid="consent-decline"
			>
				Decline
			</button>
			<button
				type="button"
				class="consent-btn accept"
				on:click={accept}
				data-testid="consent-accept"
			>
				Accept
			</button>
		</div>
	</div>
{/if}

<style>
	/* Use the project's actual theme variables (defined in
	   site/src/app.css for both [data-theme="light"] and dark): the
	   prior fallback names (--bg-card) were undefined, so the
	   hardcoded #fff fallback fired on every theme and produced an
	   unreadable light-on-light banner in dark mode. */
	.consent-banner {
		position: fixed;
		left: 1rem;
		right: 1rem;
		bottom: 1rem;
		max-width: 42rem;
		margin-left: auto;
		margin-right: auto;
		display: flex;
		gap: 1rem;
		align-items: center;
		flex-wrap: wrap;
		padding: 0.85rem 1rem;
		border-radius: 8px;
		background: var(--bg-elevated);
		color: var(--text);
		border: 1px solid var(--border-strong);
		box-shadow: 0 8px 24px rgba(0, 0, 0, 0.25);
		z-index: 1200;
		font-size: 0.9rem;
		line-height: 1.4;
	}
	.consent-body {
		flex: 1 1 18rem;
		min-width: 0;
	}
	.consent-text {
		margin: 0;
	}
	.consent-actions {
		display: flex;
		gap: 0.5rem;
		flex-shrink: 0;
	}
	.consent-btn {
		all: unset;
		cursor: pointer;
		padding: 0.4rem 0.95rem;
		border-radius: 4px;
		font-size: 0.85rem;
		font-weight: 500;
		border: 1px solid transparent;
	}
	.consent-btn.decline {
		color: var(--text);
		border-color: var(--border-strong);
		background: transparent;
	}
	.consent-btn.decline:hover {
		background: var(--bg-subtle);
	}
	.consent-btn.accept {
		background: var(--accent);
		color: var(--accent-text);
	}
	.consent-btn.accept:hover {
		filter: brightness(1.08);
	}
	.consent-btn:focus-visible {
		outline: 2px solid var(--accent);
		outline-offset: 2px;
	}
</style>
