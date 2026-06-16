# plan-bug1 — Sync de-dup by Zotero key (BUG-1)

**Authorized by:** Ruling 6 (2026-06-15)
**Status:** complete — Planner ✅ · Tester ✅ · Coder ✅ · Docs ✅

---

## Problem

`sync` created duplicate pages on every run: the skip-check asked "does
`{vault}/{Zotero title}.md` exist?", but pages are saved under the LLM-chosen
title, which usually differs — so items were re-compiled endlessly.

## Fix (Ruling 6)

Record the source Zotero item `key`(s) in a new `zotero_keys` frontmatter field
and skip by key. Schema bumps `zotwiki: 1` → `zotwiki: 2` (breaking; old pages
must be regenerated). On `--update`, the compiled article's title is pinned to
the found page's title so the update lands in place (no duplicate, merge fires).

---

## Phase status

### Planner ✅ (committed + pushed: `ee70a49`, `724c709`)
- Ruling 6 (`docs/rulings.md`); REQ-046/047/048 (`docs/requirements.md` §J).
- Contract: §6.2 (`zotero_keys`, `zotwiki: 2`), §6.4 (`render_page` sig +
  round-trip), §6.5 (`publish` sig + union + `compiled_keys()`), §6.7/§6.8
  (`zotero_keys: []`), §6.9 (migration), §7 (`CompileResult.zotero_keys`), §9.2,
  §9.6 (skip-by-key + `--update` title-pin).

### Tester ✅ (this commit — red gate verified)
- New: `tests/test_req_046_048_zotero_keys.py` (11 tests, REQ-046/047/048).
- Oracle retrofit: `tests/m3_helpers.py` (`frontmatter_block`/`render_oracle`
  gain `zotero_keys`; `zotwiki: 2`; `PINNED_PAGE`/`EMPTY_PAGE`),
  `tests/m5_helpers.py` (`_PINNED_INDEX`/`_PINNED_CONTRADICTIONS`).
- Fixture retrofit: `tests/test_m3_parse.py` (`_fm_unknown_key`,
  `_fm_wrong_schema_version` flipped to reject v1),
  `tests/test_m4_auditor_violations.py` (`_insert_unknown_frontmatter_key`).
- Sync retrofit: `tests/test_sync_cli.py` REQ-041/042 pre-write pages with
  `zotero_keys` so the skip is key-based.
- **Red gate:** `81 failed, 307 passed`. All failures are feature-absence:
  `render_page()/publish() got an unexpected keyword argument 'zotero_keys'`,
  `'CompileResult' object has no attribute 'zotero_keys'`, and v2-vs-v1 byte
  diffs (`index 13: b'1' != b'2'`). `test_req_019` (macOS case-collision) is a
  pre-existing, unrelated known failure.

### Coder ✅ (done — full suite green except the known `test_req_019`)

Implement in `src/zotwiki/` (auditor.py / ask.py / models.py need **no** change
— they inherit via the shared `_parse_frontmatter`/`parse_page`):

1. **`compiler.py`** — `CompileResult` gains `zotero_keys: tuple[str, ...]`;
   `compile` returns it `= tuple(sorted(set(keys)))` (the input keys).
2. **`publisher.py`**
   - `_frontmatter_block(...)`: add `zotero_keys=()`; emit `zotwiki: 2`; render a
     `zotero_keys` block (sorted, deduped) **after `citekeys`, before `tags`**;
     empty → `zotero_keys: []`.
   - `_parse_frontmatter`: require first key `zotwiki: 2`; parse `zotero_keys`
     (same block/`[]` grammar as `citekeys`) into `values["zotero_keys"]`, in
     canonical order after `citekeys`, before `tags`.
   - `render_page(...)`: add `zotero_keys=()`; pass `sorted(set(zotero_keys))` to
     `_frontmatter_block`.
   - `publish(article, *, zotero_keys=())`: new page → `sorted(set(zotero_keys))`;
     existing page → **union** with the existing page's `fm["zotero_keys"]`
     (sorted), keeping the byte-level idempotence write-gate.
   - `_render_index` / `publish_contradictions`: keep `zotero_keys: []` (default).
   - NEW `compiled_keys(self) -> dict[str, Path]`: scan `*.md`; map each key in a
     page's frontmatter `zotero_keys` → its `Path` (lexicographically-smallest
     filename wins on collision); skip unparseable pages; Index/Contradictions
     contribute nothing.
3. **`syncer.py`**: `known = publisher.compiled_keys()` once; skip iff
   `item.key in known` and not `--update`; on `--update`,
   `existing = parse_page(known[item.key].read_text())`, compile, then
   `article = dataclasses.replace(result.article, title=existing.title)` (pin)
   before `publish(article, zotero_keys=result.zotero_keys)`; new item →
   `publish(result.article, zotero_keys=result.zotero_keys)`.
4. **`cli.py`** `_cmd_compile`: `publish(result.article, zotero_keys=result.zotero_keys)`.

**Done-gate:** full suite green except the known `test_req_019`:
`uv run --with pytest --with hypothesis --with pytest-httpserver pytest -q`
Watch byte-exactness — frontmatter key order is exactly
`zotwiki, title, created, updated, citekeys, zotero_keys, tags`.

### After coder
- Update docs for the new field + migration: `README.md`, `docs/operator.md`
  (frontmatter / migration note), `docs/document-library.md`, `CLAUDE.md`
  (status → REQ-048; frontmatter layout). Commit + push coder, then docs.
