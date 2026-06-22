# ZotWiki — operator guide for Claude Code

Copy this file into your research project's `CLAUDE.md` (or reference it) so Claude Code knows how to drive ZotWiki. This is not the development guide — for that, see `CLAUDE.md` at the repo root.

ZotWiki is a CLI tool that compiles a Zotero research library into an Obsidian-compatible wiki vault. Use it to add sources, sync a Zotero collection into wiki pages, audit vault integrity, and answer questions from the vault.

---

## Upgrading an existing vault (schema v2)

ZotWiki now records each page's source Zotero item keys in frontmatter (`zotero_keys`; schema `zotwiki: 2`) and skips/updates by key, so re-syncing no longer creates duplicate pages. **This is a breaking format change:** pages written by an older ZotWiki (`zotwiki: 1`) report as `PAGE_UNPARSEABLE` under `audit` and are not recognized by `sync`. To migrate, **delete the vault's `*.md` files (or use a fresh vault) and re-run `sync`** — this rebuilds every page in the new format and clears any duplicates the old sync left behind.

---

## Before running any command

- **Zotero must be open.** The local API at `http://127.0.0.1:23119` must be reachable. If not, every command exits 2 with `error: Zotero unavailable ...`.
- **`claude` must be on PATH** for `compile`, `sync`, and `ask`. If missing, those commands exit 2 with `error: claude not found`.
- **`--vault DIR`** must be an existing directory for `compile`, `sync`, `audit`, and `ask`.

---

## Commands

### sync — compile all new items in a Zotero collection  *(primary workflow)*

```
zotwiki sync --vault DIR --collection NAME [--update] [--today YYYY-MM-DD]
```

- Finds the Zotero collection named `NAME` (case-sensitive).
- For each item in the collection:
  - If no page exists yet: compiles it and writes a new page.
  - If a page already exists and `--update` is set: re-compiles and overwrites.
  - If a page already exists and `--update` is not set: skips it.
  - If the item has no citekey: skips it silently (not an error).
- **stdout per item:**
  ```
  compiled\t{title}\t{absolute_path}\n   # new page written
  skipped\t{title}\n                     # page already exists, no --update
  ```
  If contradictions were detected during a compile, an additional line follows:
  ```
  contradictions\t{title}\t{count}\n
  ```
- **stdout summary (always last):**
  ```
  sync: {n} compiled, {m} skipped\n
  ```
- **exit 0** on success; **exit 1** on domain failure (bad LLM output); **exit 2** on environment failure (Zotero unavailable, collection not found, `claude` missing).
- `error: collection {name!r} not found` → exit 2 when no collection matches `NAME`.

### ingest — add a source to Zotero

```
zotwiki ingest --title TITLE [--url URL] [--creator NAME]... [--year YEAR] [--type ITEMTYPE]
```

- `--creator` repeatable; `--type` defaults to `webpage`.
- **stdout on success:** `{citekey}\t{zotero_key}\n`
- **exit 0** on success; **exit 2** on Zotero error.

### compile — synthesize specific items into a wiki page

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
- **exit 0** on success; **exit 1** if vault has no entity pages or Claude returns malformed output; **exit 2** on environment failure.

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
| 2 | Environment failure — Zotero unreachable, `claude` not found, collection not found, bad arguments |

On exit 1 or 2, exactly one `error: {message}\n` line is written to **stderr** (audit violations are the exception — they go to stdout as structured lines).

When a `compile`, `sync`, or `ask` run fails because the LLM did not return valid structured JSON, ZotWiki **fails closed** and writes the full exchange — the exact `claude` invocation, the prompt it sent, and the raw response/envelope — to a timestamped file under `~/.zotwiki/failures/`. The `error:` line names that file; open it to see exactly what the model returned.

---

## Vault layout

```
vault/
├── Index.md            # bullet list of [[PageTitle]] links; auto-updated by compile/sync
├── Contradictions.md   # append-only; created on first contradiction
└── {Title}.md          # one entity page per article; title = safe filename
```

Entity page filenames use the article title directly (e.g. `Attention Mechanism.md`). Titles are restricted to `[A-Za-z0-9][A-Za-z0-9 ,()'\\-]*` and capped at 120 characters.

---

## Citekeys

Citekeys follow the pattern `{author}{year}{word}` (e.g. `vaswani2017attention`). Items added via `ingest` get citekeys automatically. Items added externally need the [Better BibTeX plugin](https://retorque.re/zotero-better-bibtex/installation/) or a manually added `Citation Key: ...` line in Zotero's Extra field. Items without citekeys are silently skipped by `sync`.

---

## Typical workflow

```bash
# First time: create a vault directory
mkdir -p ./wiki

# Sync all new items from a Zotero collection
zotwiki sync --vault ./wiki --collection "AI Papers"

# Add a paper manually and re-sync
zotwiki ingest --title "BERT" --creator "Jacob Devlin" --year 2019
zotwiki sync --vault ./wiki --collection "AI Papers"

# Re-compile existing pages when you want them updated
zotwiki sync --vault ./wiki --collection "AI Papers" --update

# Check vault integrity
zotwiki audit --vault ./wiki

# Answer a research question
zotwiki ask --vault ./wiki "What problem does self-attention solve?"
```

---

## Internal notes

- **Update mode** (re-compiling an existing page via `compile --page` or `sync --update`) embeds the current page's article into the LLM prompt as **compact** JSON (`json.dumps(..., sort_keys=True)`, no indentation), fixed by contract §7.1 and not configurable. Operators don't control this; noted for completeness.

---

## Known limitations

- **macOS case-collision:** two items with titles differing only in case silently overwrite each other's page. Avoid titles that are case-variants of existing pages.
- `sync` and `compile` require items to have citekeys; `sync` skips items without them, `compile` exits 1.
