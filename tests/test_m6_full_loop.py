"""M6 / the plan SS M6 done-loop, in-process against the 127.0.0.1 fakes:

    ingest -> compile --today -> audit (exit 0) -> corrupt -> audit (exit 1)
    -> ask with cited sources

with the exact SS9.2 stdout bytes at every step, all data runtime-random
(the compile step cites the citekey the ingest step generated, parsed back
out of ingest's own stdout).
"""
from __future__ import annotations

import json
import random

import pytest

from zotwiki.models import SourceItem

from m2_helpers import FakeLLM, expected_article_from_dict, rand_word
from m3_helpers import render_oracle
from m4_helpers import TODAY, fulltext_containing
from m5_helpers import distinct_titles, index_oracle
from m6_helpers import (
    ask_payload,
    assert_compiled_line,
    expected_ask_stdout,
    expected_citekey,
)

main = None  # bound by _require_m6_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main
    from zotwiki.cli import main as main_

    main = main_


def test_req_037__ingest_compile_audit_corrupt_audit_ask_full_loop(
    tmp_path, zstore, fake_zotero, capsys
):
    store, _ = zstore()
    vault = tmp_path / "vault"
    [page_title] = distinct_titles(1)

    # --- ingest ----------------------------------------------------------
    word = rand_word()
    source_title = f"A Study of {word.capitalize()} Migration"
    first, last = rand_word().capitalize(), rand_word().capitalize()
    year = random.randint(1900, 2099)
    url = f"https://{rand_word()}.example"
    rc = main(
        ["ingest", "--title", source_title, "--url", url,
         "--creator", f"{first} {last}", "--year", str(year)],
        store=store,
    )
    out = capsys.readouterr()
    assert rc == 0
    citekey = expected_citekey(title=source_title,
                               creators=(f"{first} {last}",), year=year)
    [key] = fake_zotero.created_keys
    assert out.out == f"{citekey}\t{key}\n"
    # Downstream steps consume ingest's OWN stdout, like a shell user would.
    stdout_citekey, stdout_key = out.out.rstrip("\n").split("\t")
    assert (stdout_citekey, stdout_key) == (citekey, key)

    # The library indexes the attachment: fulltext appears server-side.
    quote = f"the {word} population {rand_word()} measurably {rand_word()}"
    fake_zotero.fulltext[stdout_key] = fulltext_containing([quote])

    # --- compile --today --------------------------------------------------
    payload = {
        "title": page_title,
        "summary": f"A synthesis about {word} {rand_word()}.",
        "sections": [
            {"heading": f"Findings {rand_word()}",
             "body": f"Body {rand_word()} text."}
        ],
        "claims": [
            {"text": f"Migration {rand_word()} shifts measurably.",
             "citekeys": [stdout_citekey],
             "quotes": [{"citekey": stdout_citekey, "text": quote}]}
        ],
        "links": [],
    }
    llm = FakeLLM(json.dumps(payload))
    rc = main(
        ["compile", "--vault", str(vault), "--key", stdout_key,
         "--today", TODAY],
        store=store, llm=llm,
    )
    out = capsys.readouterr()
    assert rc == 0
    lines = out.out.splitlines(keepends=True)
    assert len(lines) == 1
    assert_compiled_line(lines[0], title=page_title, vault=vault)
    [prompt] = llm.prompts
    assert stdout_citekey in prompt and source_title in prompt
    assert quote in prompt  # the fulltext reached the prompt

    article = expected_article_from_dict(payload)[0]
    ingested_item = SourceItem(
        key=stdout_key, citekey=stdout_citekey, title=source_title,
        creators=(f"{first} {last}",), year=year, url=url,
        has_fulltext=True,
    )
    expected_page = render_oracle(article, [ingested_item],
                                  created=TODAY, updated=TODAY)
    assert (vault / f"{page_title}.md").read_bytes() == (
        expected_page.encode("utf-8")
    )
    assert (vault / "Index.md").read_bytes() == index_oracle(
        [page_title], created=TODAY, updated=TODAY).encode("utf-8")

    # --- audit: clean -> exit 0 -------------------------------------------
    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "audit: ok (1 pages)\n"
    assert out.err == ""

    # --- corrupt: the cited item vanishes from the library -----------------
    del fake_zotero.items[stdout_key]
    fake_zotero.fulltext.pop(stdout_key, None)

    # --- audit: violation -> exit 1, exact report lines --------------------
    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 1
    assert out.err == ""
    assert out.out == (
        f"CITEKEY_UNRESOLVED\t{page_title}.md\t{stdout_citekey}\n"
        "audit: 1 violation(s)\n"
    )

    # --- ask with cited sources --------------------------------------------
    question = f"How does {word} migration {rand_word()}?"
    answer = f"It shifts {rand_word()} measurably."
    sources = [(page_title, [stdout_citekey])]
    ask_llm = FakeLLM(ask_payload(answer, sources))
    rc = main(["ask", "--vault", str(vault), question],
              store=store, llm=ask_llm)
    out = capsys.readouterr()
    assert rc == 0
    assert out.err == ""
    assert out.out == expected_ask_stdout(answer, sources)
    assert question in ask_llm.prompts[0]
    page_text = (vault / f"{page_title}.md").read_text(encoding="utf-8")
    assert page_text in ask_llm.prompts[0]
