# ZotWiki — Operator/Tester Findings for the Planner

**Date:** 2026-06-19 
**Update:** The operator now runs zotwiki from a **plain terminal** via `scripts/zw` (Ruling 8), so the nested-Claude-Code failure documented below no longer occurs in normal use. It was **avoided by workflow, not fixed in code** — `zw` adds no env-stripping; a nested invocation would still corrupt output. **BUG-2's LLM-boundary hardening (`docs/plan-bug2.md`, `--json-schema`) remains open/unimplemented.** 
Separately, `zw sync` now *succeeds* and produces a wiki, but the generated pages show **content peculiarities** (a different class of problem from the char-0 JSON failure below) — those are logged as their own findings entry, not here.

**Date:** 2026-06-16
**Role:** Operating zotwiki as a tool (driving it, not developing it) from *inside* a Claude Code session.
**Goal at the time:** Populate the `Test` wiki by syncing the Zotero `Test` collection (1 paper: Ackoff, *From Data to Wisdom*, citekey `ackoffDataWisdomPresidential1989`, key `FET24BAZ`).
**Status:** Wiki **NOT** populated — blocked by the bug below. This is a summary to debug *with the Planner*, not a fix.

---

## TL;DR

`zotwiki sync` (and any claude-shelling command: `sync`, `compile`, `ask`) **fails reliably** with:

```
error: $: not a JSON object (Expecting value: line 1 column 1 (char 0))
```

The compile prompt is fine. The Zotero data is fine. `claude` is logged in and responding. The failure is that, when run **nested inside a Claude Code session**, `claude --print` inherits `CLAUDECODE=1` + the session's dynamic system prompt and frequently answers **conversationally** (prose), which zotwiki's strict JSON parser rejects at char 0. **Stripping the Claude Code env vars largely fixes it** (see corrected evidence below: 3/3 parsed end-to-end with a clean env), but one real `env -u … zotwiki sync` still failed once — so it's a strong mitigation, not a proven-deterministic fix. This is almost certainly the same underlying issue as the known, still-open **BUG-2** ("occasional LLM schema errors").

> **Correction note (kept for honesty):** an intermediate metric in our notes said "0/4 bare JSON," based on a crude *first-character* check. That was misleading — zotwiki's `_strip_fence` correctly handles ```` ``` ````-fenced JSON, so fence-wrapped responses parse fine. Run through zotwiki's **actual parser**, clean-env output parsed **3/3**. Trust the end-to-end number, not the first-char one.

---

## Reproduction

1. Zotero open; `Test` collection has exactly one item with a citekey.
2. `zotwiki sync --vault ".../Library/Test" --collection Test`
3. → exit 1, `error: $: not a JSON object (Expecting value: line 1 column 1 (char 0))`. Reproduced **4×** in a row.

## What is NOT the cause (ruled out by experiment)

- **Bad/oversized prompt.** Reconstructed the exact prompt zotwiki builds: 21,317 chars, within the 20k fulltext cap. Well-formed.
- **Zotero / citekey / collection.** Item resolves, has citekey, is in the collection.
- **`claude` down / auth / rate-limit.** `claude` returns valid content when called by hand. (Initial wrong guess; ruled out.)
- **Installed binary ≠ source.** Installed `zotwiki` (uv tool, Python 3.14) `llm.py` is byte-identical to `src/`. Invocation is `subprocess.run(["claude","--print"], input=prompt, capture_output=True)`.

## Root cause (confirmed by experiment)

zotwiki shells out to `claude --print`. When that subprocess runs **inside a Claude Code session**, the child `claude` inherits `CLAUDECODE=1`, `CLAUDE_CODE_*`, and the session's *dynamic system prompt*. In that context `claude` frequently treats the compile prompt as a chat turn and answers **conversationally** — prose, or JSON wrapped in a ```` ``` ```` fence followed by trailing commentary. zotwiki's parser (`llm.py: parse_article_json` → `json.loads(_strip_fence(text))`) requires either a bare JSON object or a response that *both starts and ends* with a code fence. Anything else fails at "line 1 column 1 (char 0)" because the first character isn't `{`.

### Evidence

