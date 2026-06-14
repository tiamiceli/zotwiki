# ZotWiki — Planner Rulings

## Ruling 1 — M5 red gate unachievable (already-satisfied)

**Date:** 2026-06-11 · **Scope:** M5 (REQ-020, REQ-022, REQ-031) · **Status:** binding.

**1. Disposition: M5 is closed as satisfied-at-M3; no coder invocation.**
plan.md's M3 scope deliberately forward-deployed the machinery ("Index
regeneration is wired in here mechanically but its acceptance lives in M5"),
and the M5 scope itself is acceptance-shaped (update path, `Index.md`
maintenance, `publish_contradictions`) over surfaces M2/M3 already built
(contract §6.5 update path, §6.7, §6.8, §7.2). An empty implementation delta
is therefore a foreseen outcome of the plan, not a process failure. The red
gate exists to prove tests are implementation-sensitive, not to force code
churn; with nothing left to implement, a failing test could only be a wrong
test. The 25 tester-authored tests (`test_m5_update_publish.py`,
`test_m5_index.py`, `test_m5_contradictions.py`, `test_m5_end_to_end.py`) are
accepted as regression armor and M5 is closed.

**2. REQ-020, REQ-022, REQ-031 are confirmed covered — mark green at M5.**
- REQ-020: update publish merges per §7.2 with `created` preserved and
  change-gated `updated` (§6.5), pinned by independent oracle tests.
- REQ-022: `Index.md` lists exactly the entity pages, sorted, byte-idempotent
  on republish, pinned against §6.7 byte oracles — the orchestrator's
  title-order mutation failing 6 tests on byte-diff assertions proves these
  oracles bite.
- REQ-031: append-only `Contradictions.md` per §6.8, entity page
  byte-identical, `ValueError` on empty sequence — all asserted.
plan.md M5 "Done when" criteria (idempotent update merge, index correctness,
append-only contradictions, post-update full audit clean) hold at 295 passed,
including the REQ-014/016 integration re-runs. The final REQ-coverage report
may mark REQ-020/022/031 green at M5.

**3. Conditions (binding):**
- (a) **No-red closures require non-vacuity evidence**, exactly the form the
  orchestrator produced: (i) implementation-absence run (all new test modules
  error), (ii) ≥1 behavioral mutation failing new tests on assertions, (iii)
  restoration to full green. The M5 record (remove `publisher.py` → 4 modules
  error; reverse Index title order → 6 byte-diff failures; restore → 295
  passed) satisfies this and shall be stored under `.gates/` as M5's gate
  artifact in lieu of `M5.red`.
- (b) The 25 M5 tests are frozen as regression armor: they run in every later
  milestone's cross-milestone done-gate (plan.md preamble) and may not be
  weakened or removed without a new ruling.
- (c) This ruling is precedent only where the plan's scope notes
  forward-deployed the implementation (as M3's did). Any other unachievable
  red gate requires its own ruling.
- (d) M5 closure does not discharge M6: the CLI update flow must still
  independently exercise the REQ-020/REQ-031 path (requirements.md §G:
  "merged per REQ-020, `Contradictions.md` is appended per REQ-031").

---

## Ruling 2 — LLM backend replaced; plan-v1.1.md authorized

**Date:** 2026-06-14 · **Scope:** post-M6 · **Status:** binding.

**1. Disposition: `AnthropicLLMClient` is removed; `ClaudeCodeLLMClient` is
the sole production LLM implementation.**

A post-M6 review found that the Anthropic API backend (`AnthropicLLMClient`,
`ANTHROPIC_API_KEY`, `ZOTWIKI_MODEL`) is the wrong default for a tool built
around Claude Code: it requires a separate paid API account, separate
credentials, and separate error handling. The Claude Code CLI (`claude`)
is already present in the user's environment and handles auth transparently.
Removing the API backend simplifies the contract, eliminates a class of
runtime errors, and makes ZotWiki usable without additional setup.

**2. Contract and requirements changes (binding):**

- contract.md §5.1: `AnthropicLLMClient` paragraph replaced with
  `ClaudeCodeLLMClient` paragraph. `ANTHROPIC_API_KEY` and `ZOTWIKI_MODEL`
  are no longer referenced anywhere in the contract.
- contract.md §9.4: env-var check replaced with PATH check for `claude`.
  Missing `claude` → `error: claude not found`, exit 2.
- requirements.md REQ-038 error behavior revised: "missing API key" →
  "`claude` not on PATH". The tester must update the existing test accordingly.
- requirements.md REQ-039 added: `ClaudeCodeLLMClient` behavior under success
  and failure, tested hermetically with a fake `claude` binary on PATH.

**3. plan-v1.1.md is authorized with two phases:**

- **Phase A (TDD):** tester revises REQ-038 test and writes REQ-039 test
  (fake `claude` binary) before the coder touches any code. Coder deletes
  `AnthropicLLMClient`, adds `ClaudeCodeLLMClient`, updates `cli.py`.
- **Phase B (refactors, no new REQs):** T1 (`pyproject.toml`), T3
  (deduplicate `_parse_frontmatter`), T4 (remove `ask.py` private imports).
  Existing passing tests are the sole gate for Phase B.

**4. Conditions (binding):**

- (a) All tests passing at the start of Phase A must remain passing at the
  end of Phase B. The only tests that may change are those directly testing
  REQ-038 behavior (to reflect the revised error condition).
- (b) `ClaudeCodeLLMClient` must use only stdlib (`subprocess`, `shutil`).
  No new runtime dependencies are introduced.
- (c) The `LLMClient` protocol (contract §5.1) and the injection seam
  (`main(store=, llm=)`) are unchanged. All existing fake-LLM tests remain
  valid without modification.
- (d) Phase B tasks are pure refactors: no observable behavior changes, no
  contract surface changes. If any Phase B task would require a contract
  amendment, it must be raised as a new ruling before proceeding.

---

## Ruling 3 — sync subcommand authorized

**Date:** 2026-06-14 · **Scope:** post-M6 · **Status:** binding.

**1. Disposition: `zotwiki sync` is added as the primary user-facing workflow.**

The current `compile` subcommand requires the user or driver to specify individual Zotero keys or search queries. The intended usage model is simpler: the human maintains a named Zotero collection; one command syncs the entire collection into the vault, compiling new items and (optionally) updating existing ones. This requires a new `sync` subcommand and a new `collection_items` method on `ZoteroStore`.

**2. Contract changes (binding, see plan-sync.md for details):**

- `errors.py`: add `CollectionNotFoundError(ZoteroError)`.
- `contract.md §3`: add `collection_items(name: str) -> list[SourceItem]` to the `ZoteroStore` protocol.
- `contract.md §4`: document the two new Zotero local API endpoints (`/collections`, `/collections/{key}/items`).
- `contract.md §9`: add §9.6 specifying the `sync` subcommand's flags, stdout format, and exit codes.

**3. Requirements added (binding):**

REQ-040 through REQ-044, specified in `plan-sync.md`.

**4. plan-sync.md is authorized.**

TDD discipline applies: tester writes and commits red tests before coder writes any implementation.

**5. Conditions (binding):**

- (a) All pre-existing tests remain green at the end of the coder phase.
- (b) `collection_items` uses only stdlib HTTP (`urllib.request`); no new runtime dependencies.
- (c) The `LLMClient` protocol and injection seam are unchanged.
- (d) `sync` skips items with no citekey silently (not an error, not counted in summary totals).
- (e) Default behavior (no `--update`) never overwrites an existing page.
