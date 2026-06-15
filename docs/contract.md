# ZotWiki — Contract

Status: binding and exhaustive. A tester and a coder who never communicate
must be able to build, respectively, a test suite (with a fake Zotero HTTP
server and a fake LLM) and the real implementation, from this file alone, and
have them mate. Where this file is silent, behavior is unspecified; where it
speaks, it is law. Ambiguities resolved here are marked `DECISION:`.

Python: **3.12**. Test runner: **pytest ≥ 7.0**.

**DECISION: zero third-party runtime dependencies.** Stdlib only: HTTP via
`urllib.request`, JSON via `json`, no PyYAML (frontmatter is a restricted
subset defined in §6.2 and emitted/parsed by ZotWiki itself), no pyzotero.
The only test-time dependency is `pytest`.

---

## 1. Package layout, discovery, imports

src-layout, no install step required to run tests:

```
zotwiki/                      (repo root = /mnt/e/test/zotwiki)
├── pytest.ini
├── docs/
├── src/
│   └── zotwiki/
│       ├── __init__.py       (defines __version__ = "0.1.0")
│       ├── __main__.py       (runs sys.exit(main()))
│       ├── errors.py
│       ├── models.py
│       ├── zotero.py
│       ├── llm.py
│       ├── compiler.py
│       ├── publisher.py
│       ├── auditor.py
│       ├── ask.py
│       ├── syncer.py
│       └── cli.py
└── tests/                    (tester-owned; coder never writes here)
```

`pytest.ini` (coder creates it in M1, byte-exact; tester may rely on it):

```ini
[pytest]
pythonpath = src
testpaths = tests
```

This is the *only* mechanism by which pytest finds the package (pytest ≥ 7.0
`pythonpath` ini option). No `conftest.py` sys.path hacks, no editable
install needed.

### 1.1 Public import surface (complete; nothing else is public)

```python
from zotwiki import __version__

from zotwiki.errors import (
    ZotWikiError,              # base, subclasses Exception
    ZoteroError,               # subclasses ZotWikiError
    ItemNotFoundError,         # subclasses ZoteroError
    CitekeyNotFoundError,      # subclasses ZoteroError
    FulltextNotFoundError,     # subclasses ZoteroError
    ZoteroUnavailableError,    # subclasses ZoteroError
    CollectionNotFoundError,   # subclasses ZoteroError
    ArticleSchemaError,        # subclasses ZotWikiError
    PageParseError,            # subclasses ZotWikiError
    VaultError,                # subclasses ZotWikiError
)

from zotwiki.models import (
    SourceItem, Article, Section, Claim, Quote, Contradiction,
    normalize_text,
)

from zotwiki.zotero import ZoteroStore, HTTPZoteroStore, DEFAULT_BASE_URL

from zotwiki.llm import LLMClient, parse_article_json, article_to_json_dict

from zotwiki.compiler import Compiler, CompileResult, merge_articles, FULLTEXT_PROMPT_LIMIT

from zotwiki.publisher import (
    VaultPublisher, render_page, parse_page,
    INDEX_FILENAME, CONTRADICTIONS_FILENAME,
)

from zotwiki.auditor import Auditor, AuditReport, Violation, AUDIT_CODES

from zotwiki.ask import ask, Answer, SourceRef

from zotwiki.syncer import Syncer, SyncReport

from zotwiki.cli import main, EXIT_OK, EXIT_FAIL, EXIT_ENV
```

All exception constructors take a single message argument
(`ZoteroError("...")` etc.); none define extra required parameters.

---

## 2. Datatypes (`zotwiki.models`)

All dataclasses are `@dataclass(frozen=True)`. Sequence-valued fields are
tuples so instances are hashable and compare by value.

```python
@dataclass(frozen=True)
class SourceItem:
    key: str                      # Zotero item key, 8 chars [A-Z0-9]
    citekey: str                  # Better BibTeX citekey; "" if absent
    title: str
    creators: tuple[str, ...]     # display names, e.g. ("Ada Lovelace",)
    year: int | None
    url: str | None
    has_fulltext: bool

@dataclass(frozen=True)
class Section:
    heading: str
    body: str                     # may contain blank lines; never lines starting with '#'

@dataclass(frozen=True)
class Quote:
    citekey: str
    text: str                     # single line

@dataclass(frozen=True)
class Claim:
    text: str                     # single line
    citekeys: tuple[str, ...]     # sorted ascending, len >= 1
    quotes: tuple[Quote, ...]     # sorted by (citekey, text), len >= 1

@dataclass(frozen=True)
class Article:
    title: str
    summary: str
    sections: tuple[Section, ...]
    claims: tuple[Claim, ...]
    links: tuple[str, ...]        # sorted ascending, deduped

@dataclass(frozen=True)
class Contradiction:
    existing_claim: str
    new_claim: str
    citekeys: tuple[str, ...]     # sorted ascending, len >= 1
```

DECISION: `Article` instances are always *canonical*: claim citekeys sorted,
quotes sorted, links sorted+deduped. `parse_article_json`, `parse_page`, and
`merge_articles` all produce canonical articles; `render_page` may assume its
input is canonical. Sorting is plain Python `str` ordering (codepoint-wise).

### 2.1 `normalize_text(text: str) -> str`

Used for quote matching and claim identity. Exact algorithm, in order:

