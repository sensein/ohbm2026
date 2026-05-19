/**
 * Helpers for the FINAL OHBM 2026 poster-listing stand-by times.
 *
 * Source: `data/primary/032626 OHBM 2026 Poster Listing_FINAL.xlsx
 * - Poster Listing.csv` (authoritative; sourced into the parquet by
 * `src/ohbm2026/ui_data/abstracts.py` via the shared parser in
 * `src/ohbm2026/standby.py`). On the parquet wire the field is
 * `poster_standby: {first: timestamp[ms, UTC], second: ...}`.
 * hyparquet surfaces timestamps as either `Date` instances or
 * millisecond-since-epoch numbers depending on the column metadata;
 * this module normalises both forms.
 *
 * Display uses Europe/Paris (Bordeaux) local time — the conference
 * venue — so attendees see the labels they recognise from OHBM
 * communications. The window length is always one hour.
 *
 * Hot-path note: the facet recomputer calls `standbySummary` once
 * per abstract per filter change (~6.5 K calls). Every public
 * function in this module is memoised by the input millisecond
 * value (only 8 distinct standby slots in the corpus, so the cache
 * is effectively constant-size). Without the memo, allocating
 * fresh `Intl.DateTimeFormat` instances on every call froze the
 * browser tab when the user clicked a `Stand-by time` facet option.
 */

const VENUE_TZ = 'Europe/Paris';

// Module-scoped formatters — created once at import. Constructing
// a fresh `Intl.DateTimeFormat` is expensive (~30 µs each); the
// hot path was building three per call × 6.5 K calls × N filter
// changes per click.
const _LABEL_FMT = new Intl.DateTimeFormat('en-US', {
	timeZone: VENUE_TZ,
	weekday: 'long',
	month: 'long',
	day: 'numeric'
});
const _TIME_FMT = new Intl.DateTimeFormat('en-US', {
	timeZone: VENUE_TZ,
	hour: '2-digit',
	minute: '2-digit',
	hour12: false
});
const _WEEKDAY_SHORT_FMT = new Intl.DateTimeFormat('en-US', {
	timeZone: VENUE_TZ,
	weekday: 'short'
});
const _MON_DAY_FMT = new Intl.DateTimeFormat('en-US', {
	timeZone: VENUE_TZ,
	month: 'short',
	day: '2-digit'
});
const _PARIS_ISO_DATE_FMT = new Intl.DateTimeFormat('en-CA', {
	timeZone: VENUE_TZ,
	year: 'numeric',
	month: '2-digit',
	day: '2-digit'
});

const CONFERENCE_DAY_BASE_MS = Date.parse('2026-06-15');
const MS_PER_DAY = 86_400_000;

/** Per-(ms-since-epoch) memo. The corpus has 8 unique program slots
 * across all 3,242 abstracts, so this cache stays at ~8 entries.
 */
const _labelCache = new Map<number, string>();
const _blockKeyCache = new Map<number, string>();

/** Coerce a parquet-emitted timestamp value to milliseconds-since-epoch. */
export function toMillis(v: Date | number | null | undefined): number | null {
	if (v == null) return null;
	if (v instanceof Date) return v.getTime();
	if (typeof v === 'number') return Number.isFinite(v) ? v : null;
	// hyparquet sometimes hands back BigInt for INT64 timestamps; coerce.
	if (typeof v === 'bigint') {
		const n = Number(v);
		return Number.isFinite(n) ? n : null;
	}
	return null;
}

/** Format one standby window as "Monday, June 15 · 13:45-14:45 (Paris)". */
export function formatStandbyWindow(start: Date | number | null | undefined): string | null {
	const ms = toMillis(start);
	if (ms == null) return null;
	const cached = _labelCache.get(ms);
	if (cached !== undefined) return cached;
	const startDate = new Date(ms);
	const endDate = new Date(ms + 60 * 60 * 1000);
	const day = _LABEL_FMT.format(startDate);
	const s = _TIME_FMT.format(startDate);
	const e = _TIME_FMT.format(endDate);
	const out = `${day} · ${s}–${e}`;
	_labelCache.set(ms, out);
	return out;
}

/**
 * Day-block key used by the facet filter — coarse enough that an
 * attendee can pick one of the 8 program windows. Format:
 * `Day N (Wkd Mon DD) · HH:MM-HH:MM` in Paris time. The leading
 * conference-day index makes the lex sort match chronological sort
 * (without that prefix, a naive sort would put Thursday before
 * Tuesday). Stable, comparable, human-readable. Memoised by `ms`.
 */
export function standbyBlockKey(start: Date | number | null | undefined): string | null {
	const ms = toMillis(start);
	if (ms == null) return null;
	const cached = _blockKeyCache.get(ms);
	if (cached !== undefined) return cached;
	const startDate = new Date(ms);
	const endDate = new Date(ms + 60 * 60 * 1000);
	const wkd = _WEEKDAY_SHORT_FMT.format(startDate);
	const monDay = _MON_DAY_FMT.format(startDate);
	const s = _TIME_FMT.format(startDate);
	const e = _TIME_FMT.format(endDate);
	// OHBM 2026 venue programme runs Mon Jun 15 → Thu Jun 18 in Paris
	// time. Map each date to its 1-based conference day so lex sort
	// matches chronological order across all 8 standby windows.
	const dayParis = _PARIS_ISO_DATE_FMT.format(startDate); // "2026-06-15"
	const dayIndex = Math.max(
		1,
		Math.round((Date.parse(dayParis) - CONFERENCE_DAY_BASE_MS) / MS_PER_DAY) + 1
	);
	const out = `Day ${dayIndex} (${wkd} ${monDay}) · ${s}–${e}`;
	_blockKeyCache.set(ms, out);
	return out;
}

interface _StandbySummary {
	firstLabel: string | null;
	secondLabel: string | null;
	firstKey: string | null;
	secondKey: string | null;
	keys: string[];
}

const _EMPTY_SUMMARY: _StandbySummary = {
	firstLabel: null,
	secondLabel: null,
	firstKey: null,
	secondKey: null,
	keys: []
};

/** Per-(firstMs, secondMs) memo for `standbySummary` — the facet
 * recomputer calls this per abstract per filter change. */
const _summaryCache = new Map<string, _StandbySummary>();

/** Convenience: both windows, both keys, both display strings.
 * Result is memoised by the `(firstMs, secondMs)` pair so repeated
 * calls during reactive recompute hit the cache after the first
 * pass over the corpus. */
export function standbySummary(
	standby: { first: Date | number | null; second: Date | number | null } | null | undefined
): _StandbySummary {
	if (!standby) return _EMPTY_SUMMARY;
	const firstMs = toMillis(standby.first);
	const secondMs = toMillis(standby.second);
	const cacheKey = `${firstMs ?? ''}|${secondMs ?? ''}`;
	const cached = _summaryCache.get(cacheKey);
	if (cached !== undefined) return cached;
	const firstLabel = formatStandbyWindow(standby.first);
	const secondLabel = formatStandbyWindow(standby.second);
	const firstKey = standbyBlockKey(standby.first);
	const secondKey = standbyBlockKey(standby.second);
	const keys: string[] = [];
	if (firstKey) keys.push(firstKey);
	if (secondKey) keys.push(secondKey);
	const summary: _StandbySummary = { firstLabel, secondLabel, firstKey, secondKey, keys };
	_summaryCache.set(cacheKey, summary);
	return summary;
}
