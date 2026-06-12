"""M6 / exit-code mapping (REQ-037, contract SS9.3): each mapped exception
class is provoked through a real command (fake-store failure injection,
corrupt vaults, unresolvable citekeys, usage errors) and must yield exactly
its table code, with exactly one `error: {message}` line on stderr and an
empty stdout (audit violations excepted -- covered in test_m6_cli_audit).
Also pins EXIT_OK/EXIT_FAIL/EXIT_ENV and `python -m zotwiki` (SS9.1).

Black-box; in-memory recording store (no sockets) plus tmp_path vaults;
FakeLLM sentinels prove which failures fire before any LLM call.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from zotwiki.errors import ZoteroUnavailableError

from m2_helpers import FakeLLM, article_to_plain_dict, rand_citekey, rand_word
from m4_helpers import TODAY, build_article
from m5_helpers import distinct_titles
from m6_helpers import (
    InMemoryStore,
    assert_single_error_line,
    supporting_fulltext,
    write_static_vault,
)

main = None  # bound by _require_m6_surface
EXIT_OK = EXIT_FAIL = EXIT_ENV = None


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main, EXIT_OK, EXIT_FAIL, EXIT_ENV
    from zotwiki.cli import EXIT_ENV as EXIT_ENV_
    from zotwiki.cli import EXIT_FAIL as EXIT_FAIL_
    from zotwiki.cli import EXIT_OK as EXIT_OK_
    from zotwiki.cli import main as main_

    main = main_
    EXIT_OK = EXIT_OK_
    EXIT_FAIL = EXIT_FAIL_
    EXIT_ENV = EXIT_ENV_


@pytest.fixture
def memstore():
    return InMemoryStore()


def _assert_failure(capsys, rc, expected_code):
    out = capsys.readouterr()
    assert rc == expected_code
    assert out.out == ""
    assert_single_error_line(out.err)


def test_req_037__exit_constants_match_the_contract_table():
    assert (EXIT_OK, EXIT_FAIL, EXIT_ENV) == (0, 1, 2)


def test_req_037__item_not_found_maps_to_1(tmp_path, memstore, capsys):
    llm = FakeLLM("must never be consulted")
    rc = main(
        ["compile", "--vault", str(tmp_path / "v"), "--key", "NOSUCHK1",
         "--today", TODAY],
        store=memstore, llm=llm,
    )
    _assert_failure(capsys, rc, 1)
    assert llm.prompts == []
    assert memstore.method_calls("get")  # the store really was consulted


def test_req_037__citekey_not_found_maps_to_1_before_any_llm_call(
    tmp_path, memstore, capsys
):
    item = memstore.put(citekey="")  # no Citation Key line (REQ-015)
    llm = FakeLLM("must never be consulted")
    rc = main(
        ["compile", "--vault", str(tmp_path / "v"), "--key", item.key,
         "--today", TODAY],
        store=memstore, llm=llm,
    )
    _assert_failure(capsys, rc, 1)
    assert llm.prompts == []  # SS7.1: raised before any LLM call


def test_req_037__fulltext_not_found_maps_to_1(tmp_path, memstore, capsys):
    from zotwiki.errors import FulltextNotFoundError

    item = memstore.put(citekey=rand_citekey(),
                        fulltext=f"present {rand_word()}")
    memstore.raises["fulltext"] = FulltextNotFoundError("injected loss")
    rc = main(
        ["compile", "--vault", str(tmp_path / "v"), "--key", item.key,
         "--today", TODAY],
        store=memstore, llm=FakeLLM("must never be consulted"),
    )
    _assert_failure(capsys, rc, 1)
    assert memstore.method_calls("fulltext")


def test_req_037__article_schema_error_maps_to_1(tmp_path, memstore, capsys):
    # Contradictions without an existing page (SS7.1 step 4).
    ck = rand_citekey()
    item = memstore.put(citekey=ck)
    [title] = distinct_titles(1)
    payload = article_to_plain_dict(build_article([(ck,)], title=title))
    payload["contradictions"] = [{
        "existing_claim": f"Old {rand_word()}.",
        "new_claim": f"New {rand_word()}.",
        "citekeys": [ck],
    }]
    vault = tmp_path / "v"
    rc = main(
        ["compile", "--vault", str(vault), "--key", item.key,
         "--today", TODAY],
        store=memstore, llm=FakeLLM(json.dumps(payload)),
    )
    _assert_failure(capsys, rc, 1)
    assert not list(vault.glob("*.md"))  # nothing written


def test_req_037__page_parse_error_maps_to_1_before_any_llm_call(
    tmp_path, memstore, capsys
):
    [title] = distinct_titles(1)
    ck = rand_citekey()
    item = memstore.put(citekey=ck)
    vault = tmp_path / "vault"
    vault.mkdir()
    corrupt = f"this is not a zotwiki page {rand_word()}\n"
    page = vault / f"{title}.md"
    page.write_text(corrupt, encoding="utf-8")

    llm = FakeLLM("must never be consulted")
    rc = main(
        ["compile", "--vault", str(vault), "--page", title,
         "--key", item.key, "--today", TODAY],
        store=memstore, llm=llm,
    )
    _assert_failure(capsys, rc, 1)
    assert llm.prompts == []  # SS9.2 step 2 fails before step 3
    assert page.read_text(encoding="utf-8") == corrupt  # file untouched


@pytest.mark.parametrize("command", ["ingest", "compile", "audit"])
def test_req_037__zotero_unavailable_maps_to_2(
    tmp_path, memstore, capsys, command
):
    [title] = distinct_titles(1)
    ck = rand_citekey()
    if command == "ingest":
        memstore.raises["add"] = ZoteroUnavailableError("injected outage")
        argv = ["ingest", "--title", f"T {rand_word()}"]
    elif command == "compile":
        memstore.raises["get"] = ZoteroUnavailableError("injected outage")
        argv = ["compile", "--vault", str(tmp_path / "v"), "--key",
                "AAAA1111", "--today", TODAY]
    else:
        vault = tmp_path / "vault"
        article = write_static_vault(vault, title, ck)
        memstore.put(citekey=ck, fulltext=supporting_fulltext(article))
        memstore.raises["resolve"] = ZoteroUnavailableError("injected outage")
        argv = ["audit", "--vault", str(vault)]

    rc = main(argv, store=memstore, llm=FakeLLM("must never be consulted"))
    _assert_failure(capsys, rc, 2)


def test_req_037__vault_error_maps_to_2(tmp_path, memstore, capsys):
    rc = main(
        ["audit", "--vault", str(tmp_path / f"gone{rand_word()}")],
        store=memstore,
    )
    _assert_failure(capsys, rc, 2)

    empty = tmp_path / "empty"
    empty.mkdir()
    llm = FakeLLM("must never be consulted")
    rc = main(["ask", "--vault", str(empty), "Q?"],
              store=memstore, llm=llm)
    _assert_failure(capsys, rc, 2)
    assert llm.prompts == []


@pytest.mark.parametrize(
    "argv_builder",
    [
        lambda v: [],                                      # no subcommand
        lambda v: ["frobnicate"],                          # unknown command
        lambda v: ["ingest"],                              # missing --title
        lambda v: ["compile", "--key", "AAAA1111"],        # missing --vault
        lambda v: ["compile", "--vault", v],               # no --key/--query
        lambda v: ["compile", "--vault", v, "--key", "AAAA1111",
                   "--query", "q"],                        # exclusive group
        lambda v: ["audit"],                               # missing --vault
        lambda v: ["ask", "--vault", v],                   # missing QUESTION
    ],
    ids=[
        "no-subcommand", "unknown-subcommand", "ingest-no-title",
        "compile-no-vault", "compile-no-items", "compile-key-and-query",
        "audit-no-vault", "ask-no-question",
    ],
)
def test_req_037__usage_errors_return_2_without_sys_exit(
    tmp_path, memstore, capsys, argv_builder
):
    vault = tmp_path / "vault"
    vault.mkdir()
    # If main leaked argparse's SystemExit, this call would abort the test
    # instead of returning -- returning an int IS the assertion (SS9.1).
    rc = main(argv_builder(str(vault)), store=memstore,
              llm=FakeLLM("must never be consulted"))
    assert isinstance(rc, int) and not isinstance(rc, bool)
    _assert_failure(capsys, rc, 2)


def test_req_037__python_dash_m_zotwiki_exits_2_on_usage_error(tmp_path):
    """SS9.1: `python -m zotwiki` runs sys.exit(main()) via __main__.py.
    A bare invocation is an argparse usage error -> process exit code 2 and
    the single SS9.3 error line.  Subprocess of our own package only; the
    failure happens in argparse, long before any I/O."""
    repo_src = Path(__file__).resolve().parent.parent / "src"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(repo_src)
    env.pop("ANTHROPIC_API_KEY", None)
    env.pop("ZOTWIKI_MODEL", None)
    proc = subprocess.run(
        [sys.executable, "-m", "zotwiki"],
        capture_output=True, text=True, env=env, cwd=str(tmp_path),
        timeout=60,
    )
    assert proc.returncode == 2
    assert proc.stdout == ""
    assert_single_error_line(proc.stderr)
