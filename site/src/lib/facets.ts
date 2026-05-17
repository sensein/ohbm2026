import type { AbstractRecord } from '$lib/shards';

/**
 * Facet recomputation per US4 / FR-013.
 *
 * For each facet (Topics + Methods + Study type + Population + Field strength
 * + Processing packages + Species + Recording technology + Brain regions +
 * Brain networks + Keywords + Accepted-for), build `{option → count}` over
 * the abstracts that pass the current intersection of (search ∩ lasso ∩
 * other-facet-filters). The "other-facet-filters" detail is the FR-013 nuance:
 * within a given facet we want to show what's reachable IF the user also
 * selected another option from that facet — so the count for facet F uses the
 * intersection EXCLUDING F's current selections (otherwise once you select
 * Species=Human you'd see counts of 0 for every other Species).
 */

export type ActiveFilters = Map<string, Set<string>>;

const FACETS_FROM_BLOCK = [
	'keywords',
	'methods',
	'study_type',
	'population',
	'field_strength',
	'processing_packages',
	'species',
	'recording_technology',
	'brain_regions',
	'brain_networks'
] as const;

export type FacetKey =
	| 'accepted_for'
	| 'topic'
	| 'subcategory'
	| (typeof FACETS_FROM_BLOCK)[number];

export const FACET_KEYS_ORDERED: FacetKey[] = [
	'topic',
	'subcategory',
	'methods',
	'study_type',
	'population',
	'field_strength',
	'processing_packages',
	'species',
	'recording_technology',
	'brain_regions',
	'brain_networks',
	'keywords',
	'accepted_for'
];

export const FACET_LABELS: Record<FacetKey, string> = {
	accepted_for: 'Accepted for',
	topic: 'Topic',
	subcategory: 'Subcategory',
	keywords: 'Keywords',
	methods: 'Methods',
	study_type: 'Study type',
	population: 'Population',
	field_strength: 'Field strength',
	processing_packages: 'Processing packages',
	species: 'Species',
	recording_technology: 'Recording technology',
	brain_regions: 'Brain regions',
	brain_networks: 'Brain networks'
};

function dedupe(values: string[]): string[] {
	const out: string[] = [];
	const seen = new Set<string>();
	for (const v of values) {
		if (!v || seen.has(v)) continue;
		seen.add(v);
		out.push(v);
	}
	return out;
}

function valuesFor(record: AbstractRecord, key: FacetKey): string[] {
	if (key === 'accepted_for') return record.accepted_for ? [record.accepted_for] : [];
	// The Topic facet is the UNION of primary + secondary topic values per
	// abstract (deduped). A selected Topic option matches if EITHER position
	// equals it — the previous split into primary_topic / secondary_topic
	// made users pick the same term twice for the same conceptual filter.
	if (key === 'topic') return dedupe([record.topics.primary, record.topics.secondary]);
	if (key === 'subcategory')
		return dedupe([record.topics.primary_subcategory, record.topics.secondary_subcategory]);
	const v = record.facets[key];
	if (Array.isArray(v)) return v.map((x) => String(x)).filter(Boolean);
	if (typeof v === 'string' && v) return [v];
	return [];
}

/** Does *record* pass the active filters in `filters`, optionally ignoring facet *exceptKey*? */
function passesFilters(
	record: AbstractRecord,
	filters: ActiveFilters,
	exceptKey: FacetKey | null = null
): boolean {
	for (const [key, options] of filters) {
		if (!options.size) continue;
		if (key === exceptKey) continue;
		const recordValues = valuesFor(record, key as FacetKey);
		let hit = false;
		for (const v of recordValues) {
			if (options.has(v)) {
				hit = true;
				break;
			}
		}
		if (!hit) return false;
	}
	return true;
}

export function filterByFacets(
	abstracts: AbstractRecord[],
	filters: ActiveFilters
): Set<number> | null {
	let active = false;
	for (const set of filters.values()) {
		if (set.size) {
			active = true;
			break;
		}
	}
	if (!active) return null;
	const out = new Set<number>();
	for (const a of abstracts) {
		if (passesFilters(a, filters)) out.add(a.abstract_id);
	}
	return out;
}

export interface FacetOption {
	value: string;
	count: number;
}

export type FacetCounts = Map<FacetKey, FacetOption[]>;

/**
 * Compute the per-option counts for every facet, restricted to the abstracts
 * that pass `(searchIds ∩ lassoIds ∩ facetsExceptSelf)`. The per-facet
 * exception lets the sidebar show "what would happen if I added another
 * option from this facet" — selecting Methods=fMRI doesn't zero out every
 * other Method count.
 */
export function recomputeFacets(
	abstracts: AbstractRecord[],
	filters: ActiveFilters,
	preFilteredIds: Set<number> | null
): FacetCounts {
	const out: FacetCounts = new Map();
	for (const key of FACET_KEYS_ORDERED) {
		const counts = new Map<string, number>();
		for (const record of abstracts) {
			if (preFilteredIds && !preFilteredIds.has(record.abstract_id)) continue;
			if (!passesFilters(record, filters, key)) continue;
			for (const v of valuesFor(record, key)) {
				counts.set(v, (counts.get(v) ?? 0) + 1);
			}
		}
		const sorted: FacetOption[] = [...counts.entries()]
			.map(([value, count]) => ({ value, count }))
			.sort((a, b) => b.count - a.count || a.value.localeCompare(b.value));
		out.set(key, sorted);
	}
	return out;
}

/** Helper for the sidebar: toggle a single (facet, option) selection. */
export function toggleFilter(
	filters: ActiveFilters,
	key: FacetKey,
	option: string
): ActiveFilters {
	const next = new Map<string, Set<string>>(
		[...filters].map(([k, v]) => [k, new Set(v)])
	);
	const set = next.get(key) ?? new Set();
	if (set.has(option)) set.delete(option);
	else set.add(option);
	if (set.size) next.set(key, set);
	else next.delete(key);
	return next;
}

export function clearAllFilters(): ActiveFilters {
	return new Map();
}
