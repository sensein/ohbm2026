# Contract: `id:` operator and navigator-mode dropdown in SearchBar

## Modified file
`site/src/lib/components/SearchBar.svelte`

The existing component gains:
1. a new prop `abstractsByPosterId: Map<number, AbstractRecord>`,
2. internal navigator-mode state derived from the typed query, and
3. a dropdown overlay shown ONLY while in navigator mode.

The route owner (`+page.svelte`, permalink `+page.svelte`) gains a
listener on the SearchBar's `mode-change` event so it can hide its
result list while the SearchBar is in navigator mode.

## Props (new only)

| Name | Type | Required | Description |
|---|---|---|---|
| `abstractsByPosterId` | `Map<number, AbstractRecord>` | yes | Source of truth for the suggestion list. The bar renders the dropdown in a loading state when the map is empty. |

Existing props (e.g. the `value` binding, `placeholder`, etc.) stay
unchanged.

## New event

| Name | Detail | When fired |
|---|---|---|
| `mode-change` | `{ navigator: boolean }` | Whenever `parseIdOperator(value)` toggles between `null` and non-null. Route owner toggles its result-list visibility on this. |

## DOM contract (for e2e tests + a11y)

The existing `<input data-testid="search-input">` gains combobox
attributes when navigator mode is active; the listbox overlay is a
sibling element rendered only in that state.

```html
<div class="searchbar" role="search">
  <input
    data-testid="search-input"
    {/* existing attrs ... */}
    role="combobox"                          {/* navigator mode only */}
    aria-autocomplete="list"                 {/* nav only */}
    aria-expanded="{open}"                   {/* nav only */}
    aria-controls="search-id-listbox"        {/* nav only */}
    aria-activedescendant="{activeId || ''}" {/* nav only */}
  />
  {#if inNavigatorMode}
    <ul
      id="search-id-listbox"
      data-testid="search-id-listbox"
      role="listbox"
    >
      {#each result.visible as s, i (s.posterId)}
        <li
          id="search-id-option-{s.posterId}"
          data-testid="search-id-option"
          data-poster-id="{s.posterId}"
          role="option"
          aria-selected="{i === activeIndex}"
        >
          <span class="display">{s.display}</span>
          <span class="title">{s.title}</span>
        </li>
      {/each}
      {#if result.visible.length === 0 && idPayload.length === 0}
        <li class="hint" data-testid="search-id-hint" role="status">
          Type a poster number, e.g. <code>id:1234</code>
        </li>
      {/if}
      {#if result.visible.length === 0 && idPayload.length > 0}
        <li class="empty" data-testid="search-id-empty" role="status">
          No matching posters
        </li>
      {/if}
      {#if result.total > result.visible.length}
        <li class="overflow" data-testid="search-id-overflow" aria-live="polite">
          + {result.total - result.visible.length} more — keep typing
        </li>
      {/if}
    </ul>
  {/if}
</div>
```

## Behavior contract

| Trigger | Outcome |
|---|---|
| User types into `[data-testid="search-input"]` | `raw` updates; `inNavigatorMode = parseIdOperator(raw) !== null`. If the flag changed, fire `mode-change`. |
| `inNavigatorMode` becomes true | Result list hidden by route owner; listbox renders. `aria-expanded="true"`. |
| `inNavigatorMode` becomes false | Listbox unmounts; result list re-renders; combobox attrs removed. |
| ArrowDown / ArrowUp in nav mode | Cycle `activeIndex` over `result.visible`. |
| Enter in nav mode with `canNavigate` | `goto(`${base}/abstract/${posterId}/`)`; navigator mode ends on route swap. |
| Click on `[data-testid="search-id-option"]` | Same as Enter on that suggestion. |
| Escape in nav mode | Restore the pre-mode query from the undo buffer if one was set by US2; otherwise close dropdown only. |
| Backspace until `id:` prefix is removed | Mode exits same render cycle. |

## Keyboard shortcut (registered separately, US2)

A layout-level `keydown` listener on `window`:

- Key: `g`, no modifiers.
- If `document.activeElement` is an `<input>`, `<textarea>`, or
  `[contenteditable]` → return early.
- Else: save the current SearchBar value into an `undoBuffer` writable;
  set the SearchBar value to `id:`; focus the SearchBar; place cursor
  at end.
- Escape, while in nav mode and the undoBuffer has a value, restores
  it and clears the buffer.

## A11y contract

- Combobox semantics per WAI-ARIA 1.2 only while in navigator mode.
- The existing `<label>` of the SearchBar still applies; it doesn't
  need to change wording (the operator is the discoverability cue;
  About-page docs name the operator).
- `aria-live="polite"` on the overflow row announces "+ N more".
- Visible focus ring preserved.
- Submit (Enter) is reachable from the keyboard only when
  `canNavigate`; the bar does NOT need a disabled "submit" element
  because the search bar already has no submit affordance — Enter is
  the only commit gesture.

## Test contract

Tests added BEFORE the component is modified:

- `site/src/tests/unit/goto_poster.test.ts` — vitest, covering:
  1. `parseIdOperator`: `id:1234` → `"1234"`, `id:` → `""`,
     `id` (no colon) → `null`, leading non-`id` → `null`,
     case-insensitive `ID:34` → `"34"`, embedded `... id:34` → `null`,
     `topic:x` → `null`.
  2. `normaliseQuery`: empty / whitespace / pure-zero queries → `""`;
     `"0345"` → `"345"`; `"12 3"` → `"123"`.
  3. `filterSuggestions` against a fixture map with ids
     `{12, 121, 129, 212, 1012, 1200, 1299, 2094}`: query `"12"` returns
     `{12, 121, 129, 1200, 1299}` and explicitly excludes `212` and
     `1012`; query `"2094"` returns `total: 1, exactMatch.posterId === 2094`;
     query `"9999"` returns `total: 0`; the 10-row `limit` is honored;
     `visible` is sorted ascending.

- `site/src/tests/e2e/goto_poster.spec.ts` — Playwright, 6 specs:
  1. Type `id:2094` in the search bar → result list hides + dropdown
     shows one match → Enter navigates to `/abstract/2094/`.
  2. Type `id:12` → dropdown lists `0012`, `0120`–`0129`, `1200`–`1299`
     (sampled assertions); `1012` / `0212` are NOT visible.
  3. Type `id:9999` → "No matching posters" hint; Enter is a no-op
     (URL unchanged).
  4. Type `id:` (no digits) → "Type a poster number" hint;
     result list is hidden.
  5. Type `id:12` then Backspace until `id:` is gone → result list
     re-renders; combobox attrs removed from input.
  6. Click on a listbox option's `<li>` → navigation without keyboard.

US2 adds a 7th case for the `g` keyboard shortcut (focus + prefix +
Escape-restores-undo-buffer).
