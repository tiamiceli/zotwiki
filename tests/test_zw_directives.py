"""REQ-049–053: the `scripts/zw` operator terminal wrapper (contract §11).

Hermetic: a fake `zotwiki` executable (a small Python script) is placed in
tmp_path/bin and prepended to PATH. It echoes the argv it received as a single
`ARGV\\t<json>` line on stdout and exits with the code in $FAKE_ZOTWIKI_EXIT
(default 0). The real `zotwiki`, `claude`, Zotero, and the network are never
touched. The vault root is a real `tmp_path` directory so `zw sync`'s `mkdir -p`
of `$ZOTWIKI_VAULT/$COLLECTION` is observable. `scripts/zw` is invoked by path.

Covers:
  - REQ-049: usage/help to stdout, exit 0, zotwiki not invoked.
  - REQ-050: vault-needing directive with ZOTWIKI_VAULT unset → exit 2, one
    stderr line, zotwiki not invoked.
  - REQ-051: each directive forwards the exact zotwiki argv (vault =
    $ZOTWIKI_VAULT/$COLLECTION; sync NAME override; ingest takes no vault).
  - REQ-052: zw's exit code == the wrapped zotwiki's; unknown directive → exit 2.
  - REQ-053: zw sync creates $ZOTWIKI_VAULT/$COLLECTION; unresolved collection
    → exit 2 with no directory created.
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
    """Install a fake `zotwiki` on PATH; return (vault_root, run). run() invokes
    scripts/zw with that PATH and a real tmp vault root, returning the
    CompletedProcess."""
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

    vault_root = tmp_path / "Library"
    vault_root.mkdir()

    base_env = dict(os.environ)
    base_env["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")

    def run(args, *, vault=str(vault_root), collection="Papers",
            fake_exit=None, drop_vault=False, drop_collection=False):
        env = dict(base_env)
        env.pop("ZOTWIKI_VAULT", None)
        env.pop("ZOTWIKI_COLLECTION", None)
        if not drop_vault and vault is not None:
            env["ZOTWIKI_VAULT"] = vault
        if not drop_collection and collection is not None:
            env["ZOTWIKI_COLLECTION"] = collection
        if fake_exit is not None:
            env["FAKE_ZOTWIKI_EXIT"] = str(fake_exit)
        return subprocess.run(
            [str(ZW), *args], env=env, capture_output=True, text=True
        )

    return vault_root, run


def _forwarded_argv(proc):
    """Return the argv the fake zotwiki received, or None if it was not invoked."""
    for line in proc.stdout.splitlines():
        if line.startswith("ARGV\t"):
            return json.loads(line[len("ARGV\t"):])
    return None


# ----- REQ-049: usage / help -------------------------------------------------


@pytest.mark.parametrize("args", [[], ["help"], ["-h"], ["--help"]])
def test_req_049__usage_to_stdout_exit_0_no_zotwiki(zotwiki_bin, args):
    _, run = zotwiki_bin
    proc = run(args, drop_vault=True, drop_collection=True)
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) is None, "usage path must not invoke zotwiki"
    for directive in ("sync", "ask", "compile", "ingest", "audit"):
        assert directive in proc.stdout


# ----- REQ-050: missing ZOTWIKI_VAULT ---------------------------------------


@pytest.mark.parametrize(
    "args", [["sync"], ["ask", "why"], ["compile", "--query", "x"], ["audit"]]
)
def test_req_050__unset_vault_exits_2_no_zotwiki(zotwiki_bin, args):
    _, run = zotwiki_bin
    proc = run(args, drop_vault=True)
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None, "must not invoke zotwiki without a vault"
    assert len(proc.stderr.strip().splitlines()) == 1


def test_req_050__empty_vault_exits_2(zotwiki_bin):
    _, run = zotwiki_bin
    proc = run(["audit"], vault="")
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None


# ----- REQ-051: directive → argv forwarding (collection-scoped) --------------


def test_req_051__sync_uses_env_collection(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["sync", "--update"], collection="Papers")
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "sync", "--vault", f"{vault_root}/Papers", "--collection", "Papers",
        "--update",
    ]


def test_req_051__sync_positional_overrides_collection(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["sync", "Other", "--update"], collection="Papers")
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "sync", "--vault", f"{vault_root}/Other", "--collection", "Other",
        "--update",
    ]


def test_req_051__ask_joins_into_one_positional(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["ask", "why", "does", "X", "matter"], collection="Papers")
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "ask", "--vault", f"{vault_root}/Papers", "why does X matter"
    ]


def test_req_051__compile_forwards(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["compile", "--query", "transformers", "--limit", "5"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == [
        "compile", "--vault", f"{vault_root}/Papers", "--query", "transformers",
        "--limit", "5",
    ]


def test_req_051__audit_forwards(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["audit"])
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["audit", "--vault", f"{vault_root}/Papers"]


def test_req_051__ingest_forwards_without_vault_or_collection(zotwiki_bin):
    _, run = zotwiki_bin
    proc = run(["ingest", "--title", "BERT", "--year", "2019"],
               drop_vault=True, drop_collection=True)
    assert proc.returncode == 0, proc.stderr
    assert _forwarded_argv(proc) == ["ingest", "--title", "BERT", "--year", "2019"]


def test_req_051__ask_without_question_errors(zotwiki_bin):
    _, run = zotwiki_bin
    proc = run(["ask"])
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert proc.stderr.strip()


# ----- REQ-052: exit-code passthrough + unknown directive --------------------


@pytest.mark.parametrize("code", [0, 1, 2])
def test_req_052__exit_code_passthrough(zotwiki_bin, code):
    vault_root, run = zotwiki_bin
    proc = run(["audit"], fake_exit=code)
    assert proc.returncode == code
    assert _forwarded_argv(proc) == ["audit", "--vault", f"{vault_root}/Papers"]


def test_req_052__unknown_directive_exits_2(zotwiki_bin):
    _, run = zotwiki_bin
    proc = run(["frobnicate", "--whatever"])
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert proc.stderr.strip()


# ----- REQ-053: sync creates the folder; unresolved collection errors --------


def test_req_053__sync_creates_collection_folder(zotwiki_bin):
    vault_root, run = zotwiki_bin
    target = vault_root / "Papers"
    assert not target.exists()
    proc = run(["sync"], collection="Papers")
    assert proc.returncode == 0, proc.stderr
    assert target.is_dir(), "zw sync must mkdir -p $ZOTWIKI_VAULT/$COLLECTION"
    assert _forwarded_argv(proc) == [
        "sync", "--vault", str(target), "--collection", "Papers"
    ]


def test_req_053__sync_positional_creates_named_folder(zotwiki_bin):
    vault_root, run = zotwiki_bin
    proc = run(["sync", "Other"], drop_collection=True)
    assert proc.returncode == 0, proc.stderr
    assert (vault_root / "Other").is_dir()


@pytest.mark.parametrize("args", [["sync"], ["ask", "q"], ["compile"], ["audit"]])
def test_req_053__unresolved_collection_exits_2(zotwiki_bin, args):
    vault_root, run = zotwiki_bin
    proc = run(args, drop_collection=True)
    assert proc.returncode == 2
    assert _forwarded_argv(proc) is None
    assert len(proc.stderr.strip().splitlines()) == 1
    # no directory created on the error path
    assert list(vault_root.iterdir()) == []
