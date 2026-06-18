# plan-zw — `zw` operator terminal wrapper

**Status:** authorized (Ruling 7, 2026-06-18). Planner → tester → coder.

## Why

The operator drives zotwiki by hand from a plain terminal. Every command repeats
a long `--vault "<path>"` (and `sync` repeats `--collection NAME`). `scripts/zw`
gives short directives that inject `$ZOTWIKI_VAULT` and forward the rest to the
installed `zotwiki` console script. It composes the public CLI (§9) — no new
zotwiki behavior, no dependency, no §1–§10 change. Running from a plain terminal
also avoids the nested-session BUG-2 corruption (`docs/user-testing/
zotwiki-bug-findings.md`), so no env-stripping is needed.

## Spec

Binding spec is **contract §11**; behaviors are **REQ-049–052**.

Directives: `zw sync NAME [...]`, `zw ask Q...`, `zw compile [...]`,
`zw audit [...]`, `zw ingest [...]`, `zw` / `zw help`. `claude` is reached only
via `sync`/`ask`/`compile` (unchanged from §9.4).

## Phases

1. **Planner (done):** Ruling 7, contract §11, REQ-049–052, this plan.
2. **Tester:** `tests/test_zw_directives.py` — hermetic, fake `zotwiki` shim on
   `PATH` echoing argv + controllable exit code. Cover REQ-049–052. Commit red.
3. **Coder:** `scripts/zw` (`chmod +x`); reads only contract §11. Full suite green
   (4 new pass; baseline 387 passed + 1 known `test_req_019` failure unchanged).
   Add README "Operating from the terminal (`zw` directives)" section.
4. **Notes:** update `CLAUDE.md` status + `docs/document-library.md`; mark this
   plan complete.

## Done-gate

`tests/test_zw_directives.py` green; baseline unchanged; `bash -n scripts/zw`
clean; README documents `ZOTWIKI_VAULT` + install + directive table.

## Files

- `docs/rulings.md`, `docs/contract.md`, `docs/requirements.md`, `docs/plan-zw.md` (planner)
- `tests/test_zw_directives.py` (tester)
- `scripts/zw`, `README.md` (coder)
- `CLAUDE.md`, `docs/document-library.md` (notes)
