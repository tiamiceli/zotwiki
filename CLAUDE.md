# ZotWiki — development guide for Claude Code

This file is for Claude Code working **inside the zotwiki repo** — adding features, writing tests, fixing bugs. If you are looking for instructions on how to drive zotwiki as a tool from another project, see `docs/operator.md`.

---

## Repo layout

```
zotwiki/
├── src/zotwiki/          # production source (coder-owned)
│   ├── errors.py         # ZotWikiError hierarchy
│   ├── models.py         # frozen dataclasses (Article, Claim, SourceItem, …)
│   ├── zotero.py         # ZoteroStore protocol + HTTPZoteroStore
│   ├── llm.py            # LLMClient protocol + ClaudeCodeLLMClient
│   ├── compiler.py       # Compiler: items → Article
│   ├── publisher.py      # VaultPublisher: Article → .md files
│   ├── auditor.py        # Auditor: vault → AuditReport
│   ├── ask.py            # ask(): question + vault → Answer
│   ├── syncer.py         # Syncer: collection → vault sync
│   └── cli.py            # main() entry point; run() for pyproject.toml
├── tests/                # tester-owned; coder never writes here
├── docs/
│   ├── contract.md         # binding wire/file/behavior spec (exhaustive)
│   ├── requirements.md     # one observable REQ per behavior
│   ├── rulings.md          # planner decisions; override contract where noted
│   ├── plan.md             # completed plan (initial build, M1–M6)
│   ├── plan-sync.md        # completed plan (sync subcommand, REQ-040–044)
│   ├── plan-v1.1.md        # completed plan (ClaudeCodeLLMClient, refactors)
│   ├── plan-v1.2.md        # completed plan (REQ-045 + prompt refactors); BUG-1/2 tracked
│   ├── plan-bug1.md        # completed plan (sync de-dup by zotero_keys, REQ-046–048)
│   ├── plan-zw.md          # completed plan (zw terminal wrapper, REQ-049–053)
│   ├── plan-bug2.md        # completed plan (structured-output LLM boundary, REQ-039/054/055)
│   ├── operator.md         # operator guide (drive zotwiki from another project)
│   └── document-library.md # full repo file index by location
├── scripts/
│   └── zw                # operator terminal wrapper over the zotwiki CLI (contract §11)
└── pyproject.toml        # setuptools build; [project.scripts] zotwiki = cli:run
```

**Zero runtime dependencies.** Stdlib only. No PyYAML, no requests, no pyzotero. Test-time deps: `pytest`, `hypothesis`, `pytest-httpserver`.

---

## How development works

Development follows strict **TDD discipline** with three roles: planner, tester, and coder. They work in sequence and are intentionally kept blind from each other's implementation.

```
Planner  →  Ruling + Contract + Requirements
Tester   →  Failing tests (red gate committed before any code)
Coder    →  Implementation that makes the tests pass
```

### The planner

- Decides what to build and why. Records decisions in **`docs/rulings.md`** — these are binding and override `docs/contract.md` where noted.
- Updates `docs/contract.md` with the wire format, file format, and behavioral spec (exhaustive — if the contract is silent, behavior is unspecified).
- Updates `docs/requirements.md` with new REQs. Each REQ is one observable behavior expressed as Given/When/Then with explicit error behavior.
- Writes a plan in `docs/plan-*.md` naming phases, which files change, and what the done-gate is.

### The tester

- Reads only `docs/contract.md` and `docs/requirements.md`. Does not read source.
- Writes tests in `tests/` that **must fail** before committing (red gate). If a test passes without code changes, it is wrong.
- A change to a **shared format** (frontmatter, page bytes, a dataclass shape) breaks more test sites than the oracle helpers (`m3_helpers`/`m5_helpers`): also retrofit direct dataclass constructions and inline expected-page builders (e.g. `render_oracle(...)` in the m6 CLI tests). At the red gate, confirm each failure would flip to green with correct code — a red that *stays* red is a tester-incomplete test, not feature-absence. (The BUG-1 cycle missed 8 such sites and only caught them mid-coder.)
- Commits the failing tests before the coder writes a line.
- Tester owns `tests/`. The coder never writes or edits test files.

### The coder

- Reads only `docs/contract.md`. Does not read existing tests.
- Writes source in `src/zotwiki/` to make the tests pass. No gold-plating beyond what the contract specifies.
- Runs the full suite to confirm green, then commits.

### Refactors

