# zotwiki

ZotWiki compiles your Zotero research library into an Obsidian wiki using Claude. It pulls sources from Zotero's local API, sends them to an Anthropic LLM, and writes canonical Markdown pages into a vault directory. It also audits the vault for broken links and stale citations, and can answer questions from the vault using the LLM.

## How it works

```
Zotero library  →  zotwiki compile  →  Obsidian vault (.md pages)
                      ↑ Claude LLM           ↓
                                      zotwiki audit / ask
```

ZotWiki has four subcommands:

| Command | What it does |
|---|---|
| `ingest` | Add a source item to Zotero with an auto-generated citekey |
| `compile` | Ask the LLM to synthesize one or more Zotero items into a wiki page |
| `audit` | Check the vault for broken links, unresolved citekeys, orphan pages, etc. |
| `ask` | Answer a natural-language question from the vault's content |

---

## Prerequisites

### 1. Python 3.12

ZotWiki targets Python 3.12 exactly. Check your version:

```
python3 --version
```

### 2. Zotero 7 (desktop app, running)

ZotWiki talks to the **Zotero local API** at `http://127.0.0.1:23119`. This requires:

- [Zotero 7](https://www.zotero.org/download/) installed and **open** while you run any ZotWiki command.
- The local API is enabled by default in Zotero 7 — no additional configuration is needed.

Confirm it is reachable:

```
curl http://127.0.0.1:23119/api/users/0/items?limit=1&format=json
```

If Zotero is not running, every ZotWiki command will fail with `error: ...` and exit code 2.

### 3. Better BibTeX for Zotero (recommended for existing libraries)

ZotWiki identifies items by citekey — the `Citation Key: authorYYYYword` line in a Zotero item's Extra field. There are two ways to get citekeys into your library:

- **Via `zotwiki ingest`**: ZotWiki generates and writes the citekey itself.
- **For existing items**: Install the [Better BibTeX for Zotero](https://retorque.re/zotero-better-bibtex/installation/) plugin. It automatically adds `Citation Key:` lines to every item's Extra field.

Without citekeys, `compile` will fail with a `CitekeyNotFoundError`.

### 4. An Anthropic API key

The `compile` and `ask` commands call the Anthropic Messages API. You need:

- An [Anthropic API account](https://console.anthropic.com/) with a valid API key.
- A model ID (e.g. `claude-sonnet-4-6`). See the [Anthropic model docs](https://docs.anthropic.com/en/docs/models-overview) for current IDs.

---

## First-time setup

### Clone the repository

```bash
git clone <repo-url>
cd zotwiki
```

### Install test dependencies (optional, for running the test suite)

ZotWiki has **zero runtime dependencies** — it uses only the Python standard library. The test suite requires additional packages:

```bash
pip install pytest>=7.0 hypothesis pytest-httpserver
```

Or:

```bash
pip install -r requirements-test.txt
```

### Set environment variables

For commands that call the LLM (`compile`, `ask`), set:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
export ZOTWIKI_MODEL="claude-sonnet-4-6"
```

You can add these to your shell profile or a `.env` file. If either variable is missing when running `compile` or `ask`, ZotWiki will print `error: LLM not configured` and exit with code 2.

---

## Running ZotWiki

Because there is no `pyproject.toml`, the package is not pip-installable. You must set `PYTHONPATH` to point at the `src` directory when running the CLI directly:

```bash
PYTHONPATH=src python -m zotwiki --help
```

For convenience, define a shell alias:

```bash
alias zotwiki='PYTHONPATH=/path/to/zotwiki/src python -m zotwiki'
```

All examples below assume this alias (or equivalent `PYTHONPATH` setup).

---

## Usage

### `zotwiki ingest` — Add a source to Zotero

```
zotwiki ingest --title TITLE [--url URL] [--creator NAME]... [--year YEAR] [--type ITEMTYPE]
```

Adds one item to your Zotero library with an auto-generated citekey. Prints `{citekey}\t{key}` on success.

```bash
zotwiki ingest \
  --title "Attention Is All You Need" \
  --creator "Ashish Vaswani" \
  --year 2017 \
  --url "https://arxiv.org/abs/1706.03762"
```

- `--creator` can be repeated for multiple authors.
- `--type` defaults to `webpage`; pass any Zotero item type (e.g. `journalArticle`).

---

### `zotwiki compile` — Compile Zotero items into a wiki page

```
zotwiki compile --vault DIR (--key KEY [--key KEY ...] | --query QUERY) [--limit N] [--page TITLE] [--today YYYY-MM-DD]
```

Fetches items from Zotero, sends them to the LLM, and writes a Markdown page into `--vault DIR`. On success, prints a `compiled\t{title}\t{path}` line.

**Compile by Zotero key:**

```bash
zotwiki compile --vault ./wiki --key ABCD1234
```

**Compile by search query (default limit: 10):**

```bash
zotwiki compile --vault ./wiki --query "attention transformer" --limit 5
```

**Update an existing page** (merge new findings into an existing page without clobbering it):

```bash
zotwiki compile --vault ./wiki --query "transformer" --page "Transformer"
```

`--page TITLE` names the expected page title. If the article the LLM returns has a different title, the command fails (exit 1) and nothing is written.

If the LLM detects that a new finding contradicts something already on the page, a `Contradictions.md` file is appended automatically, and a `contradictions\t{title}\t{count}` line is printed.

---

### `zotwiki audit` — Check the vault for problems

```
zotwiki audit --vault DIR
```

Runs seven checks on every `.md` file in the vault root:

| Code | What triggers it |
|---|---|
| `PAGE_UNPARSEABLE` | A `.md` file violates the ZotWiki page grammar |
| `CITEKEY_UNRESOLVED` | A cited citekey cannot be resolved in Zotero |
| `QUOTE_NOT_FOUND` | A verbatim quote is not found in the item's fulltext |
| `BROKEN_LINK` | A `[[wiki link]]` target has no corresponding `.md` file |
| `ORPHAN_PAGE` | An entity page is absent from `Index.md` |
| `INDEX_STALE` | An `Index.md` entry points to a missing file |
| `REFERENCE_MISSING` | Citekeys in claims, References block, and frontmatter are inconsistent |

On a clean vault:

```
audit: ok (4 pages)
```

On violations (exit code 1):

```
CITEKEY_UNRESOLVED  Transformer.md  vaswani2017attention
audit: 1 violation(s)
```

---

### `zotwiki ask` — Answer a question from the vault

```
zotwiki ask --vault DIR QUESTION
```

Reads every entity page in the vault, asks the LLM your question, and prints an answer with source citations.

```bash
zotwiki ask --vault ./wiki "What is self-attention and why does it replace recurrence?"
```

Output:

```
Self-attention allows each position in a sequence to attend to all other
positions simultaneously, eliminating the need for sequential computation.

Sources:
- [[Transformer]] [@vaswani2017attention]
```

---

### Global option

```
zotwiki --zotero-url URL <subcommand> ...
```

Override the Zotero local API base URL (default: `http://127.0.0.1:23119/api/users/0`). Useful if your Zotero runs on a non-standard port.

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Domain failure (bad LLM output, item not found, audit violations, etc.) |
| 2 | Environment failure (Zotero unreachable, missing API key, bad arguments) |

Every non-zero exit prints exactly one `error: {message}` line to stderr (audit violations go to stdout instead).

---

## Running the test suite

All tests are hermetic — no real Zotero, no real LLM, no network beyond `127.0.0.1` test fixtures.

```bash
pytest
```

`pytest.ini` sets `pythonpath = src`, so no `PYTHONPATH` export is needed for tests.

---

## Vault layout

ZotWiki writes into a flat directory of `.md` files:

```
wiki/
├── Index.md            # Auto-maintained list of all pages
├── Contradictions.md   # Append-only log of contradicted claims (created on first contradiction)
├── Transformer.md      # Entity pages named after the article title
├── Attention Mechanism.md
└── ...
```

Pages are valid Obsidian Markdown with YAML frontmatter. You can open the vault directory directly in Obsidian. The files are also plain text — no Obsidian installation is required to use ZotWiki.

---

## Subsequent sessions

Once you've set `ANTHROPIC_API_KEY` and `ZOTWIKI_MODEL` and confirmed Zotero is running, a typical session looks like:

```bash
# 1. Add a new paper to Zotero
zotwiki ingest --title "BERT" --creator "Jacob Devlin" --year 2019

# 2. Compile it into the wiki (will create BERT.md and update Index.md)
zotwiki compile --vault ./wiki --query "BERT devlin"

# 3. Update an existing page with a new paper
zotwiki compile --vault ./wiki --key NEWKEY99 --page "BERT"

# 4. Audit for integrity
zotwiki audit --vault ./wiki

# 5. Ask a question
zotwiki ask --vault ./wiki "How does BERT differ from GPT?"
```

---

## Known issues

### No `pyproject.toml` — package is not pip-installable

There is no `pyproject.toml` or `setup.cfg`. ZotWiki cannot be installed with `pip install .` and the `zotwiki` command will not be available on your `PATH` without a wrapper. You must prefix every invocation with `PYTHONPATH=src` or define a shell alias. Adding a `pyproject.toml` with a `[project.scripts]` entry would resolve this.

### `AnthropicLLMClient` does not handle HTTP errors

The production LLM client (`zotwiki/llm.py:49–73`) uses `urllib.request.urlopen` with no error handling around the HTTP call. Errors from the Anthropic API — including a 401 for a bad API key, a 429 for rate limiting, or any 5xx server error — will raise a raw `urllib.error.HTTPError` exception. These are not caught and converted into the ZotWikiError taxonomy, so they bypass the CLI's `error: ...` formatting and instead produce a Python traceback. The fix is to wrap the `urlopen` call in a try/except and raise a `ZotWikiError` (or return a useful error string).

### `_parse_frontmatter` is duplicated

The frontmatter parser is implemented twice: once in `publisher.py` (returns `tuple[dict, int]`) and again in `auditor.py` (returns `dict`). The two copies must be kept in sync by hand. The auditor version should delegate to the publisher version or share a common helper.

### `ask.py` imports private internals

`ask.py` imports `_strip_fence` from `zotwiki.llm` and `_parse_frontmatter` from `zotwiki.publisher` — both underscore-prefixed and not in the public API surface defined by the contract. Changes to those private functions could silently break `ask` without any contract violation. These helpers should either be promoted to the public surface or `ask` should reimplement the small pieces it needs.
