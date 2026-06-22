# ZotWiki — Requirements

Status: binding. Every REQ is one observable behavior, testable from outside the
system. Exact types, signatures, wire formats, file formats, and exit codes are
defined in `docs/contract.md`; this file defines *what must happen*.

Test environment ground rules (apply to every REQ):

- Tests are hermetic. Network connections only to `127.0.0.1` fixtures (a fake
  Zotero HTTP server started by the test). No real Zotero, no real Anthropic.
- The LLM is always an injected fake implementing the `LLMClient` protocol.
- The vault is always a `tmp_path` directory.
- "The store" below means an `HTTPZoteroStore` pointed at the test's fake
  server unless a REQ says otherwise.

---

## A. ZoteroStore adapter

### REQ-001 — Search returns mapped SourceItems
**Given** the fake Zotero server holds two items whose titles contain
"attention", with creators, dates, URLs and `extra` citekey lines as in
contract §4.4,
**When** `store.search("attention")` is called,
**Then** it returns a `list[SourceItem]` of length 2, in server order, with
`key`, `citekey`, `title`, `creators`, `year`, `url`, `has_fulltext` mapped
exactly per contract §3.1/§4.4 (year extracted as the first 4-digit run of the
`date` field; empty `url` mapped to `None`; missing creators mapped to `()`).
**Error behavior:** a malformed JSON body from the server raises
`ZoteroError`.

### REQ-002 — Search wire parameters and limit validation
**Given** a fake server that records request paths and query strings,
**When** `store.search("two words", limit=7)` is called,
**Then** the server receives exactly one
`GET /items?q=two+words&qmode=titleCreatorYear&limit=7&format=json` request
(URL-encoded query) plus the per-item fulltext probes of REQ-009.
**Error behavior:** `limit < 1` or `limit > 100` raises `ValueError` before
any HTTP request is made.

### REQ-003 — Get by key
**Given** the fake server holds item `ABCD1234`,
**When** `store.get("ABCD1234")` is called,
**Then** it returns the mapped `SourceItem` for that item.
**Error behavior:** if the server returns 404 for the key, `get` raises
`ItemNotFoundError`; no retry is attempted.

### REQ-004 — Fulltext fetch
**Given** the fake server serves `{"content": "Sphinx of black quartz."}` at
`GET /items/ABCD1234/fulltext`,
**When** `store.fulltext("ABCD1234")` is called,
**Then** it returns exactly `"Sphinx of black quartz."`.
**Error behavior:** 404 on the fulltext path raises `FulltextNotFoundError`;
no retry is attempted.

### REQ-005 — Citekey extraction from `extra`
**Given** an item whose `data.extra` is
`"Some note\nCitation Key: doe2020attention\nMore"`,
**When** the item is returned by `get`, `search`, or `resolve`,
**Then** its `SourceItem.citekey == "doe2020attention"`.
**Error behavior:** none — if no line matches the contract §3.1 pattern,
`citekey` is the empty string `""` (no exception).

### REQ-006 — Resolve citekey to item
**Given** the fake server holds exactly one item whose `extra` contains
`Citation Key: doe2020attention` among other items,
**When** `store.resolve("doe2020attention")` is called,
**Then** it issues `GET /items?q=doe2020attention&qmode=everything&limit=100&format=json`
and returns the `SourceItem` whose parsed citekey equals the argument exactly
(case-sensitive); if several match, the first in server order.
**Error behavior:** if no returned item's parsed citekey matches exactly,
raises `CitekeyNotFoundError` (a server hit on a different field is not a
match).

### REQ-007 — Add a source
**Given** an empty fake server that records POST bodies,
**When** `store.add(title="A Study of Owls", url="https://owl.example", creators=["Ada Lovelace"], year=2021)`
is called,
**Then** the server receives one `POST /items` whose body is a JSON array of
one item-data object per contract §4.6, whose `extra` is
`"Citation Key: lovelace2021study"` (citekey generated per contract §3.3), and
the call returns the `SourceItem` built from the server's `successful`
response with that citekey.
**Error behavior:** a response with a non-empty `failed` object raises
`ZoteroError`. If the generated citekey already resolves, suffixes `a`–`z`
are tried in order; if all collide, `ZoteroError` is raised and nothing is
posted.

