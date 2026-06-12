"""M6 / injection seam (REQ-038): with `store=` and `llm=` injected and the
environment empty, no real adapter or LLM client may touch any socket -- a
monkeypatched socket layer fails the test on the first outgoing connection
attempt while the whole ingest -> compile -> audit -> ask loop runs offline
against recording fakes.  Plus: `--zotero-url` is ignored when a store is
injected, env sentinels are never consulted when an LLM is injected,
ingest/audit need no LLM configuration, and the SS9.4 unconfigured-LLM
failure is exit 2 with the exact `error: LLM not configured` line.

Black-box; pure in-memory store; FakeLLM; vaults in tmp_path; zero sockets.
"""
from __future__ import annotations

import json

import pytest

from m2_helpers import FakeLLM, article_to_plain_dict, rand_citekey, rand_word
from m3_helpers import render_oracle
from m4_helpers import TODAY, build_article, closed_port
from m5_helpers import distinct_titles, index_oracle
from m6_helpers import (
    InMemoryStore,
    ask_payload,
    assert_compiled_line,
    clear_llm_env,
    expected_ask_stdout,
    install_network_guard,
    supporting_fulltext,
    write_static_vault,
)

main = None  # bound by _require_m6_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main
    from zotwiki.cli import main as main_

    main = main_


@pytest.fixture
def offline(monkeypatch):
    """REQ-038 preconditions: no LLM env vars, every outgoing socket
    connection attempt recorded and failed."""
    clear_llm_env(monkeypatch)
    return install_network_guard(monkeypatch)


def test_req_038__full_cli_loop_offline_touches_no_socket(
    tmp_path, offline, capsys
):
    store = InMemoryStore()
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    ck = rand_citekey()
    article = build_article([(ck,)], title=title)
    item = store.put(citekey=ck, fulltext=supporting_fulltext(article))

    # ingest -- stdout echoes whatever the injected store returned.
    rc = main(["ingest", "--title", f"Offline {rand_word()}",
               "--creator", f"{rand_word().capitalize()} "
                            f"{rand_word().capitalize()}"],
              store=store)
    out = capsys.readouterr()
    assert rc == 0
    [added] = store.added
    assert out.out == f"{added.citekey}\t{added.key}\n"
    assert out.err == ""

    # compile -- publisher resolution included, all through the fake.
    llm = FakeLLM(json.dumps(article_to_plain_dict(article)))
    rc = main(["compile", "--vault", str(vault), "--key", item.key,
               "--today", TODAY],
              store=store, llm=llm)
    out = capsys.readouterr()
    assert rc == 0
    lines = out.out.splitlines(keepends=True)
    assert len(lines) == 1
    assert_compiled_line(lines[0], title=title, vault=vault)
    expected_page = render_oracle(article, [item], created=TODAY,
                                  updated=TODAY)
    assert (vault / f"{title}.md").read_bytes() == expected_page.encode("utf-8")
    assert llm.prompts != []

    # audit -- resolve + fulltext checks all served from memory.
    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "audit: ok (1 pages)\n"

    # ask -- cited sources from the page just compiled.
    question = f"What does {rand_word()} show?"
    answer = f"It shows {rand_word()}."
    ask_llm = FakeLLM(ask_payload(answer, [(title, [ck])]))
    rc = main(["ask", "--vault", str(vault), question],
              store=store, llm=ask_llm)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == expected_ask_stdout(answer, [(title, [ck])])
    assert question in ask_llm.prompts[0]

    # The fakes were exercised; the network never was.
    for method in ("add", "get", "resolve", "fulltext"):
        assert store.method_calls(method), f"store.{method} never called"
    assert offline == []


def test_req_038__compile_without_llm_config_returns_2_no_network(
    tmp_path, offline, capsys
):
    store = InMemoryStore()
    item = store.put(citekey=rand_citekey())
    vault = tmp_path / "vault"
    rc = main(["compile", "--vault", str(vault), "--key", item.key,
               "--today", TODAY],
              store=store)  # llm NOT injected, env empty
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert out.err == "error: LLM not configured\n"  # SS9.4, byte-exact
    assert not list(vault.glob("*.md"))
    assert offline == []


def test_req_038__ask_without_llm_config_returns_2_no_network(
    tmp_path, offline, capsys
):
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    write_static_vault(vault, title, rand_citekey())
    rc = main(["ask", "--vault", str(vault), f"Q {rand_word()}?"],
              store=InMemoryStore())  # llm NOT injected, env empty
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert out.err == "error: LLM not configured\n"
    assert offline == []


def test_req_038__ingest_and_audit_never_need_llm_config(
    tmp_path, offline, capsys
):
    store = InMemoryStore()
    rc = main(["ingest", "--title", f"NoLLM {rand_word()}"], store=store)
    out = capsys.readouterr()
    assert rc == 0
    [added] = store.added
    assert out.out == f"{added.citekey}\t{added.key}\n"

    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    ck = rand_citekey()
    article = write_static_vault(vault, title, ck)
    store.put(citekey=ck, fulltext=supporting_fulltext(article))
    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "audit: ok (1 pages)\n"
    assert offline == []


def test_req_038__injected_store_wins_over_zotero_url(offline, capsys):
    """SS9.2: --zotero-url is ignored when `store` is injected -- pointing
    it at a dead port must not matter and nothing may be dialed."""
    store = InMemoryStore()
    dead = f"http://127.0.0.1:{closed_port()}/api/users/0"
    rc = main(["--zotero-url", dead, "ingest",
               "--title", f"Routed {rand_word()}"],
              store=store)
    out = capsys.readouterr()
    assert rc == 0
    [added] = store.added
    assert out.out == f"{added.citekey}\t{added.key}\n"
    assert store.method_calls("add")
    assert offline == []


def test_req_038__env_sentinels_unused_when_llm_injected(
    tmp_path, monkeypatch, capsys
):
    """With llm= injected, ANTHROPIC_API_KEY/ZOTWIKI_MODEL must never be
    acted on: the page content provably comes from the injected fake and no
    socket is opened toward any API."""
    attempts = install_network_guard(monkeypatch)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-sentinel-do-not-use")
    monkeypatch.setenv("ZOTWIKI_MODEL", "sentinel-model-do-not-use")

    store = InMemoryStore()
    [title] = distinct_titles(1)
    ck = rand_citekey()
    article = build_article([(ck,)], title=title)
    item = store.put(citekey=ck, fulltext=supporting_fulltext(article))
    llm = FakeLLM(json.dumps(article_to_plain_dict(article)))

    vault = tmp_path / "vault"
    rc = main(["compile", "--vault", str(vault), "--key", item.key,
               "--today", TODAY],
              store=store, llm=llm)
    capsys.readouterr()
    assert rc == 0
    assert llm.prompts != []  # the injected fake answered ...
    expected_page = render_oracle(article, [item], created=TODAY,
                                  updated=TODAY)
    assert (vault / f"{title}.md").read_bytes() == expected_page.encode("utf-8")
    assert (vault / "Index.md").read_bytes() == index_oracle(
        [title], created=TODAY, updated=TODAY).encode("utf-8")
    assert attempts == []  # ... and nothing was dialed
