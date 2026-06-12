"""M6 / `zotwiki ask` (REQ-036) and the zotwiki.ask surface: exact SS9.2
stdout (answer, blank line, `Sources:`, one `- [[page]] [@citekey]` line per
pair in given order), SS9.5 prompt and validation rules (question + every
entity page's full text in the prompt; cited pages must exist; citekeys must
be frontmatter members), fence tolerance, and the VaultError exits with the
LLM provably never called.

Black-box; vaults built through the frozen M3 publisher against the
127.0.0.1 fake Zotero; FakeLLM; all content runtime-random.
"""
from __future__ import annotations

import pytest

from m2_helpers import FakeLLM, rand_citekey, rand_word
from m3_helpers import cited_citekeys
from m4_helpers import build_article, distinct_citekeys, publish_clean_vault
from m5_helpers import distinct_titles
from m6_helpers import (
    ask_payload,
    assert_single_error_line,
    expected_ask_stdout,
)

main = None  # bound by _require_m6_surface
ask = None
Answer = None
SourceRef = None


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error."""
    global main, ask, Answer, SourceRef
    from zotwiki.ask import Answer as Answer_
    from zotwiki.ask import SourceRef as SourceRef_
    from zotwiki.ask import ask as ask_
    from zotwiki.cli import main as main_

    main = main_
    ask = ask_
    Answer = Answer_
    SourceRef = SourceRef_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


@pytest.fixture
def two_page_vault(tmp_path, store, fake_zotero):
    """A clean two-page vault; returns (vault, {title: article})."""
    vault = tmp_path / "vault"
    title_a, title_b = distinct_titles(2)
    ck_a, ck_b, ck_c = distinct_citekeys(3)
    articles = {
        title_a: build_article([(ck_a,), (ck_b,)], title=title_a),
        title_b: build_article([(ck_c,)], title=title_b),
    }
    publish_clean_vault(fake_zotero, store, vault, list(articles.values()))
    return vault, articles


def test_req_036__answer_with_cited_sources_exact_stdout(
    two_page_vault, capsys
):
    vault, articles = two_page_vault
    question = f"What do {rand_word()} {rand_word()} eat?"
    answer = f"They mostly eat {rand_word()} and {rand_word()}."
    # Source pages deliberately in REVERSE-sorted order: SS9.2 prints pages
    # in the order the answer gave them, not re-sorted.
    pages = sorted(articles, reverse=True)
    sources = [(page, cited_citekeys(articles[page])) for page in pages]
    assert any(len(cks) > 1 for _, cks in sources)  # multi-citekey source

    llm = FakeLLM(ask_payload(answer, sources))
    rc = main(["ask", "--vault", str(vault), question], llm=llm)
    out = capsys.readouterr()

    assert rc == 0
    assert out.err == ""
    assert out.out == expected_ask_stdout(answer, sources)

    # SS9.5 step 2: prompt contains the question and the full text of every
    # entity page.
    [prompt] = llm.prompts
    assert question in prompt
    for title in articles:
        page_text = (vault / f"{title}.md").read_text(encoding="utf-8")
        assert page_text in prompt


def test_req_036__fenced_answer_json_is_tolerated(two_page_vault, capsys):
    vault, articles = two_page_vault
    title = sorted(articles)[0]
    answer = f"Fenced result {rand_word()}."
    sources = [(title, cited_citekeys(articles[title]))]
    fenced = f"```json\n{ask_payload(answer, sources)}\n```"

    rc = main(["ask", "--vault", str(vault), f"Q {rand_word()}?"],
              llm=FakeLLM(fenced))
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == expected_ask_stdout(answer, sources)
    assert out.err == ""


def test_req_036__empty_sources_render_bare_sources_block(
    two_page_vault, capsys
):
    vault, _articles = two_page_vault
    answer = f"Nothing relevant {rand_word()}."
    rc = main(["ask", "--vault", str(vault), f"Q {rand_word()}?"],
              llm=FakeLLM(ask_payload(answer, [])))
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == f"{answer}\n\nSources:\n"
    assert out.err == ""


def test_req_036__nonexistent_page_citation_returns_1(
    two_page_vault, capsys
):
    vault, articles = two_page_vault
    ghost = f"Ghost {rand_word().capitalize()} {rand_word().capitalize()}"
    assert not (vault / f"{ghost}.md").exists()
    payload = ask_payload(f"Wrong {rand_word()}.", [(ghost, [rand_citekey()])])

    rc = main(["ask", "--vault", str(vault), "Q?"], llm=FakeLLM(payload))
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)


def test_req_036__citekey_outside_page_frontmatter_returns_1(
    two_page_vault, capsys
):
    vault, articles = two_page_vault
    title = sorted(articles)[0]
    foreign = rand_citekey()
    assert foreign not in cited_citekeys(articles[title])
    payload = ask_payload(f"Wrong {rand_word()}.", [(title, [foreign])])

    rc = main(["ask", "--vault", str(vault), "Q?"], llm=FakeLLM(payload))
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)


def test_req_036__special_page_is_not_a_citable_source(
    two_page_vault, capsys
):
    # Index.md exists but is not an entity page (SS6.1 / SS9.5 step 4).
    vault, _articles = two_page_vault
    assert (vault / "Index.md").is_file()
    payload = ask_payload(f"Wrong {rand_word()}.", [("Index", [rand_citekey()])])

    rc = main(["ask", "--vault", str(vault), "Q?"], llm=FakeLLM(payload))
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d.pop("sources"),                      # missing key
        lambda d: d.pop("answer"),                       # missing key
        lambda d: d.update(extra="nope"),                # unknown top key
        lambda d: d.update(answer=""),                   # empty answer
        lambda d: d["sources"][0].pop("citekeys"),       # entry missing key
        lambda d: d["sources"][0].update(citekeys=[]),   # len >= 1 required
        lambda d: d["sources"][0].update(note="x"),      # unknown entry key
    ],
    ids=[
        "no-sources", "no-answer", "extra-top-key", "empty-answer",
        "entry-no-citekeys", "entry-empty-citekeys", "entry-extra-key",
    ],
)
def test_req_036__malformed_answer_json_returns_1(
    two_page_vault, capsys, mutate
):
    import json

    vault, articles = two_page_vault
    title = sorted(articles)[0]
    payload = json.loads(
        ask_payload(f"A {rand_word()}.", [(title, cited_citekeys(articles[title]))])
    )
    mutate(payload)

    rc = main(["ask", "--vault", str(vault), "Q?"],
              llm=FakeLLM(json.dumps(payload)))
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)


def test_req_036__vault_without_entity_pages_returns_2_llm_never_called(
    tmp_path, capsys
):
    vault = tmp_path / "vault"
    vault.mkdir()
    llm = FakeLLM("must never be consulted")
    rc = main(["ask", "--vault", str(vault), f"Q {rand_word()}?"], llm=llm)
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert_single_error_line(out.err)
    assert llm.prompts == []  # REQ-036: the LLM is never called


def test_req_036__missing_vault_returns_2(tmp_path, capsys):
    llm = FakeLLM("must never be consulted")
    rc = main(
        ["ask", "--vault", str(tmp_path / f"never{rand_word()}"), "Q?"],
        llm=llm,
    )
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert_single_error_line(out.err)
    assert llm.prompts == []


def test_req_036__ask_function_returns_answer_with_sourcerefs(
    two_page_vault
):
    vault, articles = two_page_vault
    question = f"How do {rand_word()} interact?"
    answer = f"Through {rand_word()} coupling."
    pages = sorted(articles, reverse=True)
    sources = [(page, cited_citekeys(articles[page])) for page in pages]

    result = ask(vault, question, FakeLLM(ask_payload(answer, sources)))

    assert isinstance(result, Answer)
    assert result.text == answer
    assert result.sources == tuple(
        SourceRef(page=page, citekeys=tuple(cks)) for page, cks in sources
    )