### REQ-008 — Retry, backoff, and timeout
**Given** a fake server that returns HTTP 500 twice and then 200 for the same
GET,
**When** `store.get(key)` is called on a store constructed with
`retries=2, backoff=0.1` and an injected recording `sleep`,
**Then** the call succeeds, exactly 3 HTTP attempts were made, and `sleep` was
called with `0.1` then `0.2`.
**Error behavior:** if all `1 + retries` attempts fail with 5xx, connection
error, or timeout, `ZoteroUnavailableError` is raised. HTTP 4xx is never
retried: 404 maps per REQ-003/004/006; any other 4xx raises `ZoteroError`
immediately.

### REQ-009 — Fulltext availability probe
**Given** item `AAAA0001` whose fulltext endpoint returns 200 and item
`BBBB0002` whose fulltext endpoint returns 404,
**When** either item is materialized as a `SourceItem` (via `get`, `search`,
or `resolve`),
**Then** `has_fulltext` is `True` for `AAAA0001` and `False` for `BBBB0002`,
established by a `GET /items/{key}/fulltext` probe per item.
**Error behavior:** probe failures other than 404 follow REQ-008.

---

## B. Article schema and LLM boundary

### REQ-010 — Valid article JSON parses to an Article
**Given** a string containing exactly the JSON object of contract §5.2 (all
five required keys, well-formed claims with citekeys and quotes),
**When** `parse_article_json(text)` is called,
**Then** it returns `(article, contradictions)` where `article` is a frozen
`Article` whose fields equal the JSON values (with the whitespace
normalization of contract §5.4) and `contradictions` is `()` when the key is
absent.
**Error behavior:** none for valid input.

### REQ-011 — Invalid article JSON always raises
**Given** any of: non-JSON text; a JSON array; a missing required key; an
unknown top-level key; an empty `title` or a `title` failing the safe-charset
rule; a claim with zero citekeys; a claim with zero quotes; a quote whose
`citekey` is not in its claim's `citekeys`; a section heading equal to
`Claims`, `Links`, or `References`; duplicate section headings; a claim text
containing the substring `" [@"`; a body line starting with `#`,
**When** `parse_article_json(text)` is called,
**Then** it raises `ArticleSchemaError` whose message names the offending
JSON path; no partial `Article` is ever returned.
**Error behavior:** this REQ *is* the error behavior; silent pass-through is
a failure.

### REQ-012 — Code-fence tolerance
**Given** the same valid JSON wrapped as ` ```json\n{...}\n``` ` (with or
without the `json` language tag),
**When** `parse_article_json(text)` is called,
**Then** it parses identically to the unfenced input.
**Error behavior:** anything other than optional outer whitespace and one
outer fence pair still raises `ArticleSchemaError`.

---

## C. Compiler

### REQ-013 — Compile a new article
**Given** a store holding item `ABCD1234` (citekey `doe2020attention`, with
fulltext) and a fake `LLMClient` that records its prompt and returns a valid
article JSON,
**When** `Compiler(store, llm).compile(["ABCD1234"])` is called,
**Then** the recorded prompt contains the item's citekey, its title, and its
fulltext truncated to at most `FULLTEXT_PROMPT_LIMIT` characters, and the
result is a `CompileResult` whose `article` equals the fake's JSON parsed per
REQ-010 and whose `contradictions == ()`.
**Error behavior:** if the fake returns invalid JSON, `compile` raises
`ArticleSchemaError`.

### REQ-014 — Compile in update mode
**Given** an existing `Article` and a fake LLM returning a valid article JSON
that includes a non-empty `contradictions` array,
**When** `compile(keys, existing=existing)` is called,
**Then** the recorded prompt contains the existing article as the **compact**
substring `json.dumps(article_to_json_dict(existing), sort_keys=True)` (no
indentation), and `CompileResult.contradictions` contains the parsed
`Contradiction` values in order.
**Error behavior:** a non-empty `contradictions` array when `existing is None`
raises `ArticleSchemaError`.

### REQ-015 — Items without citekeys cannot be compiled
**Given** a store item whose `extra` has no citation-key line (so
`citekey == ""`),
**When** `compile` is called with that item's key,
**Then** it raises `CitekeyNotFoundError` naming the offending Zotero key,
before any LLM call is made.
**Error behavior:** this REQ is the error behavior.

