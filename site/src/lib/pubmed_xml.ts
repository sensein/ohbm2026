/**
 * Stage 15 (spec 015-neuroscape-context, T063):
 * Browser-side parser for NCBI E-utilities EFetch responses.
 *
 * EFetch returns MEDLINE citation XML — a moderately deep structure
 * documented at https://www.nlm.nih.gov/bsd/licensee/elements_descriptions.html.
 * This module is a pure function from raw XML string to the
 * `FetchedRecord` shape consumed by `PubmedBodyRegion.svelte`.
 *
 * Defensive parsing:
 *  - Missing elements yield empty / null fields (the body offline
 *    state already covers the case of "no fetched data at all"; a
 *    record with an abstract but no DOI is normal and should render).
 *  - Multi-paragraph abstracts (NLM tags `<AbstractText Label="…">`)
 *    are joined with `\n\n` so the consumer can render them as
 *    distinct paragraphs.
 *  - Authors are emitted as "LastName Initials" — the canonical
 *    MEDLINE display form. ForeName is also captured when present
 *    but Initials reads better in the typical detail-panel layout.
 */

export type FetchedRecord = {
	authors: string[];
	journal: string;
	abstract_text: string;
	doi: string | null;
};

export class PubmedXmlParseError extends Error {
	constructor(message: string) {
		super(message);
		this.name = 'PubmedXmlParseError';
	}
}

/**
 * Parse an EFetch XML response string into a single FetchedRecord.
 *
 * The caller is responsible for the network fetch + retry — this
 * function is pure and synchronous (no DOM mutation, no I/O).
 */
export function parsePubmedXml(xml: string): FetchedRecord {
	if (!xml || typeof xml !== 'string' || xml.length < 10) {
		throw new PubmedXmlParseError('empty or invalid XML payload');
	}
	const parser = new DOMParser();
	const doc = parser.parseFromString(xml, 'application/xml');
	const parseError = doc.querySelector('parsererror');
	if (parseError) {
		throw new PubmedXmlParseError(`XML parse failed: ${parseError.textContent ?? '(empty)'}`);
	}

	// EFetch returns `<PubmedArticleSet>` containing one or more
	// `<PubmedArticle>` — for our `id=<single pubmed_id>` request,
	// exactly one. Allow zero (fall through to empty record) for
	// resilience.
	const article = doc.querySelector('PubmedArticle');
	if (!article) {
		return { authors: [], journal: '', abstract_text: '', doi: null };
	}

	return {
		authors: extractAuthors(article),
		journal: extractJournal(article),
		abstract_text: extractAbstract(article),
		doi: extractDoi(article)
	};
}

function extractAuthors(article: Element): string[] {
	const out: string[] = [];
	for (const a of article.querySelectorAll('AuthorList > Author')) {
		const last = a.querySelector('LastName')?.textContent?.trim();
		const initials = a.querySelector('Initials')?.textContent?.trim();
		const forename = a.querySelector('ForeName')?.textContent?.trim();
		const collective = a.querySelector('CollectiveName')?.textContent?.trim();
		if (last && initials) {
			out.push(`${last} ${initials}`);
		} else if (last && forename) {
			out.push(`${last}, ${forename}`);
		} else if (last) {
			out.push(last);
		} else if (collective) {
			out.push(collective);
		}
	}
	return out;
}

function extractJournal(article: Element): string {
	// Prefer the ISO abbreviation when present (shorter, more
	// recognisable); fall back to the full journal title.
	const iso = article.querySelector('Journal > ISOAbbreviation')?.textContent?.trim();
	if (iso) return iso;
	const full = article.querySelector('Journal > Title')?.textContent?.trim();
	return full ?? '';
}

function extractAbstract(article: Element): string {
	const blocks: string[] = [];
	for (const at of article.querySelectorAll('Abstract > AbstractText')) {
		const label = at.getAttribute('Label')?.trim();
		// AbstractText may contain inline italic / sup / sub elements; we
		// flatten to text content. Preserve label prefix when present
		// (e.g. "BACKGROUND:", "METHODS:") so the rendered body keeps
		// MEDLINE's structured-abstract sectioning.
		const text = at.textContent?.trim() ?? '';
		if (!text) continue;
		blocks.push(label ? `${label.toUpperCase()}: ${text}` : text);
	}
	return blocks.join('\n\n');
}

function extractDoi(article: Element): string | null {
	// MEDLINE places DOI under `<ELocationID EIdType="doi">…</ELocationID>`.
	// Some older records use `<ArticleId IdType="doi">` instead — accept
	// both.
	for (const el of article.querySelectorAll('ELocationID[EIdType="doi"]')) {
		const v = el.textContent?.trim();
		if (v) return v;
	}
	for (const el of article.querySelectorAll('ArticleId[IdType="doi"]')) {
		const v = el.textContent?.trim();
		if (v) return v;
	}
	return null;
}
