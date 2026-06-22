"""Structured-output LLM boundary (BUG-2, Ruling 9) — contract §5.6.

`ClaudeCodeLLMClient` constrains the model to schema-shaped JSON at the source
and fails closed. It is tested hermetically by this dedicated module only: the
client is imported lazily and driven through a **fake `claude` binary on PATH**
(a small Python script) prepended to PATH per test. The real `claude` binary and
the network are never invoked. The injected-fake suite (Compiler/CLI/`ask`) is
unchanged and still never constructs the real client.

Covered:
  - REQ-039: structured-output invocation + extraction.
    * output_schema set → argv carries `--json-schema <json.dumps(schema)>`,
      prompt on stdin, complete() returns json.dumps(envelope["structured_output"]).
    * output_schema None → `--json-schema` absent, complete() returns
      envelope["result"].
    * `claude` absent from PATH → ZotWikiError("claude not found"), no artifact.
  - REQ-054: child env strips CLAUDECODE / CLAUDE_CODE_*, preserves others.
  - REQ-055: fail-closed with a verbatim failure artifact on each of the four
    failure conditions (non-success subtype, non-zero exit, non-JSON stdout,
    missing extraction field).
"""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from zotwiki.errors import ZotWikiError

ClaudeCodeLLMClient = None  # bound at module scope by the autouse fixture


@pytest.fixture(scope="module", autouse=True)
def _require_surface():
    global ClaudeCodeLLMClient
    from zotwiki.llm import ClaudeCodeLLMClient as _C
    ClaudeCodeLLMClient = _C


# ----- fake-binary infrastructure -------------------------------------------