### REQ-016 — Merge never clobbers
**Given** an existing `Article` with sections `Intro`, `Method`, claims C1, C2
and links `[[A]]`, and an update `Article` (same title) with section `Method`
(new body), new section `Results`, claim C2 (same normalized text, different
citekeys/quotes) and new claim C3, and link `[[B]]`,
**When** `merge_articles(existing, update)` is called,
**Then** the result keeps `Intro` verbatim, replaces the body of `Method`,
appends `Results`, keeps C1 verbatim, merges C2 (citekey union sorted, quote
union deduped by `(citekey, normalized text)`), appends C3, links are the
sorted union, and the update's summary replaces the old one.
**Error behavior:** differing titles raise `ArticleSchemaError`. The function
is pure: identical inputs give identical (equal) outputs.

---

## D. VaultPublisher

### REQ-017 — Deterministic page rendering
**Given** an `Article` and its references,
**When** `render_page(article, references, created="2026-06-11", updated="2026-06-11")`
is called,
**Then** the output is byte-for-byte the canonical format of contract §6
(frontmatter keys in fixed order, sorted citekeys, sorted claim citekeys,
quotes sorted by `(citekey, text)`, sorted Links, References sorted by
citekey, LF line endings, no trailing spaces, exactly one trailing newline),
and calling it twice gives identical strings.
**Error behavior:** none for valid input.

### REQ-018 — References block resolves to Zotero
**Given** an article whose claims cite `doe2020attention` (Zotero key
`ABCD1234`),
**When** the page is rendered,
**Then** the References block contains the line format of contract §6.6
including `zotero://select/library/items/ABCD1234`.
**Error behavior:** `render_page` raises `VaultError` if `references` is
missing a cited citekey or contains an uncited one.

### REQ-019 — Publish is idempotent
**Given** a publisher with fixed `today="2026-06-11"` and an article not yet
in the vault,
**When** `publish(article)` is called twice,
**Then** the first call creates `{Title}.md` with `created == updated ==
"2026-06-11"`, and the second call leaves the file byte-identical (the
publisher must not rewrite an unchanged page; `updated` stays unchanged even
if `today` differs on the second call).
**Error behavior:** a title that differs from an existing page's title only
by case raises `VaultError` (no file written).

### REQ-020 — Publish merges with the on-disk page
**Given** a published page and a second `Article` (same title) adding a claim,
published with a later `today`,
**When** `publish` is called,
**Then** the on-disk page contains the mechanical merge per REQ-016 rendered
canonically, `created` keeps its original value, and `updated` equals the new
`today`.
**Error behavior:** an on-disk page that fails `parse_page` raises
`PageParseError`; the file is left unmodified.

### REQ-021 — Page round-trip
**Given** any valid `Article` `a` rendered to text `t`,
**When** `parse_page(t)` is called,
**Then** it returns an `Article` equal to `a`.
**Error behavior:** text violating the contract §6 grammar (bad frontmatter,
missing `## Claims`/`## Links`/`## References` headings, malformed claim or
quote lines) raises `PageParseError`.

### REQ-022 — Index maintenance
**Given** a vault where pages `Beta.md` then `Alpha.md` are published,
**When** each `publish` returns,
**Then** `Index.md` exists, conforms to contract §6.7, and lists exactly
`[[Alpha]]` then `[[Beta]]` (every entity page, sorted, excluding `Index.md`
and `Contradictions.md`); republishing without change leaves `Index.md`
byte-identical.
**Error behavior:** none beyond REQ-019/020.

---

## E. Auditor

### REQ-023 — Clean vault passes
**Given** a vault produced by publishing valid articles whose citekeys all
resolve on the fake server and whose quotes all appear in the corresponding
fulltexts,
**When** `Auditor(vault, store).audit()` is called,
**Then** it returns an `AuditReport` with `ok is True`, zero violations, and
`pages_checked` equal to the number of entity pages.
**Error behavior:** none.

### REQ-024 — Unresolvable citekey is flagged
**Given** a page citing a citekey the store cannot resolve,
**When** the audit runs,
**Then** the report contains a violation with `code == "CITEKEY_UNRESOLVED"`,
the page filename, and the citekey in `detail`; `ok is False`.
**Error behavior:** none (a violation is the outcome, not an exception).

