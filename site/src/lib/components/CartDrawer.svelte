<script lang="ts">
	import { cartStore } from '$lib/stores/cart';
	import { focusedAbstract } from '$lib/stores/selection';
	import { buildMailtoLink, buildPlainTextList } from '$lib/cart_email';
	import { base } from '$app/paths';
	import type { AbstractRecord, AuthorRecord } from '$lib/shards';

	export let open = false;
	export let abstracts: AbstractRecord[] = [];
	export let authorsById: Map<number, AuthorRecord> = new Map();

	let clipboardStatus: 'idle' | 'copied' | 'error' = 'idle';

	$: byPosterId = (() => {
		const m = new Map<number, AbstractRecord>();
		for (const a of abstracts) if (a.poster_id) m.set(a.poster_id, a);
		return m;
	})();
	$: items = [...$cartStore]
		.map((pid) => byPosterId.get(pid))
		.filter((r): r is AbstractRecord => r !== undefined);
	$: leadAuthorByPosterId = (() => {
		const m = new Map<number, string>();
		for (const rec of items) {
			const id = rec.author_ids[0];
			if (id === undefined) continue;
			const name = authorsById.get(id)?.name;
			if (name) m.set(rec.poster_id, name);
		}
		return m;
	})();
	// `base` is the SvelteKit-resolved subpath ('/ohbm2026' in production,
	// '/pr-<N>/ohbm2026' in PR previews, '' in pre-rework deploys). Composing
	// from `origin + base` keeps the cart-email permalinks valid regardless
	// of which route the cart was opened from — the previous approach
	// (regex-stripping `/abstract/.+$`) was broken on the About page and
	// would have been broken under the conference subpath as well.
	$: siteUrl = typeof window !== 'undefined' ? window.location.origin + base : '';

	function close() {
		open = false;
	}
	// Reactive mailto: href for the cart-email anchor. Empty `#` when the
	// cart is empty so the anchor remains valid HTML but a click is a
	// no-op (anchor also carries aria-disabled).
	$: mailtoHref =
		items.length > 0 ? buildMailtoLink(items, leadAuthorByPosterId, { siteUrl }) : '#';
	async function copyList() {
		if (items.length === 0) return;
		try {
			const text = buildPlainTextList(items, leadAuthorByPosterId, siteUrl);
			await navigator.clipboard.writeText(text);
			clipboardStatus = 'copied';
			setTimeout(() => (clipboardStatus = 'idle'), 2000);
		} catch {
			clipboardStatus = 'error';
			setTimeout(() => (clipboardStatus = 'idle'), 2000);
		}
	}
	function openDetail(posterId: number) {
		$focusedAbstract = posterId;
		open = false;
	}
</script>

{#if open}
	<div class="cart-backdrop" on:click={close} role="presentation"></div>
	<aside class="cart-drawer" role="dialog" aria-label="Saved list" data-testid="cart-drawer">
		<header class="cart-header">
			<h2>Your list <span class="muted">({items.length})</span></h2>
			<button type="button" class="close" on:click={close} aria-label="Close list">×</button>
		</header>

		{#if items.length === 0}
			<p class="empty">
				No saved abstracts yet. Click the cart icon on any result to save it for later.
			</p>
		{:else}
			<ul class="items" tabindex="0" aria-label="Your saved abstracts">
				{#each items as record (record.poster_id)}
					<li class="item">
						<button
							type="button"
							class="item-body"
							on:click={() => openDetail(record.poster_id)}
							data-testid="cart-item"
						>
							<span class="poster">{String(record.poster_id).padStart(4, '0')}</span>
							<span class="title">{record.title}</span>
						</button>
						<button
							type="button"
							class="remove"
							on:click={() => cartStore.remove(record.poster_id)}
							aria-label="Remove from list"
							title="Remove from list"
							data-testid="cart-remove"
						>
							×
						</button>
					</li>
				{/each}
			</ul>

			<footer class="cart-footer">
				<!-- Anchor instead of button: the href is part of the visible
					 contract (e2e tests + accessibility tools read the mailto:
					 URL without simulating a click). The browser opens the
					 user's mail client on activation, same UX as the prior
					 button + `window.location.href = ...` handler. -->
				<a
					class="cart-action primary"
					href={mailtoHref}
					aria-disabled={items.length === 0}
					data-testid="cart-email"
				>
					✉ Email my list
				</a>
				<button
					type="button"
					class="cart-action secondary"
					on:click={copyList}
					data-testid="cart-copy"
				>
					{clipboardStatus === 'copied' ? '✓ Copied' : clipboardStatus === 'error' ? 'Copy failed' : '📋 Copy'}
				</button>
				<button
					type="button"
					class="cart-action danger"
					on:click={() => cartStore.clear()}
					data-testid="cart-clear"
				>
					Clear
				</button>
			</footer>
		{/if}
	</aside>
{/if}

<style>
	.cart-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.35);
		z-index: 100;
	}
	.cart-drawer {
		position: fixed;
		top: 0;
		right: 0;
		bottom: 0;
		width: min(26rem, 100vw);
		background: var(--bg-elevated);
		border-left: 1px solid var(--border);
		z-index: 101;
		display: flex;
		flex-direction: column;
		box-shadow: -4px 0 16px rgba(0, 0, 0, 0.15);
	}
	.cart-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--border);
	}
	.cart-header h2 {
		margin: 0;
		font-size: 1rem;
		color: var(--text);
	}
	.cart-header .muted {
		color: var(--text-faint);
		font-weight: 400;
	}
	.close {
		all: unset;
		cursor: pointer;
		font-size: 1.4rem;
		color: var(--text-muted);
		padding: 0 0.5rem;
	}
	.close:hover {
		color: var(--text);
	}
	.empty {
		padding: 1rem;
		color: var(--text-muted);
		font-style: italic;
	}
	.items {
		list-style: none;
		padding: 0.5rem 0.75rem;
		margin: 0;
		flex: 1;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.item {
		display: flex;
		align-items: stretch;
		border: 1px solid var(--border);
		border-radius: 4px;
		background: var(--bg);
	}
	.item-body {
		all: unset;
		cursor: pointer;
		flex: 1;
		padding: 0.5rem 0.75rem;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
	}
	.item-body:hover {
		background: var(--bg-sunken);
	}
	.poster {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.78rem;
		color: var(--accent);
		font-weight: 600;
	}
	.title {
		font-size: 0.88rem;
		color: var(--text);
		line-height: 1.3;
	}
	.remove {
		all: unset;
		cursor: pointer;
		padding: 0 0.6rem;
		color: var(--text-faint);
		font-size: 1.2rem;
		border-left: 1px solid var(--border);
		display: flex;
		align-items: center;
	}
	.remove:hover {
		color: var(--text);
		background: var(--bg-sunken);
	}
	.cart-footer {
		display: flex;
		gap: 0.4rem;
		padding: 0.75rem 1rem;
		border-top: 1px solid var(--border);
		background: var(--bg-sunken);
	}
	.cart-action {
		all: unset;
		cursor: pointer;
		flex: 1;
		text-align: center;
		padding: 0.5rem 0.6rem;
		border-radius: 4px;
		font-size: 0.85rem;
	}
	.cart-action.primary {
		background: var(--accent);
		color: var(--accent-text);
	}
	.cart-action.secondary {
		background: var(--bg-elevated);
		color: var(--text);
		border: 1px solid var(--border);
	}
	.cart-action.danger {
		background: var(--bg-elevated);
		color: var(--text-muted);
		border: 1px solid var(--border);
	}
	.cart-action:hover {
		filter: brightness(1.05);
	}
</style>