@pytest.fixture
def claude_bin(tmp_path, monkeypatch):
    """Prepend tmp_path/bin to PATH; return the directory for binary writing."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    monkeypatch.setenv(
        "PATH", str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    )
    return bin_dir


def _install_claude(bin_dir: Path, *, body: str, exit_code: int = 0) -> Path:
    """Write a fake `claude` Python script into bin_dir and make it executable."""
    script = bin_dir / "claude"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        + body
        + f"\nsys.exit({exit_code})\n",
        encoding="utf-8",
    )
    mode = script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    os.chmod(script, mode)
    return script


def _install_recording_claude(
    bin_dir: Path,
    record_path: Path,
    *,
    stdout: str,
    stderr: str = "",
    exit_code: int = 0,
) -> Path:
    """Fake `claude` that records its invocation (argv / stdin / full env) as
    JSON to ``record_path``, then emits the given stdout/stderr and exit code.

    The record lets the success-path tests inspect argv, the stdin prompt, and
    the (sanitized) child environment without coupling to the production client.
    """
    body = (
        "import json, os\n"
        "stdin = sys.stdin.read()\n"
        "record = {'argv': sys.argv[1:], 'stdin': stdin, 'env': dict(os.environ)}\n"
        "open(" + repr(str(record_path)) + ", 'w', encoding='utf-8')"
        ".write(json.dumps(record))\n"
        "sys.stderr.write(" + repr(stderr) + ")\n"
        "sys.stdout.write(" + repr(stdout) + ")\n"
    )
    return _install_claude(bin_dir, body=body, exit_code=exit_code)


def _flag_value(argv: list[str], flag: str) -> str:
    """The value immediately following ``flag`` in ``argv`` (asserts presence)."""
    assert flag in argv, f"{flag!r} missing from argv {argv!r}"
    i = argv.index(flag)
    assert i + 1 < len(argv), f"{flag!r} has no value in argv {argv!r}"
    return argv[i + 1]


# A distinctive loose schema for the failure tests. The bareword marker survives
# any reasonable argv serialization in the artifact (json.dumps of the argv list,
# repr, space-join), so asserting it is layout-independent (§5.6 leaves the
# artifact layout unspecified). The real ARTICLE_SCHEMA content is unspecified;
# REQ-039 tests only that a *supplied* schema becomes `--json-schema <json>`.
_SCHEMA_MARKER = "SCHEMA_SENTINEL_PROP"
_SCHEMA = {"type": "object", "properties": {_SCHEMA_MARKER: {"type": "string"}}}


def _assert_failure_artifact(msg, dump_dir, *, prompt, stdout):
    """Common REQ-055 contract: a single-line message that points to exactly one
    artifact under ``dump_dir`` whose verbatim content carries the mandated
    fields — the argv (incl. the `--json-schema` flag and the schema value), the
    prompt, and the verbatim stdout. Returns ``(artifact_path, artifact_text)``
    for case-specific assertions."""
    assert "\n" not in msg, f"failure message must be single-line, got {msg!r}"
    artifacts = list(dump_dir.glob("*.txt"))
    assert len(artifacts) == 1, f"expected one artifact in {dump_dir}, got {artifacts}"
    artifact = artifacts[0]
    assert artifact.name in msg, (
        f"message must point to the artifact {artifact.name!r}; got {msg!r}"
    )
    text = artifact.read_text(encoding="utf-8")
    assert "--print" in text, "argv must be recorded in the artifact"
    assert "--json-schema" in text, "the --json-schema flag must be in the argv"
    assert _SCHEMA_MARKER in text, "the schema value must be recorded in the argv"
    assert prompt in text, "the prompt sent on stdin must be in the artifact"
    if stdout:
        assert stdout in text, "the verbatim stdout envelope must be in the artifact"
    return artifact, text


# ----- REQ-039: structured-output invocation + extraction --------------------


def test_req_039__schema_invocation_and_structured_output(claude_bin, tmp_path):
    """output_schema set → argv carries the structured-output flags + the schema;
    the full prompt is delivered on stdin; complete() returns the serialized
    `structured_output` (which the unchanged parse_article_json then gates)."""
    schema = {"type": "object", "properties": {"title": {"type": "string"}}}
    structured = {"title": "T", "summary": "S", "sections": [], "claims": [], "links": []}
    envelope = {
        "type": "result", "subtype": "success", "is_error": False,
        "structured_output": structured,
        "result": "raw text that must be ignored when a schema is set",
        "stop_reason": "end_turn", "session_id": "sid-1",
        "usage": {"input_tokens": 9}, "num_turns": 1, "total_cost_usd": 0.01,
    }
    stdout = json.dumps(envelope)
    record = tmp_path / "record.json"
    dump_dir = tmp_path / "failures"
    _install_recording_claude(claude_bin, record, stdout=stdout)

    prompt = "Compile this article. " + "x" * 1500 + " PROMPT_SENTINEL_039"
    result = ClaudeCodeLLMClient(output_schema=schema, dump_dir=dump_dir).complete(prompt)

    # Returns the serialized validated object — both byte-exact (§5.6) and semantic.
    assert result == json.dumps(structured)
    assert json.loads(result) == structured

    rec = json.loads(record.read_text(encoding="utf-8"))
    argv = rec["argv"]
    assert "--print" in argv
    assert _flag_value(argv, "--output-format") == "json"
    assert "--exclude-dynamic-system-prompt-sections" in argv
    assert _flag_value(argv, "--json-schema") == json.dumps(schema)
    assert rec["stdin"] == prompt

    # Success writes no failure artifact.
    assert not dump_dir.exists() or list(dump_dir.glob("*.txt")) == []


def test_req_039__no_schema_omits_json_schema_and_returns_result(claude_bin, tmp_path):
    """output_schema None → `--json-schema` absent; complete() returns the
    envelope's `result` string."""
    envelope = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "RAW_RESULT_SENTINEL the models text",
        "stop_reason": "end_turn", "session_id": "sid-2",
        "usage": {}, "num_turns": 1, "total_cost_usd": 0.0,
    }
    record = tmp_path / "record.json"
    _install_recording_claude(claude_bin, record, stdout=json.dumps(envelope))

    result = ClaudeCodeLLMClient().complete("a prompt")
    assert result == "RAW_RESULT_SENTINEL the models text"

    argv = json.loads(record.read_text(encoding="utf-8"))["argv"]
    assert "--json-schema" not in argv
    assert "--print" in argv
    assert _flag_value(argv, "--output-format") == "json"
    assert "--exclude-dynamic-system-prompt-sections" in argv