1. `unicodedata.normalize("NFKC", text)`
2. Replace `‘` and `’` with `'`; `“` and `”` with `"`;
   `–` (en dash) and `—` (em dash) with `-`.
3. `str.casefold()`
4. Collapse every maximal run of whitespace (`\s+`, Unicode) to a single
   space; strip leading/trailing whitespace.

---

## 3. `ZoteroStore` protocol (`zotwiki.zotero`)

```python
@runtime_checkable
class ZoteroStore(Protocol):
    def search(self, query: str, limit: int = 25) -> list[SourceItem]: ...
    def get(self, key: str) -> SourceItem: ...
    def fulltext(self, key: str) -> str: ...
    def resolve(self, citekey: str) -> SourceItem: ...
    def add(
        self,
        *,
        title: str,
        url: str | None = None,
        item_type: str = "webpage",
        creators: Sequence[str] = (),
        year: int | None = None,
    ) -> SourceItem: ...
    def collection_items(self, name: str) -> list[SourceItem]: ...
```

Semantics (binding for fakes and the real adapter alike):

| method | success | failure |
|---|---|---|
| `search` | list (possibly empty) in server order | `ValueError` if `limit` not in `1..100` (no I/O); `ZoteroUnavailableError`; `ZoteroError` |
| `get` | the item | `ItemNotFoundError` (unknown key); `ZoteroUnavailableError`; `ZoteroError` |
| `fulltext` | the full text string | `FulltextNotFoundError` (no fulltext or unknown key); `ZoteroUnavailableError`; `ZoteroError` |
| `resolve` | first item whose parsed citekey equals the argument exactly | `CitekeyNotFoundError`; `ZoteroUnavailableError`; `ZoteroError` |
| `add` | the created item (with generated citekey) | `ZoteroError` (server reported failure, or citekey suffixes exhausted); `ZoteroUnavailableError` |
| `collection_items` | list of items in the named collection (possibly empty), in server order, each mapped per §3.1 | `CollectionNotFoundError` (no collection with that exact name); `ZoteroUnavailableError`; `ZoteroError` |

### 3.1 Mapping Zotero JSON → `SourceItem`

Given an item object (§4.4), with `d = obj["data"]` (missing keys are treated
as `""` / `[]`):

- `key` = `obj["key"]`
- `title` = `d.get("title", "")`
- `creators`: for each entry in `d.get("creators", [])`, display name =
  `"{firstName} {lastName}"` if both present and non-empty, else `lastName`
  or `firstName` alone, else the entry's `name` field, else skip the entry.
  Single internal space; stripped.
- `year`: first match of regex `\d{4}` in `d.get("date", "")` as `int`,
  else `None`.
- `url` = `d.get("url") or None` (empty string → `None`)
- `citekey`: scan `d.get("extra", "")` line by line; the first line matching
  the regex `^Citation Key:\s*(\S+)\s*$` (case-sensitive on
  `Citation Key:`) yields the citekey; otherwise `""`.
- `has_fulltext`: per §4.5 two-step probe. DECISION: every `SourceItem`
  materialization (from `get`, `search`, and `resolve`) performs the §4.5
  probe on the item's own key, falling through to child items on 404.

### 3.2 `HTTPZoteroStore` constructor

```python
class HTTPZoteroStore:
    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,   # "http://127.0.0.1:23119/api/users/0"
        *,
        timeout: float = 5.0,               # per-request socket timeout, seconds
        retries: int = 2,                   # additional attempts after the first
        backoff: float = 0.1,               # seconds; see retry schedule
        sleep: Callable[[float], None] = time.sleep,  # injectable for tests
    ) -> None: ...
```

`DEFAULT_BASE_URL = "http://127.0.0.1:23119/api/users/0"` (Zotero 7 local
API). Tests construct the store with the fake server's
`http://127.0.0.1:{port}/api/users/0`. A trailing `/` on `base_url` is
stripped.

**Retry policy** (applies to every request, GET and POST):

- Retryable: HTTP 5xx, connection errors (`OSError`/`URLError`), timeouts.
- Not retryable: any HTTP 4xx. 404 maps to the per-endpoint not-found
  exception; other 4xx → `ZoteroError` immediately.
- Attempts = `1 + retries`. Before retry *i* (0-indexed), call
  `sleep(backoff * (2 ** i))` — with defaults: `0.1`, then `0.2`.
- After exhausting attempts → `ZoteroUnavailableError`.

Every request sends headers `Accept: application/json` and
`Zotero-API-Version: 3`; POST also sends
`Content-Type: application/json`. The fake may ignore headers.

### 3.3 Citekey generation in `add` (DECISION)

`citekey = f"{author}{year}{word}"` where:

- `author` = last whitespace-separated token of the first creator's display
  name, lowercased, with non-`[a-z0-9]` characters removed; `"anon"` if there
  are no creators or the result is empty.
- `year` = `str(year)` if given, else `"nd"`.
- `word` = first whitespace-separated word of `title`, lowercased,
  non-`[a-z0-9]` removed, that is **not** in
  `{"a","an","the","on","of","in","and","for","to"}`; `"item"` if none.

Collision handling: try `resolve(candidate)`; if it resolves, append `"a"`,
then `"b"`, … `"z"`; first non-resolving candidate wins. If all 27 collide →
`ZoteroError`, nothing posted. The chosen citekey is pinned by writing
`Citation Key: {citekey}` as a line of the posted item's `extra` field.

