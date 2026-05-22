# Contract — Permalink page (`/abstract/<poster_id>/`)

UI surface contract for Stage 12's brief-preview + show-more affordances. The Playwright e2e test (`site/src/tests/e2e/permalink_show_more.spec.ts`) and the vitest unit test (`site/src/tests/unit/detail_panel_modes.test.ts`) target this contract.

## Route

- Path: `/abstract/<poster_id>/`
- Mounted at `site/src/routes/abstract/[poster_id]/+page.svelte`
- Default base path on prod: `https://abstractatlas.brainkb.org/ohbm2026/abstract/<poster_id>/`
- PR-preview base path: `https://abstractatlas.brainkb.org/pr-<N>/ohbm2026/abstract/<poster_id>/`

## Component composition

The permalink page route imports `DetailPanel.svelte` and passes:

```svelte
<DetailPanel
    abstract={abstractRecord}
    {authorsById}
    {abstractsById}
    dismissable={false}
    mode="permalink"   <!-- NEW Stage 12 prop -->
/>
```

The in-grid drawer call site (in `site/src/routes/+page.svelte`) does NOT pass `mode`; it defaults to `'panel'`. The drawer's content + behaviour are unchanged.

## DOM contract — `mode='permalink'`

### Section ordering (top to bottom in the left column)

1. Title + authors (existing)
2. Introduction
3. Methods
4. Results
5. Conclusion
6. **Acknowledgments** (NEW; only when `sections.acknowledgments` non-empty after trim)
7. References (existing)
8. Topics (existing)
9. Methods checklist (existing)

The brief-preview UX applies to **sections 2–6 only** (Introduction through Acknowledgments). References / Topics / Methods checklist render as today.

### Per-section structure (clamped state)

```html
<section
    class="verbatim-section section-clamped"
    data-testid="section-{skey}">
    <h3>{slabel}</h3>
    <div class="section-body section-body-clamped">
        {sbody}
    </div>
    <button
        class="section-toggle"
        data-testid="section-toggle-{skey}"
        aria-expanded="false"
    >Show more</button>
</section>
```

### Per-section structure (expanded state)

```html
<section
    class="verbatim-section section-expanded"
    data-testid="section-{skey}">
    <h3>{slabel}</h3>
    <div class="section-body">
        {sbody}
    </div>
    <button
        class="section-toggle"
        data-testid="section-toggle-{skey}"
        aria-expanded="true"
    >Show less</button>
</section>
```

### Per-section structure (short — no clamp needed)

When `isClampable(sbody) === false` (text length < 280 chars):

```html
<section
    class="verbatim-section section-short"
    data-testid="section-{skey}">
    <h3>{slabel}</h3>
    <div class="section-body">{sbody}</div>
    <!-- NO toggle button -->
</section>
```

### Master toggle (top of left column, above the section list)

```html
<button
    class="master-toggle"
    data-testid="master-toggle"
    aria-controls="permalink-verbatim-column"
>{label}</button>
```

Label transitions:
- Initial render: `Show all` (every clampable section starts clamped).
- After any per-section "Show more" click: still `Show all` unless ALL clampable sections are expanded.
- When every clampable section is expanded: `Collapse all`.
- After `Collapse all` click: back to `Show all` (every section returns to clamp).

## CSS classes (selector contract)

- `.verbatim-section` — the wrapper for any of the 5 sections in permalink mode.
- `.section-clamped` — the wrapper while the section is in 3-line preview.
- `.section-expanded` — the wrapper while the section is fully shown.
- `.section-short` — the wrapper for a non-clampable (short) section.
- `.section-body` — the inner block holding the prose.
- `.section-body-clamped` — applies the `-webkit-line-clamp: 3` style.
- `.section-toggle` — the per-section "Show more / Show less" button.
- `.master-toggle` — the column-scoped "Show all / Collapse all" button.

## State semantics

- The component-local `Map<SectionKey, boolean>` tracks each section's expanded state. Initial: every key `false`.
- `aria-expanded` on each per-section button reflects `expanded.get(skey)`.
- The master button's `aria-pressed` is `false` when at least one clampable section is still clamped; `true` when ALL are expanded.

## Performance contract (SC-001b)

- Per-section toggle round-trip (click → DOM update): ≤ 100 ms on a 2026-era laptop.
- Master toggle round-trip (click → DOM update): ≤ 200 ms with all 5 sections expanding simultaneously.
- Initial paint of the permalink page: matches the prior page's TTI (no regression budget).

## Accessibility

- Each `.section-toggle` button has `aria-expanded` reflecting state.
- The master button has `aria-controls="permalink-verbatim-column"` pointing at the wrapping `<div id="permalink-verbatim-column">`.
- The toggle text is a real word ("Show more" / "Show less" / "Show all" / "Collapse all") — no glyph-only buttons. Screen readers read state changes naturally.
- Focus-visible outlines on toggles use the existing site theme tokens; tab order is logical (top-of-section → toggle → next-section).

## Out of scope

- Persistent state across page navigation (deferred per spec).
- Brief-preview UX in the in-grid drawer (deferred per spec).
- AI-derived right-column cards' presentation (untouched by Stage 12).