def test_req_039__claude_not_on_path_raises_no_artifact(monkeypatch, tmp_path):
    """`claude` absent from PATH → ZotWikiError('claude not found'); no subprocess
    runs and no failure artifact is written."""
    monkeypatch.setenv("PATH", "/no-such-directory-zotwiki-test")
    dump_dir = tmp_path / "failures"
    with pytest.raises(ZotWikiError, match="claude not found"):
        ClaudeCodeLLMClient(output_schema={"type": "object"}, dump_dir=dump_dir).complete(
            "a prompt"
        )
    assert not dump_dir.exists() or list(dump_dir.glob("*.txt")) == []


# ----- REQ-054: subprocess environment sanitized of nested-session vars ------


def test_req_054__strips_nested_session_env_preserves_unrelated(
    claude_bin, tmp_path, monkeypatch
):
    """The child env removes CLAUDECODE and every CLAUDE_CODE_* key (defense in
    depth against nested-session context) while preserving unrelated vars."""
    monkeypatch.setenv("CLAUDECODE", "1")
    monkeypatch.setenv("CLAUDE_CODE_ENTRYPOINT", "cli")
    monkeypatch.setenv("CLAUDE_CODE_SSE_PORT", "57321")
    monkeypatch.setenv("ZOTWIKI_TEST_MARKER", "preserved-value")

    envelope = {
        "subtype": "success", "is_error": False,
        "structured_output": {"ok": True}, "result": "x",
    }
    record = tmp_path / "record.json"
    _install_recording_claude(claude_bin, record, stdout=json.dumps(envelope))

    ClaudeCodeLLMClient(
        output_schema={"type": "object"}, dump_dir=tmp_path / "failures"
    ).complete("a prompt")

    env = json.loads(record.read_text(encoding="utf-8"))["env"]
    assert "CLAUDECODE" not in env
    assert [k for k in env if k.startswith("CLAUDE_CODE_")] == []
    assert env.get("ZOTWIKI_TEST_MARKER") == "preserved-value"


# ----- REQ-055: fail-closed with a verbatim failure artifact -----------------


def test_req_055__non_success_subtype_fails_closed_with_artifact(claude_bin, tmp_path):
    """subtype != "success" → raise (no retry), naming the subtype, and dump a
    verbatim artifact carrying the diagnostic fields (no `result` is present)."""
    dump_dir = tmp_path / "failures"
    envelope = {
        "type": "result",
        "subtype": "error_max_structured_output_retries",
        "is_error": True,
        "errors": ["structured output validation failed: ERRORS_SENTINEL"],
        "stop_reason": "refusal",
        "session_id": "SESSION_SENTINEL",
        "usage": {"input_tokens": 14},
        "num_turns": 3,
        "total_cost_usd": 0.07,
        # No "result"/"structured_output" on a non-success subtype.
    }
    stdout = json.dumps(envelope)
    _install_recording_claude(claude_bin, tmp_path / "record.json", stdout=stdout)

    prompt = "Compile PROMPT_SENTINEL_nonsuccess"
    with pytest.raises(ZotWikiError) as exc:
        ClaudeCodeLLMClient(output_schema=_SCHEMA, dump_dir=dump_dir).complete(prompt)

    msg = str(exc.value)
    assert "error_max_structured_output_retries" in msg  # message names the subtype
    _, text = _assert_failure_artifact(
        msg, dump_dir, prompt=prompt, stdout=stdout
    )
    assert "error_max_structured_output_retries" in text  # subtype
    assert "ERRORS_SENTINEL" in text                      # errors
    assert "refusal" in text                              # stop_reason
    assert "SESSION_SENTINEL" in text                     # metadata


