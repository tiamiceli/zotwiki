"""M6 / `zotwiki compile` (REQ-033, REQ-034): page + Index.md creation per
contract SS6 with the exact SS9.2 stdout lines; --query wire parameters;
zero-items and invalid-LLM failures; and -- per docs/rulings.md Ruling 1(d)
-- the CLI update flow over an existing page exercising the REQ-020 merge
and the REQ-031 contradictions append, byte-exact against the independent
oracles.

Black-box; fake Zotero on 127.0.0.1; FakeLLM; vaults in tmp_path; --today
always injected; all content runtime-random.
"""
from __future__ import annotations

import json

import pytest

from m2_helpers import (
    FakeLLM,
    article_to_plain_dict,
    expected_article_from_dict,
    expected_merge,
    rand_citekey,
    rand_word,
)
from m3_helpers import render_oracle, stamp_mtimes, vault_snapshot
from m4_helpers import TODAY, build_article, register_supporting_reference
from m5_helpers import (
    LATER,
    contradictions_oracle,
    distinct_titles,
    index_oracle,
    refs_for,
)
from m6_helpers import assert_compiled_line, assert_single_error_line

main = None  # bound by _require_m6_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main
    from zotwiki.cli import main as main_

    main = main_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def _prefixed_citekeys(*prefixes: str) -> list[str]:
    """Runtime-random citekeys whose sort order is pinned by prefix."""
    return [f"{prefix}{rand_citekey()}" for prefix in prefixes]


