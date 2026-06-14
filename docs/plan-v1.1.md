# ZotWiki — Plan v1.1 (Post-M6)

Authorized by docs/rulings.md Ruling 2 (2026-06-14). Addresses post-M6 gaps
identified by planner review: the Anthropic API backend is replaced with a
Claude Code backend (Phase A), followed by infrastructure and refactor cleanup
(Phase B). Tester and coder discipline from plan.md applies throughout: in
Phase A the tester writes tests before the coder writes code; in Phase B the
existing test suite is the gate and no new tests are written.

Cross-milestone done-gate: all tests passing at the start of Phase A must
still pass at the end of Phase B. The only tests that may be modified are
those covering REQ-038 error behavior.

---

## Phase A — Replace LLM backend (TDD)

**Scope:** `src/zotwiki/llm.py`, `src/zotwiki/cli.py`, and the test covering
REQ-038 error behavior. New test file `tests/test_m6_llm_client.py` for
REQ-039.

**REQs:** REQ-038 (revised error behavior), REQ-039 (new).

### Tester work (before coder starts)

The tester owns REQ-038 and REQ-039 per contract §1 (blind from
implementation). Before the coder changes any production code:

1. **Revise the REQ-038 error-behavior test** in the existing CLI injection
   test file. The error condition changes from "missing `ANTHROPIC_API_KEY` /
   `ZOTWIKI_MODEL`" to "`claude` not on PATH". The test must confirm
   `main(["compile", ...])` without an injected `llm` and with `claude`
   absent from PATH returns 2 and prints `error: claude not found` to stderr.

2. **Write `tests/test_m6_llm_client.py`** covering REQ-039. The fake
   `claude` binary is a tiny executable script placed in a `tmp_path`
   directory prepended to `PATH` for the duration of the test. It reads
   stdin and prints a canned response to stdout. Tests must cover:
   - Successful call: prompt arrives on stdin, stdout is returned as-is.
   - Non-zero exit code from `claude`: `ZotWikiError` is raised, message
     includes the exit code.
   - `claude` not on PATH: `ZotWikiError` is raised with message
     `"claude not found"`.

   The fake binary must be hermetic: it runs on `127.0.0.1` only and makes
   no real network calls.

**Done when:** both revised and new tests fail (red) because the production
code has not yet changed. This is the mandatory red gate before coder starts.

### Coder work (after tester's red gate)

From `src/zotwiki/llm.py` and `src/zotwiki/cli.py` only, working from
contract §5.1 and §9.4:

1. **Delete `AnthropicLLMClient`** and all `ANTHROPIC_*` constants from
   `llm.py`. Remove `urllib.request` imports that are no longer used.

2. **Add `ClaudeCodeLLMClient`** to `llm.py`. It implements `LLMClient`.
   Uses only stdlib (`subprocess`, `shutil`). Passes the prompt via stdin
   to `claude -p -` and returns stdout as a string. Raises `ZotWikiError`
   on non-zero exit or if `claude` is not on PATH. Error messages must be
   single-line.

3. **Update `cli.py` §9.4 logic**: replace the `ANTHROPIC_API_KEY` /
   `ZOTWIKI_MODEL` env-var check with a PATH check for `claude`. Construct
   `ClaudeCodeLLMClient()` when no `llm` is injected and the command needs
   one.

4. **Update `__all__` in `llm.py`**: remove `AnthropicLLMClient`, add
   `ClaudeCodeLLMClient`.

**Done when:** all previously passing tests still pass and the new REQ-039
tests pass (green).

---

## Phase B — Infrastructure and refactors

No new REQs. No new tests. Existing passing tests are the sole gate after
each task. Tasks are ordered; complete each fully before starting the next.

### B-T1 — Add `pyproject.toml` and installable entry point

**Scope:** new `pyproject.toml` at repo root; `src/zotwiki/cli.py`.

**Why:** no `pyproject.toml` means `pip install .` fails and `zotwiki` is not
available on PATH. Users must prefix every invocation with `PYTHONPATH=src`.

Add a `run()` function to `cli.py` (not in `__all__`) that calls
`sys.exit(main())`. This is the entry point target; it keeps `main()`'s
contract (returns int, never calls `sys.exit`) intact.

Create `pyproject.toml` at the repo root declaring the package, Python ≥ 3.12,
zero runtime dependencies, and `zotwiki = "zotwiki.cli:run"` as the console
script entry point. Use `setuptools` as the build backend with `where = ["src"]`
package discovery.

**Done when:** `pip install -e .` succeeds, `zotwiki --help` runs from PATH,
all existing tests still pass.

### B-T3 — Deduplicate `_parse_frontmatter`

**Scope:** `src/zotwiki/auditor.py` only.

**Why:** `auditor.py` contains a near-identical copy of `_parse_frontmatter`
from `publisher.py`. The publisher's version is canonical (returns
`tuple[dict, int]`); the auditor's copy (returns `dict`) diverges and must
be kept in sync by hand.

Delete the local `_parse_frontmatter` (and its helper `_parse_quoted_scalar`
if not used elsewhere in `auditor.py`) from `auditor.py`. Import
`_parse_frontmatter` from `zotwiki.publisher`. Update every call site in
`auditor.py` to unpack the tuple and discard the line index.

**Done when:** `auditor.py` contains no local definition of
`_parse_frontmatter` and all existing tests still pass.

### B-T4 — Remove `ask.py` cross-module private imports

**Scope:** `src/zotwiki/ask.py` only. **Must follow B-T3.**

**Why:** `ask.py` imports `_strip_fence` from `zotwiki.llm` — a private
helper not in the public surface of §1.1. After B-T3, the `_parse_frontmatter`
import already points to the correct module; the remaining issue is
`_strip_fence`.

Copy the `_strip_fence` logic into `ask.py` as a module-local function
(identical behavior, no import from `llm`). Remove the `from zotwiki.llm
import _strip_fence` line.

After this task, `ask.py` must contain no `from zotwiki.<module> import _*`
lines.

**Done when:** all existing tests still pass and `ask.py` carries no
underscore imports from sibling modules.
