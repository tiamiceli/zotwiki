"""M4 / Auditor: hypothesis property tests.

Laws derived from docs/contract.md SS8 over runtime-generated vaults:

  - any vault the M3 publisher builds from articles whose links close over
    the published titles and whose quotes are embedded in their items'
    fulltexts audits ok (REQ-023);
  - unregistering one randomly chosen cited citekey yields exactly the
    CITEKEY_UNRESOLVED violations of the pages citing it (REQ-024);
  - erasing one randomly chosen item's fulltext yields exactly the
    QUOTE_NOT_FOUND violations for that item's quotes, with the
    "{citekey}: {first 60 chars}" detail (REQ-025);
  - SS2.1-equivalent surface forms (curly quotes, dashes, case, whitespace
    runs) never produce a quote violation (REQ-025).

The fake Zotero server is function-scope-reset per drawn example, every
example publishes into a fresh tmp_path subdirectory, and the store's sleep
seam is always injected -- no real time, no sleeps, 127.0.0.1 only.
"""
from __future__ import annotations

import itertools

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from zotwiki.models import Article, Claim, Quote, normalize_text

from m4_helpers import (
    TODAY,
    VaultPublisher,
    clean_vault_articles,
    equivalent_quote_pairs,
    publish_clean_vault,
    quotes_by_citekey,
    rand_citekey,
    rand_word,
    register_supporting_reference,
    unregister,
)

SETTINGS = settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_DIRS = itertools.count()

Auditor = None  # bound by _require_m4_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m4_surface():
    """Bind the M4 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error."""
    global Auditor
    from zotwiki.auditor import Auditor as Auditor_

    Auditor = Auditor_


def _fresh_vault(tmp_path):
    return tmp_path / f"vault{next(_DIRS)}"


@SETTINGS
@given(articles=clean_vault_articles())
def test_req_023__random_clean_vaults_always_audit_ok(
    fake_zotero, zstore, tmp_path, articles
):
    fake_zotero.reset()
    store, _ = zstore()
    vault = _fresh_vault(tmp_path)
    publish_clean_vault(fake_zotero, store, vault, articles)

    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == len(articles)


@SETTINGS
@given(articles=clean_vault_articles(), data=st.data())
def test_req_024__single_unresolved_citekey_yields_exactly_its_violations(
    fake_zotero, zstore, tmp_path, articles, data
):
    cited = sorted(quotes_by_citekey(articles))
    assume(cited)
    target = data.draw(st.sampled_from(cited))

    fake_zotero.reset()
    store, _ = zstore()
    vault = _fresh_vault(tmp_path)
    refs = publish_clean_vault(fake_zotero, store, vault, articles)

    unregister(fake_zotero, refs[target])
    report = Auditor(vault, store).audit()

    expected = sorted(
        ("CITEKEY_UNRESOLVED", f"{article.title}.md", target)
        for article in articles
        if any(target in claim.citekeys for claim in article.claims)
    )
    assert sorted(
        (v.code, v.page, v.detail) for v in report.violations
    ) == expected
    assert [(v.page, v.code, v.detail) for v in report.violations] == sorted(
        (v.page, v.code, v.detail) for v in report.violations
    )
    assert report.ok is False
    assert report.pages_checked == len(articles)


@SETTINGS
@given(articles=clean_vault_articles(), data=st.data())
def test_req_025__erased_fulltext_yields_exactly_quote_violations(
    fake_zotero, zstore, tmp_path, articles, data
):
    quoted = sorted(
        ck for ck, quotes in quotes_by_citekey(articles).items() if quotes
    )
    assume(quoted)
    target = data.draw(st.sampled_from(quoted))
    for article in articles:  # keep per-page quote identities unambiguous
        page_quotes = [
            q.text
            for claim in article.claims
            for q in claim.quotes
            if q.citekey == target
        ]
        assume(len({normalize_text(t) for t in page_quotes})
               == len(page_quotes))

    fake_zotero.reset()
    store, _ = zstore()
    vault = _fresh_vault(tmp_path)
    refs = publish_clean_vault(fake_zotero, store, vault, articles)

    # 200 with empty content: has_fulltext stays True, every quote misses.
    fake_zotero.fulltext[refs[target].key] = ""
    report = Auditor(vault, store).audit()

    expected = sorted(
        (f"{article.title}.md", "QUOTE_NOT_FOUND",
         f"{target}: {quote.text[:60]}")
        for article in articles
        for claim in article.claims
        for quote in claim.quotes
        if quote.citekey == target
    )
    assert [(v.page, v.code, v.detail) for v in report.violations] == expected
    assert report.pages_checked == len(articles)


@SETTINGS
@given(pair=equivalent_quote_pairs())
def test_req_025__equivalent_surface_forms_always_verify(
    fake_zotero, zstore, tmp_path, pair
):
    page_quote, fulltext_snippet = pair
    assert normalize_text(page_quote) == normalize_text(fulltext_snippet)

    fake_zotero.reset()
    store, _ = zstore()
    vault = _fresh_vault(tmp_path)
    ck = rand_citekey()
    article = Article(
        title=f"Quote Study {rand_word().capitalize()}",
        summary=f"Normalization {rand_word()}.",
        sections=(),
        claims=(
            Claim(
                text=f"Claim {rand_word()} holds.",
                citekeys=(ck,),
                quotes=(Quote(citekey=ck, text=page_quote),),
            ),
        ),
        links=(),
    )
    register_supporting_reference(
        fake_zotero, ck,
        fulltext=f"Begin {rand_word()} {fulltext_snippet} end {rand_word()}.",
    )
    VaultPublisher(vault, store, today=TODAY).publish(article)

    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == 1
