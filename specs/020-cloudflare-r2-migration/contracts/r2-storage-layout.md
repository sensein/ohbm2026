# Contract: R2 Storage Layout & Bucket Configuration

The content-addressed object layout and the bucket-side configuration the live
site depends on. The object layout is enforced by the uploader; the bucket
configuration is a one-time **operator action** (documented here and in
`quickstart.md`).

## Object key scheme (enforced by the uploader)

```
[<R2_KEY_PREFIX>/]<sha256hex>/<original-filename>
```

- `<sha256hex>`: full 64-char lowercase hex SHA-256 of the **exact bytes** the
  browser fetches.
- `<original-filename>`: e.g. `neuroscape.parquet` (preserves extension + a
  human-recognisable name).
- `<R2_KEY_PREFIX>`: optional namespace (default empty).

**Invariants**
- *Content-addressed*: identical bytes → identical key (dedup); different bytes
  → different key (no collision, no overwrite).
- *Immutable*: a key, once written, is never overwritten or deleted by the
  pipeline. New versions add new keys.
- *Self-describing*: the key's hash equals the served content's hash, so a
  consumer can verify integrity from the URL alone (and the registry's `sha256`
  field matches it).

Example:
```
a3f1…d9/ohbm2026.parquet
b7c2…04/neuroscape.parquet
c91e…7a/atlas.parquet
d042…11/neuroscape_vectors.parquet   # required — production build keeps the semantic index on
```

## Public URL

```
${R2_PUBLIC_BASE_URL}/<object_key>
```

`R2_PUBLIC_BASE_URL` is either R2's managed `https://pub-<hash>.r2.dev` or a
Cloudflare custom domain bound to the bucket. The site stores this full URL in
the registry and treats it as opaque.

## Required bucket configuration (operator)

The site is a static gh-pages app fetching cross-origin with Range; the bucket
MUST provide, equivalently to Dropbox's `dl.dropboxusercontent.com` today:

1. **Public read** — unauthenticated `GET` on objects (via r2.dev public access
   or a custom domain with public read).
2. **CORS** — a rule allowing the production origin(s) and PR-preview origin(s):
   - `AllowedOrigins`: the gh-pages production origin (e.g.
     `https://abstractatlas.brainkb.org`) and the preview origin pattern.
   - `AllowedMethods`: `GET`, `HEAD`.
   - `AllowedHeaders`: `Range`.
   - `ExposeHeaders`: `Content-Range`, `Accept-Ranges`, `ETag`, `Content-Length`.
3. **Range** — byte-range GET (`206 Partial Content`). R2 supports this on
   public objects by default; the CORS `ExposeHeaders` above make the ranged
   bytes usable by the browser.
4. **Cache** — `Cache-Control: public, max-age=31536000, immutable` on uploaded
   objects (safe because keys are content-addressed). Set via object metadata at
   upload time and/or a bucket rule.

`compare-data-hosting` verifies (1)–(3) against the live endpoint before any
cutover; (4) is a performance optimisation, not a correctness gate.

## What is NOT in R2's object layout

- No mutable "latest" alias — versioning is by content hash + the registry
  channel that an operator points at a specific set.
- No directory manifest object — the **upload manifest** (local, under
  `data/provenance/`) and the **registry channel entry** carry the grouping;
  the bucket holds only content-addressed blobs.
