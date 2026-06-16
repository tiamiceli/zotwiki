"""M4 / Auditor, the seven SS8 checks one corruption at a time
(REQ-024..REQ-029): every vault starts clean -- built by the real M3
publisher against the fake Zotero on 127.0.0.1 -- and is then corrupted
programmatically in exactly one way; the audit must report exactly the
matching code (page, detail per SS8.1) and nothing else.

Runtime-random content everywhere; vaults in tmp_path; injected `today`.
"""
from __future__ import annotations

import random
import string

import pytest

from zotwiki.models import Article, Claim, Quote, Section

from m4_helpers import (
    TODAY,
    VaultPublisher,
    build_article,
    distinct_citekeys,
    drop_line,
    publish_clean_vault,
    rand_citekey,
    rand_word,
    register_supporting_reference,
    render_page_with,
    unregister,
    violation_pairs,
    violation_triples,
)

Auditor = None  # bound by _require_m4_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m4_surface():
    """Bind the M4 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error."""
    global Auditor
    from zotwiki.auditor import Auditor as Auditor_

    Auditor = Auditor_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


# ----- REQ-024: CITEKEY_UNRESOLVED ------------------------------------------


def test_req_024__unresolvable_citekey_flagged_with_citekey_detail(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck_keep, ck_gone = distinct_citekeys(2)
    article = build_article([(ck_keep,), (ck_gone,)])
    refs = publish_clean_vault(fake_zotero, store, vault, [article])

    unregister(fake_zotero, refs[ck_gone])
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("CITEKEY_UNRESOLVED", f"{article.title}.md", ck_gone)
    ]
    assert report.ok is False
    assert report.pages_checked == 1  # the page itself still parses


def test_req_024__one_violation_per_distinct_page_citekey_pair(
    tmp_path, store, fake_zotero
):
    """The shared citekey appears in two claims (plus quotes plus the
    References block) of page Alpha and once on page Bravo: SS8.1 check 2
    demands exactly one violation per distinct (page, citekey)."""
    vault = tmp_path / "vault"
    shared, other = distinct_citekeys(2)
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(shared,), (shared, other)], title=title_a),
        build_article([(shared,)], title=title_b),
    ]
    refs = publish_clean_vault(fake_zotero, store, vault, articles)

    unregister(fake_zotero, refs[shared])
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("CITEKEY_UNRESOLVED", f"{title_a}.md", shared),
        ("CITEKEY_UNRESOLVED", f"{title_b}.md", shared),
    ]
    assert report.pages_checked == 2


# ----- REQ-025: QUOTE_NOT_FOUND ----------------------------------------------


def test_req_025__contract_normalization_example_is_not_flagged(
    tmp_path, store, fake_zotero
):
    """The exact REQ-025 pair: fulltext `It's  a "QUARTZ-sphinx".` in curly
    quotes/em-dash/double-space form vs the plain page quote must match
    under SS2.1 normalization -- no violation."""
    vault = tmp_path / "vault"
    ck = rand_citekey()
    article = Article(
        title=f"Sphinx {rand_word().capitalize()}",
        summary=f"Normalization of {rand_word()}.",
        sections=(),
        claims=(
            Claim(
                text=f"The sphinx is {rand_word()}.",
                citekeys=(ck,),
                quotes=(Quote(citekey=ck, text='it\'s a "quartz-sphinx".'),),
            ),
        ),
        links=(),
    )
    register_supporting_reference(
        fake_zotero, ck, fulltext="It’s  a “QUARTZ—sphinx”."
    )
    VaultPublisher(vault, store, today=TODAY).publish(article)

    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == 1


def test_req_025__quote_absent_from_fulltext_flagged_with_60_char_prefix(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck = rand_citekey()
    long_quote = " ".join(
        "".join(random.choices(string.ascii_lowercase, k=6)) for _ in range(10)
    )
    assert len(long_quote) > 60
    article = Article(
        title=f"Quotes {rand_word().capitalize()}",
        summary=f"About {rand_word()}.",
        sections=(),
        claims=(
            Claim(
                text=f"Claim {rand_word()} holds.",
                citekeys=(ck,),
                quotes=(Quote(citekey=ck, text=long_quote),),
            ),
        ),
        links=(),
    )
    refs = publish_clean_vault(fake_zotero, store, vault, [article])
    assert Auditor(vault, store).audit().ok is True  # clean before corruption

    fake_zotero.fulltext[refs[ck].key] = f"Replacement {rand_word()} body."
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("QUOTE_NOT_FOUND", f"{article.title}.md", f"{ck}: {long_quote[:60]}")
    ]
    assert report.ok is False
    assert report.pages_checked == 1


