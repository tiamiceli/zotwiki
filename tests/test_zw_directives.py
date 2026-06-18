"""REQ-049–052: the `scripts/zw` operator terminal wrapper (contract §11).

Hermetic: a fake `zotwiki` executable (a small Python script) is placed in
tmp_path/bin and prepended to PATH. It echoes the argv it received as a single
`ARGV\\t<json>` line on stdout and exits with the code in $FAKE_ZOTWIKI_EXIT
(default 0). The real `zotwiki`, `claude`, Zotero, and the network are never
touched. `scripts/zw` is invoked by its absolute path.

Covers:
  - REQ-049: usage/help to stdout, exit 0, zotwiki not invoked (vault may be unset).
  - REQ-050: vault-needing directive with ZOTWIKI_VAULT unset/empty → exit 2,
    one stderr line, zotwiki not invoked.
  - REQ-051: each directive forwards the exact zotwiki argv (vault injected).
  - REQ-052: zw's exit code == the wrapped zotwiki's; unknown directive → exit 2.
"""
from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

import pytest

ZW = Path(__file__).resolve().parents[1] / "scripts" / "zw"


# ----- fake-binary infrastructure -------------------------------------------


@pytest.fixture
def zotwiki_bin(tmp_path, monkeypatch):
    """Install a fake `zotwiki` on PATH; return (bin_dir, run) where run() invokes
    scripts/zw with that PATH and returns the CompletedProcess."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    script = bin_dir / "zotwiki"
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys, os, json\n"
        'sys.stdout.write("ARGV\\t" + json.dumps(sys.argv[1:]) + "\\n")\n'
        'sys.exit(int(os.environ.get("FAKE_ZOTWIKI_EXIT", "0")))\n',
        encoding="utf-8",
    )
    mode = script.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH
    os.chmod(script, mode)

    base_env = dict(os.environ)
    base_env["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    def run(args, *, vault="/V", fake_exit=None, drop_vault=False):
        env = dict(base_env)
        if drop_vault:
            env.pop("ZOTWIKI_VAULT", None)
        elif vault is not None:
            env["ZOTWIKI_VAULT"] = vault
        if fake_exit is not None:
            env["FAKE_ZOTWIKI_EXIT"] = str(fake_exit)
        return subprocess.run(
            [str(ZW), *args], env=env, capture_output=True, text=True
        )

    return run


def _forwarded_argv(proc):
    """Return the argv the fake zotwiki received, or None if it was not invoked."""
    for line in proc.stdout.splitlines():
        if line.startswith("ARGV\t"):
            return json.loads(line[len("ARGV\t"):])
    return None


# ----- REQ-049: usage / help -------------------------------------------------


@pytest.mark.parametrize("args", [[], ["help"], ["-h"], ["--help"]])
def test_req_049__usage_to_stdout_exit_0_no_zotwiki(zotwiki_bin, args):
    proc = zotwiki_bin(args, drop_vault=True)  # works even with vault unset
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) is None, "usage path must not invoke zotwiki"
    # the directive list is on stdout
    for directive in ("sync", "ask", "compile", "ingest", "audit"):
        assert directive in proc.stdout


# ----- REQ-050: missing ZOTWIKI_VAULT ---------------------------------------


@pytest.mark.parametrize(
    "args",
    [["sync", "Test"], ["ask", "why"], ["compile", "--query", "x"], ["audit"]],
)
def test_req_050__unset_vault_exits_2_no_zotwiki(zotwiki_bin, args):
    proc = zotwiki_bin(args, drop_vault=True)
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None, "must not invoke zotwiki without a vault"
    assert proc.stderr.strip(), "one error line expected on stderr"
    assert len(proc.stderr.strip().splitlines()) == 1


def test_req_050__empty_vault_exits_2(zotwiki_bin):
    proc = zotwiki_bin(["audit"], vault="")
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None


# ----- REQ-051: directive → argv forwarding ----------------------------------


def test_req_051__sync_forwards(zotwiki_bin):
    proc = zotwiki_bin(["sync", "Test", "--update"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "sync", "--vault", "/V", "--collection", "Test", "--update"
    ]


def test_req_051__ask_joins_into_one_positional(zotwiki_bin):
    proc = zotwiki_bin(["ask", "why", "does", "X", "matter"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["ask", "--vault", "/V", "why does X matter"]


def test_req_051__compile_forwards(zotwiki_bin):
    proc = zotwiki_bin(["compile", "--query", "transformers", "--limit", "5"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "compile", "--vault", "/V", "--query", "transformers", "--limit", "5"
    ]


def test_req_051__audit_forwards(zotwiki_bin):
    proc = zotwiki_bin(["audit"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["audit", "--vault", "/V"]


def test_req_051__ingest_forwards_without_vault_flag(zotwiki_bin):
    proc = zotwiki_bin(["ingest", "--title", "BERT", "--year", "2019"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["ingest", "--title", "BERT", "--year", "2019"]


def test_req_051__ingest_needs_no_vault(zotwiki_bin):
    """ingest is exempt from the ZOTWIKI_VAULT requirement (§11.1)."""
    proc = zotwiki_bin(["ingest", "--title", "BERT"], drop_vault=True)
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["ingest", "--title", "BERT"]


def test_req_051__sync_without_collection_errors(zotwiki_bin):
    proc = zotwiki_bin(["sync"])
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert proc.stderr.strip()


def test_req_051__ask_without_question_errors(zotwiki_bin):
    proc = zotwiki_bin(["ask"])
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert proc.stderr.strip()


# ----- REQ-052: exit-code passthrough + unknown directive --------------------


@pytest.mark.parametrize("code", [0, 1, 2])
def test_req_052__exit_code_passthrough(zotwiki_bin, code):
    proc = zotwiki_bin(["audit"], fake_exit=code)
    assert proc.returncode == code
    assert _forwarded_argv(proc) == ["audit", "--vault", "/V"]


def test_req_052__unknown_directive_exits_2(zotwiki_bin):
    proc = zotwiki_bin(["frobnicate", "--whatever"])
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert proc.stderr.strip()
