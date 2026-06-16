"""M3 / parse_page: the REQ-021 round-trip law (property-style over the M2
article strategies and against independently rendered canonical bytes) and
its negative space — every contract SS6.2/SS6.3 grammar violation must raise
PageParseError.

All malformed pages are produced by mutating an *independently* rendered
canonical page (m3_helpers.render_oracle over a runtime-random article), so
neither side of the test depends on render_page being correct, and nothing
can be satisfied by hardcoding.
"""
from __future__ import annotations

import re

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from zotwiki.errors import PageParseError

from m2_helpers import articles_st
from m3_helpers import (
    EMPTY_ARTICLE,
    EMPTY_PAGE,
    PINNED_ARTICLE,
    PINNED_PAGE,
    cited_citekeys,
    dates_st,
    local_references_for,
    random_publishable_article,
    references_for,
    render_oracle,
)

SETTINGS = settings(deadline=None, max_examples=40)

render_page = None  # bound by _require_m3_surface
parse_page = None


@pytest.fixture(scope="module", autouse=True)
def _require_m3_surface():
    """Bind the M3 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1+M2 suites)."""
    global render_page, parse_page
    from zotwiki.publisher import parse_page as parse_page_
    from zotwiki.publisher import render_page as render_page_

    render_page = render_page_
    parse_page = parse_page_


# ----- REQ-021: round-trip law ----------------------------------------------


def test_req_021__pinned_contract_page_parses_to_pinned_article():
    # Bytes transcribed from contract SS6; no zotwiki renderer involved.
    assert parse_page(PINNED_PAGE) == PINNED_ARTICLE


def test_req_021__pinned_empty_blocks_page_parses():
    assert parse_page(EMPTY_PAGE) == EMPTY_ARTICLE


@SETTINGS
@given(data=st.data())
def test_req_021__parse_inverts_render_for_every_article(data):
    article = data.draw(articles_st())
    refs = data.draw(references_for(article))
    created = data.draw(dates_st())
    updated = data.draw(dates_st())

    text = render_page(article, refs, created=created, updated=updated)

    assert parse_page(text) == article


@SETTINGS
@given(data=st.data())
def test_req_021__parse_accepts_independently_rendered_canonical_bytes(data):
    article = data.draw(articles_st())
    refs = data.draw(references_for(article))
    created = data.draw(dates_st())
    updated = data.draw(dates_st())

    text = render_oracle(article, refs, created=created, updated=updated)

    assert parse_page(text) == article


# ----- negative space: building malformed pages ----------------------------


def _sample_page() -> tuple[str, list[str]]:
    """A runtime-random canonical page (independent oracle bytes) that is
    guaranteed to have >= 1 section, >= 2 claims with quotes, >= 1 link and
    a non-empty References block, plus its cited citekeys."""
    article = random_publishable_article(n_claims=2)
    page = render_oracle(
        article,
        local_references_for(article),
        created="2026-02-03",
        updated="2026-04-05",
    )
    return page, cited_citekeys(article)


def _split_section_blocks(page: str) -> tuple[str, str, str, str]:
    """(head, claims_block, links_block, refs_block) — each block includes
    its leading '\\n\\n## Heading' marker; refs_block runs to EOF."""
    i_claims = page.index("\n\n## Claims\n")
    i_links = page.index("\n\n## Links\n")
    i_refs = page.index("\n\n## References\n")
    assert i_claims < i_links < i_refs
    return page[:i_claims], page[i_claims:i_links], page[i_links:i_refs], page[i_refs:]


# Each mutator: canonical page text -> grammar-violating text.

def _fm_strip_frontmatter(page: str, cited: list[str]) -> str:
    return page[page.index("\n\n# ") + 2:]  # body only, no '---' block


def _fm_unknown_key(page: str, cited: list[str]) -> str:
    return page.replace("zotwiki: 2\n", 'zotwiki: 2\nextra: "x"\n', 1)


def _fm_wrong_key_order(page: str, cited: list[str]) -> str:
    title_line = re.search(r"(?m)^title: .*$", page).group(0)
    created_line = re.search(r"(?m)^created: .*$", page).group(0)
    return page.replace(
        f"{title_line}\n{created_line}\n",
        f"{created_line}\n{title_line}\n",
        1,
    )


def _fm_unquoted_string(page: str, cited: list[str]) -> str:
    return re.sub(r'(?m)^title: "([^"]*)"$',
                  lambda m: f"title: {m.group(1)}", page, count=1)


def _fm_flow_list_with_content(page: str, cited: list[str]) -> str:
    return re.sub(r'citekeys:\n(?:  - "[^"\n]*"\n)+',
                  lambda m: f'citekeys: ["{cited[0]}"]\n', page, count=1)


def _fm_missing_required_key(page: str, cited: list[str]) -> str:
    return re.sub(r'(?m)^updated: "[^"\n]*"\n', "", page, count=1)


def _fm_wrong_schema_version(page: str, cited: list[str]) -> str:
    return page.replace("zotwiki: 2\n", "zotwiki: 1\n", 1)


def _fm_invalid_escape(page: str, cited: list[str]) -> str:
    # Only \\ and \" are legal escapes inside quoted scalars (SS6.2).
    return re.sub(r"(?m)^title: \".*\"$",
                  lambda m: 'title: "bad\\escape"', page, count=1)