### REQ-025 — Quote verification with normalization
**Given** a fulltext `It’s  a “QUARTZ—sphinx”.` and a page quote
`it's a "quartz-sphinx".`,
**When** the audit runs,
**Then** no quote violation is reported (normalization per contract §8.2:
NFKC, curly→straight quotes, dashes→`-`, casefold, whitespace collapse).
**And given** a quote not present in the normalized fulltext, or a cited item
with `has_fulltext == False`,
**Then** a violation `code == "QUOTE_NOT_FOUND"` is reported naming the
citekey and quote prefix.
**Error behavior:** none.

### REQ-026 — Broken wiki-links are flagged
**Given** a page body or Links section containing `[[Missing Page]]` with no
`Missing Page.md` in the vault,
**When** the audit runs,
**Then** a violation `code == "BROKEN_LINK"` names the page and the target.
Alias links `[[Target|shown]]` are checked against `Target`.
**Error behavior:** none.

### REQ-027 — Orphans and stale index entries
**Given** an entity page absent from `Index.md`, and an `Index.md` entry whose
file does not exist,
**When** the audit runs,
**Then** the first yields `code == "ORPHAN_PAGE"` and the second
`code == "INDEX_STALE"`.
**Error behavior:** a missing `Index.md` with ≥1 entity page yields
`ORPHAN_PAGE` for every entity page.

### REQ-028 — Unparseable pages are flagged
**Given** a `.md` file in the vault root that violates the page grammar,
**When** the audit runs,
**Then** a violation `code == "PAGE_UNPARSEABLE"` names the file; other pages
are still audited.
**Error behavior:** none.

### REQ-029 — Reference-block completeness
**Given** a page where the set of citekeys in claims, the References block,
and the frontmatter `citekeys` list are not all equal,
**When** the audit runs,
**Then** a violation `code == "REFERENCE_MISSING"` names the page and the
mismatching citekey(s).
**Error behavior:** none.

### REQ-030 — Audit determinism and hard failures
**Given** a vault with multiple violations,
**When** the audit runs twice,
**Then** both reports list violations in identical order, sorted by
`(page, code, detail)`.
**Error behavior:** if the vault directory does not exist, `audit()` raises
`VaultError`; if Zotero is unreachable (per REQ-008 exhaustion),
`ZoteroUnavailableError` propagates. `Contradictions.md` is exempt from
claim/quote/reference checks but its `[[links]]` are still checked.

---

## F. Contradiction flagging

### REQ-031 — Contradictions go to the contradictions page
**Given** a `CompileResult` with one `Contradiction` for page `Gravity`,
**When** `publish_contradictions("Gravity", contradictions)` is called with
`today="2026-06-11"`,
**Then** `Contradictions.md` exists (created on first use) and ends with the
block of contract §6.8 (`## Gravity (2026-06-11)` plus the
`- EXISTING:`/`- NEW:` pair), prior blocks are preserved verbatim, and the
`Gravity.md` entity page is byte-identical to before the call (the existing
claim is never rewritten and the contradicting claim is not added).
**Error behavior:** an empty `contradictions` sequence raises `ValueError`
(callers must not create empty blocks).

---

## G. CLI

All commands: stdout/stderr formats and the exit-code mapping are contract §9.
CLI tests run hermetically by calling `main(argv, store=fake_store, llm=fake_llm)`
in-process; `main` returns the exit code as an `int` and never calls
`sys.exit` itself.

### REQ-032 — `zotwiki ingest`
**Given** a fake store,
**When** `main(["ingest", "--title", "A Study of Owls", "--url", "https://owl.example", "--creator", "Ada Lovelace", "--year", "2021"], store=fake)`
runs,
**Then** the item is added per REQ-007, stdout is exactly one line
`{citekey}\t{key}\n`, and the return value is 0.
**Error behavior:** Zotero unreachable → return 2, one `error: ...` line on
stderr, empty stdout.

### REQ-033 — `zotwiki compile` creates a page
**Given** a fake store with item `ABCD1234` and a fake LLM returning a valid
article titled `Owls`,
**When** `main(["compile", "--vault", str(vault), "--key", "ABCD1234", "--today", "2026-06-11"], store=fake, llm=fakellm)`
runs,
**Then** `Owls.md` and `Index.md` exist per contract §6, stdout contains the
line `compiled\tOwls\t{path}`, and the return value is 0.
**Error behavior:** invalid LLM output → return 1, `error: ...` on stderr,
no page written. Zero matched items → return 1.

