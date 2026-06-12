"""M5 end-to-end: the compiler's update mode (REQ-014) and the never-clobber
merge matrix (REQ-016) re-run through the full public surface -- compile with
`existing` (FakeLLM) -> VaultPublisher update publish -> publish_contradictions
-> full audit still clean -- plus a publish->update->audit invariant property
over random vaults (REQ-020/022).

Black-box; fake Zotero on 127.0.0.1; FakeLLM from m2_helpers; vaults in
tmp_path; `today` injected; expectations come from the independent oracles
(SS7.2 merge in m2_helpers, SS6 page renderer in m3_helpers, SS6.7/SS6.8 in
m5_helpers), never from zotwiki itself.
"""
from __future__ import annotations

import itertools
import json

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zotwiki.auditor import Auditor
from zotwiki.compiler import Compiler
from zotwiki.llm import article_to_json_dict
from zotwiki.models import Article, Claim, Quote, Section
from zotwiki.publisher import (
    CONTRADICTIONS_FILENAME,
    INDEX_FILENAME,
    VaultPublisher,
    parse_page,
)

from m2_helpers import (
    FakeLLM,
    expected_article_from_dict,
    expected_merge,
    rand_citekey,
    rand_word,
)
from m3_helpers import render_oracle
from m4_helpers import (
    build_article,
    clean_vault_articles,
    distinct_citekeys,
    register_supporting_reference,
    register_supporting_references,
)
from m5_helpers import (
    LATER,
    TODAY,
    article_citekeys,
    contradictions_oracle,
    distinct_titles,
    index_oracle,
    refs_for,
    register_citekey_map,
)

SETTINGS = settings(
    deadline=None,
    max_examples=8,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_DIRS = itertools.count()


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_014__compile_with_existing_then_publish_then_audit_full_loop(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    ck1, ck2 = distinct_citekeys(2)
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
    result_one = Compiler(store, FakeLLM(json.dumps(version_one))).compile(
        [item_one.key]
    )
    assert result_one.contradictions == ()
    page = VaultPublisher(vault, store, today=TODAY).publish(
        result_one.article
    )
    first_report = Auditor(vault, store).audit()
    assert first_report.ok is True
    assert first_report.pages_checked == 1

    # The on-disk page round-trips into `existing` for update mode.
    existing = parse_page(page.read_text(encoding="utf-8"))
    assert existing == result_one.article

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
             "citekeys": [ck2]},
            {"existing_claim": claim_one_text,
             "new_claim": f"Second contrary result {rand_word()}.",
             "citekeys": sorted([ck1, ck2])},
        ],
    }
    update_llm = FakeLLM(json.dumps(version_two))
    result_two = Compiler(store, update_llm).compile(
        [item_two.key], existing=existing
    )

    # REQ-014 end to end: the update prompt embeds the existing article JSON
    # and the contradictions come back parsed, in order.
    embedded = json.dumps(article_to_json_dict(existing), sort_keys=True)
    assert embedded in update_llm.prompts[0]
    expected_update, expected_contradictions = expected_article_from_dict(
        version_two
    )
    assert len(expected_contradictions) == 2
    assert result_two.article == expected_update  # the compiler did not merge
    assert result_two.contradictions == expected_contradictions

    update_publisher = VaultPublisher(vault, store, today=LATER)
    update_publisher.publish(result_two.article)
    merged = expected_merge(existing, result_two.article)
    items = {ck1: item_one, ck2: item_two}
    expected_page = render_oracle(merged, refs_for(merged, items),
                                  created=TODAY, updated=LATER)
    assert page.read_bytes() == expected_page.encode("utf-8")

    update_publisher.publish_contradictions(title, result_two.contradictions)
    expected_contra = contradictions_oracle(
        [(title, LATER, result_two.contradictions)],
        created=LATER, updated=LATER,
    )
    assert (vault / CONTRADICTIONS_FILENAME).read_bytes() == (
        expected_contra.encode("utf-8")
    )

    assert (vault / INDEX_FILENAME).read_bytes() == index_oracle(
        [title], created=TODAY, updated=TODAY).encode("utf-8")

    final_report = Auditor(vault, store).audit()
    assert final_report.violations == ()
    assert final_report.ok is True
    assert final_report.pages_checked == 1


