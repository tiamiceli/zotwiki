# zotwiki

ZotWiki compiles your Zotero research library into an Obsidian wiki using Claude. It pulls sources from Zotero's local API, sends them to Claude via the Claude Code CLI, and writes canonical Markdown pages into a vault directory. It also audits the vault for broken links and stale citations, and can answer questions from the vault.

```
Zotero library  →  zotwiki compile  →  Obsidian vault (.md pages)
                      ↑ Claude CLI           ↓
                                      zotwiki audit / ask
```

---

## Prerequisites

**Python 3.12+** — check with `python3 --version`. If unavailable: `uv python install 3.12`.

**uv** — ZotWiki is installed via [uv](https://docs.astral.sh/uv/):
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Claude Code CLI** — the `compile` and `ask` commands shell out to `claude`. Requires a [Claude Pro or Claude for Work](https://claude.ai) subscription and the Claude Code CLI on your PATH. Follow the [Claude Code quickstart](https://docs.anthropic.com/en/docs/claude-code/quickstart) to install it.

**Zotero 7+** — must be open while you run ZotWiki. The local API at `http://127.0.0.1:23119` is enabled by default; no extra configuration needed.

**Better BibTeX** (recommended for existing libraries) — ZotWiki identifies items by citekey (`Citation Key: authorYYYYword` in Zotero's Extra field). The [Better BibTeX plugin](https://retorque.re/zotero-better-bibtex/installation/) adds these automatically to all items. Without citekeys, `compile` will fail. Items added via `zotwiki ingest` get citekeys automatically.

---

## Installation

```bash
git clone <repo-url>
cd zotwiki
uv tool install .
zotwiki --help
```

### Development install

To have source edits take effect immediately without reinstalling:

```bash
uv pip install -e .
```

### Test suite

```bash
uv run --with pytest --with hypothesis --with pytest-httpserver pytest
```

All tests are hermetic — no real Zotero, no real LLM, no network beyond `127.0.0.1` fixtures.

---

## Typical session

```bash
# Add a paper to Zotero
zotwiki ingest --title "BERT" --creator "Jacob Devlin" --year 2019

# Compile it into the wiki (creates BERT.md and updates Index.md)
zotwiki compile --vault ./wiki --query "BERT devlin"

# Update an existing page with another paper
zotwiki compile --vault ./wiki --key NEWKEY99 --page "BERT"

# Audit for integrity
zotwiki audit --vault ./wiki

# Ask a question
zotwiki ask --vault ./wiki "How does BERT differ from GPT?"
```

---

## Vault layout

ZotWiki writes a flat directory of `.md` files you can open directly in Obsidian:

```
wiki/
├── Index.md            # auto-maintained list of all pages
├── Contradictions.md   # append-only log of contradicted claims
├── Transformer.md      # entity pages, named after the article title
├── Attention Mechanism.md
└── ...
```

---

## Using with Claude Code

If you use Claude Code to help manage your research wiki, copy the contents of `CLAUDE.md` from this repo into your project's own `CLAUDE.md`. It gives Claude Code the exact command syntax, output formats, and error behaviors it needs to drive ZotWiki reliably.

---

## Known issues

**macOS case-collision** — two items whose titles differ only in case (e.g. `"Bert"` and `"BERT"`) map to the same `.md` file. The collision is not detected before the write, so one page silently overwrites the other. Will be fixed in a future release.