def test_req_025__cited_item_without_fulltext_is_flagged(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck = rand_citekey()
    article = build_article([(ck,)])
    quote_text = article.claims[0].quotes[0].text
    assert len(quote_text) <= 60
    refs = publish_clean_vault(fake_zotero, store, vault, [article])

    del fake_zotero.fulltext[refs[ck].key]  # probe now 404s: has_fulltext False
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("QUOTE_NOT_FOUND", f"{article.title}.md", f"{ck}: {quote_text}")
    ]
    assert report.ok is False


# ----- REQ-026: BROKEN_LINK ---------------------------------------------------


def test_req_026__dangling_link_in_links_block_is_flagged(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ghost = f"Ghost {rand_word().capitalize()}"
    article = build_article([(rand_citekey(),)], links=(ghost,))
    publish_clean_vault(fake_zotero, store, vault, [article])

    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("BROKEN_LINK", f"{article.title}.md", ghost)
    ]
    assert report.ok is False
    assert report.pages_checked == 1


def test_req_026__alias_links_are_checked_against_their_target(
    tmp_path, store, fake_zotero
):
    """[[Target|shown]] in a section body audits against Target: the alias
    to an existing page is clean, the alias to a missing page is flagged
    with the target (not the alias text) as detail."""
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    ghost = f"Ghost {rand_word().capitalize()}"
    alpha = Article(
        title=title_a,
        summary=f"About {rand_word()}.",
        sections=(
            Section(
                heading=f"Context {rand_word()}",
                body=(
                    f"A real alias [[{title_b}|the bravo study]] and a "
                    f"missing alias [[{ghost}|nowhere at all]]."
                ),
            ),
        ),
        claims=(),
        links=(),
    )
    bravo = build_article([(rand_citekey(),)], title=title_b)
    publish_clean_vault(fake_zotero, store, vault, [alpha, bravo])

    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("BROKEN_LINK", f"{title_a}.md", ghost)
    ]
    assert report.pages_checked == 2


def test_req_026__hash_target_is_flagged_even_when_page_exists(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    alpha = Article(
        title=title_a,
        summary=f"About {rand_word()}.",
        sections=(
            Section(
                heading=f"Anchors {rand_word()}",
                body=f"An anchored link [[{title_b}#Methods]] inline.",
            ),
        ),
        claims=(),
        links=(title_b,),
    )
    bravo = build_article([(rand_citekey(),)], title=title_b)
    publish_clean_vault(fake_zotero, store, vault, [alpha, bravo])
    assert (vault / f"{title_b}.md").exists()

    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("BROKEN_LINK", f"{title_a}.md", f"{title_b}#Methods")
    ]


# ----- REQ-027: ORPHAN_PAGE and INDEX_STALE -----------------------------------


def test_req_027__page_missing_from_index_is_orphan(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck,)], title=t)
        for ck, t in zip(distinct_citekeys(2), (title_a, title_b))
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)

    drop_line(vault / "Index.md", f"- [[{title_b}]]")
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [("ORPHAN_PAGE", f"{title_b}.md")]
    assert report.ok is False
    assert report.pages_checked == 2


def test_req_027__hand_added_page_not_in_index_is_orphan(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = build_article([(rand_citekey(),)])
    publish_clean_vault(fake_zotero, store, vault, [article])

    orphan_title = f"Orphan {rand_word().capitalize()}"
    orphan = build_article([], title=orphan_title)  # no claims: no citekeys
    (vault / f"{orphan_title}.md").write_text(
        render_page_with(orphan, (), created=TODAY, updated=TODAY),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [("ORPHAN_PAGE", f"{orphan_title}.md")]
    assert report.pages_checked == 2  # the orphan itself parses fine


def test_req_027__index_bullet_without_file_is_stale(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck,)], title=t)
        for ck, t in zip(distinct_citekeys(2), (title_a, title_b))
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)

    (vault / f"{title_b}.md").unlink()
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [("INDEX_STALE", "Index.md", title_b)]
    assert report.ok is False
    assert report.pages_checked == 1


def test_req_027__missing_index_orphans_every_entity_page(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck,)], title=t)
        for ck, t in zip(distinct_citekeys(2), (title_a, title_b))
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)

    (vault / "Index.md").unlink()
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [
        ("ORPHAN_PAGE", f"{title_a}.md"),
        ("ORPHAN_PAGE", f"{title_b}.md"),
    ]
    assert report.pages_checked == 2


# ----- REQ-028: PAGE_UNPARSEABLE ----------------------------------------------