### REQ-034 — `zotwiki compile --page` updates and reports contradictions
**Given** an existing `Owls.md` and a fake LLM whose output contains one
contradiction,
**When** `main(["compile", "--vault", v, "--page", "Owls", "--key", K, "--today", D], ...)`
runs,
**Then** the page is merged per REQ-020, `Contradictions.md` is appended per
REQ-031, stdout contains `compiled\tOwls\t{path}` and
`contradictions\tOwls\t1`, and the return value is 0.
**Error behavior:** LLM output whose `title` differs from `--page` → return 1,
nothing written.

### REQ-035 — `zotwiki audit`
**Given** a vault and fake store,
**When** `main(["audit", "--vault", v], store=fake)` runs,
**Then** on a clean vault stdout's last line is `audit: ok ({n} pages)` and
the return is 0; on violations stdout has one `{code}\t{page}\t{detail}` line
per violation in report order, a final `audit: {n} violation(s)` line, and
the return is 1.
**Error behavior:** missing vault dir or unreachable Zotero → return 2.

### REQ-036 — `zotwiki ask`
**Given** a vault with published pages and a fake LLM returning the answer
JSON of contract §7 citing an existing page and its citekeys,
**When** `main(["ask", "--vault", v, "What do owls eat?"], llm=fakellm)` runs,
**Then** stdout is the answer text, a blank line, `Sources:`, then one
`- [[Page]] [@citekey]` line per (page, citekey) pair, and the return is 0.
**Error behavior:** answer JSON citing a nonexistent page or a citekey not in
that page's frontmatter → return 1. A vault with no entity pages → return 2
(`VaultError`), and the LLM is never called.

### REQ-037 — Exit-code mapping
**Given** any command,
**When** it fails,
**Then** the process-level mapping of contract §9.3 holds: 0 success;
1 domain failure (`ArticleSchemaError`, `ItemNotFoundError`,
`CitekeyNotFoundError`, `FulltextNotFoundError`, `PageParseError`, audit
violations, ask-citation failures); 2 environment failure
(`ZoteroUnavailableError`, `VaultError`, missing LLM configuration, argparse
usage errors). Every failure prints exactly one `error: {message}` line to
stderr (audit violations excepted: they go to stdout per REQ-035).
**Error behavior:** this REQ is the error behavior.

### REQ-038 — Injection seam
**Given** no network and no environment variables,
**When** `main` is called with explicit `store=` and `llm=` keyword arguments,
**Then** no real adapter or LLM client is constructed and no connection is
attempted to any host other than what the injected fakes do.
**Error behavior:** `main(["compile", ...])` without an injected `llm` and
with `claude` not on PATH → return 2 with `error: claude not found` on stderr.

### REQ-039 — `ClaudeCodeLLMClient` calls `claude -p` with structured output and extracts the result
**Given** a fake `claude` binary on PATH that reads a prompt from stdin and
prints a **success envelope** to stdout (a JSON object with
`"subtype": "success"`, a `"structured_output"` object, and a `"result"` string)
with exit code 0 (contract §5.6),
**When** `ClaudeCodeLLMClient(output_schema=SCHEMA).complete(prompt)` is called,
**Then** the fake binary is invoked with `--print --output-format json
--json-schema <json.dumps(SCHEMA)> --exclude-dynamic-system-prompt-sections`, the
full prompt is passed via stdin, and the returned string equals
`json.dumps(envelope["structured_output"])` (so the unchanged `parse_article_json`
gates it). **And** with `output_schema=None`, `--json-schema` is **absent** from
the argv and the returned string equals the envelope's `"result"`.
**Error behavior:** if `claude` is not found on PATH → `ZotWikiError` is raised
with the message `"claude not found"` (no subprocess, no artifact). Non-success
envelopes, non-zero exit, and malformed output are covered by REQ-055.

---

## H. Syncer and sync subcommand