def test_req_055__nonzero_exit_fails_closed_with_artifact(claude_bin, tmp_path):
    """Non-zero `claude` exit → raise + dump; the artifact carries stderr and the
    exit code."""
    dump_dir = tmp_path / "failures"
    _install_recording_claude(
        claude_bin, tmp_path / "record.json",
        stdout="", stderr="claude failed: STDERR_SENTINEL", exit_code=42,
    )
    prompt = "Compile PROMPT_SENTINEL_exit"
    with pytest.raises(ZotWikiError) as exc:
        ClaudeCodeLLMClient(output_schema=_SCHEMA, dump_dir=dump_dir).complete(prompt)

    msg = str(exc.value)
    _, text = _assert_failure_artifact(
        msg, dump_dir, prompt=prompt, stdout=""
    )
    assert "STDERR_SENTINEL" in text  # stderr captured
    assert "42" in text               # exit code captured (distinctive)


def test_req_055__non_json_stdout_fails_closed_with_artifact(claude_bin, tmp_path):
    """stdout that is not a JSON object → raise + dump the verbatim prose."""
    dump_dir = tmp_path / "failures"
    prose = "I'm sorry, I can't produce JSON for that. NONJSON_SENTINEL"
    _install_recording_claude(claude_bin, tmp_path / "record.json", stdout=prose)

    prompt = "Compile PROMPT_SENTINEL_prose"
    with pytest.raises(ZotWikiError) as exc:
        ClaudeCodeLLMClient(output_schema=_SCHEMA, dump_dir=dump_dir).complete(prompt)

    msg = str(exc.value)
    _assert_failure_artifact(msg, dump_dir, prompt=prompt, stdout=prose)


def test_req_055__json_non_object_stdout_fails_closed_with_artifact(claude_bin, tmp_path):
    """stdout that is valid JSON but not an *object* (e.g. an array) → raise +
    dump. Distinct from the prose case: guards an impl that calls `.get` on the
    parsed value without an isinstance(dict) check."""
    dump_dir = tmp_path / "failures"
    stdout = "[1, 2, 3]"
    _install_recording_claude(claude_bin, tmp_path / "record.json", stdout=stdout)

    prompt = "Compile PROMPT_SENTINEL_array"
    with pytest.raises(ZotWikiError) as exc:
        ClaudeCodeLLMClient(output_schema=_SCHEMA, dump_dir=dump_dir).complete(prompt)

    msg = str(exc.value)
    _assert_failure_artifact(msg, dump_dir, prompt=prompt, stdout=stdout)


def test_req_055__success_subtype_missing_structured_output_fails_closed(
    claude_bin, tmp_path
):
    """subtype "success" but the extraction field (structured_output, since a
    schema was set) is absent → still fail closed + dump."""
    dump_dir = tmp_path / "failures"
    envelope = {
        "type": "result", "subtype": "success", "is_error": False,
        "result": "some prose, but no structured_output field",
        "stop_reason": "end_turn", "session_id": "SESSION_MISSING",
        "usage": {}, "num_turns": 1, "total_cost_usd": 0.0,
    }
    stdout = json.dumps(envelope)
    _install_recording_claude(claude_bin, tmp_path / "record.json", stdout=stdout)

    prompt = "Compile PROMPT_SENTINEL_missingfield"
    with pytest.raises(ZotWikiError) as exc:
        ClaudeCodeLLMClient(output_schema=_SCHEMA, dump_dir=dump_dir).complete(prompt)

    msg = str(exc.value)
    _assert_failure_artifact(msg, dump_dir, prompt=prompt, stdout=stdout)