---

## 4. Zotero HTTP API subset (the fake server's spec)

The fake server implements exactly this; the real adapter consumes exactly
this. Base path below is `{base}` = the path part of `base_url`
(e.g. `/api/users/0`). All bodies are UTF-8 JSON.

### 4.1 `GET {base}/items?q={q}&qmode={qmode}&limit={n}&format=json`

Search. `q` is URL-encoded. `qmode` ∈ `titleCreatorYear` | `everything`.
Response `200` with a JSON **array** of item objects (§4.4), server-chosen
order (the fake should preserve insertion order). Empty array if no match.

DECISION (fake matching semantics, so fixtures behave predictably): match is
case-insensitive substring; `titleCreatorYear` searches `data.title`,
creator name parts, and `data.date`; `everything` additionally searches
`data.extra` and `data.url`. At most `limit` results.

- `search()` sends `qmode=titleCreatorYear` and its `limit`.
- `resolve()` sends `qmode=everything&limit=100` with `q={citekey}` and
  filters client-side for an exact `citekey` match (§3.1).

### 4.2 `GET {base}/items/{KEY}?format=json`

Single item. `200` with one item object (§4.4), or `404` (any body) if the
key is unknown.

### 4.3 `GET {base}/items/{KEY}/fulltext`

`200` with `{"content": "<full text>"}` (the adapter reads only `content`,
which must be a string), or `404` if the item has no fulltext **or** the key
is unknown.

### 4.4 Item object shape

```json
{
  "key": "ABCD1234",
  "version": 42,
  "data": {
    "key": "ABCD1234",
    "itemType": "journalArticle",
    "title": "Attention Is All You Need",
    "creators": [
      {"creatorType": "author", "firstName": "Ashish", "lastName": "Vaswani"},
      {"creatorType": "author", "name": "DeepThought Collective"}
    ],
    "date": "2017-06-12",
    "url": "https://arxiv.org/abs/1706.03762",
    "extra": "Citation Key: vaswani2017attention"
  }
}
```

`version` is present but ignored by the adapter. Any `data` key may be
absent; the adapter treats absent as empty (§3.1).

### 4.5 Fulltext probe (two-step)

`has_fulltext` is determined by a two-step procedure applied to a parent item
key `KEY`:

1. **Parent probe:** `GET {base}/items/{KEY}/fulltext` — if 200, `has_fulltext
   = True` and the content is available.
2. **Children fallback:** if step 1 returns 404, fetch child keys via §4.9,
   then probe each child key with `GET {base}/items/{child_key}/fulltext` in
   server order. The first 200 response sets `has_fulltext = True` and
   provides the content.
3. If no probe returns 200, `has_fulltext = False`.

The same two-step procedure applies when `store.fulltext(key)` is called:
step 1 returns the parent's content on 200; step 2 returns the first child's
content on 200; if all return 404, `FulltextNotFoundError` is raised.

DECISION: children are fetched only when the parent returns 404 (lazy). A 404
from the children endpoint itself is treated as an empty list (no children).
The fake server decides per item whether to serve fulltext on the parent or on
a child.

### 4.7 `GET {base}/collections?format=json`

Returns a JSON **array** of collection objects. Each has the shape:

```json
{"key": "COL00001", "version": 1, "data": {"key": "COL00001", "name": "AI Papers", "parentCollection": false}}
```

The adapter reads only `key` and `data.name`. The fake returns all registered collections in insertion order.

### 4.8 `GET {base}/collections/{KEY}/items?format=json&limit=100`

Returns a JSON **array** of item objects (same shape as §4.4) for all items in the collection. The adapter always sends `limit=100`. The fake returns items in insertion order (same limit is sent; the fake need not enforce it).

### 4.9 `GET {base}/items/{KEY}/children?format=json`

Returns a JSON **array** of child item objects (attachments, notes) of the given
parent item. Each child object has at minimum a top-level `"key"` string field;
the adapter reads only that field.

- `200` with a JSON array (possibly empty) when the parent key is known.
- `404` when the parent key is unknown — the adapter treats this identically to
  an empty array (no children, no error).

The adapter does not retry on 404. The fake returns children in insertion order.

---

### 4.6 `POST {base}/items`

Create. Request body: JSON **array with exactly one** item-data object:

```json
[{
  "itemType": "webpage",
  "title": "A Study of Owls",
  "creators": [{"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}],
  "date": "2021",
  "url": "https://owl.example",
  "extra": "Citation Key: lovelace2021study"
}]
```

Creator encoding in the request: a display name with ≥1 space splits at the
*last* space into `firstName`/`lastName`; a single-token name is sent as
`{"creatorType": "author", "name": "<token>"}`. `date` = `str(year)` or `""`.
DECISION: the `url` key is always present in the request, `""` when `None`.

Response `200`:

```json
{
  "successful": {"0": {"key": "NEWKEY01", "version": 1, "data": { ...as §4.4... }}},
  "failed": {}
}
```

Adapter behavior: if `failed` is non-empty → `ZoteroError`. Otherwise map
`successful["0"]` per §3.1 (the fake must echo back the posted data, with its
chosen `key`) and return the `SourceItem`. The probe of §4.5 applies (a
fresh webpage item normally has no fulltext → `has_fulltext False`).

