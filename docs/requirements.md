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
**Then** the recorded prompt contains the existing article serialized via
`article_to_json_dict` (as a JSON substring), and `CompileResult.contradictions`
contains the parsed `Contradiction` values in order.
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
without `ANTHROPIC_API_KEY`/`ZOTWIKI_MODEL` set → return 2 with `error:` on
stderr.

---

Total: 38 requirements (REQ-001 … REQ-038).
