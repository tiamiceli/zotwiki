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

## Ruling 4 — fulltext probe must fall through to child attachment items

**Date:** 2026-06-14 · **Scope:** `zotero.py` §4.5 probe, plan-v1.2.md · **Status:** binding.

**1. Disposition: `_probe_fulltext` and `fulltext` are extended to check child
attachment items when the parent item returns 404.**

In Zotero 7, fulltext is indexed on child attachment items (PDFs stored as
`imported_file` attachments), not on the parent bibliographic record. The
current contract (§4.5) and implementation probe only
`GET /items/{KEY}/fulltext` on the parent key. This causes every item with an
attached PDF to have `has_fulltext = False`, so the compiler never includes
fulltext in the LLM prompt, and the LLM refuses to produce verbatim-quoted
claims.

**2. Contract changes (binding, see plan-v1.2.md for tester/coder details):**

- `contract.md §4.5`: rewrite the fulltext probe as a two-step procedure:
  (1) try the parent key; (2) on 404, fetch the item's children via §4.9 and
  probe each child key. First 200 wins; all 404 → `False`/`FulltextNotFoundError`.
- `contract.md §4.9` (new): `GET {base}/items/{KEY}/children?format=json` —
  returns a JSON array of child item objects; 404 treated as empty (no children).
- `contract.md §3.1`: `has_fulltext` note updated to reference the two-step probe.

**3. Requirements added (binding):**

REQ-045: fulltext probe and fetch fall through to child attachment items.

**4. plan-v1.2.md is authorized.**

TDD discipline applies: tester writes and commits red tests before the coder
writes any implementation.

**5. Conditions (binding):**

- (a) All pre-existing tests remain green at the end of the coder phase.
- (b) Only `src/zotwiki/zotero.py` changes; no other source files are touched.
- (c) The `_child_keys` helper is private; no public protocol changes.
- (d) A 404 from the children endpoint is treated as an empty list (not an
  error), because Zotero may return 404 for items with no children depending
  on version.
- (e) Child ordering follows server order; the first child with fulltext wins.

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

---

## Ruling 5 — existing-article embed in update prompts must be compact JSON

**Date:** 2026-06-15 · **Scope:** `compiler.py` prompt construction, contract §7.1/§5.5, plan-v1.2.md B4 · **Status:** binding.

**1. Disposition: the existing article embedded in an update-mode prompt is
serialized as the compact form
`json.dumps(article_to_json_dict(existing), sort_keys=True)` — no `indent`.**

During plan-v1.2 Phase B, the B4 refactor proposed re-serializing the embedded
existing article with `indent=2`. This broke three tests (REQ-014 ×2, REQ-034):
contract §7.1 requires the exact compact string
`json.dumps(article_to_json_dict(existing), sort_keys=True)` to appear in the
prompt **as a verbatim substring**, and an indented serialization is not a
substring of that compact form. The compact form is retained.

**2. Rationale — the two JSON roles in the prompt are deliberately different.**

The prompt contains JSON in two distinct roles, formatted differently on purpose:

- **Templates the LLM should _produce_** — the schema example (B1) and the
  `Contradiction` example (B5). These are small and fixed-size; `indent=2` makes
  their *structure* obvious, which is the point of an example. They are
  "surrounding instruction text" and contract §7.1 leaves their format
  unspecified.
- **Data the LLM should _consume_** — the existing-article embed (B4). It can be
  large (a mature article with many claims and quotes), the LLM only needs to
  *parse* it, and indentation roughly doubles–triples its token count on every
  update compile. There is no correctness benefit: the merge happens in Python
  (`merge_articles`), not by the LLM re-serializing.

The rule is therefore scoped narrowly: **only the existing-article embed must be
compact.** The instruction-text examples (B1, B5) stay indented; de-indenting
them would worsen the BUG-2 schema-error surface (the inverse error).

**3. Documentation changes (binding):**

- `contract.md §7.1`: the embed is the **compact** form (no `indent`); the exact
  string must appear verbatim as a substring.