---

## 5. `LLMClient` protocol and the compiled-article JSON (`zotwiki.llm`)

### 5.1 Protocol

```python
@runtime_checkable
class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...
```

One method, one string in, one string out. Tests implement this with canned
returns and optional prompt recording.

Production: `zotwiki.llm.ClaudeCodeLLMClient()` — shells out to the `claude`
CLI (Claude Code) via `subprocess` (stdlib). DECISION: no API key or model
configuration is required; the CLI uses the user's existing Claude Code
installation and session (§9.4). This class is **never** imported by any test
and is out of audit scope for the hermetic suite.

### 5.2 Compiled-article JSON schema (exact)

The LLM must return one JSON object. Required keys: `title`, `summary`,
`sections`, `claims`, `links`. Optional key: `contradictions`. **No other
top-level keys are permitted** (unknown key → `ArticleSchemaError`).

```json
{
  "title": "Transformer",
  "summary": "One-paragraph synthesis of what the page is about.",
  "sections": [
    {"heading": "Architecture", "body": "Multi-line markdown without headings."}
  ],
  "claims": [
    {
      "text": "Self-attention replaces recurrence entirely.",
      "citekeys": ["vaswani2017attention"],
      "quotes": [
        {"citekey": "vaswani2017attention",
         "text": "we propose a new simple network architecture, the Transformer"}
      ]
    }
  ],
  "links": ["Attention Mechanism", "Sequence Modeling"],
  "contradictions": [
    {"existing_claim": "X holds.", "new_claim": "X does not hold.",
     "citekeys": ["doe2020counter"]}
  ]
}
```

Validation rules (each violation → `ArticleSchemaError` naming the JSON path,
e.g. `claims[0].quotes[1].citekey`):

- `title`: non-empty `str`, ≤ 120 chars, matching
  `^[A-Za-z0-9][A-Za-z0-9 ,()'\-]*$` (the safe-filename charset), no
  leading/trailing space (regex enforces leading; trailing space → error).
- `summary`: non-empty `str`.
- `sections`: array (may be empty) of objects with exactly `heading`, `body`.
  `heading`: non-empty single-line `str`, not one of the reserved headings
  `Claims`, `Links`, `References` (exact match), unique across sections.
  `body`: non-empty `str`; after the normalization of §5.4 no line may start
  with `#`.
- `claims`: array (may be empty) of objects with exactly `text`, `citekeys`,
  `quotes`. `text`: non-empty single-line `str` not containing the substring
  `" [@"` and not starting with `-` or `>`. `citekeys`: array, length ≥ 1,
  of strings matching `^[A-Za-z0-9_.:\-]+$`, no duplicates. `quotes`: array,
  length ≥ 1, of objects with exactly `citekey`, `text`; each `citekey` must
  be a member of the claim's `citekeys`; `text` non-empty single-line `str`.
- `links`: array (may be empty) of strings each satisfying the `title` rule.
  Duplicates allowed in input but removed in output.
- `contradictions` (optional, default `[]`): array of objects with exactly
  `existing_claim`, `new_claim`, `citekeys` — same rules as claim `text` and
  `citekeys`.

### 5.3 `parse_article_json`

```python
def parse_article_json(text: str) -> tuple[Article, tuple[Contradiction, ...]]
```

1. Strip outer whitespace. If the result starts with ` ``` ` (optionally
   followed by a language tag on the same line) and ends with ` ``` `, remove
   the first and last lines. Anything else around the JSON →
   `ArticleSchemaError`.
2. `json.loads`; a non-object top level → `ArticleSchemaError`.
3. Validate per §5.2; normalize per §5.4; canonicalize per §2 (sort claim
   citekeys, sort quotes by `(citekey, text)`, sort+dedupe links, sort
   contradiction citekeys).
4. Return the frozen `Article` and the `Contradiction` tuple.

Invalid input must raise; partially-valid output must never escape.

### 5.4 Whitespace normalization at the schema boundary (DECISION)

- `title`, `summary`, claim `text`, quote `text`, `heading`,
  `existing_claim`, `new_claim`, link entries: strip; collapse internal
  whitespace runs to one space. DECISION: `summary` is single-paragraph —
  whitespace runs *including newlines* collapse to one space.
- Section `body`: split into lines; strip trailing whitespace per line; drop
  leading and trailing blank lines; collapse runs of ≥ 2 blank lines to one.
  Newlines inside the body are otherwise preserved.

### 5.5 `article_to_json_dict(article: Article) -> dict`

Inverse of §5.3 step 3–4 minus contradictions: returns a plain dict with
exactly the five required keys, suitable for `json.dumps`. Used to embed the
existing article in update prompts as the **compact** form (no `indent`; see
§7.1). Round-trip law:
`parse_article_json(json.dumps(article_to_json_dict(a)))[0] == a`.

---

## 6. Obsidian page format (`zotwiki.publisher`)

### 6.1 Files

- Entity page for title `T`: `{vault}/{T}.md` — the filename is the title
  verbatim plus `.md` (the §5.2 title charset guarantees filesystem safety).
- `INDEX_FILENAME = "Index.md"`, `CONTRADICTIONS_FILENAME =
  "Contradictions.md"` — reserved; never entity pages. DECISION: the strings
  `Index` and `Contradictions` are forbidden as article titles
  (`ArticleSchemaError` at validation time).
