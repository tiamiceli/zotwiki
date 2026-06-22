# plan-bug2 — Structured-output LLM boundary (BUG-2)

**Status:** COMPLETE (2026-06-22). Authorized by **Ruling 9**; the tester red
gate (`tests/test_m6_llm_client.py`, REQ-039 revised + REQ-054/REQ-055) and the
coder implementation (`llm.py`/`ask.py`/`cli.py`) have both landed and the suite
is green (418 passed, 1 failed — the known macOS `test_req_019` only). The
blocking precondition
(§7.1 — does structured output work under the Claude Code OAuth login?) was
**resolved 2026-06-22**: validated against real `claude` v2.1.185 inside a Claude
Code session with **no `ANTHROPIC_API_KEY`** —
`claude --print --output-format json --json-schema <schema>
--exclude-dynamic-system-prompt-sections` (with `CLAUDECODE`/`CLAUDE_CODE_*`
stripped from the child env) returned `subtype: "success"` and a populated
`structured_output`. The TDD sequence is now: tester revises REQ-039 and adds
**REQ-054**/**REQ-055** against contract §5.6 (red gate), then the coder edits
`llm.py`/`ask.py`/`cli.py`. This file is the **planner's worksheet**; the binding
spec for the blind tester (contract.md + requirements.md) and coder (contract.md)
is Ruling 9 + contract §5.1/§5.6/§9.3/§9.4/§9.5 + REQ-039/054/055.

> **Numbering note.** This plan's draft referred to its authorizing ruling as
> "Ruling 7"; Rulings 7 and 8 were taken by the `zw` wrapper work, so the BUG-2
> ruling is **Ruling 9** (as Ruling 8 foretold). References to "Ruling 7" below
> mean Ruling 9.

> **Test-import invariant (resolved, Ruling 9 §7).** CLAUDE.md's
> "`ClaudeCodeLLMClient` is never imported by any test" means the *injected-fake*
> suite; the dedicated module `tests/test_m6_llm_client.py` already imports the
> client lazily and drives a **fake `claude` binary on PATH**. The REQ-039/054/055
> tests extend that module and seam — no real binary, no network. The CLAUDE.md
> bullet has been corrected to say this.

This file captures the design agreed with the project owner, the Claude Code CLI
documentation findings (fetched 2026-06-17), and the format-checker recommendation
requested for the tester.

**Relationship to prior work:** BUG-2 was opened in `plan-v1.2.md` ("LLM
sometimes produces invalid claim schema") and classified **mitigated (not fully
fixed)** via prompt refactors. The 2026-06-16 operator findings
(`docs/user-testing/zotwiki-bug-findings1.md`) found the dominant, reproducible
failure mode and its root cause. This plan is the full fix. It is **independent
of** the Operator-role cleanup (the "B" discussion); that role work removes the
nested-session *trigger*, while this plan fixes the *boundary* so zotwiki is
robust regardless of who runs it.

---

## 1. Problem (root cause verified against source)

`ClaudeCodeLLMClient.complete()` (`src/zotwiki/llm.py:37–53`) makes a **single**
`subprocess.run(["claude", "--print"], input=prompt…)` call with **no output
constraint, no retry, and no envelope** — it returns `result.stdout` verbatim to
the strict `parse_article_json`.

When zotwiki runs **nested inside a Claude Code session**, the child `claude`
inherits `CLAUDECODE=1`, `CLAUDE_CODE_*`, and the session's dynamic system
prompt, and frequently answers **conversationally** (prose). The first character
is not `{`, so `parse_article_json` fails at
`$: not a JSON object (Expecting value: line 1 column 1 (char 0))`. This is the
same class as BUG-2 (occasional schema/prose failures).

The operator's *code-level* claims were re-verified against `llm.py` and hold
(invocation shape, no retry, fence-only `_strip_fence`, the char-0 error). The
operator's *experimental* claims (clean-env "3/3", nested prose) are unverified
here and are treated as untrusted symptom reports — see §7.

**Constraint the owner set:** no tolerant/prose-extracting parser. The fix must
make the *source* emit clean JSON, not make the *parser* forgive prose.

---

## 2. Decision summary

1. **DECIDED — structured output at the source (`--json-schema`).**
   `ClaudeCodeLLMClient` invokes `claude --print --output-format json
   --json-schema <schema>`. On `subtype == "success"`, read the validated object
   from `structured_output` and hand it to the **unchanged, strict**
   `parse_article_json`. This is the opposite of a tolerant parser: the model is
   constrained to emit schema-shaped JSON. *(Only remaining precondition: §7.1 —
   structured output must work under the Claude Code subscription/OAuth login. If
   it requires an API key, this plan is **blocked** and we re-plan; **no** non-JSON
   fallback is built. The raw-output tension is **resolved** — see item 2.)*
2. **DECIDED — fail closed, log the structured failure report.** A single
   `claude` invocation, no zotwiki-level retry/fallback. The owner accepts the
   CLI's *structured* failure report in place of the raw prose, because **`result`
   is only present on `subtype: success`** — the raw model output is not in the
   envelope on failure, so no mechanism short of abandoning `--json-schema` could
   capture it. On any `subtype != "success"` (or non-zero exit / unparseable
   envelope), fail loud and record the failure report — see §3.
3. **`parse_article_json` stays the sole authoritative validator/canonicalizer.
   No new generic JSON format checker is added.** See §5.
4. **Environment hardening** (defense in depth, independent of the role fix):
   strip `CLAUDECODE` / `CLAUDE_CODE_*` from the subprocess environment, and
   pass `--exclude-dynamic-system-prompt-sections`, so a nested invocation does
   not inherit conversational context.

---

## 3. Fail-closed, dump-verbatim behavior

On any `subtype != "success"`, a malformed/non-JSON envelope, or a non-zero
`claude` exit, `complete()` raises (no retry) **and** records the failure report
for the user-testing notes:

- the result **`subtype`** (`error_max_turns`, `error_max_budget_usd`,
  `error_during_execution`, `error_max_structured_output_retries`)
- the **`errors`** field (loop-level error strings — present on
  `error_max_structured_output_retries`; distinguishes a schema-too-complex
  validation failure from a model-fallback retraction)
- **`stop_reason`** (always present; e.g. `refusal` vs `max_tokens` is a
  materially different failure and must be visible)
- the always-present metadata: `session_id`, `usage`, `num_turns`,
  `total_cost_usd`
- the exact **argv** (full invocation), the exact **prompt** sent on stdin, the
  full **stdout** bytes (the verbatim envelope), `claude`'s **stderr** and
  **exit code**

> Note: `result` (the raw text) is **only present on `success`**, so it cannot
> appear in a failure record — the structured fields above are the diagnostic.

**Contract wrinkle to resolve in the ruling:** §9.3 currently mandates *exactly
one* `error: {message}` line to stderr. A 20 K-char prompt + full response
cannot go in that line. **Recommended resolution:** write the verbatim exchange
to a timestamped artifact file (e.g. `~/.zotwiki/failures/<ISO-ts>.txt`, or a
`--dump-dir`), and make the one-line `error:` *point to the file path*. This
preserves the one-line-stderr invariant and gives the operator an exact
copy-paste artifact. (Alternative considered: multi-line stderr dump — rejected,
breaks the §9.3 invariant for every caller.)

---

## 4. Claude Code CLI documentation findings (fetched 2026-06-17)

From `code.claude.com/docs/en/cli-reference`, `/headless`, and
`/agent-sdk/structured-outputs`:

- **`--output-format json`** → envelope with the model's text in the **`result`**
  field, plus metadata (`session_id`, `total_cost_usd`, per-model cost). It does
  **not** constrain the output to JSON — `result` can still be prose. So this
  flag *alone* does not fix the bug; it only structures the wrapper.
- **`--json-schema '<schema>'`** (print mode only) → "Get validated JSON output
  matching a JSON Schema." The validated object lands in the **`structured_output`**
  field. The CLI **validates against the schema and re-prompts on mismatch**;
  if validation does not succeed within its retry limit, the result is an
  **error** instead of structured data.
- **Result `subtype`** (Agent SDK `ResultMessage`, serialized into the
  `--output-format json` envelope): `success`, `error_max_turns`,
  `error_max_budget_usd`, `error_during_execution`, `error_max_structured_output_retries`.
- **`result` is present only on `success`.** On any error subtype the raw text is
  absent — so a failure cannot carry the model's raw prose. The
  **`errors`** field (loop-level error strings, on
  `error_max_structured_output_retries`) distinguishes a validation failure from
  a model-fallback retraction.
- **Every result, including errors, carries** `stop_reason` (`end_turn`,
  `max_tokens`, `refusal`, …), `session_id`, `usage`, `num_turns`,
  `total_cost_usd`. The fail-loud record (§3) captures these.
- **`--bare`** skips hooks/skills/plugins/MCP/auto-memory/CLAUDE.md (would best
  neutralize nested context) **but requires `ANTHROPIC_API_KEY` or an
  apiKeyHelper** — it "skips OAuth and keychain reads." **Rejected:** it
  reintroduces the API-key requirement that Ruling 2 deliberately removed. We use
  env-stripping + `--exclude-dynamic-system-prompt-sections` instead, which keep
  the OAuth session.
- **Anthropic API** (the `anthropic` SDK / `output_config.format`) gives the same
  guarantee but reintroduces the API key, a paid account, and a dependency —
  contradicts Ruling 2 and the zero-runtime-deps invariant. **Rejected** unless
  the owner reopens Ruling 2.

> ✅ **Tension resolved (owner decision, 2026-06-17).** `--json-schema`
> re-prompts internally and, on exhaustion, returns
> `error_max_structured_output_retries` with **no `result` field** — the raw
> prose is gone. Rather than abandon the strong constraint to preserve raw prose,
> the owner chose `--json-schema` and accepts the CLI's *structured*
> failure report (`subtype` + `errors` + `stop_reason` + metadata, §3) as the
> diagnostic. The internal re-prompting is the CLI's, not a zotwiki retry;
> zotwiki still makes one invocation.

### 4a. No fallback mechanism is built

**There is exactly one mechanism: `--json-schema`, fail-closed.** §7.1 (does
structured output work on the subscription login?) is a **precondition gate, not
a fallback**: if validation shows it requires an API key, this plan is *blocked*
and the Planner re-plans (which would mean revisiting Ruling 2) — the Tester is
**never** directed to build or test a non-JSON path. We do not ship a degraded
"if JSON fails, do X" branch; "if JSON fails" means *fail closed and report*
(§3), full stop.

---

## 5. Format-checker recommendation (the question you asked)

**Do not add a separate "standard JSON format checker." Keep `parse_article_json`
as the single authority. It is not redundant with `--json-schema`; they are
different layers.**

The CLI's `--json-schema` validates against a *JSON Schema*, which **cannot**
express the rules `parse_article_json` enforces:

- **cross-field:** every quote `citekey` must be a member of its claim's
  `citekeys` (JSON Schema cannot reference a sibling array's values);
- **derived uniqueness:** section headings unique across sections;
- **content bans / normalization:** claim text must not contain `" [@"` or start
  with `-`/`>`; body lines must not start with `#` *after* NFKC + casefold +
  whitespace collapse;
- **canonicalization:** `parse_article_json` doesn't just validate, it *produces
  the canonical `Article`* (sorts citekeys/quotes/links, dedupes, normalizes) —
  a schema validator produces nothing;
- **mode rule:** `contradictions` only permitted when `existing is not None`
  (compiler-level).

So the two layers are complementary, not redundant:

- **`--json-schema` (upstream, best-effort, environment-dependent):** kills the
  prose failure at the source. It is a *decoding hint*, not the contract — kept
  deliberately minimal (top-level required keys + the claim/quote/section shape),
  in the spirit of Ruling 5 (the prompt's JSON example is an aid, not the gate).
- **`parse_article_json` (downstream, authoritative, hermetically tested):** the
  real contract. Unchanged. Still the gate that fails-loud on anything the schema
  let through.

Adding a *third* generic JSON validator inside zotwiki would be (a) redundant
with `parse_article_json`'s stricter checks, (b) a second source of truth that
can drift, and (c) incapable of canonicalizing. **For the tester:** there is
**one** new validation concern, and it is *not* an article-format checker — it is
**envelope handling** inside `ClaudeCodeLLMClient` (parse the wrapper, branch on
`subtype`, extract `structured_output`/`result`, fail-loud-dump otherwise).
Tests should cover that envelope handling and confirm `parse_article_json`
remains the unmodified downstream gate — **not** add a new schema-validator and
its tests.

---

## 6. Design — schema threading without touching the protocol

The `LLMClient` protocol stays `complete(self, prompt: str) -> str` (invariant;
all injected fakes unchanged). The schema differs per call site (compile/sync
want the article shape; `ask` wants the answer shape), so it is supplied at
**construction**, by the command handler that knows what it is producing:

- `ClaudeCodeLLMClient(output_schema: dict | None = None)`.
  - `None` → `--output-format json`, read `.result` (generic behavior).
  - set → add `--json-schema <schema>`, read `.structured_output`.
- `cli.py` §9.4 constructs per command: `compile`/`sync` → `ARTICLE_SCHEMA`
  (a new minimal constant in `llm.py`, next to `parse_article_json`); `ask` →
  `ANSWER_SCHEMA` (in `ask.py`). `cli.py` imports the constants.
- `complete()` returns a **string** as before: `json.dumps(structured_output)`
  (or `.result`), which `parse_article_json` / the ask validator then gate.

This keeps the seam, the fakes, and the hermetic suite untouched; only the
production client's internals and the `cli.py` construction sites change.

To minimize drift between `ARTICLE_SCHEMA` and `parse_article_json`, prefer
deriving/minimal (e.g. from the dataclass shape, echoing plan-v1.2 B1) over a
hand-maintained full re-encoding — but it need only be a loose shape hint.

---

## 7. Open validation items — BLOCKING the ruling

These are empirical and **cannot** be settled by documentation or by the
hermetic suite (the failure was an environment × invocation interaction). They
are exactly the new Operator's job: run real `claude`, report verbatim. Resolve
before Ruling 7 is finalized.

**Validation conditions (the conditions *are* the test).** The bug only appears
nested. So validation must run **inside a Claude Code session**, with the
working directory set to the research-vault project — which, under the B3 design,
now contains an operator `CLAUDE.md`. Without `--bare`, `claude -p` "loads the
same context an interactive session would, including the working directory's
CLAUDE.md," so the check must confirm that env-stripping +
`--exclude-dynamic-system-prompt-sections` actually suppress *that project
CLAUDE.md* and the session's dynamic prompt. A clean-terminal run won't
reproduce the failure and proves nothing.

1. **[RESOLVED 2026-06-22] Does `--json-schema` / structured output work under
   the Claude Code *subscription* (OAuth) login, with no `ANTHROPIC_API_KEY`?**
   **Yes.** Observed on real `claude` v2.1.185 inside a Claude Code session
   (`CLAUDECODE=1`, `CLAUDE_CODE_*` set, no `ANTHROPIC_API_KEY`): the env-stripped
   invocation exited 0 with `subtype: "success"`, `is_error: false`,
   `structured_output: {"answer":"Paris"}`, and full metadata. The plan is
   unblocked; Ruling 9 is binding. *(Not proven, and deliberately punted to
   fail-loud operator runs: determinism on a real 20K `ARTICLE_SCHEMA` compile,
   and the exact `error_max_structured_output_retries` failure envelope — both
   doc-settled.)*
2. **Confirm the CLI envelope mirrors the Agent SDK `ResultMessage`.** The SDK
   docs (and the owner-supplied error-return reference) pin the shape: `result`
   only on `success`; `structured_output` on success with `--json-schema`;
   `subtype` ∈ the five values; `errors` on `error_max_structured_output_retries`;
   `stop_reason`/`session_id`/`usage`/`num_turns`/`total_cost_usd` always. This is
   **answered by documentation** — the only confirmation needed is that `claude
   --print --output-format json` serializes these same fields at top level (a
   one-time `jq` inspection of a real success *and* a forced failure), so the
   coder keys on real field names.
3. **Confirm one zotwiki invocation = one `claude` process** — the CLI's internal
   re-prompting is the CLI's, not a zotwiki retry. (Settled in principle; confirm
   on the real binary.)

> Documentation settled the envelope *shape and semantics* (§4); it cannot
> certify *determinism in this environment*. A CI integration test can't either
> (one green run ≠ deterministic, and it breaks hermeticity). The determinism
> evidence accrues for free from the fail-loud Operator runs (§3).

---

## 8. Contract surfaces to change (for Ruling 7 + contract.md)

- **§5.1** — revise `ClaudeCodeLLMClient` description (structured-output
  invocation; per-command `output_schema`).
- **new §5.6** — the structured-output invocation: flags, envelope handling
  (`subtype`/`structured_output`/`result`), env-stripping, fail-loud-dump
  artifact, and the rule that `parse_article_json` remains authoritative.
- **§9.3 / §9.4** — the failure-artifact pointer line; per-command construction
  with the right schema.
- **requirements.md** — **revise REQ-039** (it asserted `complete()` returns raw
  stdout; under structured output it returns the extracted field —
  `structured_output` with a schema, `result` without) and add **REQ-054**
  (subprocess env sanitization — no `CLAUDECODE`/`CLAUDE_CODE_*`) and **REQ-055**
  (fail-loud-dump artifact on any non-`success` subtype / non-zero exit /
  malformed-or-missing field, recording `subtype` + `errors` + `stop_reason` +
  metadata; single-line message pointing to the artifact). **No fallback-path
  REQ** — there is one mechanism (§4a). `ARTICLE_SCHEMA`/`ANSWER_SCHEMA` are loose
  hints; **REQ-010/011 (parse_article_json authority) are unchanged.**

---

## 9. Test strategy (for the tester)

- **Hermetic, via the fake-`claude`-binary seam** — extend the
  `test_m6_llm_client.py` pattern: `ClaudeCodeLLMClient` is lazily imported in an
  autouse fixture and driven through a fake `claude` script on a `tmp_path` `PATH`
  (no real `claude`, no network). The fake script emits a **JSON envelope** and
  tests assert `complete()`:
  - on `subtype: success` → returns the `structured_output` object (serialized);
  - on each error subtype (`error_max_turns`, `error_max_budget_usd`,
    `error_during_execution`, `error_max_structured_output_retries`) → fails loud
    and the record carries `subtype`, `errors` (when present), `stop_reason`, and
    the metadata (§3);
  - **never reads `result` on a non-`success` subtype** (it is absent there);
  - on a malformed/non-JSON envelope or non-zero exit → fails loud + dumps.
- **The injected-fake-LLM suite is untouched** — `Compiler`/CLI tests still inject
  string-returning fakes through the seam; they never construct the real client.
  Existing compiler/CLI green stays green.
- **No real-`claude` integration test.** Empirical determinism is validated by the
  Operator via the fail-loud artifacts (§3, §7). Keep integration tests at zero.
- **No new generic-JSON-validator tests** — see §5. The new tests are
  envelope-handling + fail-loud-dump only; `parse_article_json` tests are unchanged.

---

## 10. Files expected to change (coder)

- `src/zotwiki/llm.py` — `ClaudeCodeLLMClient` (structured-output invocation,
  `output_schema`, envelope handling, env-stripping, fail-loud-dump);
  `ARTICLE_SCHEMA` constant. `parse_article_json` **unchanged**.
- `src/zotwiki/ask.py` — `ANSWER_SCHEMA` constant.
- `src/zotwiki/cli.py` — per-command construction with the right schema; the
  failure-artifact `error:` line.
- No new runtime dependency (stdlib `subprocess`/`json`/`os`). Injection seam and
  `LLMClient` protocol unchanged.

---

## 11. Sequencing

Per the owner's preference, the **Operator-role cleanup (B)** landed first (the
`zw` wrapper, Rulings 7 & 8 — it protects every future bug report). The §7.1
validation is **resolved** (above) and **Ruling 9 is written and binding**;
contract.md (§5.1/§5.6/§9.3/§9.4/§9.5) and requirements.md (REQ-039 revised +
REQ-054/REQ-055) are updated. **Done:** the tester red gate
(`tests/test_m6_llm_client.py`, extending the fake-`claude`-binary seam) and the
coder (`llm.py`/`ask.py`/`cli.py`) both landed in fresh sessions reading only the
binding docs (tester: contract.md + requirements.md; coder: contract.md). The
suite is green (418 passed, 1 failed — the known macOS `test_req_019` only).