- `contract.md §5.5`: the embed use is compact (no `indent`); the round-trip law
  is unaffected.
- `requirements.md REQ-014`: the "Then" clause names the compact form explicitly.
- `plan-v1.2.md B4`: the `indent=2` instruction is corrected to compact.

**4. Conditions (binding):**

- (a) This rule applies **only** to the existing-article embed, not to the
  instruction-text JSON examples (B1, B5), which remain indented.
- (b) Changing the embed serialization (e.g. to indented) is a contract change
  requiring a new ruling, a contract §7.1 amendment, and a tester update — it is
  not a refactor.
- (c) The compact-embed behavior is already pinned by the REQ-014/REQ-034 tests;
  no new test is required.

---

## Ruling 6 — BUG-1 fix: track compiled items by Zotero key in page frontmatter

**Date:** 2026-06-15 · **Scope:** frontmatter §6.2, publisher §6.4/§6.5, compiler §7, CLI §9.2/§9.6, requirements REQ-046–048, plan-bug1.md · **Status:** binding.

**1. Disposition: `sync` recognizes already-compiled items by Zotero item
`key`, recorded in a new `zotero_keys` frontmatter field — replacing the
title-based skip-check that causes BUG-1.**

BUG-1 (duplicate pages on every sync) is a *drift* bug: the skip-check asked
"does `{vault}/{Zotero title}.md` exist?", but pages are saved under the
LLM-chosen title, which usually differs. The fix removes the divergent state
rather than adding more — the pages themselves record which Zotero items
produced them, and sync consults that.