- Vault is flat: only `{vault}/*.md` files are considered; subdirectories
  are ignored by publisher and auditor.
- Encoding UTF-8, LF (`\n`) line endings only, no trailing whitespace on any
  line, file ends with exactly one `\n`.

### 6.2 Frontmatter (restricted YAML subset)

Exactly this shape, keys in exactly this order, nothing else:

```
---
zotwiki: 1
title: "Transformer"
created: "2026-06-11"
updated: "2026-06-11"
citekeys:
  - "doe2020attention"
  - "vaswani2017attention"
tags:
  - "zotwiki"
---
```

- `zotwiki`: literal int `1` (schema version), unquoted.
- All strings double-quoted; `\` and `"` escaped as `\\` and `\"`; no other
  escapes are emitted, and the parser accepts only those two.
- Dates are `YYYY-MM-DD` strings.
- Lists: block style, items indented two spaces as `  - "value"`. An empty
  list is rendered inline as `citekeys: []` (same for `tags`, though `tags`
  is always exactly `["zotwiki"]` on pages ZotWiki writes).
- `citekeys` = sorted union of all claim citekeys on the page.
- The parser (`parse_page`, auditor) accepts only this subset; anything else
  (unknown key, wrong order, flow lists with content, unquoted strings) →
  `PageParseError`.

### 6.3 Page body grammar (canonical, byte-exact)

After the closing `---` comes, in order, each block separated by exactly one
blank line:

```
# {title}

{summary}

## {section 1 heading}

{section 1 body}

…more sections in article order…

## Claims

- {claim text} [@{ck1}; @{ck2}]
  > [@{ck1}] {quote text}
  > [@{ck2}] {quote text}

## Links

- [[{Target A}]]
- [[{Target B}]]

## References

- [@{citekey}] {creators} ({year}). *{title}*. [Zotero](zotero://select/library/items/{KEY})
```

Rules:

- `## Claims`, `## Links`, `## References` always appear, in that order, after
  all content sections, even when empty (an empty block renders as just its
  heading line).
- Claim line: `- ` + claim text + the citekey suffix. The suffix is, byte
  exact: one space, `[`, the sorted citekeys each prefixed `@` and joined by
  `; `, then `]` — i.e.
  `" [" + "; ".join("@" + ck for ck in sorted_citekeys) + "]"`.
  Example with two citekeys:
  `- Self-attention replaces recurrence. [@doe2020; @vaswani2017attention]`.
- Quote lines immediately follow their claim line, one per quote, sorted by
  `(citekey, text)`, each exactly two spaces, `> [@`, citekey, `] `, text:
  `  > [@vaswani2017attention] we propose a new simple network architecture`.
- Claims appear in article order (merge order, §7.2). No blank lines between
  a claim and its quotes or between claims.
- Links block: one `- [[{target}]]` per link, sorted. No aliases are ever
  *written* (aliases are tolerated when *auditing*, §8).
- References block: one line per citekey in sorted order; format exactly:
  `- [@{citekey}] {creators} ({year}). *{title}*. [Zotero](zotero://select/library/items/{key})`
  where `{creators}` = display names joined by `", "`, or `Unknown` if empty;
  `{year}` = decimal year or `n.d.`; `{title}` and `{key}` from the resolved
  `SourceItem` (not from the page). URI scheme is exactly
  `zotero://select/library/items/{KEY}`.

### 6.4 Rendering and parsing functions

```python
def render_page(
    article: Article,
    references: Sequence[SourceItem],
    *,
    created: str,            # "YYYY-MM-DD"
    updated: str,            # "YYYY-MM-DD"
) -> str
```

`references` must contain exactly one `SourceItem` per citekey cited by the
article's claims — no missing, no extras, duplicates forbidden — else
`VaultError`. Pure function; deterministic; output obeys §6.1–6.3 byte-exactly.

```python
def parse_page(text: str) -> Article
```

Strict inverse on the body: returns `Article(title, summary, sections,
claims, links)`; ignores frontmatter dates and rebuilds nothing. References
lines are parsed only to the extent of validating the line shape; their
content is *not* represented in `Article` (it is recomputed at render time).
Violations of §6.2/§6.3 → `PageParseError`.

**Round-trip law:** for every canonical `Article` `a` and matching `refs`:
`parse_page(render_page(a, refs, created=c, updated=u)) == a`.

### 6.5 `VaultPublisher`

```python
class VaultPublisher:
    def __init__(self, vault_dir: Path, store: ZoteroStore, *, today: str | None = None) -> None
    def page_path(self, title: str) -> Path
    def publish(self, article: Article) -> Path
    def publish_contradictions(self, page_title: str,
                               contradictions: Sequence[Contradiction]) -> Path
```

- `today` defaults to the real current date as `YYYY-MM-DD`; tests pass a
  fixed value. The constructor creates `vault_dir` (parents included) if
  missing.
- `publish` resolves every cited citekey via `store.resolve` (propagating
  `CitekeyNotFoundError` / `ZoteroUnavailableError`), then:
  - **New page** (no `{title}.md`): write
    `render_page(article, refs, created=today, updated=today)`. Case
    collision (an existing `.md` whose stem casefold-equals the title but is
    not byte-equal) → `VaultError`, nothing written.
  - **Existing page**: `existing = parse_page(file)` (failure →
    `PageParseError`, file untouched); `merged = merge_articles(existing,
    article)`; render with `created` = the existing page's frontmatter
    `created`. If rendering `merged` with `updated` = the existing
    frontmatter `updated` reproduces the current file byte-for-byte, **do not
    write** (idempotence; the old `updated` stands). Otherwise write with
    `updated = today`.
  - After any publish (including no-op), regenerate `Index.md` (§6.7) with
    the same change-detection rule (rewrite only if its rendering differs).
