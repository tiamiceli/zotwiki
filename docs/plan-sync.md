# ZotWiki — sync subcommand plan

**Status: completed** (REQ-040–044 green, all commits merged to main).

## Goal

Add `zotwiki sync --vault DIR --collection NAME [--update]` as the primary user-facing workflow. The human adds papers to a named Zotero collection; one `sync` call compiles all new items into the vault, skipping pages that already exist (unless `--update` is given).

Authorized by Ruling 3 (see `rulings.md`).

---

## New requirements (REQ-040 through REQ-044)

These extend `docs/requirements.md` §A (ZoteroStore) and §G (CLI).

### REQ-040 — ZoteroStore resolves a collection by name and returns its items

**Given** the fake Zotero server exposes two collections ("AI Papers" and "Other"), "AI Papers" holding two items,
**When** `store.collection_items("AI Papers")` is called,
**Then** it returns a `list[SourceItem]` of length 2, mapped per contract §3.1.
**Error:** no collection matches the name → `CollectionNotFoundError`; Zotero unavailable → `ZoteroUnavailableError`.

### REQ-041 — sync compiles new items, skips existing pages

**Given** a vault with one existing page ("Transformer.md") and a collection containing that item plus one new item,
**When** `zotwiki sync --vault DIR --collection "AI Papers"` is run with a fake LLM and fake store,
**Then** exit 0; stdout contains `compiled\t{new title}\t{path}\n`, `skipped\tTransformer\n`, and `sync: 1 compiled, 1 skipped\n`.

### REQ-042 — sync with --update re-compiles existing pages

**Given** the same setup as REQ-041,
**When** `zotwiki sync --vault DIR --collection "AI Papers" --update` is run,
**Then** exit 0; stdout contains two `compiled\t...\n` lines and `sync: 2 compiled, 0 skipped\n`; the previously existing page is overwritten.

### REQ-043 — collection not found exits 2

**Given** the fake Zotero server has no collection named "Nonexistent",
**When** `zotwiki sync --vault DIR --collection "Nonexistent"` is run,
**Then** exit 2; stderr is `error: collection 'Nonexistent' not found\n`.

### REQ-044 — items without citekeys are skipped silently

**Given** a collection where one item has no citekey (empty Extra field),
**When** `zotwiki sync --vault DIR --collection "AI Papers"` is run,
**Then** exit 0; the citekey-less item produces neither a `compiled` nor an error line; `sync:` summary counts it neither compiled nor skipped (it is simply absent from the count).

---

## Contract changes required

### §3 ZoteroStore protocol — new method

```
collection_items(name: str) -> list[SourceItem]
```

Resolves a collection by exact name (case-sensitive), then returns all items in it. Raises `CollectionNotFoundError` (new subclass of `ZoteroError`) if no match; raises `ZoteroUnavailableError` on network failure.

### §4 Zotero local API — new endpoints

- `GET /collections?format=json` — returns array of collection objects; each has `key` and `data.name`.
- `GET /collections/{key}/items?format=json&limit=100` — returns items in that collection (same shape as `/items`).

### §9 CLI — new subcommand §9.6

```
zotwiki sync --vault DIR --collection NAME [--update]
```

- Requires LLM (same PATH check as `compile` and `ask`; exit 2 if `claude` missing).
- Requires vault directory to exist; exit 2 with `error: vault directory not found: {path}` if not.
- Collection not found → exit 2 with `error: collection {name!r} not found`.
- Per-item stdout: `compiled\t{title}\t{path}\n` or `skipped\t{title}\n`.
- Contradictions line follows compiled line when applicable.
- Final stdout line always: `sync: {n} compiled, {m} skipped\n`.
- Items with no citekey are silently skipped (not counted in either total).
- Exit 0 on success (even if 0 compiled); exit 1 on LLM domain failure mid-sync; exit 2 on environment failure.

### §2 errors — new error class

`CollectionNotFoundError(ZoteroError)` — raised by `store.collection_items` when no collection matches the given name.

---

## New source files

| File | Role |
|---|---|
| `src/zotwiki/syncer.py` | `Syncer(store, llm, vault, today=None).sync(name, update) -> SyncReport` |
| `tests/test_sync_store.py` | REQ-040, REQ-043, REQ-044 (store layer, fake HTTP server) |
| `tests/test_sync_cli.py` | REQ-041, REQ-042, REQ-043 (CLI layer, fake store + fake LLM) |

### `SyncReport` dataclass

```python
@dataclass(frozen=True)
class SyncReport:
    compiled: int
    skipped: int
```

---

## Modified source files

| File | Change |
|---|---|
| `src/zotwiki/errors.py` | Add `CollectionNotFoundError` |
| `src/zotwiki/zotero.py` | Add `collection_items(name)` to `ZoteroStore` protocol and `HTTPZoteroStore` |
| `src/zotwiki/cli.py` | Add `sync` subcommand; add it to `_NEEDS_LLM`; add `_cmd_sync` |

---

## Phases

### Phase A — tester (red gate first)

1. Add `CollectionNotFoundError` to `errors.py` (import surface; tester needs it for assertions).
2. Write `tests/test_sync_store.py` covering REQ-040, REQ-043, REQ-044. Run suite — new tests must fail (store method not yet implemented).
3. Write `tests/test_sync_cli.py` covering REQ-041, REQ-042, REQ-043. Run suite — new tests must fail (`sync` subcommand not yet implemented).
4. Commit: "Phase A tester: REQ-040 through REQ-044 (red gate)".

### Phase B — coder

1. Update `src/zotwiki/zotero.py`: add `collection_items` to protocol and implement in `HTTPZoteroStore`.
2. Create `src/zotwiki/syncer.py` with `Syncer` and `SyncReport`.
3. Update `src/zotwiki/cli.py`: add `sync` parser, `_cmd_sync`, add `"sync"` to `_NEEDS_LLM`.
4. Run full suite — all tests green.
5. Commit: "Phase B coder: sync subcommand (REQ-040 through REQ-044)".

### Done-gate

- All pre-existing tests still pass.
- REQ-040 through REQ-044 green.
- `zotwiki sync --help` shows correct usage.
- No new runtime dependencies (stdlib only).
