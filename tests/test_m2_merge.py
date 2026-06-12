"""M2 / merge_articles: the REQ-016 never-clobber matrix, pinned and as
hypothesis properties against an independent re-implementation of
docs/contract.md SS7.2.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings

from zotwiki.errors import ArticleSchemaError
from zotwiki.models import Article, Claim, Quote, Section

from m2_helpers import articles_st, expected_merge, merge_pairs, rand_word

SETTINGS = settings(deadline=None, max_examples=40)

merge_articles = None  # bound by _require_m2_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m2_surface():
    """Bind the M2 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1 suite)."""
    global merge_articles
    from zotwiki.compiler import merge_articles as merge_articles_

    merge_articles = merge_articles_


def _matrix_pair():
    """The exact REQ-016 scenario, with runtime-random title/body details."""
    title = f"{rand_word().capitalize()} Page"
    intro = Section(heading="Intro", body=f"intro body {rand_word()}")
    method_old = Section(heading="Method", body=f"old method body {rand_word()}")
    c1 = Claim(
        text=f"Alpha finding about {rand_word()}.",
        citekeys=("aaa2020x",),
        quotes=(Quote(citekey="aaa2020x", text="alpha quote"),),
    )
    c2_old = Claim(
        text="Beta holds under load",
        citekeys=("bbb2019y",),
        quotes=(Quote(citekey="bbb2019y", text="beta quote one"),),
    )
    existing = Article(
        title=title,
        summary=f"old summary {rand_word()}",
        sections=(intro, method_old),
        claims=(c1, c2_old),
        links=("A",),
    )

    method_new = Section(heading="Method", body=f"new method body {rand_word()}")
    results = Section(heading="Results", body=f"results body {rand_word()}")
    # Same claim identity as c2_old under normalize_text (case differences
    # only), different citekeys and quotes; one quote is a normalize_text
    # duplicate of the existing one.
    c2_new = Claim(
        text="BETA Holds Under LOAD",
        citekeys=("bbb2019y", "ccc2021z"),
        quotes=(
            Quote(citekey="bbb2019y", text="Beta QUOTE One"),
            Quote(citekey="ccc2021z", text="beta quote two"),
        ),
    )
    c3 = Claim(
        text=f"Gamma emerges from {rand_word()}.",
        citekeys=("ddd2022w",),
        quotes=(Quote(citekey="ddd2022w", text="gamma quote"),),
    )
    update = Article(
        title=title,
        summary=f"new summary {rand_word()}",
        sections=(method_new, results),
        claims=(c2_new, c3),
        links=("B",),
    )
    return existing, update, intro, method_new, results, c1, c2_old, c3


def test_req_016__never_clobber_matrix():
    existing, update, intro, method_new, results, c1, c2_old, c3 = _matrix_pair()

    merged = merge_articles(existing, update)

    assert merged == Article(
        title=existing.title,
        summary=update.summary,  # update's summary replaces the old one
        sections=(
            intro,  # kept verbatim
            Section(heading="Method", body=method_new.body),  # body replaced in place
            results,  # new section appended
        ),
        claims=(
            c1,  # kept verbatim
            Claim(
                text=c2_old.text,  # existing text survives
                citekeys=("bbb2019y", "ccc2021z"),  # sorted union
                quotes=(
                    # union deduped by (citekey, normalized text), first-seen
                    # text kept, sorted by (citekey, text)
                    Quote(citekey="bbb2019y", text="beta quote one"),
                    Quote(citekey="ccc2021z", text="beta quote two"),
                ),
            ),
            c3,  # new claim appended
        ),
        links=("A", "B"),  # sorted union
    )


def test_req_016__differing_titles_raise():
    existing, update, *_ = _matrix_pair()
    renamed = Article(
        title=update.title + " Renamed",
        summary=update.summary,
        sections=update.sections,
        claims=update.claims,
        links=update.links,
    )
    with pytest.raises(ArticleSchemaError):
        merge_articles(existing, renamed)


def test_req_016__merge_is_pure_and_deterministic():
    existing, update, *_ = _matrix_pair()
    existing_copy = Article(
        title=existing.title,
        summary=existing.summary,
        sections=existing.sections,
        claims=existing.claims,
        links=existing.links,
    )
    update_copy = Article(
        title=update.title,
        summary=update.summary,
        sections=update.sections,
        claims=update.claims,
        links=update.links,
    )

    first = merge_articles(existing, update)
    second = merge_articles(existing, update)

    assert first == second
    assert existing == existing_copy  # inputs untouched
    assert update == update_copy


@SETTINGS
@given(pair=merge_pairs())
def test_req_016__merge_matches_independent_reimplementation(pair):
    existing, update = pair
    assert merge_articles(existing, update) == expected_merge(existing, update)


@SETTINGS
@given(pair=merge_pairs())
def test_req_016__existing_only_content_survives_byte_identically(pair):
    existing, update = pair
    merged = merge_articles(existing, update)

    update_headings = {s.heading for s in update.sections}
    merged_sections = {s.heading: s for s in merged.sections}
    for section in existing.sections:
        assert section.heading in merged_sections
        if section.heading not in update_headings:
            assert merged_sections[section.heading] == section  # verbatim

    merged_texts = [c.text for c in merged.claims]
    for claim in existing.claims:
        assert claim.text in merged_texts  # existing claim text always kept
    for merged_claim, existing_claim in zip(merged.claims, existing.claims):
        # existing claims keep their positions and never lose citekeys/quotes
        assert merged_claim.text == existing_claim.text
        assert set(existing_claim.citekeys) <= set(merged_claim.citekeys)

    assert set(existing.links) <= set(merged.links)
    assert merged.links == tuple(sorted(set(existing.links) | set(update.links)))
    assert merged.summary == update.summary


@SETTINGS
@given(article=articles_st())
def test_req_016__merging_an_article_with_itself_is_identity(article):
    assert merge_articles(article, article) == article
