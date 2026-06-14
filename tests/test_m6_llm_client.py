"""REQ-039: ClaudeCodeLLMClient shells out to `claude --print` via stdin.

Hermetic: a fake `claude` binary (a small Python script) is placed in
tmp_path/bin and prepended to PATH for each test. The real `claude` binary
is never invoked. Tests cover:

  - Full prompt delivered via stdin; stdout returned as-is.
  - Non-zero exit from `claude` → ZotWikiError with single-line message.
  - `claude` absent from PATH → ZotWikiError("claude not found").
"""
from __future__ import annotations

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


# ----- REQ-039 tests ---------------------------------------------------------


def test_req_039__stdout_returned_as_result(claude_bin):
    """Fake binary reads stdin and writes a canned response; complete() returns it."""
    canned = '{"title": "T", "summary": "S", "sections": [], "claims": [], "links": []}'
    _install_claude(
        claude_bin,
        body=(
            "sys.stdin.read()\n"               # consume stdin
            f"sys.stdout.write({canned!r})\n"
        ),
    )
    result = ClaudeCodeLLMClient().complete("a prompt")
    assert result == canned


def test_req_039__full_prompt_passed_via_stdin(claude_bin):
    """The entire prompt string reaches the binary on stdin."""
    _install_claude(
        claude_bin,
        body="sys.stdout.write(sys.stdin.read())\n",  # echo stdin to stdout
    )
    prompt = "This is the full prompt: " + "x" * 2000
    result = ClaudeCodeLLMClient().complete(prompt)
    assert result == prompt


def test_req_039__nonzero_exit_raises_zotwiki_error(claude_bin):
    """Non-zero exit code from `claude` → ZotWikiError with single-line message
    that includes the exit code."""
    _install_claude(
        claude_bin,
        body='sys.stdin.read()\nsys.stderr.write("rate limit exceeded")\n',
        exit_code=1,
    )
    with pytest.raises(ZotWikiError) as exc_info:
        ClaudeCodeLLMClient().complete("a prompt")
    msg = str(exc_info.value)
    assert "\n" not in msg, f"error message must be single-line, got {msg!r}"
    assert "1" in msg, f"exit code must appear in message, got {msg!r}"


def test_req_039__claude_not_on_path_raises_zotwiki_error(monkeypatch):
    """With `claude` absent from PATH, complete() raises ZotWikiError('claude not found')."""
    monkeypatch.setenv("PATH", "/no-such-directory-zotwiki-test")
    with pytest.raises(ZotWikiError, match="claude not found"):
        ClaudeCodeLLMClient().complete("a prompt")
