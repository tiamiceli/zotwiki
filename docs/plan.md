# ZotWiki — Plan

Milestones are strictly ordered; each builds only on contract surfaces frozen
in earlier milestones. Tester and coder work blind from
`docs/requirements.md` + `docs/contract.md`; the tester's fake Zotero server
implements contract §4, the fake LLM implements contract §5.1. Every
milestone's tests run hermetically (`127.0.0.1` fixtures, `tmp_path` vaults,
injected fakes).

Cross-milestone done-gate: all tests of the current and all previous
milestones pass via `pytest` from the repo root using the pinned
`pytest.ini` (`pythonpath = src`), with no network beyond `127.0.0.1`.

---

## M1 — Zotero adapter

**Scope:** repo skeleton (`pytest.ini` byte-exact per contract §1,
`src/zotwiki/` package, `errors.py`, `models.py` incl. `normalize_text`,
`zotero.py` with `ZoteroStore` protocol + `HTTPZoteroStore`).
Tester side: fake Zotero HTTP server fixture implementing contract §4.

**REQs:** REQ-001 … REQ-009.

**Done when:** `HTTPZoteroStore` pointed at the fake server passes
REQ-001–009 — including the recorded retry/backoff schedule of REQ-008 and
the fulltext-probe semantics of REQ-009 — with zero third-party runtime
imports.

## M2 — Article schema + compiler with fake LLM

**Scope:** `llm.py` (`LLMClient` protocol, `parse_article_json`,
`article_to_json_dict`), `compiler.py` (`Compiler`, `CompileResult`,
`merge_articles`, `FULLTEXT_PROMPT_LIMIT`). No vault I/O yet.

**REQs:** REQ-010 … REQ-016.

**Done when:** every invalid-input class of REQ-011 raises
`ArticleSchemaError` (nothing invalid passes through), the
`article_to_json_dict` round-trip law of contract §5.5 holds, and
`merge_articles` satisfies the never-clobber matrix of REQ-016.

## M3 — Vault publisher

**Scope:** `publisher.py` (`render_page`, `parse_page`, `VaultPublisher`
create-path, References resolution, frontmatter subset, constants). Index
regeneration is wired in here mechanically but its acceptance lives in M5.

**REQs:** REQ-017, REQ-018, REQ-019, REQ-021.

**Done when:** rendering is byte-deterministic against the canonical fixtures
of contract §6, `parse_page(render_page(a, …)) == a` holds property-style
over the test corpus, and double-publish leaves the vault byte-identical
(REQ-019), including the case-collision `VaultError`.

## M4 — Auditor

**Scope:** `auditor.py` (`Auditor`, `AuditReport`, `Violation`,
`AUDIT_CODES`), all seven checks of contract §8 over vaults built with M3
and hand-corrupted by tests.

**REQs:** REQ-023 … REQ-030.

**Done when:** a publisher-built clean vault audits `ok` (REQ-023); each of
the seven codes is triggered by exactly its corruption and nothing else;
reports are order-deterministic; missing vault → `VaultError` and dead
Zotero → `ZoteroUnavailableError` (REQ-030).

## M5 — Incremental maintenance + index

**Scope:** `VaultPublisher` update path (mechanical merge with on-disk page,
`created` preservation, change-gated `updated`), `Index.md` maintenance,
`publish_contradictions` / `Contradictions.md`, compiler update-mode wiring
end to end (compile with `existing` → publish → audit still clean).

**REQs:** REQ-020, REQ-022, REQ-031 (+ re-runs REQ-014/016 in integration).

**Done when:** an update publish merges without clobbering and is idempotent
on re-publish; `Index.md` always lists exactly the entity pages, sorted;
contradictions land append-only on `Contradictions.md` while the entity page
stays byte-identical (REQ-031); the post-update vault passes a full audit.

## M6 — CLI end-to-end

**Scope:** `ask.py`, `cli.py` (`main` with injection seam, four subcommands,
exit-code mapping, stdout/stderr formats), `__main__.py`.

**REQs:** REQ-032 … REQ-038.

**Done when:** the full loop runs in-process against fakes —
`ingest` → `compile --today` → `audit` (exit 0) → corrupt vault →
`audit` (exit 1) → `ask` with cited sources — with the exact stdout lines of
contract §9.2, the exit-code table of REQ-037 verified per exception class,
and REQ-038's no-network guarantee when fakes are injected.

---

## REQ → milestone map (complete, 38 REQs)

| Milestone | REQs |
|---|---|
| M1 | 001 002 003 004 005 006 007 008 009 |
| M2 | 010 011 012 013 014 015 016 |
| M3 | 017 018 019 021 |
| M4 | 023 024 025 026 027 028 029 030 |
| M5 | 020 022 031 |
| M6 | 032 033 034 035 036 037 038 |