def test_req_016__never_clobber_matrix_survives_publisher_round_trip(
    tmp_path, store, fake_zotero
):
    """The full REQ-016 matrix, end to end through the vault: kept section,
    replaced body, appended section, kept claim, merged claim (existing text
    wins, citekey union, quote union), appended claim, link union, summary
    replaced -- all on disk, byte-exact."""
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    # Prefixes force the sorted order a < b < c < d for suffix assertions.
    ck_a, ck_b, ck_c, ck_d = (
        f"{prefix}{rand_citekey()}" for prefix in ("a", "b", "c", "d")
    )
    intro_body = f"Intro body {rand_word()}."
    method_old = f"Method body {rand_word()} one."
    method_new = f"Method body {rand_word()} two."
    results_body = f"Results body {rand_word()}."
    claim_one = f"First claim {rand_word()} stands."
    claim_two = f"Second claim {rand_word()} couples."
    claim_three = f"Third claim {rand_word()} emerges."
    quote_a = f"alpha evidence {rand_word()}"
    quote_b = f"bravo evidence {rand_word()}"
    quote_c = f"charlie evidence {rand_word()}"
    quote_d = f"delta evidence {rand_word()}"

    existing = Article(
        title=title,
        summary=f"Old summary {rand_word()}.",
        sections=(Section(heading="Intro", body=intro_body),
                  Section(heading="Method", body=method_old)),
        claims=(
            Claim(text=claim_one, citekeys=(ck_a,),
                  quotes=(Quote(citekey=ck_a, text=quote_a),)),
            Claim(text=claim_two, citekeys=(ck_b,),
                  quotes=(Quote(citekey=ck_b, text=quote_b),)),
        ),
        links=("Linked Alpha",),
    )
    claim_two_variant = claim_two.upper()
    assert claim_two_variant != claim_two  # same identity, different bytes
    update = Article(
        title=title,
        summary=f"New summary {rand_word()}.",
        sections=(Section(heading="Method", body=method_new),
                  Section(heading="Results", body=results_body)),
        claims=(
            Claim(text=claim_two_variant, citekeys=(ck_c,),
                  quotes=(Quote(citekey=ck_c, text=quote_c),)),
            Claim(text=claim_three, citekeys=(ck_d,),
                  quotes=(Quote(citekey=ck_d, text=quote_d),)),
        ),
        links=("Linked Beta",),
    )
    items = register_citekey_map(fake_zotero, [ck_a, ck_b, ck_c, ck_d])
    page = VaultPublisher(vault, store, today=TODAY).publish(existing)

    VaultPublisher(vault, store, today=LATER).publish(update)

    merged = expected_merge(existing, update)
    expected = render_oracle(merged, refs_for(merged, items),
                             created=TODAY, updated=LATER)
    assert page.read_bytes() == expected.encode("utf-8")

    text = page.read_text(encoding="utf-8")
    assert f"## Intro\n\n{intro_body}" in text          # kept verbatim
    assert f"## Method\n\n{method_new}" in text         # body replaced
    assert method_old not in text
    assert (text.index("## Intro") < text.index("## Method")
            < text.index("## Results"))                 # append at the end
    assert f"- {claim_one} [@{ck_a}]" in text           # kept verbatim
    merged_claim_line = f"- {claim_two} [@{ck_b}; @{ck_c}]"
    assert merged_claim_line in text                    # union, existing text
    assert claim_two_variant not in text
    assert f"  > [@{ck_b}] {quote_b}" in text           # quote union
    assert f"  > [@{ck_c}] {quote_c}" in text
    assert f"- {claim_three} [@{ck_d}]" in text         # appended claim
    assert (text.index(f"- {claim_one} ") < text.index(merged_claim_line)
            < text.index(f"- {claim_three} "))
    assert "- [[Linked Alpha]]\n- [[Linked Beta]]" in text  # sorted union
    assert update.summary in text                       # new summary wins
    assert existing.summary not in text
    assert f'created: "{TODAY}"' in text
    assert f'updated: "{LATER}"' in text
    assert parse_page(text) == merged


@SETTINGS
@given(articles=clean_vault_articles(max_articles=3), data=st.data())
def test_req_020__publish_update_audit_invariants_over_random_vaults(
    fake_zotero, zstore, tmp_path, articles, data
):
    fake_zotero.reset()
    store, _ = zstore()
    vault = tmp_path / f"vault{next(_DIRS)}"
    titles = [article.title for article in articles]

    cited = article_citekeys(*articles)
    fresh: list[str] = []
    while len(fresh) < len(articles):
        candidate = rand_citekey()
        if candidate not in cited and candidate not in fresh:
            fresh.append(candidate)

    updates = []
    for index_no, (article, ck) in enumerate(zip(articles, fresh)):
        if article.sections:
            sections = (Section(heading=article.sections[0].heading,
                                body=f"Replaced body {rand_word()}."),)
        else:
            sections = (Section(heading=f"Fresh section {rand_word()}",
                                body=f"Fresh body {rand_word()}."),)
        links = tuple(sorted(set(
            data.draw(st.lists(st.sampled_from(titles), max_size=2))
        )))
        updates.append(Article(
            title=article.title,
            summary=f"Updated summary {rand_word()} {index_no}.",
            sections=sections,
            claims=(
                Claim(
                    text=f"Fresh claim {rand_word()} {index_no} emerges.",
                    citekeys=(ck,),
                    quotes=(Quote(citekey=ck,
                                  text=f"fresh evidence {rand_word()}"),),
                ),
            ),
            links=links,
        ))

    refs = register_supporting_references(
        fake_zotero, list(articles) + updates
    )
    create_publisher = VaultPublisher(vault, store, today=TODAY)
    for article in articles:
        create_publisher.publish(article)
    index = vault / INDEX_FILENAME
    expected_index = index_oracle(titles, created=TODAY,
                                  updated=TODAY).encode("utf-8")
    assert index.read_bytes() == expected_index

    update_publisher = VaultPublisher(vault, store, today=LATER)
    for update in updates:
        update_publisher.publish(update)

    for article, update in zip(articles, updates):
        merged = expected_merge(article, update)
        expected = render_oracle(merged, refs_for(merged, refs),
                                 created=TODAY, updated=LATER)
        path = vault / f"{article.title}.md"
        assert path.read_bytes() == expected.encode("utf-8")
        assert parse_page(path.read_text(encoding="utf-8")) == merged

    # No title changed: Index.md is byte-identical to its first rendering.
    assert index.read_bytes() == expected_index

    report = Auditor(vault, store).audit()
    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == len(articles)
