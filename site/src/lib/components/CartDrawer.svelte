<script lang="ts">
	import { cartStore, cartItems } from '$lib/stores/cart';
	import type { CartItem } from '$lib/stores/cart';
	import { focusedAbstract } from '$lib/stores/selection';
	import { ohbmTitleLookup, neuroscapeTitleLookup } from '$lib/stores/cart_ui';
	import { buildUnifiedMailtoLink, buildUnifiedPlainTextList } from '$lib/cart_email';
	import type { UnifiedCartRow } from '$lib/cart_email';
	import { base } from '$app/paths';
	import { SITE_MODE } from '$lib/site_mode';

	export let open = false;

	let clipboardStatus: 'idle' | 'copied' | 'error' = 'idle';

	$: ohbmByPosterId = $ohbmTitleLookup;
	$: neuroscapeByPubmedId = $neuroscapeTitleLookup;

	// Cross-conference deploy root — used to construct sibling
	// permalinks for the email + clipboard exports. The drawer is
	// rendered on every subsite, so `base` carries different per-mode
	// suffixes; strip them to get the deploy root.
	$: siteRoot = (() => {
		if (typeof window === 'undefined') return '';
		const origin = window.location.origin;
		let root: string = base;
		if (SITE_MODE === 'ohbm2026' && root.endsWith('/ohbm2026')) {
			root = root.slice(0, -'/ohbm2026'.length);
		} else if (SITE_MODE === 'neuroscape' && root.endsWith('/neuroscape')) {
			root = root.slice(0, -'/neuroscape'.length);
		}
		return origin + root;
	})();

	$: rows = (() => {
		const out: Array<{
			item: CartItem;
			title: string;
			subline: string;
			href: string;
			knownTitle: boolean;
		}> = [];
		for (const it of $cartItems) {
			if (it.kind === 'ohbm2026') {
				const info = ohbmByPosterId.get(it.id);
				const id4 = String(it.id).padStart(4, '0');
				out.push({
					item: it,
					title: info?.title ?? `OHBM 2026 poster ${id4}`,
					subline: info?.lead_author ?? '',
					href: `${siteRoot}/ohbm2026/abstract/${id4}/`,
					knownTitle: !!info?.title
				});
			} else {
				const info = neuroscapeByPubmedId.get(it.id);
				const subline = info
					? [info.year ? String(info.year) : '', info.cluster_title ?? '']
							.filter(Boolean)
							.join(' · ')
					: '';
				out.push({
					item: it,
					title: info?.title ?? `PubMed ${it.id}`,
					subline,
					href: `${siteRoot}/neuroscape/abstract/${it.id}/`,
					knownTitle: !!info?.title
				});
			}
		}
		return out;
	})();

	$: unifiedRows = rows.map(
		(r): UnifiedCartRow => ({
			kind: r.item.kind,
			id: r.item.id,
			title: r.title,
			subline: r.subline
		})
	);

	$: mailtoHref =
		unifiedRows.length > 0 ? buildUnifiedMailtoLink(unifiedRows, siteRoot) : '#';

	function close() {
		open = false;
	}
	async function copyList() {
		if (unifiedRows.length === 0) return;
		try {
			const text = buildUnifiedPlainTextList(unifiedRows, siteRoot);
			await navigator.clipboard.writeText(text);
			clipboardStatus = 'copied';
			setTimeout(() => (clipboardStatus = 'idle'), 2000);
		} catch {
			clipboardStatus = 'error';
			setTimeout(() => (clipboardStatus = 'idle'), 2000);
		}
	}
	// JSON export/import — the canonical mechanism for sharing carts
	// larger than what fits in a URL or email body. ?cart=… URL
	// restore tops out at ~200 items before URL length caps trip
	// (Outlook 2KB, Gmail ~8KB). Email-body item lists are likewise
	// truncated to MAX_EMAIL_ITEMS=100. The JSON file has no length
	// budget — works for any size cart, persists across devices, and
	// the import handler validates the shape before resetting state.
	let importInput: HTMLInputElement | null = null;
	let importStatus: 'idle' | 'success' | 'error' = 'idle';
	function exportJson() {
		if ($cartItems.length === 0) return;
		const payload = {
			schema: 'ohbm2026.cart.v2',
			generated_at: new Date().toISOString(),
			site_root: siteRoot,
			item_count: $cartItems.length,
			items: $cartItems
		};
		const blob = new Blob([JSON.stringify(payload, null, 2)], {
			type: 'application/json'
		});
		const url = URL.createObjectURL(blob);
		const a = document.createElement('a');
		a.href = url;
		const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
		a.download = `abstract-atlas-cart-${stamp}.json`;
		document.body.appendChild(a);
		a.click();
		document.body.removeChild(a);
		URL.revokeObjectURL(url);
	}
	function pickImport() {
		importInput?.click();
	}
	async function onImportFile(ev: Event) {
		const file = (ev.target as HTMLInputElement).files?.[0];
		if (!file) return;
		try {
			const text = await file.text();
			const parsed = JSON.parse(text);
			let items: Array<{ kind: 'ohbm2026' | 'neuroscape'; id: number }> = [];
			if (Array.isArray(parsed)) {
				// Bare array form — accept for forward-compat with hand-edited files.
				items = parsed.filter(
					(it) =>
						it &&
						typeof it === 'object' &&
						(it.kind === 'ohbm2026' || it.kind === 'neuroscape') &&
						typeof it.id === 'number' &&
						Number.isFinite(it.id)
				);
			} else if (parsed && Array.isArray(parsed.items)) {
				items = parsed.items.filter(
					(it: unknown): it is { kind: 'ohbm2026' | 'neuroscape'; id: number } =>
						!!it &&
						typeof it === 'object' &&
						((it as { kind: unknown }).kind === 'ohbm2026' ||
							(it as { kind: unknown }).kind === 'neuroscape') &&
						typeof (it as { id: unknown }).id === 'number' &&
						Number.isFinite((it as { id: number }).id)
				);
			} else {
				throw new Error('unrecognised cart-export format');
			}
			cartStore.resetAll(items);
			importStatus = 'success';
			setTimeout(() => (importStatus = 'idle'), 2500);
		} catch (err) {
			console.error('[cart] import failed:', err);
			importStatus = 'error';
			setTimeout(() => (importStatus = 'idle'), 3000);
		} finally {
			if (importInput) importInput.value = '';
		}
	}
	function openOhbmDetail(posterId: number) {
		// Only meaningful on the OHBM home; for other sites the cart
		// row carries the cross-deploy permalink already.
		if (SITE_MODE !== 'ohbm2026') return;
		$focusedAbstract = posterId;
		open = false;
	}