- Returns the page path.

### 6.6 References resolution

The publisher builds `references` by calling `store.resolve(ck)` for each of
the merged article's citekeys, sorted ascending. (Audit re-verifies later;
publish-time resolution is a convenience fail-fast, not the gate.)

### 6.7 `Index.md` layout

Frontmatter per §6.2 with `title: "Index"`, `citekeys: []`,
`tags: ["zotwiki"]`, dates managed like any page (`created` on first write,
`updated` bumped only on change). Body:

```
# Index

- [[Alpha]]
- [[Beta]]
```

One `- [[{title}]]` line per entity page in the vault root (every `*.md`
except `Index.md` and `Contradictions.md`), sorted by title. Empty vault →
`# Index` with no bullets.

### 6.8 `Contradictions.md` layout

Frontmatter per §6.2 with `title: "Contradictions"`, `citekeys: []`. Body
starts `# Contradictions`, then appended blocks (never rewritten or
reordered), one per `publish_contradictions` call:

```
## {page_title} ({today})

- EXISTING: {existing_claim}
- NEW: {new_claim} [@{ck1}; @{ck2}]
```

One `EXISTING`/`NEW` pair, in order, per `Contradiction` in the call
(multiple contradictions in one call produce consecutive pairs under one
heading). The `[@…]` suffix uses the §6.3 claim-suffix format. Calling with
an empty sequence → `ValueError`. The targeted entity page is **never**
modified by this method.

---

## 7. Compiler and incremental semantics (`zotwiki.compiler`)

```python
FULLTEXT_PROMPT_LIMIT = 20000   # characters per item in the prompt

@dataclass(frozen=True)
class CompileResult:
    article: Article
    contradictions: tuple[Contradiction, ...]

class Compiler:
    def __init__(self, store: ZoteroStore, llm: LLMClient) -> None
    def compile(self, keys: Sequence[str], existing: Article | None = None) -> CompileResult
```

### 7.1 `compile` algorithm (observable parts binding)

1. For each Zotero key: `store.get(key)`; if `citekey == ""` →
   `CitekeyNotFoundError` naming the key, **before any LLM call**. If
   `has_fulltext`, fetch `store.fulltext(key)` and truncate to
   `FULLTEXT_PROMPT_LIMIT` characters.
2. Build a single prompt string that **must contain**, for each item: its
   citekey, its title, and its (truncated) fulltext when available; and, when
   `existing is not None`, the **compact** existing-article embed
   `json.dumps(article_to_json_dict(existing), sort_keys=True)` (no `indent`)
   as a verbatim substring. (Surrounding instruction text — including any
   indented JSON examples — is unspecified.)
3. `raw = llm.complete(prompt)`; `article, contradictions =
   parse_article_json(raw)`.
4. If `existing is None` and `contradictions` is non-empty →
   `ArticleSchemaError`.
5. Return `CompileResult(article, contradictions)`.

The compiler does **not** merge and does **not** touch the vault.

### 7.2 `merge_articles(existing: Article, update: Article) -> Article`

Pure, deterministic. Titles must be equal, else `ArticleSchemaError`.

- `summary`: the update's summary wins.
- `sections`: keyed by exact heading. Existing order preserved; an update
  section with a matching heading replaces that section's body in place; new
  headings append in update order.
- `claims`: keyed by `normalize_text(claim.text)`. Existing order preserved;
  on a key match the surviving claim keeps the **existing** text, citekeys =
  sorted union, quotes = union deduped by `(citekey, normalize_text(text))`
  keeping first-seen text, sorted per §2; unmatched update claims append in
  update order.
- `links`: sorted union.

Never-clobber guarantee: content present only in `existing` survives
byte-identically.

### 7.3 Contradiction semantics

Contradictions are produced by the LLM in update mode (§5.2) — the compiler
performs no semantic contradiction detection of its own. The CLI (§9) routes
them to `publish_contradictions`. A contradicted existing claim stays on the
entity page untouched; the contradicting new claim appears **only** on
`Contradictions.md`. DECISION: it is the LLM's contract obligation (stated
in the prompt) not to also include the contradicting claim in `claims`;
ZotWiki does not cross-filter.

---

## 8. Auditor (`zotwiki.auditor`)

```python
AUDIT_CODES = (
    "CITEKEY_UNRESOLVED", "QUOTE_NOT_FOUND", "BROKEN_LINK",
    "ORPHAN_PAGE", "INDEX_STALE", "PAGE_UNPARSEABLE", "REFERENCE_MISSING",
)

@dataclass(frozen=True)
class Violation:
    code: str        # member of AUDIT_CODES
    page: str        # filename, e.g. "Transformer.md"
    detail: str      # human-readable specifics (citekey, target, quote prefix…)

@dataclass(frozen=True)
class AuditReport:
    violations: tuple[Violation, ...]   # sorted by (page, code, detail)
    pages_checked: int                  # entity pages successfully parsed

    @property
    def ok(self) -> bool: ...           # violations == ()

class Auditor:
    def __init__(self, vault_dir: Path, store: ZoteroStore) -> None
    def audit(self) -> AuditReport
```