### REQ-040 — `collection_items` returns mapped items from a named collection
**Given** the fake Zotero server exposes two collections ("AI Papers" with key
`COL00001` holding two items, and "Other" with key `COL00002` holding none),
**When** `store.collection_items("AI Papers")` is called,
**Then** it returns a `list[SourceItem]` of length 2 in server order, each
mapped per contract §3.1 (citekeys, titles, has_fulltext probes, etc.).
**Error behavior:** `store.collection_items("Nonexistent")` raises
`CollectionNotFoundError`; Zotero unreachable → `ZoteroUnavailableError`.

### REQ-041 — sync compiles new items and skips existing pages
**Given** a vault with one existing page (`Transformer.md` for an item with
citekey `vaswani2017attention`) and a collection containing that item plus one
new item (citekey `devlin2019bert`, title `BERT`),
**When** `main(["sync", "--vault", v, "--collection", "AI Papers"], store=fake, llm=fakelLm)`
is called,
**Then** exit 0; stdout contains `compiled\tBERT\t{path}\n`,
`skipped\tTransformer\n`, and `sync: 1 compiled, 1 skipped\n` (in that order,
summary always last).
**Error behavior:** vault directory missing → return 2.

### REQ-042 — sync with --update re-compiles existing pages
**Given** the same vault and collection as REQ-041,
**When** `main(["sync", "--vault", v, "--collection", "AI Papers", "--update"], ...)`
is called,
**Then** exit 0; stdout contains two `compiled\t...\n` lines (one per item) and
`sync: 2 compiled, 0 skipped\n`; `Transformer.md` is overwritten with the
LLM's output.
**Error behavior:** same as REQ-041.

### REQ-043 — collection not found exits 2
**Given** a fake store where no collection is named `"Nonexistent"`,
**When** `main(["sync", "--vault", v, "--collection", "Nonexistent"], store=fake, llm=fakellm)`
is called,
**Then** exit 2; stderr is exactly `error: collection 'Nonexistent' not found\n`.
**Error behavior:** this REQ is the error behavior.

### REQ-044 — items without citekeys are skipped silently
**Given** a collection containing one item with a citekey and one with an
empty Extra field (no citekey),
**When** `main(["sync", "--vault", v, "--collection", "AI Papers"], ...)`
is called,
**Then** exit 0; the citekey-less item produces no stdout line (neither
`compiled` nor `skipped`); the summary is `sync: 1 compiled, 0 skipped\n`
(the no-citekey item is absent from both totals).
**Error behavior:** none.

---

## I. Fulltext child-attachment fallback

### REQ-045 — fulltext probe and fetch fall through to child attachment items

**Given** a fake Zotero server where:
- Item `AAAA0001` has fulltext at `GET /items/AAAA0001/fulltext` (200) — no
  children endpoint is needed (regression guard).
- Item `BBBB0002` has no fulltext at `GET /items/BBBB0002/fulltext` (404), but
  has one child key `CCCC0003` whose fulltext endpoint returns 200 with content
  `"child text"`. The children endpoint `GET /items/BBBB0002/children` returns
  `[{"key": "CCCC0003"}]`.
- Item `DDDD0004` has no fulltext at the parent (404), one child `EEEE0005`
  also with no fulltext (404), and `GET /items/DDDD0004/children` returns
  `[{"key": "EEEE0005"}]`.
- Item `FFFF0006` has no parent fulltext (404) and `GET /items/FFFF0006/children`
  returns `[]`.

**When** each item is materialized as a `SourceItem` (via `get`, `search`, or
`resolve`) and `store.fulltext(key)` is called,

**Then:**
- `AAAA0001.has_fulltext == True`; `store.fulltext("AAAA0001")` returns the
  parent content; the children endpoint is never hit for `AAAA0001`.
- `BBBB0002.has_fulltext == True`; `store.fulltext("BBBB0002")` returns
  `"child text"`.
- `DDDD0004.has_fulltext == False`; `store.fulltext("DDDD0004")` raises
  `FulltextNotFoundError`.
- `FFFF0006.has_fulltext == False`; `store.fulltext("FFFF0006")` raises
  `FulltextNotFoundError`.

**Error behavior:** the children endpoint is only called when the parent
fulltext probe returns 404 (lazy). A 404 from the children endpoint itself is
treated as an empty list (no error). Non-404 HTTP errors from any probe follow
REQ-008.

---

## J. Compiled-item tracking (BUG-1)

