/**
 * Stage 14 — `id:` operator parser + suggestion filter for the
 * SearchBar's "poster navigator" mode.
 *
 * All functions are pure: they only read their arguments and return
 * fresh structures. The SearchBar component imports them; vitest
 * tests `goto_poster.test.ts` exercise them without a DOM mount.
 *
 * See `specs/014-poster-id-nav/data-model.md` for the activation +
 * matching rules.
 */
import type { AbstractRecord } from '$lib/shards';

/** A single suggestion shown in the dropdown. */
export interface Suggestion {
	/** The integer poster id. Always present in `abstractsByPosterId`. */
	posterId: number;
	/** 4-digit zero-padded display form, e.g. "0345". */
	display: string;
	/** The abstract title; used for orientation in the dropdown row. */
	title: string;
}

/** The result of filtering the corpus by the user's typed query. */
export interface SuggestionResult {
	/** Visible suggestions, sorted ascending by `posterId`, capped at `limit`. */
	visible: Suggestion[];
	/** Total matches; `overflow = total - visible.length` becomes the "+ N more" footer. */
	total: number;
	/** Non-null iff `visible.length === 1 && total === 1`. */
	exactMatch: Suggestion | null;
}

const ID_OPERATOR_RE = /^id:(.*)$/is;

/**
 * Return the digit payload when `raw` starts with the `id:` operator
 * (case-insensitive), or `null` otherwise. `raw === "id:"` returns
 * `""` to drive the "type a poster number" hint.
 *
 * The match must be at the very start (no leading whitespace, no
 * other tokens). The payload is returned verbatim; whitespace and
 * non-digit characters are stripped downstream by `normaliseQuery`.
 */
export function parseIdOperator(raw: string): string | null {
	const m = ID_OPERATOR_RE.exec(raw);
	return m ? m[1] : null;
}

/**
 * Normalize the digit payload to the matching query string: drop
 * non-digits, then strip leading zeros. Returns `""` for empty /
 * pure-zero payloads (which yield no suggestions, only the hint).
 */
export function normaliseQuery(payload: string): string {
	const digits = payload.replace(/\D/g, '');
	const trimmed = digits.replace(/^0+/, '');
	return trimmed;
}

/**
 * Run the prefix-on-integer filter against the loaded corpus.
 *
 * Match rule: an id is included iff `id.toString().startsWith(q)`
 * where `q = normaliseQuery(payload)`. Empty `q` returns the empty
 * result. The visible list is sorted ascending by `posterId` and
 * capped at `limit`. `exactMatch` is non-null only when EXACTLY one
 * id matches (so the SearchBar's Enter handler can commit).
 */
export function filterSuggestions(
	payload: string,
	abstractsByPosterId: Map<number, AbstractRecord>,
	limit: number = 10
): SuggestionResult {
	const q = normaliseQuery(payload);
	if (q === '') {
		return { visible: [], total: 0, exactMatch: null };
	}

	const matched: Suggestion[] = [];
	for (const [id, record] of abstractsByPosterId) {
		if (id.toString().startsWith(q)) {
			matched.push({
				posterId: id,
				display: String(id).padStart(4, '0'),
				title: record.title ?? ''
			});
		}
	}
	matched.sort((a, b) => a.posterId - b.posterId);

	const visible = matched.slice(0, limit);
	const exactMatch = matched.length === 1 ? matched[0] : null;
	return { visible, total: matched.length, exactMatch };
}