def _fm_duplicated_key(page: str, cited: list[str]) -> str:
    return page.replace("created:", 'title: "Duplicate"\ncreated:', 1)


FRONTMATTER_MUTATIONS = [
    ("missing_frontmatter", _fm_strip_frontmatter),
    ("unknown_key", _fm_unknown_key),
    ("wrong_key_order", _fm_wrong_key_order),
    ("unquoted_string", _fm_unquoted_string),
    ("flow_list_with_content", _fm_flow_list_with_content),
    ("missing_required_key", _fm_missing_required_key),
    ("wrong_schema_version", _fm_wrong_schema_version),
    ("invalid_escape", _fm_invalid_escape),
    ("duplicated_key", _fm_duplicated_key),
]


def _body_missing_claims_heading(page: str, cited: list[str]) -> str:
    return page.replace("\n\n## Claims\n\n", "\n\n", 1)


def _body_missing_links_heading(page: str, cited: list[str]) -> str:
    return page.replace("\n\n## Links\n\n", "\n\n", 1)


def _body_missing_references_heading(page: str, cited: list[str]) -> str:
    return page.replace("\n\n## References\n\n", "\n\n", 1)


def _body_reserved_blocks_out_of_order(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    return head + links_b + claims_b + refs_b


def _body_claim_without_citekey_suffix(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    m = re.search(r"(?m)^- (.+) \[@[^\n]+\]$", claims_b)
    claims_b = claims_b[: m.start()] + "- " + m.group(1) + claims_b[m.end():]
    return head + claims_b + links_b + refs_b


def _body_quote_before_any_claim(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    claims_b = claims_b.replace(
        "## Claims\n\n", "## Claims\n\n  > [@zz9999orphan] floating quote\n", 1
    )
    return head + claims_b + links_b + refs_b


def _body_claim_with_zero_quotes(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    claims_b += f"\n- Extra claim carrying no quotes. [@{cited[0]}]"
    return head + claims_b + links_b + refs_b


def _body_quote_with_bad_indent(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    claims_b = claims_b.replace("\n  > [@", "\n> [@", 1)
    return head + claims_b + links_b + refs_b


def _body_quote_citing_unlisted_citekey(page: str, cited: list[str]) -> str:
    assert "zz9999unlisted" not in cited
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    claims_b = re.sub(r"(?m)^(  > \[@)[^\]\n]+(\] )",
                      r"\g<1>zz9999unlisted\g<2>", claims_b, count=1)
    return head + claims_b + links_b + refs_b


def _body_link_without_brackets(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    links_b = re.sub(r"(?m)^- \[\[([^\]\n]+)\]\]$", r"- \1", links_b, count=1)
    return head + claims_b + links_b + refs_b


def _body_reference_line_without_zotero_link(page: str, cited: list[str]) -> str:
    head, claims_b, links_b, refs_b = _split_section_blocks(page)
    refs_b = re.sub(
        r"(?m)^- \[@([^\]\n]+)\] .*$",
        lambda m: f"- [@{m.group(1)}] dangling reference without a link",
        refs_b,
        count=1,
    )
    return head + claims_b + links_b + refs_b


def _body_heading_line_inside_section_body(page: str, cited: list[str]) -> str:
    m = re.search(r"(?m)^## (?!Claims$|Links$|References$).*\n\n", page)
    return page[: m.end()] + "# Rogue\n" + page[m.end():]


BODY_MUTATIONS = [
    ("missing_claims_heading", _body_missing_claims_heading),
    ("missing_links_heading", _body_missing_links_heading),
    ("missing_references_heading", _body_missing_references_heading),
    ("reserved_blocks_out_of_order", _body_reserved_blocks_out_of_order),
    ("claim_without_citekey_suffix", _body_claim_without_citekey_suffix),
    ("quote_before_any_claim", _body_quote_before_any_claim),
    ("claim_with_zero_quotes", _body_claim_with_zero_quotes),
    ("quote_with_bad_indent", _body_quote_with_bad_indent),
    ("quote_citing_unlisted_citekey", _body_quote_citing_unlisted_citekey),
    ("link_without_brackets", _body_link_without_brackets),
    ("reference_line_without_zotero_link", _body_reference_line_without_zotero_link),
    ("heading_line_inside_section_body", _body_heading_line_inside_section_body),
]


@pytest.mark.parametrize(
    "mutate", [m for _, m in FRONTMATTER_MUTATIONS],
    ids=[name for name, _ in FRONTMATTER_MUTATIONS],
)
def test_req_021__malformed_frontmatter_raises_page_parse_error(mutate):
    page, cited = _sample_page()
    parse_page(page)  # the unmutated page must parse (non-vacuity guard)

    bad = mutate(page, cited)
    assert bad != page  # the mutation actually changed the bytes

    with pytest.raises(PageParseError):
        parse_page(bad)


@pytest.mark.parametrize(
    "mutate", [m for _, m in BODY_MUTATIONS],
    ids=[name for name, _ in BODY_MUTATIONS],
)
def test_req_021__malformed_body_raises_page_parse_error(mutate):
    page, cited = _sample_page()
    parse_page(page)  # the unmutated page must parse (non-vacuity guard)

    bad = mutate(page, cited)
    assert bad != page  # the mutation actually changed the bytes

    with pytest.raises(PageParseError):
        parse_page(bad)