def test_req_028__garbage_page_flagged_and_others_still_audited(
    tmp_path, store, fake_zotero
):
    """The overwritten page carries a dangling [[link]] and an unknown
    citekey token, but SS8.1 says unparseable pages skip checks 2-4 and 7:
    only PAGE_UNPARSEABLE may be reported, and only for that page."""
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck,)], title=t)
        for ck, t in zip(distinct_citekeys(2), (title_a, title_b))
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)

    (vault / f"{title_b}.md").write_text(
        f"This is not a wiki page.\n"
        f"See [[Nowhere {rand_word().capitalize()}]] and [@{rand_citekey()}].\n",
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [("PAGE_UNPARSEABLE", f"{title_b}.md")]
    detail = report.violations[0].detail
    assert isinstance(detail, str) and detail  # first parse error message
    assert report.ok is False
    assert report.pages_checked == 1


def _insert_unknown_frontmatter_key(text: str, article: Article) -> str:
    assert text.count("zotwiki: 2\n") == 1
    return text.replace("zotwiki: 2\n", 'zotwiki: 2\nstatus: "draft"\n', 1)


def _swap_created_updated(text: str, article: Article) -> str:
    pair = f'created: "{TODAY}"\nupdated: "{TODAY}"'
    assert pair in text
    return text.replace(pair, f'updated: "{TODAY}"\ncreated: "{TODAY}"', 1)


def _unquote_title(text: str, article: Article) -> str:
    quoted = f'title: "{article.title}"'
    assert quoted in text
    return text.replace(quoted, f"title: {article.title}", 1)


def _drop_claims_heading(text: str, article: Article) -> str:
    lines = text.split("\n")
    lines.remove("## Claims")
    return "\n".join(lines)


@pytest.mark.parametrize(
    "corrupt",
    [
        _insert_unknown_frontmatter_key,
        _swap_created_updated,
        _unquote_title,
        _drop_claims_heading,
    ],
    ids=[
        "unknown-frontmatter-key",
        "frontmatter-key-order",
        "unquoted-title",
        "missing-claims-heading",
    ],
)
def test_req_028__grammar_corruptions_are_flagged(
    tmp_path, store, fake_zotero, corrupt
):
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck,)], title=t)
        for ck, t in zip(distinct_citekeys(2), (title_a, title_b))
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)

    page = vault / f"{title_b}.md"
    page.write_text(
        corrupt(page.read_text(encoding="utf-8"), articles[1]),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [("PAGE_UNPARSEABLE", f"{title_b}.md")]
    assert report.pages_checked == 1


# ----- REQ-029: REFERENCE_MISSING ---------------------------------------------


def test_req_029__missing_reference_line_is_flagged(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    article = build_article([(ck_a, ck_b)])
    refs = publish_clean_vault(fake_zotero, store, vault, [article])
    page = vault / f"{article.title}.md"

    page.write_text(  # References block now lists only ck_a
        render_page_with(article, [refs[ck_a]], created=TODAY, updated=TODAY,
                         fm_citekeys=[ck_a, ck_b]),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("REFERENCE_MISSING", page.name, ck_b)
    ]
    assert report.ok is False
    assert report.pages_checked == 1


def test_req_029__extra_frontmatter_citekey_flagged_without_resolve_check(
    tmp_path, store, fake_zotero
):
    """A citekey present only in the frontmatter list is a check-7 set
    mismatch -- and never a CITEKEY_UNRESOLVED, because check 2 covers only
    claims, quotes, and the References block (SS8.1)."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    bogus = "0" + rand_citekey()  # unresolvable, sorts before letter-initial
    article = build_article([(ck_a, ck_b)])
    refs = publish_clean_vault(fake_zotero, store, vault, [article])
    page = vault / f"{article.title}.md"

    page.write_text(
        render_page_with(article, list(refs.values()), created=TODAY,
                         updated=TODAY, fm_citekeys=[ck_a, ck_b, bogus]),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("REFERENCE_MISSING", page.name, bogus)
    ]


def test_req_029__extra_reference_line_for_uncited_item_is_flagged(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck_a, ck_b, ck_extra = distinct_citekeys(3)
    article = build_article([(ck_a, ck_b)])
    refs = publish_clean_vault(fake_zotero, store, vault, [article])
    extra_item = register_supporting_reference(fake_zotero, ck_extra)
    page = vault / f"{article.title}.md"

    page.write_text(  # References block gains a resolvable but uncited entry
        render_page_with(article, [refs[ck_a], refs[ck_b], extra_item],
                         created=TODAY, updated=TODAY),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_triples(report) == [
        ("REFERENCE_MISSING", page.name, ck_extra)
    ]


def test_req_029__detail_lists_all_mismatched_citekeys_sorted(
    tmp_path, store, fake_zotero
):
    """claims {a,b} / References {a} / frontmatter {a,b,bogus}: the
    mismatching citekeys are those not common to all three sets -- {b,
    bogus} -- reported sorted, comma separated, in one violation."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    bogus = "0" + rand_citekey()
    article = build_article([(ck_a, ck_b)])
    refs = publish_clean_vault(fake_zotero, store, vault, [article])
    page = vault / f"{article.title}.md"

    page.write_text(
        render_page_with(article, [refs[ck_a]], created=TODAY, updated=TODAY,
                         fm_citekeys=[ck_a, ck_b, bogus]),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert violation_pairs(report) == [("REFERENCE_MISSING", page.name)]
    tokens = [t.strip() for t in report.violations[0].detail.split(",")]
    assert tokens == sorted([ck_b, bogus])
