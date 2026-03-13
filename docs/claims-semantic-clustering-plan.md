# Claims Semantic Clustering Plan

## Goal

Build a semantic clustering track that uses extracted claim text rather than abstract section text, targeting roughly `25-30` clusters for downstream review.

## Plan

- [x] Add a `claims` embedding field to the shared embedding builder.
- [x] Format claim-derived embedding text from `claim_extraction.claims`.
- [x] Ensure clustering summaries use the embedding bundle's own field list instead of always using the default abstract sections.
- [x] Add regression tests for claims embedding text and claims-aware cluster summaries.
- [ ] Generate a claims-only embedding bundle.
- [ ] Run a clustering benchmark over `k=25..30`.
- [ ] Review the best run and, if useful, build follow-on UI wiring later.

## Notes

- The claims text builder embeds one bullet per extracted claim using the claim statement itself, so cluster labels are driven by content rather than `EXPLICIT` or claim ids.
- Abstracts without extracted claims are left with empty claims text rather than falling back to title/section text, so this track stays claim-driven.
