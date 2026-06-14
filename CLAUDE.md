# ZotWiki — operator guide for Claude Code

ZotWiki is a CLI tool that compiles a Zotero research library into an Obsidian-compatible wiki vault. Use it to add sources, synthesize wiki pages, audit vault integrity, and answer questions from the vault.

## Before running any command

- **Zotero must be open.** The local API at `http://127.0.0.1:23119` must be reachable. If it is not, every command exits 2 with `error: Zotero unavailable ...`.
- **`claude` must be on PATH** for `compile` and `ask`. If missing, those commands exit 2 with `error: claude not found`.
- **`--vault DIR`** must be an existing directory for `compile`, `audit`, and `ask`.

---

## Commands

### ingest — add a source to Zotero

```
zotwiki ingest --title TITLE [--url URL] [--creator NAME]... [--year YEAR] [--type ITEMTYPE]
```

- `--creator` repeatable; `--type` defaults to `webpage`.
- **stdout on success:** `{citekey}\t{zotero_key}\n`
- **exit 0** on success; **exit 2** on Zotero error.

### compile — synthesize items into a wiki page

```
zotwiki compile --vault DIR (--key KEY [--key KEY ...] | --query QUERY) [--limit N] [--page TITLE] [--today YYYY-MM-DD]
```

- `--key` and `--query` are mutually exclusive. `--limit` defaults to 10.
- `--page TITLE` pins the expected article title. If Claude returns a different title the command exits 1 and writes nothing.
- `--today YYYY-MM-DD` overrides the date stamped into the page frontmatter.
- **stdout on success:**
  ```
  compiled\t{title}\t{absolute_path}\n
  ```
  If contradictions were detected, an additional line follows:
  ```
  contradictions\t{title}\t{count}\n
  ```
- **exit 0** on success; **exit 1** on domain failure (no items matched, title mismatch, bad LLM output); **exit 2** on environment failure.

### audit — check vault integrity

```
zotwiki audit --vault DIR
```

- **stdout on clean vault:** `audit: ok ({n} pages)\n` — exit 0.
- **stdout on violations:** one tab-separated line per violation, then a summary — exit 1:
  ```
  {CODE}\t{filename}\t{detail}\n
  ...
  audit: {n} violation(s)\n
  ```
- Violation codes: `PAGE_UNPARSEABLE`, `CITEKEY_UNRESOLVED`, `QUOTE_NOT_FOUND`, `BROKEN_LINK`, `ORPHAN_PAGE`, `INDEX_STALE`, `REFERENCE_MISSING`.

### ask — answer a question from the vault

```
zotwiki ask --vault DIR QUESTION
```

- Reads all entity pages, sends them to Claude with the question, prints the answer.
- **stdout on success:**
  ```
  {answer text}

  Sources:
  - [[{page}]] [@{citekey}]
  ...
  ```
- **exit 0** on success; **exit 1** if the vault has no entity pages or Claude returns malformed output; **exit 2** on environment failure.

### Global option

```
zotwiki --zotero-url URL <subcommand> ...
```

Overrides the Zotero API base URL (default: `http://127.0.0.1:23119/api/users/0`).

---

## Exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Domain failure — bad LLM output, item not found, title mismatch, audit violations |
| 2 | Environment failure — Zotero unreachable, `claude` not found, bad arguments |

On exit 1 or 2, exactly one `error: {message}\n` line is written to **stderr** (audit violations are the exception — they go to stdout as structured lines, not to stderr).

---

## Vault layout

```
vault/
├── Index.md            # bullet list of [[PageTitle]] links; auto-updated by compile
├── Contradictions.md   # append-only; created on first contradiction
└── {Title}.md          # one entity page per article; title = safe filename
```

Entity page filenames use the article title directly (e.g. `Attention Mechanism.md`). Titles are restricted to `[A-Za-z0-9][A-Za-z0-9 ,()'\\-]*` and capped at 120 characters.

---

## Citekeys

Citekeys follow the pattern `{author}{year}{word}` (e.g. `vaswani2017attention`). Items added via `ingest` get citekeys automatically. Items added externally need the [Better BibTeX plugin](https://retorque.re/zotero-better-bibtex/installation/) or a manually added `Citation Key: ...` line in Zotero's Extra field.

---

## Typical workflow

```bash
# 1. Add a paper
zotwiki ingest --title "Attention Is All You Need" --creator "Ashish Vaswani" --year 2017

# 2. Compile it (vault dir must already exist)
mkdir -p ./wiki
zotwiki compile --vault ./wiki --query "vaswani attention"

# 3. Add more papers and update an existing page
zotwiki compile --vault ./wiki --key ABCD1234 --page "Attention Is All You Need"

# 4. Check for integrity issues
zotwiki audit --vault ./wiki

# 5. Answer a research question
zotwiki ask --vault ./wiki "What problem does self-attention solve?"
```

---

## Known limitations

- **macOS case-collision:** two items with titles that differ only in case will silently overwrite each other's page. Avoid titles that are case-variants of existing pages.
- `compile` requires at least one Zotero item to have a citekey; otherwise it exits 1 with a `CitekeyNotFoundError` message.