### REQ-046 — Page frontmatter records source Zotero keys (schema v2)
**Given** a canonical `Article`, matching `references`, and a sequence `Z` of
Zotero item keys,
**When** `render_page(article, references, created=c, updated=u, zotero_keys=Z)`
is called,
**Then** the frontmatter opens with `zotwiki: 2`, and a `zotero_keys` entry
appears in canonical order **after `citekeys` and before `tags`**, listing the
keys sorted ascending and deduplicated (block list `  - "KEY"`, or inline
`zotero_keys: []` when `Z` is empty); and the round-trip law holds —
`parse_page(render_page(a, refs, created=c, updated=u, zotero_keys=Z)) == a` for
any `Z` (the field is frontmatter-only and does not appear in the `Article`).
**Error behavior:** a page whose first frontmatter line is not `zotwiki: 2`, or
that omits `zotero_keys`, or has it out of canonical order, raises
`PageParseError` — so legacy `zotwiki: 1` pages (no `zotero_keys`) are rejected.

### REQ-047 — `CompileResult` carries source keys; `publish` writes and unions them
**Given** `Compiler(store, llm).compile(keys, existing)` called with Zotero item
keys,
**When** it returns,
**Then** `CompileResult.zotero_keys == tuple(sorted(set(keys)))`.
**And given** `VaultPublisher.publish(article, zotero_keys=Z)`:
**When** the target page does not exist, **then** the written frontmatter's
`zotero_keys` is `sorted(set(Z))`.
**When** the target page already exists, **then** the article is merged per §7.2
and the written frontmatter's `zotero_keys` is `sorted(set(existing) | set(Z))`
(never-clobber union).
**When** a new compile's title exactly equals an existing page's title, **then**
it merges into that page and unions `zotero_keys` (same title = same article).
**Error behavior:** a case-variant (not byte-equal) title collision raises
`VaultError` (§6.5); an unparseable existing page raises `PageParseError` with
the file untouched.

### REQ-048 — `sync` de-duplicates by Zotero key (BUG-1 fixed)
**Given** a collection item whose Zotero key already appears in some page's
`zotero_keys` (it was compiled earlier, possibly under a different LLM title),
**When** `sync` runs **without** `--update`,
**Then** the item is skipped (`skipped\t{Zotero title}\n`), counted as skipped,
and no second page is created — even though recompiling would yield a different
title.
**When** `sync` runs **with** `--update`,
**Then** the page whose `zotero_keys` contains the item's key is recompiled and
updated **in place**: the compiled article's title is pinned to that page's
title (no duplicate), the §7.2 merge applies, `zotero_keys` is unioned, and
stdout is `compiled\t{page title}\t{path}\n`.
**And given** a collection item whose key is in **no** page's `zotero_keys`,
**When** `sync` runs, **then** it is compiled into a page that records its key.
**Error behavior:** `ArticleSchemaError` mid-sync → `error: {message}` on
stderr, exit 1 immediately (unchanged).

---

## K. Operator terminal wrapper (`scripts/zw`)

These REQs are about `scripts/zw` (contract §11), tested hermetically by running
the script with a **fake `zotwiki`** executable on `PATH` (no real
`claude`/Zotero/network). The fake echoes the argv it received and exits with a
code the test controls.

### REQ-049 — `zw` usage/help
**Given** `scripts/zw` is run with no arguments, or with first argument `help`,
`-h`, or `--help`,
**When** it runs (with or without `ZOTWIKI_VAULT`/`ZOTWIKI_COLLECTION` set),
**Then** it writes the directive list to **stdout**, exits **0**, and never
invokes `zotwiki`.

### REQ-050 — missing `ZOTWIKI_VAULT`
**Given** `ZOTWIKI_VAULT` is unset or empty,
**When** `zw` is run with a vault-needing directive (`sync`, `ask`, `compile`,
`audit`),
**Then** it writes exactly one line to **stderr**, exits **2**, and never invokes
`zotwiki`.

### REQ-051 — directive → `zotwiki` argv forwarding (collection-scoped)
**Given** `ZOTWIKI_VAULT=$V` and `ZOTWIKI_COLLECTION=$C` are set and a fake
`zotwiki` on `PATH`,
**When** each directive is run, **Then** the fake `zotwiki` receives exactly
(effective vault `$V/$C`, per contract §11):
- `zw sync --update` → `sync --vault $V/$C --collection $C --update`
- `zw sync Other --update` → `sync --vault $V/Other --collection Other --update`
  (positional `Other` overrides `$C` and is not forwarded)
