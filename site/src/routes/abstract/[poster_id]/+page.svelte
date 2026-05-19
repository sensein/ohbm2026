<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/stores';
	import { base } from '$app/paths';
	import {
		loadAbstracts,
		loadAuthors,
		type AbstractRecord,
		type AuthorRecord
	} from '$lib/shards';
	import DetailPanel from '$lib/components/DetailPanel.svelte';

	let abstractRecord: AbstractRecord | null = null;
	let authorsById: Map<number, AuthorRecord> = new Map();
	let abstractsById: Map<number, AbstractRecord> = new Map();
	let loaded = false;
	let unknown = false;

	// URL slug is a string; the data shape stores poster_id as a number.
	// Number("0503") === 503 — strips the leading zeros the URL may carry.
	$: posterIdParam = $page.params.poster_id;
	$: posterIdInt = Number(posterIdParam);

	onMount(async () => {
		const [a, au] = await Promise.all([loadAbstracts(), loadAuthors()]);
		if (!a || !au) {
			loaded = true;
			unknown = true;
			return;
		}
		authorsById = new Map(au.authors.map((x) => [x.author_id, x]));
		abstractsById = new Map(a.abstracts.map((x) => [x.poster_id, x]));
		const target = a.abstracts.find((x) => x.poster_id === posterIdInt) ?? null;
		abstractRecord = target;
		unknown = target === null;
		loaded = true;
	});
</script>

<svelte:head>
	{#if abstractRecord}
		<title>{String(abstractRecord.poster_id).padStart(4, '0')} — {abstractRecord.title}</title>
	{:else}
		<title>Abstract not found</title>
	{/if}
</svelte:head>

<div class="permalink-page">
	<nav class="back">
		<a href={`${base}/`}>← all abstracts</a>
	</nav>

	{#if !loaded}
		<p class="status">Loading…</p>
	{:else if unknown}
		<section class="not-found" data-testid="abstract-not-found">
			<h1>No abstract with poster id <code>{posterIdParam}</code></h1>
			<p>
				The poster id in this URL doesn't match any accepted abstract in the current data
				package. It may have been re-assigned by the program, or the data package may not be
				deployed yet.
			</p>
		</section>
	{:else if abstractRecord}
		<DetailPanel abstract={abstractRecord} {authorsById} {abstractsById} dismissable={false} />
	{/if}
</div>

<style>
	.permalink-page {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		width: 100%;
	}
	.back a {
		color: #2c5fa3;
		text-decoration: none;
		font-size: 0.9rem;
	}
	.back a:hover {
		text-decoration: underline;
	}
	.not-found {
		background: #fff8f8;
		border: 1px solid #f0c0c0;
		border-radius: 6px;
		padding: 1rem;
	}
	.not-found h1 {
		margin: 0 0 0.5rem;
		font-size: 1.1rem;
	}
	.status {
		color: #888;
		font-style: italic;
	}
	code {
		background: #f4f4f4;
		padding: 0 0.25rem;
		border-radius: 3px;
		font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
	}
</style>
