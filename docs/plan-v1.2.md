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

---

## Known bugs discovered during v1.2 work (not yet planned)

### BUG-1 — Sync skip-check uses Zotero item title, not compiled article title

**Observed:** 2026-06-15

**Symptom:** `sync` re-compiles the same Zotero item on every run, creating
multiple pages with slightly different titles (e.g. "Data Anomaly Typology",
"Typology of Data Anomalies", "A Typology of Data Anomalies") instead of
skipping it after the first compile.

**Root cause:** `Syncer.sync()` (`src/zotwiki/syncer.py:57`) determines whether
a page already exists via `publisher.page_path(item.title)` — where
`item.title` is the Zotero metadata title (e.g. "A Typology of Data
Anomalies"). The compiled article title is chosen by the LLM and is often
different (shorter, reformatted). If they don't match, no file is found at the
expected path and the item is compiled again every run.

**Impact:** Duplicate pages accumulate in the vault; skip logic is unreliable
for any item whose LLM-generated title differs from its Zotero title.

**Needs:** ruling + contract decision on how the syncer should track which
items have been compiled (by citekey? by Zotero key? by persisting a manifest?)
before a tester and coder can address it.

### BUG-2 — LLM sometimes produces invalid claim schema (addressed by prompt refactor)

**Observed:** 2026-06-15 · **Status:** mitigated (not fully fixed)

**Symptom:** `sync` exits 1 with errors like `claims[0].citekey: unknown key`
or `claims[2].quotes[1].text: must be a single line`. Inconsistent across
retries.

**Root cause:** `_BASE_INSTRUCTIONS` in `src/zotwiki/compiler.py` referenced
"docs/contract.md SS5.2" without including the actual schema. The LLM guessed
at field names (`citekey` vs `citekeys`) and allowed multi-line quote strings.

**Mitigation applied (commit 555c02d):** Prompt now includes an explicit JSON
shape example and a rule that quote text must be a single line. Schema errors
are significantly reduced but may still occur occasionally on complex papers.
