# plan-v1.2 — Fulltext child-attachment fallback (REQ-045)

**Authorized by:** Ruling 4 (2026-06-14); compact-embed rule by Ruling 5 (2026-06-15)
**Status:** Phase A + B complete; BUG-1 pending (needs ruling), BUG-2 mitigated

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

## Phase B — Prompt helper refactors (no new REQs, no contract changes)

Gate: existing test suite stays green throughout. No tester phase needed.
All changes are in `src/zotwiki/compiler.py` only unless noted.

### B1 — `_schema_example_json()`: generate schema example from real dataclasses

**Problem:** The JSON shape example in `_BASE_INSTRUCTIONS` is a hand-written
string that must be manually kept in sync with `Article`, `Claim`, `Quote`, and
`Section` in `models.py`. Drift causes schema errors in LLM output.

**Fix:** Add `_schema_example_json() -> str` that builds the example by calling
`article_to_json_dict(Article(...))` with a minimal synthetic article, then
`json.dumps(..., indent=2)`. Embed its output in `_BASE_INSTRUCTIONS` (or build
the instructions lazily at prompt time). The example will always match what
`parse_article_json` actually validates.

### B2 — `_render_validation_rules()`: derive rules from the real regex constants

**Problem:** `_BASE_INSTRUCTIONS` repeats the title/citekey character sets as
prose. The canonical patterns live in `llm.py` as `_TITLE_RE` and `_CITEKEY_RE`
but are not referenced from the prompt. If the regexes change, the prompt
silently diverges.

**Fix:** Add `_render_validation_rules() -> str` that imports `_TITLE_RE` and
`_CITEKEY_RE` from `zotwiki.llm`, extracts `.pattern`, and formats them as
explicit rules (e.g., `"Title must match: ^[A-Za-z0-9]…"`). Replace the
hard-coded prose in `_BASE_INSTRUCTIONS` with the output of this function.

### B3 — `_format_source_item(item, fulltext)`: encapsulate source block

**Problem:** Source item blocks are assembled inline in `_build_prompt`'s loop
with ad-hoc string concatenation. Adding fields (year, creators) or changing
delimiters requires editing the loop directly.

**Fix:** Extract the loop body into `_format_source_item(item: SourceItem, fulltext: str | None) -> str`. The loop becomes:
```python
for item, fulltext in items:
    parts.append(_format_source_item(item, fulltext))
```
Consider adding an explicit `[END FULLTEXT]` delimiter so the LLM knows where
the text ends.

### B4 — `_format_existing_article(article)`: encapsulate update-mode JSON block

**Problem:** The existing article is serialized inline in `_build_prompt` with
`json.dumps(article_to_json_dict(existing), sort_keys=True)`. The `sort_keys`
choice is unexplained and the label/formatting is coupled to the builder.

**Fix:** Extract to `_format_existing_article(article: Article) -> str` that
returns the labeled JSON block. Keep the serialization **compact** —
`json.dumps(article_to_json_dict(existing), sort_keys=True)`, no `indent`:
contract §7.1 requires this exact string to appear in the prompt as a verbatim
substring, so indenting it would break REQ-014/REQ-034 (see Ruling 5).
`sort_keys` ensures deterministic output across Python versions. The builder
becomes `parts.append(_format_existing_article(existing))`.

### B5 — `_update_instructions_with_schema()`: add Contradiction example to update prompt

**Problem:** `_UPDATE_INSTRUCTIONS` describes the `contradictions` array in
prose ("existing_claim, new_claim, citekeys") without a JSON example. The LLM
has no concrete shape to follow, risking the same schema-error pattern that
affected claims.

**Fix:** Replace `_UPDATE_INSTRUCTIONS` with a function
`_update_instructions_with_schema() -> str` that constructs the text and
includes a small `json.dumps` example of a `Contradiction` object with the
correct three field names.

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
