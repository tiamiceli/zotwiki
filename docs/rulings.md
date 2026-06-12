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