### 8.1 Checks (all of them, every run)

Scope: `*.md` directly in `vault_dir`. `Index.md` and `Contradictions.md`
are special; all others are entity pages.

1. **PAGE_UNPARSEABLE** — entity page (or special page frontmatter) fails
   §6 parsing. Detail: first parse error message. Unparseable pages skip
   checks 2–4 and 7 but still count for 5/6 by filename.
2. **CITEKEY_UNRESOLVED** — any citekey appearing in a page's claims,
   quotes, or References block fails `store.resolve`. One violation per
   distinct (page, citekey). Detail: the citekey.
3. **QUOTE_NOT_FOUND** — for each quote: resolve its citekey (if
   unresolved, check 2 already fired; skip), require `has_fulltext`, fetch
   fulltext, require
   `normalize_text(quote.text) in normalize_text(fulltext)`. Failure (no
   fulltext, or not a substring) → violation. Detail:
   `"{citekey}: {first 60 chars of quote}"`.
4. **BROKEN_LINK** — every `[[…]]` occurrence anywhere in the page text
   (body, Links block) is parsed as target = text before the first `|`;
   targets containing `#` are violations outright; otherwise violation iff
   `{target}.md` is not in the vault. Detail: the target.
5. **ORPHAN_PAGE** — entity page file not listed in `Index.md` (or
   `Index.md` missing entirely while ≥ 1 entity page exists). Page field:
   the orphan's filename.
6. **INDEX_STALE** — `Index.md` bullet whose target file does not exist.
   Page field: `Index.md`; detail: the target.
7. **REFERENCE_MISSING** — on an entity page, the three sets {citekeys in
   claims} / {citekeys in References lines} / {frontmatter `citekeys`} are
   not all equal. Detail: the symmetric-difference citekeys, sorted, comma
   separated.

`Contradictions.md` undergoes only frontmatter parsing (→ check 1) and check
4; its claims are intentionally conflicting and exempt from 2/3/7.

### 8.2 Quote/claim normalization

`zotwiki.models.normalize_text` (§2.1) — identical function on both sides of
the substring test.

### 8.3 Failure modes

- `vault_dir` missing or not a directory → `VaultError` (raise, no report).
- `ZoteroUnavailableError` from the store propagates (raise, no report).
- Everything else is a `Violation`, never an exception.

Determinism: equal vault + store state ⇒ equal reports (violations sorted by
`(page, code, detail)`).

---

## 9. CLI (`zotwiki.cli`) and `ask` (`zotwiki.ask`)

### 9.1 Entry points

```python
EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

def main(
    argv: Sequence[str] | None = None,          # None → sys.argv[1:]
    *,
    store: ZoteroStore | None = None,           # None → HTTPZoteroStore(--zotero-url)
    llm: LLMClient | None = None,               # None → AnthropicLLMClient from env (§9.4)
) -> int
```

`main` **returns** the exit code; it never calls `sys.exit`. argparse usage
errors are caught and returned as `2` (DECISION: `main` traps `SystemExit`
from argparse and converts it). `python -m zotwiki` runs
`sys.exit(main())` via `__main__.py`. Tests invoke `main` in-process with
injected fakes; no subprocess, no real network.

### 9.2 Commands (exact usage)

Global option (before the subcommand): `--zotero-url URL`
(default `DEFAULT_BASE_URL`); ignored when `store` is injected.

```
zotwiki ingest  --title TITLE [--url URL] [--creator NAME]... [--year YEAR] [--type ITEMTYPE]
zotwiki compile --vault DIR (--key KEY ... | --query QUERY) [--limit N] [--page TITLE] [--today YYYY-MM-DD]
zotwiki audit   --vault DIR
zotwiki ask     --vault DIR QUESTION
zotwiki sync    --vault DIR --collection NAME [--update]
```

**ingest** — `store.add(...)` (`--type` → `item_type`, default `webpage`).
stdout on success: exactly `"{citekey}\t{key}\n"`. Exit 0.

**compile** —
1. Items: each `--key` via `store.get`; or `store.search(--query, limit=--limit)`
   (`--limit` default 10). Zero items → stderr `error: no items matched`,
   exit 1.
2. `existing`: if `--page` is given and `{vault}/{PAGE}.md` exists,
   `parse_page` it; else `None`.
3. `result = Compiler(store, llm).compile(keys, existing)`. If `--page` is
   given and `result.article.title != PAGE` → exit 1, nothing written.
4. `VaultPublisher(vault, store, today=--today).publish(result.article)`;
   stdout line `"compiled\t{title}\t{path}\n"`.
5. If `result.contradictions`: `publish_contradictions(title, …)`; stdout
   line `"contradictions\t{title}\t{count}\n"`.
Exit 0 on success.

**audit** — run `Auditor(vault, store).audit()`. Clean: stdout
`"audit: ok ({pages_checked} pages)\n"`, exit 0. Violations: one
`"{code}\t{page}\t{detail}\n"` line per violation in report order, then
`"audit: {n} violation(s)\n"`, exit 1. (Violations go to **stdout**.)

