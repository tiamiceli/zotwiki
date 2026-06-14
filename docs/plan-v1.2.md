# plan-v1.2 — Fulltext child-attachment fallback (REQ-045)

**Authorized by:** Ruling 4 (2026-06-14)
**Status:** active

---

## Problem

`_probe_fulltext(key)` and `fulltext(key)` call only `GET /items/{key}/fulltext`.
In Zotero 7, fulltext is indexed on child attachment items (PDFs), not on the
parent record. So every item with an attached PDF has `has_fulltext = False` and
is compiled without fulltext — causing the LLM to refuse (no verbatim quotes
available).

---

## Scope

One file changes: `src/zotwiki/zotero.py`.

No new public symbols. No protocol changes. No CLI changes.

---

## Phase A — TDD (tester first, then coder)

### Done-gate (red)

The tester commits tests for REQ-045 that **fail** before the coder writes any
code. Failure is confirmed by running the full suite and seeing REQ-045 tests
error or fail while all pre-existing tests remain green.

### Tester deliverables

Add a test module `tests/test_req_045_fulltext_children.py` covering:

1. **Parent-has-fulltext (regression):** item whose parent fulltext endpoint
   returns 200 still resolves `has_fulltext = True` and `fulltext(key)` returns
   the parent's content. No children endpoint is hit.

2. **Child-fallback probe:** item whose parent endpoint returns 404, with one
   child key whose `/fulltext` endpoint returns 200 →
   `has_fulltext = True` for that item.

3. **Child-fallback fetch:** same setup; `store.fulltext(key)` returns the
   child's content string.

4. **No-fulltext anywhere:** item whose parent returns 404 and whose only child
   also returns 404 → `has_fulltext = False`; `store.fulltext(key)` raises
   `FulltextNotFoundError`.

5. **No children at all:** item whose parent returns 404 and whose `/children`
   endpoint returns an empty array → `has_fulltext = False`.

The fake server must serve:
- `GET /items/{KEY}/fulltext` → 200 or 404 per fixture
- `GET /items/{KEY}/children?format=json` → JSON array of child objects
  (each with at least a top-level `"key"` field), or empty array

### Coder deliverables

Modify `src/zotwiki/zotero.py` only:

1. Add a private method `_child_keys(self, key: str) -> list[str]` that:
   - Calls `GET /items/{key}/children?format=json` (contract §4.9).
   - Returns a list of child `key` strings from the response array.
   - Returns `[]` on 404 (parent unknown or no children — treat as no children).
   - Raises `ZoteroError` on malformed response (not a JSON array, or an element
     has no `"key"` string).

2. Update `_probe_fulltext(self, key: str) -> bool`:
   - Step 1: `GET /items/{key}/fulltext` → if 200, return `True`.
   - Step 2: if 404, call `_child_keys(key)`; for each child key,
     `GET /items/{child_key}/fulltext` → first 200 returns `True`.
   - Step 3: if all 404, return `False`.

3. Update `fulltext(self, key: str) -> str`:
   - Step 1: `GET /items/{key}/fulltext` → if 200, return `content`.
   - Step 2: if 404, call `_child_keys(key)`; for each child key,
     `GET /items/{child_key}/fulltext` → first 200 returns its `content`.
   - Step 3: if all 404, raise `FulltextNotFoundError`.

### Done-gate (green)

Full suite passes (all pre-existing tests + REQ-045 tests).

---

## No Phase B

No refactors, no contract surface changes beyond §4.9 and the §4.5 update.
