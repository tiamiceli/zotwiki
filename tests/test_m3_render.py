"""M3 / render_page: REQ-017 byte-deterministic canonical rendering and
REQ-018 References-block resolution, against pinned contract SS6 bytes and
an independent oracle re-implementation (m3_helpers.render_oracle).
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from zotwiki.errors import VaultError
from zotwiki.models import Article, Claim, Quote, SourceItem

from m2_helpers import articles_st
from m3_helpers import (
    EMPTY_ARTICLE,
    EMPTY_PAGE,
    PINNED_ARTICLE,
    PINNED_PAGE,
    PINNED_REFS,
    PINNED_TODAY,
    cited_citekeys,
    dates_st,
    local_references_for,
    random_publishable_article,
    references_for,
    render_oracle,
)

SETTINGS = settings(deadline=None, max_examples=40)

render_page = None  # bound by _require_m3_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m3_surface():
    """Bind the M3 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1+M2 suites)."""
    global render_page
    from zotwiki.publisher import render_page as render_page_

    render_page = render_page_


# ----- REQ-017: deterministic canonical rendering --------------------------


def test_req_017__pinned_contract_example_renders_byte_exact():
    out = render_page(
        PINNED_ARTICLE, PINNED_REFS, created=PINNED_TODAY, updated=PINNED_TODAY,
        zotero_keys=("ABCD1234", "WXYZ7890"),
    )
    assert out == PINNED_PAGE


def test_req_017__empty_blocks_render_as_bare_headings_byte_exact():
    out = render_page(
        EMPTY_ARTICLE, (), created="2026-01-02", updated="2026-03-04"
    )
    assert out == EMPTY_PAGE


def test_req_017__rendering_twice_and_with_shuffled_references_is_identical():
    article = random_publishable_article()
    refs = local_references_for(article)

    first = render_page(article, refs, created="2026-05-01", updated="2026-05-02")
    second = render_page(article, refs, created="2026-05-01", updated="2026-05-02")
    shuffled = render_page(
        article, tuple(reversed(refs)), created="2026-05-01", updated="2026-05-02"
    )

    assert first == second
    assert shuffled == first  # References emitted sorted by citekey (SS6.3)


@SETTINGS
@given(data=st.data())
def test_req_017__render_matches_independent_oracle(data):
    article = data.draw(articles_st())
    refs = data.draw(references_for(article))
    created = data.draw(dates_st())
    updated = data.draw(dates_st())

    assert render_page(article, refs, created=created, updated=updated) == (
        render_oracle(article, refs, created=created, updated=updated)
    )


@SETTINGS
@given(data=st.data())
def test_req_017__byte_level_invariants_hold_for_every_article(data):
    article = data.draw(articles_st())
    refs = data.draw(references_for(article))

    out = render_page(article, refs, created="2026-06-11", updated="2026-06-11")

    assert "\r" not in out                      # LF line endings only
    assert out.endswith("\n")                   # exactly one trailing newline
    assert not out.endswith("\n\n")
    assert "\n\n\n" not in out                  # blocks separated by ONE blank line
    lines = out.split("\n")
    assert lines[0] == "---"
    assert all(line == line.rstrip() for line in lines)  # no trailing spaces
    for heading in ("## Claims", "## Links", "## References"):
        assert lines.count(heading) == 1        # always present, exactly once


def test_req_017__frontmatter_citekeys_are_sorted_deduped_union():
    article = Article(
        title="Citekey Union",
        summary="Two claims sharing a citekey.",
        sections=(),
        claims=(
            Claim(
                text="First finding stands.",
                citekeys=("bbb2019beta", "ccc2021gamma"),
                quotes=(Quote(citekey="bbb2019beta", text="quote one"),
                        Quote(citekey="ccc2021gamma", text="quote two")),
            ),
            Claim(
                text="Second finding stands.",
                citekeys=("aaa2020alpha", "bbb2019beta"),
                quotes=(Quote(citekey="aaa2020alpha", text="quote three"),
                        Quote(citekey="bbb2019beta", text="quote four")),
            ),
        ),
        links=(),
    )
    refs = local_references_for(article)

    out = render_page(article, refs, created="2026-06-11", updated="2026-06-11")

    assert (
        "citekeys:\n"
        '  - "aaa2020alpha"\n'
        '  - "bbb2019beta"\n'
        '  - "ccc2021gamma"\n'
        "zotero_keys: []\n"
        "tags:"
    ) in out
    assert out.count('  - "bbb2019beta"') == 1  # deduped in frontmatter


# ----- REQ-018: References block resolves to Zotero -------------------------


def test_req_018__reference_line_contains_zotero_select_uri():
    out = render_page(
        PINNED_ARTICLE, PINNED_REFS, created=PINNED_TODAY, updated=PINNED_TODAY
    )

    assert "zotero://select/library/items/ABCD1234" in out
    assert (
        "\n- [@doe2020attention] Jane Doe (2020). *A Study of Attention*. "
        "[Zotero](zotero://select/library/items/ABCD1234)\n"
    ) in out


def test_req_018__empty_creators_render_unknown_and_no_year_renders_nd():
    article = Article(
        title="Anon Source",
        summary="A claim from an authorless, undated item.",
        sections=(),
        claims=(
            Claim(
                text="Anonymous wisdom persists.",
                citekeys=("anonnditem",),
                quotes=(Quote(citekey="anonnditem", text="so it is written"),),
            ),
        ),
        links=(),
    )
    ref = SourceItem(key="QQQQ0000", citekey="anonnditem",
                     title="Untitled Pamphlet", creators=(), year=None,
                     url=None, has_fulltext=False)

    out = render_page(article, (ref,), created="2026-06-11", updated="2026-06-11")

    assert (
        "\n- [@anonnditem] Unknown (n.d.). *Untitled Pamphlet*. "
        "[Zotero](zotero://select/library/items/QQQQ0000)\n"
    ) in out


def test_req_018__unicode_reference_titles_and_creators_render_verbatim():
    article = Article(
        title="Unicode Sources",
        summary="Citing a source with a non-ASCII title and creator.",
        sections=(),
        claims=(
            Claim(
                text="Unicode metadata survives rendering.",
                citekeys=("angstrom2019size",),
                quotes=(Quote(citekey="angstrom2019size",
                              text="die Größe der Ψυχή — 注意力"),),
            ),
        ),
        links=(),
    )
    ref = SourceItem(key="UNIC0001", citekey="angstrom2019size",
                     title="Größe und Ψυχή 注意力",
                     creators=("José Ångström",), year=2019, url=None,
                     has_fulltext=True)

    out = render_page(article, (ref,), created="2026-06-11", updated="2026-06-11")

    assert (
        "\n- [@angstrom2019size] José Ångström (2019). *Größe und Ψυχή 注意力*. "
        "[Zotero](zotero://select/library/items/UNIC0001)\n"
    ) in out
    assert out == render_oracle(article, (ref,),
                                created="2026-06-11", updated="2026-06-11")


def test_req_018__missing_cited_reference_raises_vault_error():
    article = random_publishable_article()
    while len(cited_citekeys(article)) < 2:  # need one to drop, one to keep
        article = random_publishable_article()
    refs = local_references_for(article)

    with pytest.raises(VaultError):
        render_page(article, refs[1:], created="2026-06-11", updated="2026-06-11")


def test_req_018__uncited_extra_reference_raises_vault_error():
    article = random_publishable_article()
    refs = local_references_for(article)
    extra = SourceItem(key="EXTRA999", citekey="uncited2099nobody",
                       title="Never Cited", creators=("Nobody Atall",),
                       year=2099, url=None, has_fulltext=False)

    with pytest.raises(VaultError):
        render_page(article, refs + (extra,),
                    created="2026-06-11", updated="2026-06-11")


def test_req_018__duplicate_reference_raises_vault_error():
    article = random_publishable_article()
    refs = local_references_for(article)

    with pytest.raises(VaultError):
        render_page(article, refs + (refs[0],),
                    created="2026-06-11", updated="2026-06-11")
