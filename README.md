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

---

## How to use ZotWiki

ZotWiki is designed to be driven by Claude Code. You work in Zotero and Obsidian; Claude Code handles the CLI.

### 1. Set up a Zotero collection

In Zotero, create a collection (folder) for the papers you want in your wiki — for example, **"AI Papers"**. Add papers to it by dragging PDFs in, using the Zotero browser connector, or asking Claude Code to run `zotwiki ingest`.

### 2. Create your vault

Create an empty directory for your wiki pages:

```bash
mkdir -p ~/research/wiki
```

### 3. Sync with Claude Code

Open Claude Code in your research project directory and ask it to sync:

> "Sync my wiki from the 'AI Papers' Zotero collection into ./wiki"

Claude Code will run `zotwiki sync`, compile each paper into a wiki page, and report what was added.

### 4. Read in Obsidian

Open the vault directory in Obsidian. Pages link to each other, cite their sources, and flag contradictions automatically. Re-sync whenever you add papers to the collection.

### 5. Ask questions

Ask Claude Code a research question from the vault:

> "What does my wiki say about the relationship between attention and recurrence?"

Claude Code will run `zotwiki ask` and synthesize an answer from your pages.

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