**ask** — `answer = ask(vault, QUESTION, llm)` (§9.5). stdout: the answer
text, `\n\n`, `Sources:\n`, then for each source page in given order and each
of its citekeys: `"- [[{page}]] [@{citekey}]\n"`. Exit 0.

### 9.3 Exit-code mapping (uniform across commands)

| code | meaning | triggers |
|---|---|---|
| 0 | success | — |
| 1 | domain failure | `ArticleSchemaError`, `ItemNotFoundError`, `CitekeyNotFoundError`, `FulltextNotFoundError`, `PageParseError`, audit violations, zero compile items, `--page` title mismatch |
| 2 | environment failure | `ZoteroUnavailableError`, `VaultError`, `CollectionNotFoundError`, missing LLM configuration, argparse usage errors |

Every nonzero exit except audit-violations prints exactly one line
`"error: {message}\n"` to **stderr** and nothing extra to stdout.

### 9.4 LLM construction (only when `llm is None` and the command needs one)

`compile`, `sync`, and `ask` need an LLM. If not injected: verify that `claude` is
available on PATH; if not found → `error: claude not found` on stderr, exit 2,
no subprocess spawned. `ingest` and `audit` never construct an LLM.

### 9.6 `sync` subcommand

```
zotwiki sync --vault DIR --collection NAME [--update]
```

Requires LLM (same PATH check as `compile`; exit 2 if `claude` not on PATH).

Algorithm:

1. Verify `--vault DIR` exists; else `VaultError` → exit 2.
2. `items = store.collection_items(NAME)`. `CollectionNotFoundError` → stderr
   `error: collection {NAME!r} not found`, exit 2.
3. For each item in `items`, in order:
   - If `item.citekey == ""`: skip silently (no stdout line, not counted).
   - Else if `{vault}/{title}.md` exists and `--update` is not set:
     stdout `"skipped\t{title}\n"`, increment skipped count.
   - Else: `result = Compiler(store, llm).compile([item.key], existing)` where
     `existing` is the parsed existing page when `--update` and the page exists,
     else `None`; then `VaultPublisher(vault, store, today=--today).publish(result.article)`;
     stdout `"compiled\t{title}\t{path}\n"`, increment compiled count.
     If `result.contradictions`: `publish_contradictions(title, …)`;
     stdout `"contradictions\t{title}\t{count}\n"`.
   - `ArticleSchemaError` mid-sync → stderr `error: {message}`, exit 1 immediately.
4. Final stdout line (always): `"sync: {compiled} compiled, {skipped} skipped\n"`.
5. Exit 0.

DECISION: the `title` used in the `skipped` line is the item's Zotero title, not
a page title derived from LLM output. DECISION: citekey-less items are not counted
in either total — they do not appear in the summary denominator.

`SyncReport` is returned by `Syncer.sync` (internal use; not printed by CLI):

```python
@dataclass(frozen=True)
class SyncReport:
    compiled: int
    skipped: int
```

`Syncer` constructor and method:

```python
class Syncer:
    def __init__(self, store: ZoteroStore, llm: LLMClient, vault: Path,
                 *, today: str | None = None) -> None: ...
    def sync(self, name: str, *, update: bool = False) -> SyncReport: ...
```

`sync` implements steps 2–4 above (raising `CollectionNotFoundError` rather than
printing to stderr — the CLI handles the error-to-exit mapping).

### 9.5 `zotwiki.ask`

```python
@dataclass(frozen=True)
class SourceRef:
    page: str                       # page title (no ".md")
    citekeys: tuple[str, ...]       # sorted, len >= 1

@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[SourceRef, ...]

def ask(vault_dir: Path, question: str, llm: LLMClient) -> Answer
```

1. Vault missing → `VaultError`. Read all entity pages; zero entity pages →
   `VaultError` (LLM never called).
2. Prompt must contain the question and the full text of every entity page.
3. The LLM must return exactly (same fence tolerance as §5.3):

   ```json
   {"answer": "…non-empty…",
    "sources": [{"page": "Transformer", "citekeys": ["vaswani2017attention"]}]}
   ```

   Exactly these keys at each level; `sources` may be empty; each entry needs
   `citekeys` length ≥ 1.
4. Validation against the vault: every `page` must be an existing entity
   page title and every citekey a member of that page's frontmatter
   `citekeys`. Any schema or vault-validation failure →
   `ArticleSchemaError` (exit 1 at the CLI).

---

## 10. Determinism and hermeticity laws (cross-cutting)

1. **Idempotent publish:** publishing the same article (same `today`) twice
   yields a byte-identical vault; the second pass writes nothing.
2. **Canonical rendering:** §6 fixes key order, sort orders, separators,
   line endings (`\n`), and the single trailing newline. Any two correct
   implementations render identical bytes for identical inputs.
3. **Hermetic tests:** fake Zotero = stdlib HTTP server on
   `127.0.0.1:<ephemeral>`; `HTTPZoteroStore(base_url=fake_url,
   sleep=lambda s: None)` keeps retry tests instant; LLM always faked;
   vault always `tmp_path`. No test may touch `api.zotero.org`,
   `api.anthropic.com`, or port 23119.
4. **Blind-mating seam:** the fake server is written from §4 alone; the
   adapter from §3–§4 alone; pages written by §6 are parsed by §6 and
   audited by §8 with no shared private helpers beyond the public surface
   in §1.1.
