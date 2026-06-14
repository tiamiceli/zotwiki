# zotwiki

ZotWiki compiles your Zotero research library into an Obsidian wiki using Claude. It pulls sources from Zotero's local API, sends them to Claude via the Claude Code CLI, and writes canonical Markdown pages into a vault directory. It also audits the vault for broken links and stale citations, and can answer questions from the vault.

## How it works

```
Zotero library  →  zotwiki compile  →  Obsidian vault (.md pages)
                      ↑ Claude CLI           ↓
                                      zotwiki audit / ask
```

ZotWiki has four subcommands:

| Command | What it does |
|---|---|
| `ingest` | Add a source item to Zotero with an auto-generated citekey |
| `compile` | Ask Claude to synthesize one or more Zotero items into a wiki page |
| `audit` | Check the vault for broken links, unresolved citekeys, orphan pages, etc. |
| `ask` | Answer a natural-language question from the vault's content |

---

## Prerequisites

### 1. Python 3.12+

ZotWiki requires Python 3.12 or later. Check your version:

```bash
python3 --version
```

If Python 3.12 is not available, uv can install it:

```bash
uv python install 3.12
```

### 2. uv

ZotWiki is installed and run via [uv](https://docs.astral.sh/uv/). Install it if you don't have it:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### 3. Claude Code CLI

The `compile` and `ask` commands call Claude via the `claude` CLI. You need:

- A [Claude Pro or Claude for Work](https://claude.ai) subscription.
- The Claude Code CLI installed. Follow the [Claude Code quickstart](https://docs.anthropic.com/en/docs/claude-code/quickstart) — the installer adds `claude` to your PATH.

Confirm it is available:

```bash
claude --version
```

If `claude` is not on your PATH when running `compile` or `ask`, ZotWiki prints `error: claude not found` and exits with code 2.

### 4. Zotero 7 or later (desktop app, running)

ZotWiki talks to the **Zotero local API** at `http://127.0.0.1:23119`. This requires:

- [Zotero 7+](https://www.zotero.org/download/) installed and **open** while you run any ZotWiki command.
- The local API is enabled by default in Zotero 7 — no additional configuration is needed.

Confirm it is reachable:

```bash
curl http://127.0.0.1:23119/api/users/0/items?limit=1&format=json
```

If Zotero is not running, every ZotWiki command fails with `error: ...` and exit code 2.

### 5. Better BibTeX for Zotero (recommended for existing libraries)

ZotWiki identifies items by citekey — the `Citation Key: authorYYYYword` line in a Zotero item's Extra field. There are two ways to get citekeys into your library:

- **Via `zotwiki ingest`**: ZotWiki generates and writes the citekey itself.
- **For existing items**: Install the [Better BibTeX for Zotero](https://retorque.re/zotero-better-bibtex/installation/) plugin. It automatically adds `Citation Key:` lines to every item's Extra field.

Without citekeys, `compile` fails with a `CitekeyNotFoundError`.

---

## Installation

Clone the repository and install ZotWiki as a uv tool. This puts `zotwiki` on your PATH with no further setup:

```bash
git clone <repo-url>
cd zotwiki
uv tool install .
```

Verify the install:

```bash
zotwiki --help
```

### Development install

If you are editing ZotWiki's source and want changes to take effect immediately without reinstalling:

```bash
uv pip install -e .
```

### Running the test suite

All tests are hermetic — no real Zotero, no real LLM, no network beyond `127.0.0.1` test fixtures:

```bash
uv run --with pytest --with hypothesis --with pytest-httpserver pytest
```

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

Fetches items from Zotero, sends them to Claude, and writes a Markdown page into `--vault DIR`. On success, prints a `compiled\t{title}\t{path}` line.

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

`--page TITLE` names the expected page title. If the article Claude returns has a different title, the command fails (exit 1) and nothing is written.

If Claude detects that a new finding contradicts something already on the page, a `Contradictions.md` file is appended automatically, and a `contradictions\t{title}\t{count}` line is printed.

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

Reads every entity page in the vault, sends them to Claude with your question, and prints an answer with source citations.

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
| 2 | Environment failure (Zotero unreachable, `claude` not found, bad arguments) |

Every non-zero exit prints exactly one `error: {message}` line to stderr (audit violations go to stdout instead).

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

## Typical session

Once ZotWiki is installed and Zotero is running:

```bash
# 1. Add a new paper to Zotero
zotwiki ingest --title "BERT" --creator "Jacob Devlin" --year 2019

# 2. Compile it into the wiki (creates BERT.md and updates Index.md)
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

### Case-colliding page titles fail on macOS

On macOS (case-insensitive filesystem), two Zotero items whose titles differ only in case — e.g. `"Bert"` and `"BERT"` — will map to the same `.md` file. The expected `VaultError` is not raised before the file is written, so one page silently overwrites the other. This is a pre-existing limitation of the current publisher implementation and will be addressed in a future release.
