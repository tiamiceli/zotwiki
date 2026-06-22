# ZotWiki Operator — Run Log

A log of every `zotwiki` command I run, plus environment checks, with my assessment of success/failure. Newest at the bottom.

## Session 2026-06-16

### Environment checks (not zotwiki commands)

| When | Command | Result | Assessment |
|------|---------|--------|------------|
| 13:1x | `curl http://127.0.0.1:23119/api/users/0/collections` | HTTP 200, collections listed | ✅ Zotero reachable |
| 13:1x | `which claude` | `/Users/miceli/.local/bin/claude` | ✅ present |
| 13:1x | `which zotwiki` | `/Users/miceli/.local/bin/zotwiki` | ✅ installed |
| 13:1x | `curl .../collections/F6RG886C` (Test) | `numItems: 0` | ⚠️ **Test collection is EMPTY in Zotero** |
| 13:17 | `mkdir -p .../Library/Test` | folder created | ✅ vault folder ready |

### ZotWiki commands

_None run yet._ Blocked: the Zotero `Test` collection currently has 0 items, so `sync --collection Test` would compile nothing.

**Plan (user decision):** User will add papers to the Zotero `Test` collection in the app, then signal me. On their go-ahead I will run:

```
zotwiki sync --vault "/Users/miceli/Library/Mobile Documents/iCloud~md~obsidian/Documents/reserach_obsidian_vault/Library/Test" --collection Test
```

then `zotwiki audit --vault .../Test` to verify integrity. Logged here with success/fail when run.

### ZotWiki commands (cont.)

| When | Command | Result | Assessment |
|------|---------|--------|------------|
| 13:2x | (verify) `curl .../collections/F6RG886C/items/top` | 1 item: "From Data to Wisdom: Presidential Address to ISGSR" (Ackoff, citekey `ackoffDataWisdomPresidential1989`, key FET24BAZ) | ✅ paper present with citekey |
| 13:2x | `zotwiki sync --vault .../Test --collection Test` | exit 1 — `error: $: not a JSON object (Expecting value: line 1 column 1 (char 0))` | ❌ **failed** — LLM returned empty/non-JSON. |
| 13:2x | `zotwiki sync ...` (2nd attempt) | exit 1 — same empty-JSON error | ❌ **failed again** (reproducible, not a one-off hiccup) |

### Diagnosis of the empty-JSON failure

The error `$: not a JSON object (Expecting value: line 1 column 1 (char 0))` comes from `llm.py` parsing an **empty** string returned by `claude --print`. I reconstructed the exact compile prompt zotwiki builds (21,317 chars — well under limits) and fed it to `claude --print` by hand:

| When | Command | Result | Assessment |
|------|---------|--------|------------|
| 13:3x | rebuild exact prompt → `/tmp/zotwiki_prompt.txt` | 21,317-char prompt; paper has 27,246 chars fulltext (capped to 20k) | ✅ prompt is well-formed |
| 13:3x | `claude --print < prompt` (from /tmp) | exit 0, **17,337 bytes of valid JSON** | ✅ claude works on this prompt |
| 13:3x | `claude --print < prompt` (from repo cwd) | exit 0, **8,235 bytes of valid JSON** | ✅ claude works here too |

**First hypothesis (WRONG):** auth/rate-limit. Ruled out — `claude` answers fine.

**Actual root cause (confirmed):** I am driving `zotwiki` from *inside* a Claude Code session. `zotwiki` shells out to `claude --print`, and that nested `claude` **inherits this session's environment** — `CLAUDECODE=1`, `CLAUDE_CODE_*`, etc. With those set, `claude` sometimes treats the compile prompt as a chat message and replies with **prose** instead of JSON (e.g. *"This looks like ZotWiki's article-compiler prompt…"*). The first character is `T`, not `{`, so `json.loads` fails at "line 1 column 1 (char 0)". It's nondeterministic, which is why hand-tests intermittently passed.

Proof:

| Interpreter / env | `claude --print` output | Parses as JSON? |
|---|---|---|
| uv-tool py3.14, full session env | prose "This looks like ZotWiki's…" (1,477 B) | ❌ |
| uv-tool py3.14, **CLAUDE\*/ANTHROPIC\* stripped** | `{ "title": "From Data to Wisdom"… }` (12,913 B) | ✅ |

**Attempted fix (env-strip):**
- `env -u CLAUDECODE … zotwiki sync` → failed once (char-0 error).
- Crude first-char test, clean env, 4 runs: first chars `` ` ``, `T`, `` ` ``, `` ` `` — looked like "0/4", but this metric is MISLEADING (see correction).
- **Definitive test — clean env, run through zotwiki's REAL parser, 3 runs: 3/3 parsed OK** (`title='From Data to Wisdom'`). zotwiki's `_strip_fence` handles fenced JSON, so the `` ` ``-starting responses parse fine.

**Real conclusion (corrected):** The breakage is driven by the **full Claude Code session environment** (`CLAUDECODE` + dynamic system prompt) leaking into the nested `claude`, which then answers in *prose*. With the env stripped, the end-to-end pass rate is high (3/3 here; one real clean-env `sync` still failed once = residual nondeterminism, ~BUG-2). So: **nested + full env ≈ reliably broken; clean env ≈ reliably works.** Running from a **plain terminal outside Claude Code** (clean env by default) is the reliable operator path today.

➡️ **Full write-up for the Planner: see `zotwiki-bug-findings1.md`** (root cause, evidence table, `claude` CLI fix levers like `--json-schema` / `--output-format json` / `--exclude-dynamic-system-prompt-sections`, and open questions).

---
_Legend: ✅ success · ⚠️ warning/blocker · ❌ failure. Maintained by Claude Code (operator)._