def test_req_033__compile_key_creates_page_and_index_exit_0(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    ck_a, ck_b = _prefixed_citekeys("a", "b")
    quote_a = f"alpha evidence {rand_word()} {rand_word()}"
    quote_b = f"bravo evidence {rand_word()} {rand_word()}"
    item_a = register_supporting_reference(fake_zotero, ck_a, [quote_a])
    item_b = register_supporting_reference(fake_zotero, ck_b, [quote_b])

    article = build_article([(ck_a,), (ck_a, ck_b)], title=title)
    llm = FakeLLM(json.dumps(article_to_plain_dict(article)))

    rc = main(
        ["compile", "--vault", str(vault), "--key", item_a.key,
         "--key", item_b.key, "--today", TODAY],
        store=store, llm=llm,
    )
    out = capsys.readouterr()

    assert rc == 0
    assert out.err == ""
    lines = out.out.splitlines(keepends=True)
    assert len(lines) == 1  # no contradictions line on a fresh compile
    assert_compiled_line(lines[0], title=title, vault=vault)

    # REQ-013 through the CLI: the prompt carries both items' citekeys and
    # their fulltexts (the supporting fulltexts embed the quotes verbatim).
    [prompt] = llm.prompts
    assert ck_a in prompt and ck_b in prompt
    assert quote_a in prompt and quote_b in prompt

    page = vault / f"{title}.md"
    items = {ck_a: item_a, ck_b: item_b}
    expected = render_oracle(article, refs_for(article, items),
                             created=TODAY, updated=TODAY)
    assert page.read_bytes() == expected.encode("utf-8")
    assert (vault / "Index.md").read_bytes() == index_oracle(
        [title], created=TODAY, updated=TODAY).encode("utf-8")


def test_req_033__compile_query_sends_search_wire_params(
    tmp_path, store, fake_zotero, capsys
):
    needle = f"needle{rand_word()}"
    [title] = distinct_titles(1)
    [ck] = _prefixed_citekeys("a")
    quote = f"query evidence {rand_word()}"
    item = register_supporting_reference(fake_zotero, ck, [quote])
    # Make the item findable by the query (title substring, SS4.1).
    fake_zotero.items[item.key]["data"]["title"] += f" {needle}"

    article = build_article([(ck,)], title=title)
    llm = FakeLLM(json.dumps(article_to_plain_dict(article)))

    rc = main(
        ["compile", "--vault", str(tmp_path / "v1"), "--query", needle,
         "--today", TODAY],
        store=store, llm=llm,
    )
    assert rc == 0
    searches = [
        r for r in fake_zotero.search_requests()
        if r.params.get("qmode") == ["titleCreatorYear"]
    ]
    assert len(searches) == 1
    assert searches[0].params["q"] == [needle]
    assert searches[0].params["limit"] == ["10"]  # SS9.2 --limit default

    rc = main(
        ["compile", "--vault", str(tmp_path / "v2"), "--query", needle,
         "--limit", "3", "--today", TODAY],
        store=store, llm=llm,
    )
    assert rc == 0
    searches = [
        r for r in fake_zotero.search_requests()
        if r.params.get("qmode") == ["titleCreatorYear"]
    ]
    assert len(searches) == 2
    assert searches[1].params["limit"] == ["3"]
    capsys.readouterr()  # drain

    assert (tmp_path / "v1" / f"{title}.md").is_file()
    assert (tmp_path / "v2" / f"{title}.md").is_file()


def test_req_033__compile_zero_matched_items_returns_1(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    llm = FakeLLM("must never be consulted")
    rc = main(
        ["compile", "--vault", str(vault), "--query",
         f"nomatch{rand_word()}{rand_word()}", "--today", TODAY],
        store=store, llm=llm,
    )
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert out.err == "error: no items matched\n"  # SS9.2, byte-exact
    assert llm.prompts == []
    assert not list(vault.glob("*.md"))


def test_req_033__compile_invalid_llm_output_returns_1_writes_nothing(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    [ck] = _prefixed_citekeys("a")
    item = register_supporting_reference(fake_zotero, ck, [])
    llm = FakeLLM(f"utterly not JSON {rand_word()}")

    rc = main(
        ["compile", "--vault", str(vault), "--key", item.key,
         "--today", TODAY],
        store=store, llm=llm,
    )
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)
    assert llm.prompts != []  # the LLM was consulted; its output failed
    assert not list(vault.glob("*.md"))


def test_req_034__compile_page_merges_appends_contradictions_audits_clean(
    tmp_path, store, fake_zotero, capsys
):
    """Ruling 1(d): the CLI update flow must exercise the REQ-020 merge and
    the REQ-031 contradictions append -- page bytes, Contradictions.md bytes
    and Index.md all pinned by the independent oracles, then a full CLI
    audit comes back clean."""
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    ck1, ck2 = _prefixed_citekeys("a", "b")
    quote_one = f"first evidence {rand_word()} {rand_word()}"
    quote_two = f"second evidence {rand_word()} {rand_word()}"
    item_one = register_supporting_reference(fake_zotero, ck1, [quote_one])
    item_two = register_supporting_reference(fake_zotero, ck2, [quote_two])

    claim_one_text = f"Original claim {rand_word()} holds."
    version_one = {
        "title": title,
        "summary": f"First synthesis {rand_word()}.",
        "sections": [
            {"heading": "Background", "body": f"Original {rand_word()} body."}
        ],
        "claims": [
            {"text": claim_one_text, "citekeys": [ck1],
             "quotes": [{"citekey": ck1, "text": quote_one}]}
        ],
        "links": [],
    }
    rc = main(
        ["compile", "--vault", str(vault), "--key", item_one.key,
         "--today", TODAY],
        store=store, llm=FakeLLM(json.dumps(version_one)),
    )
    capsys.readouterr()
    assert rc == 0
    existing = expected_article_from_dict(version_one)[0]

    version_two = {
        "title": title,
        "summary": f"Second synthesis {rand_word()}.",
        "sections": [
            {"heading": "Background", "body": f"Replaced {rand_word()} body."}
        ],
        "claims": [
            {"text": f"Newer claim {rand_word()} extends.", "citekeys": [ck2],
             "quotes": [{"citekey": ck2, "text": quote_two}]}
        ],
        "links": [],
        "contradictions": [
            {"existing_claim": claim_one_text,
             "new_claim": f"Contrary result {rand_word()}.",
             "citekeys": [ck2]}
        ],
    }
    update_llm = FakeLLM(json.dumps(version_two))
    rc = main(
        ["compile", "--vault", str(vault), "--page", title,
         "--key", item_two.key, "--today", LATER],
        store=store, llm=update_llm,
    )
    out = capsys.readouterr()
    assert rc == 0
    assert out.err == ""

    # SS9.2 steps 4+5: compiled line, then contradictions line, nothing else.
    lines = out.out.splitlines(keepends=True)
    assert len(lines) == 2
    assert_compiled_line(lines[0], title=title, vault=vault)
    assert lines[1] == f"contradictions\t{title}\t1\n"

    # SS7.1 step 2: the update prompt embeds the existing article's JSON.
    embedded = json.dumps(article_to_plain_dict(existing), sort_keys=True)
    assert embedded in update_llm.prompts[0]

    # REQ-020 via CLI: mechanical merge, created kept, updated bumped.
    update, contradictions = expected_article_from_dict(version_two)
    merged = expected_merge(existing, update)
    items = {ck1: item_one, ck2: item_two}
    expected_page = render_oracle(merged, refs_for(merged, items),
                                  created=TODAY, updated=LATER)
    assert (vault / f"{title}.md").read_bytes() == expected_page.encode("utf-8")

    # REQ-031 via CLI: append-only Contradictions.md per SS6.8.
    assert len(contradictions) == 1
    expected_contra = contradictions_oracle(
        [(title, LATER, contradictions)], created=LATER, updated=LATER
    )
    assert (vault / "Contradictions.md").read_bytes() == (
        expected_contra.encode("utf-8")
    )

    # No new titles: Index.md still its creation-time bytes.
    assert (vault / "Index.md").read_bytes() == index_oracle(
        [title], created=TODAY, updated=TODAY).encode("utf-8")

    # The post-update vault passes a full CLI audit (plan SS M6 done-loop).
    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "audit: ok (1 pages)\n"


def test_req_034__compile_page_title_mismatch_returns_1_nothing_written(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    title, other_title = distinct_titles(2)
    [ck] = _prefixed_citekeys("a")
    item = register_supporting_reference(fake_zotero, ck, [])

    seed = build_article([(ck,)], title=title)
    rc = main(
        ["compile", "--vault", str(vault), "--key", item.key,
         "--today", TODAY],
        store=store, llm=FakeLLM(json.dumps(article_to_plain_dict(seed))),
    )
    capsys.readouterr()
    assert rc == 0

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    impostor = build_article([(ck,)], title=other_title)
    rc = main(
        ["compile", "--vault", str(vault), "--page", title,
         "--key", item.key, "--today", LATER],
        store=store, llm=FakeLLM(json.dumps(article_to_plain_dict(impostor))),
    )
    out = capsys.readouterr()
    assert rc == 1
    assert out.out == ""
    assert_single_error_line(out.err)
    assert vault_snapshot(vault) == before  # bytes AND mtimes untouched
    assert not (vault / f"{other_title}.md").exists()