**2. Why in-page frontmatter (not a manifest or the Index).** A manifest is a
*second* record of what is compiled, which can re-diverge from the actual vault
— BUG-1's disease in a new costume. The Index is derived, byte-exact, and
idempotent (REQ-022), regenerated from the *filename set*; putting keys in it
would couple regeneration to page content and is the wrong layer ("what pages
exist", not "what is compiled"). The pages are the single source of truth; the
Zotero collection is the membership authority, so sync should *heal* a
user-deleted page — which the in-page design does for free.

**3. Why the Zotero `key` (not citekey, version, etc.).** The item `key` is
permanent, client-generated, present on every item, and independent of the
hosted-sync subscription. `version`/`library`/`links`/`meta` are sync-managed;
the citekey (`extra` / native `citationKey`) is user-editable. (See this
session's field-reliability analysis.)

**4. Ground truth, not "cited-by".** `zotero_keys` come from the actual keys
passed to `compile` (`CompileResult.zotero_keys` → `publish(zotero_keys=)`), not
from resolving the article's citekeys (the References block records "cited by"
and can diverge from "compiled from").

**5. Breaking change (conscious decision): schema `zotwiki: 1` → `zotwiki: 2`.**
`zotero_keys` is a required §6.2 field; the strict parser rejects pages without
it, so legacy `zotwiki: 1` pages become `PAGE_UNPARSEABLE`. Migration =
regenerate the vault (delete `*.md` and re-sync, or use a fresh vault), which
also clears existing BUG-1 duplicates. A tolerant/optional field was rejected:
legacy pages would still duplicate on the next sync (their items aren't
tracked), so regeneration is needed either way — required+v2 is the coherent
version.

**6. The `--update` title-pin (correctness).** `publish` derives the page path
from `article.title`. On `--update`, after finding page `P` by key, the compiled
article's title is pinned to `P`'s title (`dataclasses.replace`) before publish,
so the update lands in `P` (the §7.2 merge fires, never-clobber preserved)
instead of writing a duplicate under a drifted LLM title. Sync does **not**
error on title drift (unlike `compile --page`).

**7. New-item title collision (deliberate).** A new (uncompiled) item whose LLM
title exactly equals an existing page merges into it, unioning `zotero_keys`, per
§6.5 existing-title semantics — same title = same article. Case-variant titles
still raise `VaultError` (§6.5).

**8. Contract changes (binding):** §6.2 (add `zotero_keys` after `citekeys`,
before `tags`; bump to `zotwiki: 2`; empty → `zotero_keys: []`), §6.4
(`render_page` gains `zotero_keys`; round-trip law unaffected), §6.5 (`publish`
gains `zotero_keys`; new-page write and update-union rules; new
`compiled_keys()`), §6.7/§6.8 (`zotero_keys: []` on Index/Contradictions), §7
(`CompileResult.zotero_keys`), §9.2 (compile passes `result.zotero_keys`), §9.6
(sync skip/update keyed on Zotero key + the title-pin), plus a migration note.

**9. Requirements added (binding):** REQ-046, REQ-047, REQ-048.

**10. Conditions (binding):**
- (a) `zotero_keys` = sorted, deduped of the keys passed to `compile`.
- (b) Update writes the sorted union `existing ∪ new` (never-clobber).
- (c) `auditor` and `ask` require **no** source change — they read frontmatter
  via the shared `_parse_frontmatter`/`parse_page` and inherit the new field; no
  new audit code in this cycle.
- (d) TDD: the tester writes REQ-046/047/048 tests **and** retrofits every
  frontmatter byte-oracle to the v2 + `zotero_keys` format; the red gate must
  fail before the coder writes code.
- (e) Existing rendering/parse/index REQs (REQ-017/020/021/022) keep their
  statements; only their byte-oracles change to the §6.2 v2 format.
- (f) Only `compiler.py`, `publisher.py`, `syncer.py`, `cli.py` change; no new
  runtime dependency (`dataclasses` is stdlib); the injection seam is untouched.

## Ruling 7 — `zw` operator terminal wrapper authorized

**Date:** 2026-06-18 · **Scope:** new contract §11, requirements REQ-049–052, `scripts/zw`, README, plan-zw.md · **Status:** binding.

**1. Disposition: add `scripts/zw`, a thin shell wrapper giving short terminal
directives for operating zotwiki from a plain terminal.** The operator drives
zotwiki by hand and the full invocations are long and repetitive (every command
repeats `--vault "<long path>"`; `sync` also repeats `--collection NAME`). `zw`
injects the vault from `$ZOTWIKI_VAULT` and forwards the rest to the installed
`zotwiki` console script.

**2. Why a wrapper, not new zotwiki behavior.** `zw` only *composes* the existing
public CLI (§9). It adds **no** new subcommand, flag, or behavior to
`src/zotwiki/`, changes **no** existing §1–§10 contract surface, and adds **no**
runtime dependency. zotwiki still reaches `claude` only via `sync`/`ask`/`compile`
(`_NEEDS_LLM`); `zw` does not change which directives invoke the LLM.

**3. Relationship to BUG-2.** Running from a plain terminal (not nested inside a
Claude Code session) is exactly the environment in which the nested-session LLM
corruption (`docs/user-testing/zotwiki-bug-findings.md`) does not occur — the
child `claude` inherits no `CLAUDECODE`/`CLAUDE_CODE_*`. `zw` therefore needs **no**
env-stripping and is independent of the still-draft structured-output fix. (That
draft, `docs/plan-bug2.md`, reserved "Ruling 7"; since this ruling lands first it
takes 7 and that pending ruling renumbers to **Ruling 8**.)

**4. Contract change (binding):** new top-level **§11 Operator terminal wrapper
(`scripts/zw`)** — the directive→`zotwiki` argv mapping, the `ZOTWIKI_VAULT`
requirement, exit-code passthrough, usage/`help` output, and unknown-directive
behavior. No edits to §1–§10.

**5. Requirements added (binding):** REQ-049 (usage/help), REQ-050
(`ZOTWIKI_VAULT` unset → exit 2), REQ-051 (directive→argv forwarding), REQ-052
(exit-code passthrough + unknown directive).

**6. Conditions (binding):**
- (a) `$ZOTWIKI_VAULT` is the single vault directory for `sync`/`ask`/`compile`/
  `audit`; `ingest` takes no `--vault`. (A per-collection layout is a documented
  user tweak, not the shipped default.)
- (b) `zw` execs `zotwiki` so the child's exit code is the wrapper's exit code
  (0/1/2 passthrough, §9.3 preserved).
- (c) Tests are hermetic via a fake `zotwiki` shim on `PATH` (the existing
  fake-binary seam pattern); no real `claude`/Zotero/network. The real
  `ClaudeCodeLLMClient` is not involved.
- (d) TDD: tester writes REQ-049–052 against §11 and commits the red gate before
  the coder writes `scripts/zw`.

## Ruling 8 — `zw`: collection-scoped vault subfolders

**Date:** 2026-06-19 · **Scope:** contract §11.1/§11.2 (supersedes those parts of Ruling 7), requirements REQ-049–053, `scripts/zw`, README, plan-zw.md · **Status:** binding.

**1. Disposition: `zw` operates on a per-collection wiki folder, configured by
two environment variables.** `ZOTWIKI_VAULT` is the operator's Obsidian
**Library** folder; `ZOTWIKI_COLLECTION` is the Zotero collection name and also
the wiki subfolder name. The effective vault is `$ZOTWIKI_VAULT/$COLLECTION`.
This replaces Ruling 7's single-`--vault`, collection-as-required-argument model
(§11.1/§11.2), which forced the operator to repeat both the long path *and* the
collection on every command.

**2. Why this shape.** The operator keeps one Obsidian "Library" folder and wants
each synced Zotero collection to live in its own subfolder under it. Setting the
Library path and the collection name once (env vars) lets every directive target
the right wiki with no per-command path. `sync NAME` still allows a one-off
override for a different collection.

**3. `zw sync` creates the folder.** `zotwiki sync` requires an existing
`--vault` directory (§9.6, `cli.py` returns exit 2 otherwise). So `zw sync` runs
`mkdir -p "$ZOTWIKI_VAULT/$COLLECTION"` before invoking sync — the new
collection's folder appears under Library on first sync. `audit`/`ask`/`compile`
do not create it (they read an existing wiki).

**4. Still a pure composition of the public CLI.** No change to `src/zotwiki/`,
no new zotwiki behavior, no dependency, no §1–§10 change. `claude` is still
reached only via `sync`/`ask`/`compile` (§9.4).

**5. Contract changes (binding):** §11.1 (two env vars; effective vault;
resolution + error rules), §11.2 (per-collection argv mapping; `mkdir -p` on
sync; optional `sync NAME` override). §11.3–§11.5 unchanged.

**6. Requirements (binding):** REQ-049 (usage, unchanged), REQ-050
(`ZOTWIKI_VAULT` unset → exit 2), **revised** REQ-051 (collection-scoped argv
forwarding), REQ-052 (exit passthrough + unknown, unchanged), **new** REQ-053
(`sync` creates `$ZOTWIKI_VAULT/$COLLECTION`; unresolved collection → exit 2).

**7. Ruling-number note.** This is the next ruling authored, so it takes 8; the
still-draft `docs/plan-bug2.md` ruling becomes **Ruling 9** when written.

**8. Conditions (binding):**
- (a) Collection resolution: positional `NAME` not starting with `-` (sync only)
  else `$ZOTWIKI_COLLECTION`; if neither, exit 2 with one stderr line, no zotwiki.
- (b) `zw exec`s `zotwiki` (exit-code passthrough preserved, §11.5).
- (c) Tests hermetic via the fake-`zotwiki`-shim-on-PATH pattern; the real vault
  root is a `tmp_path` directory so `mkdir -p` is observable. No real
  `claude`/Zotero/network.
- (d) TDD: tester revises REQ-049–052 and adds REQ-053 against §11, red gate
  before the coder edits `scripts/zw`.

## Ruling 9 — BUG-2 fix: structured-output LLM boundary (`--json-schema`, fail-closed)

**Date:** 2026-06-22 · **Scope:** contract §5.1/new §5.6/§9.3/§9.4/§9.5,
requirements REQ-039 (revised) + REQ-054/REQ-055, `llm.py`/`ask.py`/`cli.py`,
`plan-bug2.md` · **Status:** binding.

**1. Disposition: `ClaudeCodeLLMClient` constrains the model to schema-shaped
JSON at the source and fails closed.** It invokes
`claude --print --output-format json --json-schema <schema>
--exclude-dynamic-system-prompt-sections`, reads the validated object from the
envelope's `structured_output` on `subtype == "success"`, and hands
`json.dumps(structured_output)` to the **unchanged, strict** `parse_article_json`
(or the `ask` validator). This is the opposite of a tolerant/prose-extracting
parser — the owner's constraint is that the *source* emit clean JSON, not that
the *parser* forgive prose. On any non-`success` subtype, malformed envelope, or
non-zero exit, it fails loud and writes a verbatim failure artifact (point 4).
This is the full fix for BUG-2 ("occasional LLM schema errors"); it subsumes the
nested-Claude-Code char-0 failure reported in
`docs/user-testing/zotwiki-bug-findings1.md`.

**2. Precondition resolved (was the blocking gate, `plan-bug2.md §7.1`).**
Validated 2026-06-22 against the real `claude` (v2.1.185) **inside a Claude Code
session** (`CLAUDECODE=1`, `CLAUDE_CODE_*` set, **no `ANTHROPIC_API_KEY`**):
`claude --print --output-format json --json-schema <schema>
--exclude-dynamic-system-prompt-sections` with the `CLAUDECODE`/`CLAUDE_CODE_*`
keys stripped from the child env exited 0 and returned an envelope with
`subtype: "success"`, `is_error: false`, a populated `structured_output`
(`{"answer":"Paris"}`), and the full metadata (`stop_reason`, `session_id`,
`usage`, `num_turns`, `total_cost_usd`). **Structured output works under the
OAuth subscription login with no API key**, so the approach is viable and Ruling 2
(no API-key backend) is preserved. *What this did not prove (kept explicit):*
determinism on a real 20K-char `ARTICLE_SCHEMA` compile, and the exact
`error_max_structured_output_retries` failure envelope — both are doc-settled and
deliberately punted to the fail-loud operator runs (point 4). No further
real-`claude` calls are warranted to finalize.

**3. One mechanism, no fallback.** A single `claude` invocation (the CLI's own
schema re-prompting is internal, not a zotwiki retry). There is **no** non-JSON
fallback branch and **no** zotwiki-level retry. `--bare` and the Anthropic API
SDK are rejected (both reintroduce the API-key requirement Ruling 2 removed).
`parse_article_json` stays the sole authoritative validator/canonicalizer; the
`--json-schema` shape is a *decoding hint* (Ruling 5 spirit), not the contract.
`ARTICLE_SCHEMA`/`ANSWER_SCHEMA` are loose shape hints, not re-encodings of the
full validator — REQ-010/011 (parse authority) are unchanged.

**4. Fail-closed, dump-verbatim.** On any `subtype != "success"`, a
malformed/non-object stdout, a missing extraction field, or a non-zero `claude`
exit, `complete()` raises `ZotWikiError` (no retry) **and** writes a timestamped
failure artifact under `dump_dir` (default `~/.zotwiki/failures/`) holding the
exact argv, the prompt sent on stdin, the verbatim stdout envelope, stderr, the
exit code, and the diagnostic fields present in the envelope (`subtype`,
`errors`, `stop_reason`, and metadata). The raised message is **single-line** and
**points to the artifact path**, preserving the §9.3 one-line-stderr invariant (a
20K prompt + full envelope cannot go on the `error:` line). `result` is present
only on `success`, so a failure record carries the structured fields, not raw
prose.

**5. Schema threading without touching the protocol.** `LLMClient.complete(self,
prompt: str) -> str` is unchanged; all injected fakes are unchanged. The schema
is supplied at construction by the command handler that knows what it produces:
`ClaudeCodeLLMClient(output_schema: dict | None = None, *, dump_dir=None)`.
`cli.py §9.4` constructs `compile`/`sync` with `ARTICLE_SCHEMA` (`llm.py`) and
`ask` with `ANSWER_SCHEMA` (`ask.py`). `output_schema=None` → omit `--json-schema`
and read `.result`. `complete()` still returns a **string**.

**6. Defense-in-depth env hardening.** The child env strips `CLAUDECODE` and every
`CLAUDE_CODE_*` key, and `--exclude-dynamic-system-prompt-sections` is always
passed, so a nested-session invocation does not inherit conversational context.
Unrelated env (PATH, HOME, the OAuth keychain access) is preserved. `ANTHROPIC_*`
is **not** stripped.

**7. Test-import invariant reconciled (resolves a stale CLAUDE.md line).** The
CLAUDE.md invariant "`ClaudeCodeLLMClient` is never imported by any test" was
already narrower in practice: the **injected-fake** suite (Compiler/CLI/`ask`,
etc.) never imports it, but the dedicated client module
`tests/test_m6_llm_client.py` *does* import it lazily (autouse fixture) and drives
a **fake `claude` binary on PATH** — never the real binary, never the network.
Ruling: that is the correct and only seam for testing `complete()`. The BUG-2
envelope tests (REQ-039 revised, REQ-054, REQ-055) extend exactly this module and
seam. CLAUDE.md's invariant bullet is corrected to state this precisely so the
blind tester has unambiguous license. The injected-fake suite remains forbidden
from importing the real client.

**8. Contract changes (binding):** §5.1 (revised `ClaudeCodeLLMClient`
description: structured-output invocation, per-command `output_schema`), **new
§5.6** (the structured-output invocation — flags, env-strip, envelope handling,
`structured_output`/`result` extraction, fail-loud-dump artifact, and that
`parse_article_json` remains authoritative; `ARTICLE_SCHEMA`/`ANSWER_SCHEMA` as
loose hints; the constructor), §9.3 (the failure message points to the artifact
file), §9.4 (per-command construction with the right schema), §9.5 (`ask` uses
`ANSWER_SCHEMA`).

**9. Requirements (binding):** **revise REQ-039** (success-envelope extraction +
the new flags + still-`claude not found`), **add REQ-054** (subprocess env
sanitization — no `CLAUDECODE`/`CLAUDE_CODE_*`), **add REQ-055** (fail-closed +
artifact dump on non-`success` subtype / non-zero exit / malformed-or-missing
field, single-line message pointing to the artifact). No fallback-path REQ.

**10. Conditions (binding):**
- (a) `parse_article_json` and the `ask` validator are **unchanged**; they remain
  the authoritative gate on `complete()`'s returned string.
- (b) Stdlib only (`subprocess`, `json`, `os`, `pathlib`, `datetime`); no new
  runtime dependency. The `LLMClient` protocol and the `main(store=, llm=)`
  injection seam are untouched; every injected-fake test stays valid unchanged.
- (c) Tests are hermetic via the fake-`claude`-binary-on-PATH seam of
  `tests/test_m6_llm_client.py`; the fake emits a JSON envelope and (for REQ-054)
  reports its received env; `dump_dir` is a `tmp_path` so the artifact is
  observable. No real `claude`, Zotero, or network. No real-`claude` integration
  test (determinism evidence accrues from the fail-loud operator artifacts).
- (d) Which schema each command passes (§9.4) is contract-specified but not
  hermetically tested (the injected-fake suite never constructs the real client);
  REQ-039 tests that *a supplied* `output_schema` becomes `--json-schema <json>`.
- (e) TDD: tester revises REQ-039 and adds REQ-054/REQ-055 against §5.6, commits
  the red gate before the coder edits `llm.py`/`ask.py`/`cli.py`.