</script>

{#if open}
	<div class="cart-backdrop" on:click={close} role="presentation"></div>
	<div class="cart-drawer" role="dialog" aria-modal="true" aria-label="Saved list" data-testid="cart-drawer">
		<header class="cart-header">
			<h2>Your list <span class="muted">({rows.length})</span></h2>
			<button type="button" class="close" on:click={close} aria-label="Close list">×</button>
		</header>

		{#if rows.length === 0}
			<p class="empty">
				No saved items yet. Click the 🛒 icon on any result to save it for later.
			</p>
		{:else}
			<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<ul class="items" tabindex="0" aria-label="Your saved items">
				{#each rows as r (r.item.kind + ':' + r.item.id)}
					<li class="item">
						{#if r.item.kind === 'ohbm2026' && SITE_MODE === 'ohbm2026'}
							<!-- On the OHBM home, clicking opens the inline
							     detail pane just like the previous behaviour. -->
							<button
								type="button"
								class="item-body"
								on:click={() => openOhbmDetail(r.item.id)}
								data-testid="cart-item"
							>
								<span class="kind-pill kind-ohbm">OHBM</span>
								<span class="id-pill">{String(r.item.id).padStart(4, '0')}</span>
								<span class="title">{r.title}</span>
							</button>
						{:else}
							<a
								class="item-body"
								href={r.href}
								rel="external"
								data-testid="cart-item"
							>
								<span
									class="kind-pill"
									class:kind-ohbm={r.item.kind === 'ohbm2026'}
									class:kind-neuro={r.item.kind === 'neuroscape'}
								>
									{r.item.kind === 'ohbm2026' ? 'OHBM' : 'NeuroScape'}
								</span>
								<span class="id-pill">
									{r.item.kind === 'ohbm2026'
										? String(r.item.id).padStart(4, '0')
										: `PMID ${r.item.id}`}
								</span>
								<span class="title">{r.title}</span>
							</a>
						{/if}
						<button
							type="button"
							class="remove"
							on:click={() => cartStore.removeItem(r.item.kind, r.item.id)}
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
				<div class="footer-row">
					<a
						class="cart-action primary"
						href={mailtoHref}
						aria-disabled={rows.length === 0}
						data-testid="cart-email"
					>
						✉ Email
					</a>
					<button
						type="button"
						class="cart-action secondary"
						on:click={copyList}
						data-testid="cart-copy"
					>
						{clipboardStatus === 'copied'
							? '✓ Copied'
							: clipboardStatus === 'error'
								? 'Copy failed'
								: '📋 Copy'}
					</button>
					<button
						type="button"
						class="cart-action secondary"
						on:click={exportJson}
						title="Download a JSON file of your saved list — works for any size cart, restorable via the Import button"
						data-testid="cart-export-json"
					>
						⬇ Export
					</button>
					<button
						type="button"
						class="cart-action secondary"
						on:click={pickImport}
						title="Load a previously exported cart JSON. Replaces the current list."
						data-testid="cart-import-json"
					>
						{importStatus === 'success'
							? '✓ Imported'
							: importStatus === 'error'
								? 'Import failed'
								: '⬆ Import'}
					</button>
					<input
						bind:this={importInput}
						type="file"
						accept="application/json,.json"
						on:change={onImportFile}
						class="import-input"
						aria-hidden="true"
						tabindex="-1"
					/>
				</div>
				<div class="footer-row">
					<button
						type="button"
						class="cart-action danger"
						on:click={() => cartStore.clearAll()}
						data-testid="cart-clear"
					>
						Clear list
					</button>
					{#if rows.length > 100}
						<p class="cart-large-note">
							Email + Copy truncate at 100 items. Use Export to share
							the full list of {rows.length}.
						</p>
					{/if}
				</div>
			</footer>
		{/if}
	</div>
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
		width: min(28rem, 100vw);
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
		padding: 0.85rem 1rem;
		border-bottom: 1px solid var(--border);
	}
	.cart-header h2 {
		margin: 0;
		font-size: 1rem;
		font-weight: 600;
	}
	.muted {
		color: var(--text-muted);
		font-weight: 400;
	}
	.close {
		all: unset;
		cursor: pointer;
		font-size: 1.3rem;
		padding: 0.2rem 0.45rem;
		border-radius: 4px;
		color: var(--text-muted);
	}
	.close:hover {
		color: var(--text);
		background: var(--bg-subtle);
	}
	.empty {
		padding: 1rem;
		color: var(--text-muted);
		font-size: 0.9rem;
		text-align: center;
	}
	.items {
		flex: 1;
		/* min-height:0 is REQUIRED in a flex column: without it the default
		   min-height:auto keeps this list at its full content height, so with
		   enough saved items it grows past the drawer and pushes the footer
		   (action buttons) off-screen instead of scrolling. (Stage 24 follow-up
		   — reported as "cart buttons not visible / drawer taller than screen".) */
		min-height: 0;
		overflow-y: auto;
		list-style: none;
		padding: 0.5rem;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}
	.item {
		display: flex;
		gap: 0.25rem;
		align-items: stretch;
		padding: 0.4rem;
		border: 1px solid var(--border);
		border-radius: 4px;
	}
	.item:hover {
		background: var(--bg-subtle);
	}
	.item-body {
		all: unset;
		cursor: pointer;
		flex: 1;
		display: grid;
		grid-template-columns: auto auto 1fr;
		gap: 0.4rem 0.5rem;
		align-items: start;
		min-width: 0;
		text-decoration: none;
		color: var(--text);
	}
	.kind-pill {
		font-size: 0.62rem;
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.1rem 0.35rem;
		border-radius: 3px;
		white-space: nowrap;
		align-self: center;
	}
	.kind-ohbm {
		background: var(--accent-soft-bg);
		color: var(--accent-soft-text);
	}
	.kind-neuro {
		background: var(--bg-sunken);
		color: var(--text-muted);
	}
	.id-pill {
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
		font-size: 0.72rem;
		color: var(--text-muted);
		font-variant-numeric: tabular-nums;
		align-self: center;
		white-space: nowrap;
	}
	.title {
		grid-column: 1 / -1;
		font-size: 0.85rem;
		line-height: 1.35;
		word-break: break-word;
	}
	.remove {
		all: unset;
		cursor: pointer;
		font-size: 1rem;
		padding: 0 0.5rem;
		color: var(--text-muted);
		border-radius: 3px;
	}
	.remove:hover {
		background: var(--bg-sunken);
		color: var(--accent);
	}
	.cart-footer {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		padding: 0.7rem 0.85rem;
		border-top: 1px solid var(--border);
		/* Always keep the action buttons visible at the bottom — never let the
		   footer be squeezed or pushed off-screen by a long item list. */
		flex-shrink: 0;
	}
	.footer-row {
		display: flex;
		gap: 0.4rem;
		flex-wrap: wrap;
		align-items: center;
	}
	.import-input {
		position: absolute;
		opacity: 0;
		pointer-events: none;
		width: 0;
		height: 0;
	}
	.cart-large-note {
		flex: 1;
		min-width: 0;
		margin: 0;
		font-size: 0.75rem;
		color: var(--text-muted);
		line-height: 1.35;
	}
	.cart-action {
		all: unset;
		cursor: pointer;
		padding: 0.4rem 0.75rem;
		border-radius: 4px;
		font-size: 0.85rem;
		text-decoration: none;
	}
	.cart-action.primary {
		background: var(--accent);
		color: var(--accent-text);
	}
	.cart-action.primary:hover {
		filter: brightness(1.05);
	}
	.cart-action.secondary {
		border: 1px solid var(--border);
		color: var(--text);
	}
	.cart-action.secondary:hover {
		background: var(--bg-subtle);
	}
	.cart-action.danger {
		color: var(--text-muted);
		margin-left: auto;
	}
	.cart-action.danger:hover {
		color: #c0392b;
	}
</style>