| Experiment | Result | Parses for zotwiki? |
|---|---|---|
| `claude --print < prompt`, by hand (system python, full env) | valid JSON object | ✅ (intermittently) |
| `subprocess.run([...], full session env)`, uv python | prose: *"This looks like ZotWiki's article-compiler prompt…"* (1,477 B) | ❌ |
| `subprocess.run([...], env with CLAUDE*/ANTHROPIC*/AI_AGENT stripped)`, 1 sample | bare JSON `{ "title":… }` (12,913 B) | ✅ |
| `env -u CLAUDECODE … zotwiki sync` (real command, stripped env) | char-0 error | ❌ (1 observed failure) |
| clean-env, 4 runs, **first-char check** (crude) | first chars `` ` ``, `T`, `` ` ``, `` ` `` | ⚠️ misleading metric — see below |
| **clean-env, 3 runs, through zotwiki's REAL parser** | all 3 returned a valid Article (`title='From Data to Wisdom'`) | ✅ **3/3 parsed** |

**Key takeaway (corrected):** With a clean environment, the end-to-end pass rate is high — **3/3** through zotwiki's own parser. The crude "first-char" check (0/4 starting with `{`) was *misleading*: 3 of those started with a code fence `` ` ``, and `_strip_fence` handles fenced JSON, so they parse. The genuine failure mode is the **full-session-env** case, where `claude` returns *prose* (first char `T`, no fence). The one clean-env `zotwiki sync` failure we saw is residual nondeterminism (claude occasionally still emits prose, ~BUG-2), not a reason to dismiss env-stripping. **Net: full session env ≈ reliably broken; clean env ≈ reliably works, with rare residual failures.**

### The relevant fragility in the parser

`llm.py: _strip_fence` strips a fence only when the text starts **and** ends with ```` ``` ````. It does **not** extract a JSON object embedded in surrounding prose. So a response like ```` ```json\n{...}\n```\n\nHere's a summary… ```` fails, even though a valid JSON object is right there.

### No resilience in the LLM boundary

`ClaudeCodeLLMClient.complete` makes **one** `claude` call with **no retry**, **no `--output-format`/`--json-schema` enforcement**, and **no JSON-extraction fallback**. One non-conforming response fails the whole `sync` run (and in a multi-item collection, would abort the entire batch).

---

## Concrete fix levers (for the Planner — not done here)

The `claude` CLI (v2.1.178) exposes flags that directly target this:

- `--output-format json` — returns a structured JSON envelope (only with `--print`).
- `--json-schema <schema>` — **forces** structured output to a JSON Schema (only with `--print`). zotwiki already has the article schema in `llm.py`; could be emitted as a schema.
- `--system-prompt <p>` / `--append-system-prompt <p>` — override/augment the default system prompt that's making nested calls conversational.
- `--exclude-dynamic-system-prompt-sections` — drop the session's dynamic system prompt (likely the thing flipping claude into chat mode when nested).
- `--fallback-model <model>` — resilience.

Candidate directions to discuss:
1. **Force structured output** at the LLM boundary (`--output-format json` and/or `--json-schema`). Likely the cleanest, deterministic fix.
2. **Robust JSON extraction** in the parser: pull the first balanced `{…}` object out of a prose-wrapped response before `json.loads`. Directly addresses the observed failure mode.
3. **Retry loop** (N attempts) on `ArticleSchemaError` / empty output in `ClaudeCodeLLMClient`.
4. **Neutralize nested-session context** when shelling out (clean env + `--exclude-dynamic-system-prompt-sections` or an explicit `--system-prompt`).

Any of these needs a ruling → contract change → REQ → red gate, per the dev process. This relates to/likely subsumes **BUG-2**.

---

## Operator workaround available today

Because the corruption is driven by the nested Claude Code context, **running the sync from a plain terminal (outside Claude Code) is expected to be far more reliable.** Suggested for the user to run directly:

```bash
zotwiki sync --vault "/Users/miceli/Library/Mobile Documents/iCloud~md~obsidian/Documents/reserach_obsidian_vault/Library/Test" --collection Test
```

(Even standalone, BUG-2 means an occasional retry may be needed — but it won't be the near-100% failure we see nested.)

---

## Open questions for the Planner

1. Is the *correct* behavior to force structured output (`--json-schema`/`--output-format json`), or to make the parser tolerant of prose-wrapped JSON, or both?
2. Should `ClaudeCodeLLMClient` retry on schema error, and how many times, with what backoff? (Contract currently specifies a single call.)
3. Should zotwiki detect and neutralize a nested Claude Code environment (it's a real operator scenario: Claude Code is the operator)?
4. In a multi-item `sync`, should one item's schema failure abort the whole run (current) or be reported per-item and skipped?