Refactors (no new REQs, no contract changes) skip the planner/tester phases and are gated solely by the existing test suite staying green.

---

## Running tests

```bash
uv run --with pytest --with hypothesis --with pytest-httpserver pytest
```

All tests are hermetic:
- Fake Zotero HTTP server (`pytest-httpserver`, bound to `127.0.0.1`)
- Fake LLM injected via the `LLMClient` protocol — `ClaudeCodeLLMClient` is never imported by tests
- Vault in `tmp_path`
- No real network, no real Zotero, no real Claude

---

## The injection seam

```python
# cli.py
def main(
    argv: Sequence[str] | None = None,
    *,
    store: ZoteroStore | None = None,
    llm: LLMClient | None = None,
) -> int: ...
```

Pass `store=` and/or `llm=` in tests to inject fakes. When both are `None`, `main` constructs the real `HTTPZoteroStore` and `ClaudeCodeLLMClient`. This seam must never be removed.

The `LLMClient` protocol is one method:

```python
class LLMClient(Protocol):
    def complete(self, prompt: str) -> str: ...
```

Any object with a `.complete` method satisfies it. Tests define minimal inline fakes.

---

## Error hierarchy

```
ZotWikiError
├── ZoteroError
│   ├── ZoteroUnavailableError   # network failure / Zotero not running
│   ├── ItemNotFoundError
│   ├── CitekeyNotFoundError
│   ├── FulltextNotFoundError
│   └── CollectionNotFoundError  # no collection with requested name
├── ArticleSchemaError            # bad LLM JSON output
└── PageParseError / VaultError   # vault file problems
```

---

## Current status

All planned work through BUG-2 is complete. The implemented subcommands are `ingest`, `compile`, `audit`, `ask`, and `sync`. 55 requirements are green (REQ-001–REQ-055); the suite baseline is **418 passed, 1 failed** on macOS — the one failure (`test_req_019`) is a known, accepted macOS case-collision limitation, not a regression (on case-sensitive Linux it passes, so CI shows all green). BUG-1 (sync duplicate pages) is fixed (Ruling 6, `docs/plan-bug1.md`). The `zw` terminal wrapper (`scripts/zw`, contract §11, Rulings 7 & 8, REQ-049–053) lets the operator drive zotwiki from a plain terminal: `ZOTWIKI_VAULT` is the Obsidian Library folder and `ZOTWIKI_COLLECTION` the collection, so each collection becomes its own wiki subfolder. BUG-2 (occasional LLM schema errors / nested-session char-0 failures) is **fixed** (Ruling 9, `docs/plan-bug2.md`): `ClaudeCodeLLMClient` now invokes `claude --print --output-format json --exclude-dynamic-system-prompt-sections` (+ `--json-schema <schema>` when an `output_schema` is set), strips `CLAUDECODE`/`CLAUDE_CODE_*` from the child env, returns `structured_output` (or `result`) on `subtype == "success"`, and otherwise fails closed — writing a verbatim failure artifact under `~/.zotwiki/failures/` and raising a single-line error that points to it. `parse_article_json` and the `ask` validator remain the sole authoritative gates (REQ-010/011 unchanged); `cli.py` constructs the client per command (`ARTICLE_SCHEMA` for `compile`/`sync`, `ANSWER_SCHEMA` for `ask`). The §7.1 OAuth precondition was resolved (validated 2026-06-22).

To start new work: write a ruling in `docs/rulings.md`, update `docs/contract.md` and `docs/requirements.md`, then follow the planner → tester → coder sequence.

---

## Key invariants (never break these)

- `tests/` is tester-owned. Coder never writes there.
- Zero runtime dependencies. If a new import is not in stdlib, it needs a ruling.
- The `LLMClient` injection seam in `main()` is permanent.
- `ClaudeCodeLLMClient` is never imported by the **injected-fake** suite (Compiler/CLI/`ask` tests inject a string-returning fake through the seam). Its only direct test is the dedicated module `tests/test_m6_llm_client.py`, which imports it lazily and drives a **fake `claude` binary on PATH** — never the real binary, never the network (Ruling 9).
- All new behavior needs a REQ in `docs/requirements.md` before any code is written.
- A ruling in `docs/rulings.md` is required before any contract change.
- The existing-article embed in update prompts is compact `json.dumps(…, sort_keys=True)` (no `indent`) — contract §7.1 pins it as a verbatim substring; see Ruling 5. (Indented JSON *examples* in the prompt are fine.)