- `zw ask why does X matter` → `ask --vault $V/$C "why does X matter"` (one positional)
- `zw compile --query transformers --limit 5` → `compile --vault $V/$C --query transformers --limit 5`
- `zw audit` → `audit --vault $V/$C`
- `zw ingest --title BERT --year 2019` → `ingest --title BERT --year 2019` (no `--vault`, no collection)
**Error behavior:** `zw ask` with no question writes one usage line to stderr,
exits **2**, and does not invoke `zotwiki`.

### REQ-052 — exit-code passthrough and unknown directive
**Given** a fake `zotwiki` that exits with code `C`,
**When** a forwarding directive is run, **Then** `zw` exits with the same code
`C` (verified for `C ∈ {0, 1, 2}`).
**And given** an unrecognized first argument,
**When** `zw` is run, **Then** it writes one error line to **stderr**, exits
**2**, and does not invoke `zotwiki`.

### REQ-053 — `zw sync` creates the collection folder; unresolved collection errors
**Given** `ZOTWIKI_VAULT=$V` is set and the directory `$V/$C` does not yet exist,
**When** `zw sync` runs (with `$C` from `ZOTWIKI_COLLECTION` or the positional
override),
**Then** `zw` creates `$V/$C` (recursively) before invoking `zotwiki sync`, so
`zotwiki` receives an existing `--vault $V/$C`.
**And given** `ZOTWIKI_VAULT` is set but no collection can be resolved (no
positional and `ZOTWIKI_COLLECTION` unset/empty),
**When** a collection-needing directive (`sync`, `ask`, `compile`, `audit`) runs,
**Then** `zw` writes exactly one line to **stderr**, exits **2**, and never
invokes `zotwiki` (and creates no directory).

---

## L. Structured-output LLM boundary (BUG-2, Ruling 9)

These REQs are about `ClaudeCodeLLMClient` (contract §5.6), tested hermetically by
the **dedicated client module** (`tests/test_m6_llm_client.py`) — the client is
imported lazily and driven through a **fake `claude` binary on PATH** that emits a
JSON envelope; the real `claude` and the network are never touched. The
injected-fake suite (Compiler/CLI/`ask`) is unchanged and still never constructs
the real client.

### REQ-054 — subprocess environment is sanitized of nested-session vars
**Given** a fake `claude` on PATH that records which of `CLAUDECODE` and
`CLAUDE_CODE_*` it received in its environment (e.g. encoding them into its
success-envelope output), and the parent process has `CLAUDECODE=1` and at least
one `CLAUDE_CODE_*` variable set,
**When** `ClaudeCodeLLMClient(output_schema=SCHEMA).complete(prompt)` is called,
**Then** the fake reports that **no** `CLAUDECODE` and **no** `CLAUDE_CODE_*` key
was present in its environment, while an unrelated parent variable (e.g. a custom
`ZOTWIKI_TEST_MARKER`) **is** preserved.
**Error behavior:** none.

### REQ-055 — fail-closed with a verbatim failure artifact
**Given** a `dump_dir` set to a `tmp_path` and a fake `claude` on PATH that prints
a **non-success envelope** (a JSON object with
`"subtype": "error_max_structured_output_retries"`, an `"errors"` array,
`"stop_reason"`, and metadata, and **no** `"result"`/`"structured_output"`) with
exit code 0,
**When** `ClaudeCodeLLMClient(output_schema=SCHEMA, dump_dir=DIR).complete(prompt)`
is called,
**Then** `ZotWikiError` is raised with a **single-line** message (no newline) that
names the failure (`subtype`) and includes the path to a **failure artifact** that
now exists under `DIR`; the artifact contains the invocation argv, the prompt, the
verbatim stdout envelope, and the diagnostic fields present in the envelope
(`subtype`, `errors`, `stop_reason`, and metadata).
**And** the same fail-closed-with-artifact behavior holds when the fake instead
(a) exits **non-zero**, or (b) prints stdout that is **not a JSON object** /
**omits the expected extraction field** (`structured_output` when a schema is set).
**Error behavior:** this REQ is the error behavior. No retry, no fallback path.

---

Total: 55 requirements (REQ-001 … REQ-055).
