# zotwiki

ZotWiki turns a Zotero collection into an Obsidian wiki. You add papers to a Zotero folder; ZotWiki (driven by Claude Code) synthesizes them into linked wiki pages with citations, cross-references, and contradiction tracking.

```
Zotero collection  →  zotwiki sync  →  Obsidian vault (.md pages)
                         ↑ Claude               ↓
                                         zotwiki audit / ask
```

---

## Prerequisites

**uv** — ZotWiki is installed via [uv](https://docs.astral.sh/uv/):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Python 3.12+** — if unavailable, uv can install it:
```bash
uv python install 3.12
```

**Claude Code CLI** — `compile`, `sync`, and `ask` shell out to `claude`. Requires a [Claude Pro or Claude for Work](https://claude.ai) subscription and the Claude Code CLI on your PATH. Follow the [Claude Code quickstart](https://docs.anthropic.com/en/docs/claude-code/quickstart) to install it.

**Zotero 7+** — must be open while ZotWiki is running. The local API at `http://127.0.0.1:23119` is enabled by default.

**Better BibTeX** (recommended for existing libraries) — ZotWiki identifies papers by citekey (`Citation Key: authorYYYYword` in Zotero's Extra field). The [Better BibTeX plugin](https://retorque.re/zotero-better-bibtex/installation/) adds these to all items automatically. Papers added via ZotWiki's `ingest` command get citekeys without the plugin.

---

## Installation

```bash
git clone <repo-url>
cd zotwiki
uv tool install .
```

To update after pulling new changes:

```bash
uv tool install . --reinstall
```

> **Upgrading an existing vault:** this release changed the page frontmatter
> format (schema `zotwiki: 2`). Pages written by older ZotWiki read as
> unparseable to `audit`/`sync`. To migrate, delete the vault's `*.md` files
> (or start a fresh vault) and re-run `sync` — this also clears any duplicate
> pages left by the old title-based sync.

---

## How to use ZotWiki

ZotWiki is designed to be driven by Claude Code. You work in Zotero and Obsidian; Claude Code handles the CLI.

### 1. Set up a Zotero collection

In Zotero, create a collection (folder) for the papers you want in your wiki — for example, **"AI Papers"**. Add papers to it by dragging PDFs in, using the Zotero browser connector, or asking Claude Code to run `zotwiki ingest`.

### 2. Point to your vault

The vault is just a directory of `.md` files. You can use:

- An **existing Obsidian vault** (or a subfolder of one) — ZotWiki writes standard Markdown that Obsidian reads natively.
- A **new empty directory** if you're starting fresh.

If your vault lives inside an iCloud-synced Obsidian vault, use the full path, e.g.:

```
/Users/yourname/Library/Mobile Documents/iCloud~md~obsidian/Documents/MyVault/Research
```

Paths with spaces or emoji must be quoted in the shell. When you ask Claude Code to sync, just describe the path in plain language and it will handle the quoting. (If you drive ZotWiki from a plain terminal instead, see [Operating from the terminal](#operating-from-the-terminal-zw-directives) below — it uses a single `ZOTWIKI_VAULT` setting.)

### 3. Sync with Claude Code

Open Claude Code and ask it to sync — describe your collection name and vault path in plain language:

> "Sync my wiki from the 'AI Papers' Zotero collection into my Research vault"

Claude Code will run `zotwiki sync`, compile each paper into a wiki page, and report what was added.

### 4. Read in Obsidian

Open the vault directory in Obsidian. Pages link to each other, cite their sources, and flag contradictions automatically. Re-sync whenever you add papers to the collection.

### 5. Ask questions

Ask Claude Code a research question from the vault:

> "What does my wiki say about the relationship between attention and recurrence?"

Claude Code will run `zotwiki ask` and synthesize an answer from your pages.

---

## Operating from the terminal (`zw` directives)

If you'd rather drive ZotWiki yourself from a plain terminal, `scripts/zw` gives
short directives that fill in the long paths for you. It's a tidy way to run the
LLM-backed commands outside a nested Claude Code session. (ZotWiki also hardens
the LLM boundary itself — it strips nested-session environment variables and
constrains the model to structured JSON output — so the model's output is robust
whether you run from a plain terminal or inside a session; see
`docs/user-testing/zotwiki-bug-findings1.md`.)

Set **two** things once, then put `zw` on your `PATH`:

```bash
# add to ~/.zshrc
export ZOTWIKI_VAULT="/Users/yourname/.../MyVault/Library"   # your Obsidian "Library" folder
export ZOTWIKI_COLLECTION="AI Papers"                        # the Zotero collection to work with

# put `zw` beside the installed zotwiki binary (already on your PATH):
chmod +x scripts/zw
ln -s "$PWD/scripts/zw" "$(dirname "$(command -v zotwiki)")/zw"
```

Each Zotero collection gets its **own wiki folder** under `ZOTWIKI_VAULT`:
`$ZOTWIKI_VAULT/$ZOTWIKI_COLLECTION`. `zw sync` creates that folder the first time.
So with the values above, `zw sync` builds `…/Library/AI Papers/`.

| Directive | Runs (`$V`=`ZOTWIKI_VAULT`, `$C`=`ZOTWIKI_COLLECTION`) | Calls Claude? |
|---|---|---|
| `zw sync [--update]` | `zotwiki sync --vault "$V/$C" --collection "$C"` (creates the folder) | yes |
| `zw sync "Other Collection"` | same, but for `Other Collection` (one-off override) | yes |
| `zw ask "what problem does attention solve?"` | `zotwiki ask --vault "$V/$C" "…"` | yes |
| `zw compile --query transformers [...]` | `zotwiki compile --vault "$V/$C" [...]` | yes |
| `zw ingest --title "BERT" --year 2019` | `zotwiki ingest [...]` (no vault/collection) | no |
| `zw audit` | `zotwiki audit --vault "$V/$C"` | no |
| `zw` / `zw help` | prints this directive list | no |

`zw` passes through `zotwiki`'s exit code (0 success / 1 domain failure / 2
environment failure). To work on a different collection, change `ZOTWIKI_COLLECTION`
(or pass the name to `zw sync` for a single run).

---

## Vault layout

```
wiki/
├── Index.md            # auto-maintained list of all pages
├── Contradictions.md   # append-only log of contradicted claims
├── Transformer.md      # one page per paper, named after the article title
├── Attention Mechanism.md
└── ...
```

Open the vault directory directly in Obsidian. The files are plain Markdown — no Obsidian installation is required to use ZotWiki.

---

## Development

```bash
# Editable install (changes take effect immediately)
uv pip install -e .

# Test suite (hermetic — no real Zotero, no real LLM, no external network)
uv run --with pytest --with hypothesis --with pytest-httpserver pytest
```

For Claude Code operator instructions (exact command syntax, output formats, exit codes), see [`docs/operator.md`](docs/operator.md).

---

## Known issues

**macOS case-collision** — two papers whose titles differ only in case (e.g. `"Bert"` and `"BERT"`) map to the same `.md` file. The collision is not detected before the write, so one page silently overwrites the other. Will be fixed in a future release.
