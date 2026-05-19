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
 */

const VENUE_TZ = 'Europe/Paris';

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
	const startDate = new Date(ms);
	const endDate = new Date(ms + 60 * 60 * 1000);
	const day = _LABEL_FMT.format(startDate);
	const s = _TIME_FMT.format(startDate);
	const e = _TIME_FMT.format(endDate);
	return `${day} · ${s}–${e}`;
}

/**
 * Day-block key used by the facet filter — coarse enough that an
 * attendee can pick one of the 8 program windows. Format:
 * `Day N (Wkd Mon DD) · HH:MM-HH:MM` in Paris time. The leading
 * conference-day index makes the lex sort match chronological sort
 * (without that prefix, a naive sort would put Thursday before
 * Tuesday). Stable, comparable, human-readable.
 */
export function standbyBlockKey(start: Date | number | null | undefined): string | null {
	const ms = toMillis(start);
	if (ms == null) return null;
	const startDate = new Date(ms);
	const endDate = new Date(ms + 60 * 60 * 1000);
	const wkd = new Intl.DateTimeFormat('en-US', {
		timeZone: VENUE_TZ,
		weekday: 'short'
	}).format(startDate);
	const monDay = new Intl.DateTimeFormat('en-US', {
		timeZone: VENUE_TZ,
		month: 'short',
		day: '2-digit'
	}).format(startDate);
	const s = _TIME_FMT.format(startDate);
	const e = _TIME_FMT.format(endDate);
	// OHBM 2026 venue programme runs Mon Jun 15 → Thu Jun 18 in Paris
	// time. Map each date to its 1-based conference day so lex sort
	// matches chronological order across all 8 standby windows.
	const dayParis = new Intl.DateTimeFormat('en-CA', {
		timeZone: VENUE_TZ,
		year: 'numeric',
		month: '2-digit',
		day: '2-digit'
	}).format(startDate); // "2026-06-15"
	const CONFERENCE_DAY_BASE = '2026-06-15';
	const dayIndex = Math.max(
		1,
		Math.round(
			(Date.parse(dayParis) - Date.parse(CONFERENCE_DAY_BASE)) / 86_400_000
		) + 1
	);
	return `Day ${dayIndex} (${wkd} ${monDay}) · ${s}–${e}`;
}

/** Convenience: both windows, both keys, both display strings. */
export function standbySummary(
	standby: { first: Date | number | null; second: Date | number | null } | null | undefined
): {
	firstLabel: string | null;
	secondLabel: string | null;
	firstKey: string | null;
	secondKey: string | null;
	keys: string[];
} {
	if (!standby) {
		return { firstLabel: null, secondLabel: null, firstKey: null, secondKey: null, keys: [] };
	}
	const firstLabel = formatStandbyWindow(standby.first);
	const secondLabel = formatStandbyWindow(standby.second);
	const firstKey = standbyBlockKey(standby.first);
	const secondKey = standbyBlockKey(standby.second);
	const keys: string[] = [];
	if (firstKey) keys.push(firstKey);
	if (secondKey) keys.push(secondKey);
	return { firstLabel, secondLabel, firstKey, secondKey, keys };
}
