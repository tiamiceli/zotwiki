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

## Ruling 2 — Post-M6 fix phase authorized (plan-v1.1.md)

**Date:** 2026-06-13 · **Scope:** post-M6 maintenance · **Status:** binding.

**1. Disposition: four implementation gaps identified by README audit are
authorized as plan-v1.1.md tasks T1–T4.**

A planner review of the completed M1–M6 codebase surfaced four gaps not
covered by any REQ in requirements.md §A–G but material to real-world
usability and internal correctness. None invalidates an existing green test;
all are below-the-contract quality issues or missing packaging infrastructure.
The fix phase is scoped to exactly these four tasks; no new REQs are added
to requirements.md (the contract §1.1 public surface is unchanged).

**2. Gap inventory and decisions:**

- **T1 — No installable entry point.** There is no `pyproject.toml`; the CLI
  can only be invoked via `PYTHONPATH=src python -m zotwiki`. Fix: add a
  minimal `pyproject.toml` with a `[project.scripts]` entry. A thin
  `run()` wrapper in `cli.py` shall call `sys.exit(main())` and serve as the
  entry point target so the existing `main()` contract (returns int, never
  calls `sys.exit`) remains intact.

- **T2 — `AnthropicLLMClient` swallows HTTP errors as raw tracebacks.**
  `urllib.request.urlopen` in `llm.py` is unwrapped; HTTP 4xx/5xx,
  connection errors, and timeouts surface as raw Python exceptions that
  bypass the CLI's `error: ...` formatting. Fix: wrap the call in a
  try/except covering `urllib.error.HTTPError`, `urllib.error.URLError`,
  and `OSError`; re-raise as `ZotWikiError` with a clean human-readable
  message. Decision: `ZotWikiError` (not a Zotero subclass) is the correct
  type; the CLI already catches it as a domain failure (exit 1 via the
  `except ZotWikiError` branch). The hermetic test suite never imports
  `AnthropicLLMClient`; no test changes are required.

- **T3 — `_parse_frontmatter` is duplicated.** Nearly-identical
  implementations exist in `publisher.py` (returns `tuple[dict, int]`) and
  `auditor.py` (returns `dict`). Decision: the publisher's two-return-value
  version is canonical (callers that need only the dict ignore `_`).
  `auditor.py`'s local copy is deleted; `auditor.py` imports the function
  from `publisher`. The import of a private symbol across modules is accepted
  as an internal convention (contract §1.1 enumerates the *public* surface
  only; intra-package private imports are implementation details).

- **T4 — `ask.py` imports two private helpers from sibling modules.**
  `_parse_frontmatter` from `publisher.py` is resolved by T3 (the import
  already points to the right module; no change needed there). `_strip_fence`
  from `llm.py` is used only to tolerate code-fenced LLM output; it is small
  enough to inline directly in `ask.py` as a module-local helper, severing
  the cross-module private dependency. After T3+T4, `ask.py` carries no
  underscore imports from sibling modules.

**3. Conditions (binding):**

- (a) **All 295+ passing tests must remain green** after every task. No
  existing test may be weakened or deleted to achieve a pass.
- (b) **No contract surface changes.** The §1.1 public import surface, the
  §5–§9 wire formats, and the exit-code table of §9.3 are frozen.
  `run()` added by T1 is not added to §1.1 (it is infrastructure, not API).
- (c) **T3 before T4.** `auditor.py` must import from `publisher.py` before
  `ask.py`'s `_parse_frontmatter` import is evaluated as resolved.
- (d) **T2 error messages must be single-line.** The CLI contract §9.3
  requires exactly one `error: {message}` line on stderr per failure; the
  `ZotWikiError` message raised by T2 must not contain embedded newlines.
