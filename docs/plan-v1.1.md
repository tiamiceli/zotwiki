# ZotWiki — Plan v1.1 (Post-M6 Fix Phase)

Authorized by docs/rulings.md Ruling 2 (2026-06-13). These four tasks address
implementation gaps identified by a post-M6 README audit. They are strictly
ordered (T3 before T4; otherwise independent) and touch only production code
— no test files are modified. All 295+ M1–M6 tests must remain green after
every task.

---

## T1 — Add `pyproject.toml` and installable entry point

**Scope:** new `pyproject.toml` at repo root; one new function in
`src/zotwiki/cli.py`.

**Why:** the package cannot be installed with `pip install .` and the `zotwiki`
command is not on PATH. Every invocation requires `PYTHONPATH=src python -m
zotwiki`.

**What to do:**

1. Add `run()` to `src/zotwiki/cli.py` immediately after `main()`:

   ```python
   def run() -> None:
       import sys
       sys.exit(main())
   ```

   `run` is infrastructure only; it must not appear in `__all__`.

2. Create `pyproject.toml` in the repo root (beside `pytest.ini`):

   ```toml
   [build-system]
   requires = ["setuptools>=68"]
   build-backend = "setuptools.backends.legacy:build"

   [project]
   name = "zotwiki"
   version = "0.1.0"
   requires-python = ">=3.12"
   dependencies = []

   [project.scripts]
   zotwiki = "zotwiki.cli:run"

   [tool.setuptools.packages.find]
   where = ["src"]
   ```

**Done when:** `pip install -e .` succeeds, `zotwiki --help` prints usage
from PATH, and all pre-existing tests still pass.

---

## T2 — Wrap `AnthropicLLMClient.complete()` in HTTP error handling

**Scope:** `src/zotwiki/llm.py`, the `complete` method only.

**Why:** `urllib.request.urlopen` raises `urllib.error.HTTPError`,
`urllib.error.URLError`, or `OSError` on API failures. These bypass the CLI's
`error: ...` formatter and produce raw Python tracebacks.

**What to do:**

Replace the bare `urlopen` call in `AnthropicLLMClient.complete` with a
try/except that converts every network and HTTP failure into `ZotWikiError`.
Exact pattern:

```python
import urllib.error

try:
    with urllib.request.urlopen(request) as response:
        payload = json.loads(response.read().decode("utf-8"))
except urllib.error.HTTPError as exc:
    raise ZotWikiError(
        f"Anthropic API error: HTTP {exc.code} {exc.reason}"
    ) from None
except (urllib.error.URLError, OSError) as exc:
    raise ZotWikiError(
        f"Anthropic API unreachable: {exc}"
    ) from None
```

`ZotWikiError` is already imported in `llm.py` via `zotwiki.errors`.

Constraints:
- The error message must be single-line (Ruling 2 condition d).
- Do not catch `ValueError` from `json.loads` — a malformed response body is
  a different failure and should surface as-is (it will be caught by the CLI's
  general exception handler as an unexpected error, which is acceptable).
- `urllib.error` is already used elsewhere in the codebase; no new import of
  a third-party package is introduced.

**Done when:** all pre-existing tests still pass. (No new tests are required;
`AnthropicLLMClient` is never imported by the hermetic suite, per Ruling 2.)

---

## T3 — Deduplicate `_parse_frontmatter` (auditor imports from publisher)

**Scope:** `src/zotwiki/auditor.py` only.

**Why:** `auditor.py` contains a near-identical copy of `_parse_frontmatter`
that diverges from the canonical version in `publisher.py`. Two copies must be
kept in sync by hand.

**Decision (Ruling 2 §2-T3):** the publisher's version is canonical. It
returns `tuple[dict, int]` where the int is the line index immediately after
the closing `---`. Auditor callers that need only the dict ignore `_`.

**What to do:**

1. Delete the local `_parse_frontmatter` function from `auditor.py` (the
   function body beginning at the line `def _parse_frontmatter(lines: list[str]) -> dict:`
   and its helper `_parse_quoted_scalar`).

2. Add an import at the top of `auditor.py`:

   ```python
   from zotwiki.publisher import _parse_frontmatter, _parse_quoted_scalar
   ```

   Or, if `_parse_quoted_scalar` is not called directly by `auditor.py`
   outside of `_parse_frontmatter`, import only `_parse_frontmatter`.

3. Update every call site in `auditor.py` from `_parse_frontmatter(lines)`
   (which returned `dict`) to `_parse_frontmatter(lines)[0]` (to discard the
   line index). There are three call sites: in `_audit_index`,
   `_audit_contradictions`, and `audit` itself.

**Done when:** all pre-existing tests still pass and `auditor.py` contains no
local definition of `_parse_frontmatter`.

---

## T4 — Remove `ask.py`'s cross-module private imports

**Scope:** `src/zotwiki/ask.py` only.

**Must follow T3.**

**Why:** `ask.py` imports two underscore-prefixed helpers from sibling modules,
coupling it to private implementation details. After T3, one of those imports
(`_parse_frontmatter` from `publisher.py`) is already in the right place; the
remaining issue is `_strip_fence` from `llm.py`.

**What to do:**

1. Remove the import of `_strip_fence` from `zotwiki.llm` in `ask.py`.

2. Inline the logic as a module-local function at the top of `ask.py`:

   ```python
   def _strip_fence(text: str) -> str:
       stripped = text.strip()
       if stripped.startswith("```") and stripped.endswith("```"):
           lines = stripped.split("\n")
           stripped = "\n".join(lines[1:-1])
       return stripped
   ```

   This is a verbatim copy of the function from `llm.py`; no behavior change.

3. The `_parse_frontmatter` import in `ask.py` already points to
   `zotwiki.publisher` — verify it remains correct after T3. No change needed
   to that import line.

4. After T3+T4, `ask.py` must contain no `from zotwiki.llm import _*` or
   `from zotwiki.publisher import _*` lines that refer to names not also
   exported in `__all__` of those modules.

**Done when:** all pre-existing tests still pass and `ask.py` carries no
underscore imports from sibling modules.

---

## Done-gate (all tasks)

`pytest` from the repo root must exit 0 with the same number of collected
tests as before T1. No test may be added, removed, or modified as part of
this fix phase.
