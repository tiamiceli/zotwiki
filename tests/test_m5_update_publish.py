"""M5 / VaultPublisher update path (REQ-020): publishing onto an existing
page merges mechanically with the on-disk page (contract SS6.5 + SS7.2)
rendered canonically, preserves the original `created`, sets `updated` to
the new `today` only when the rendering actually changes, is idempotent on
re-publish, and raises PageParseError (file untouched) when the on-disk
page does not parse.

Black-box through the public surface; the store is an HTTPZoteroStore
against the 127.0.0.1 fake Zotero (conftest); vaults live in tmp_path;
`today` is always injected; merge expectations come from the independent
SS7.2 re-implementation in m2_helpers and the SS6 render oracle in
m3_helpers, never from zotwiki itself.
"""
from __future__ import annotations

import itertools

import pytest
from hypothesis import HealthCheck, assume, given, settings

from zotwiki.errors import CitekeyNotFoundError, PageParseError
from zotwiki.models import Article, Claim, Quote, Section
from zotwiki.publisher import VaultPublisher, parse_page

from m2_helpers import expected_merge, merge_pairs, rand_word
from m3_helpers import render_oracle, stamp_mtimes, vault_snapshot
from m4_helpers import build_article, distinct_citekeys, drop_line, unregister
from m5_helpers import (
    EVEN_LATER,
    LATER,
    TODAY,
    article_citekeys,
    distinct_titles,
    refs_for,
    register_citekey_map,
)

SETTINGS = settings(
    deadline=None,
    max_examples=10,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_DIRS = itertools.count()


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def _published_with_update(tmp_path, fake_zotero, store):
    """Publish a base article at TODAY, and build a same-title update that
    adds a section, a fresh-citekey claim and a link under a new summary.
    Returns (vault, page_path, citekey->SourceItem, existing, update)."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    [title] = distinct_titles(1)
    existing = build_article([(ck_a,)], title=title, links=())
    items = register_citekey_map(fake_zotero, [ck_a, ck_b])
    page = VaultPublisher(vault, store, today=TODAY).publish(existing)
    update = Article(
        title=title,
        summary=f"Updated synthesis {rand_word()}.",
        sections=(
            Section(heading=f"Results {rand_word()}",
                    body=f"Result {rand_word()} body."),
        ),
        claims=(
            Claim(
                text=f"Second finding {rand_word()} emerges.",
                citekeys=(ck_b,),
                quotes=(Quote(citekey=ck_b,
                              text=f"new evidence {rand_word()}"),),
            ),
        ),
        links=(f"Linked {rand_word().capitalize()}",),
    )
    return vault, page, items, existing, update


def test_req_020__update_publish_renders_mechanical_merge_with_created_preserved(
    tmp_path, store, fake_zotero
):
    vault, page, items, existing, update = _published_with_update(
        tmp_path, fake_zotero, store
    )
    before = page.read_bytes()

    returned = VaultPublisher(vault, store, today=LATER).publish(update)

    assert returned == page == vault / f"{existing.title}.md"
    merged = expected_merge(existing, update)
    expected = render_oracle(merged, refs_for(merged, items),
                             created=TODAY, updated=LATER)
    assert page.read_bytes() == expected.encode("utf-8")
    assert page.read_bytes() != before  # the page really changed

    text = page.read_text(encoding="utf-8")
    assert f'created: "{TODAY}"' in text   # original created preserved
    assert f'updated: "{LATER}"' in text   # updated == the new today
    assert existing.claims[0].text in text  # never clobbered
    assert update.claims[0].text in text    # appended
    assert parse_page(text) == merged


def test_req_020__republish_after_update_writes_nothing_even_with_later_today(
    tmp_path, store, fake_zotero
):
    vault, page, _items, _existing, update = _published_with_update(
        tmp_path, fake_zotero, store
    )
    VaultPublisher(vault, store, today=LATER).publish(update)

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    VaultPublisher(vault, store, today=EVEN_LATER).publish(update)

    assert vault_snapshot(vault) == before  # bytes AND mtimes: no write
    text = page.read_text(encoding="utf-8")
    assert f'updated: "{LATER}"' in text    # the old `updated` stands
    assert EVEN_LATER not in text


def test_req_020__merge_equal_update_keeps_old_updated_despite_later_today(
    tmp_path, store, fake_zotero
):
    """An update that differs from the on-disk article but whose SS7.2 merge
    equals it must not be written: `updated` is gated on the merged
    rendering changing, not on the input differing."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    title, link_a, link_b = distinct_titles(3)
    existing = build_article([(ck_a, ck_b)], title=title,
                             links=(link_a, link_b))
    register_citekey_map(fake_zotero, [ck_a, ck_b])
    page = VaultPublisher(vault, store, today=TODAY).publish(existing)

    kept = existing.claims[0]
    sub_quote = next(q for q in kept.quotes if q.citekey == ck_a)
    update = Article(
        title=title,
        summary=existing.summary,
        sections=(),
        claims=(Claim(text=kept.text, citekeys=(ck_a,), quotes=(sub_quote,)),),
        links=tuple(sorted((link_a,))),
    )
    assert update != existing
    assert expected_merge(existing, update) == existing  # oracle guard

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    VaultPublisher(vault, store, today=LATER).publish(update)

    assert vault_snapshot(vault) == before  # bytes AND mtimes: no write
    text = page.read_text(encoding="utf-8")
    assert f'updated: "{TODAY}"' in text
    assert LATER not in text


def test_req_020__unparseable_on_disk_page_raises_and_leaves_vault_untouched(
    tmp_path, store, fake_zotero
):
    vault, page, _items, _existing, update = _published_with_update(
        tmp_path, fake_zotero, store
    )
    drop_line(page, "## Links")  # violates the SS6.3 grammar

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    with pytest.raises(PageParseError):
        VaultPublisher(vault, store, today=LATER).publish(update)

    assert vault_snapshot(vault) == before  # corrupt page left unmodified


def test_req_020__resolution_failure_on_update_leaves_vault_untouched(
    tmp_path, store, fake_zotero
):
    """SS6.5: publish resolves every citekey of the *merged* article (the
    on-disk page's citekeys included) and propagates CitekeyNotFoundError
    before anything is written."""
    vault, _page, items, existing, update = _published_with_update(
        tmp_path, fake_zotero, store
    )
    # The citekey cited only by the on-disk page vanishes from the server.
    unregister(fake_zotero, items[existing.claims[0].citekeys[0]])

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    with pytest.raises(CitekeyNotFoundError):
        VaultPublisher(vault, store, today=LATER).publish(update)

    assert vault_snapshot(vault) == before  # fail-fast: nothing written


def test_req_020__write_gate_is_byte_level_so_noncanonical_pages_are_healed(
    tmp_path, store, fake_zotero
):
    """SS6.5: the no-write rule compares the merged *rendering* with the
    current file bytes -- not articles.  A parseable but non-canonical
    on-disk page (hand-swapped quote lines) must be rewritten canonically
    with `updated` bumped, even though the merge changes no content."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    [title] = distinct_titles(1)
    quote_a = f"alpha evidence {rand_word()}"
    quote_b = f"bravo evidence {rand_word()}"
    article = Article(
        title=title,
        summary=f"Summary {rand_word()}.",
        sections=(),
        claims=(
            Claim(text=f"Claim {rand_word()} holds.",
                  citekeys=(ck_a, ck_b),
                  quotes=(Quote(citekey=ck_a, text=quote_a),
                          Quote(citekey=ck_b, text=quote_b))),
        ),
        links=(),
    )
    items = register_citekey_map(fake_zotero, [ck_a, ck_b])
    page = VaultPublisher(vault, store, today=TODAY).publish(article)

    text = page.read_text(encoding="utf-8")
    line_a = f"  > [@{ck_a}] {quote_a}"
    line_b = f"  > [@{ck_b}] {quote_b}"
    assert f"{line_a}\n{line_b}" in text
    page.write_text(
        text.replace(f"{line_a}\n{line_b}", f"{line_b}\n{line_a}"),
        encoding="utf-8",
    )
    assert parse_page(page.read_text(encoding="utf-8")) == article

    VaultPublisher(vault, store, today=LATER).publish(article)

    expected = render_oracle(article, refs_for(article, items),
                             created=TODAY, updated=LATER)
    assert page.read_bytes() == expected.encode("utf-8")


def test_req_020__created_is_read_from_the_on_disk_frontmatter(
    tmp_path, store, fake_zotero
):
    """SS6.5: the preserved `created` is the existing page's frontmatter
    value as found on disk at update time, not a remembered one."""
    vault, page, items, existing, update = _published_with_update(
        tmp_path, fake_zotero, store
    )
    edited = "2020-02-02"
    page.write_text(
        page.read_text(encoding="utf-8").replace(
            f'created: "{TODAY}"', f'created: "{edited}"'),
        encoding="utf-8",
    )

    VaultPublisher(vault, store, today=LATER).publish(update)

    merged = expected_merge(existing, update)
    expected = render_oracle(merged, refs_for(merged, items),
                             created=edited, updated=LATER)
    assert page.read_bytes() == expected.encode("utf-8")


@SETTINGS
@given(pair=merge_pairs())
def test_req_020__random_update_publish_equals_independent_merge_oracle(
    fake_zotero, zstore, tmp_path, pair
):
    existing, update = pair
    assume(existing.title.casefold() not in ("index", "contradictions"))

    fake_zotero.reset()
    store, _ = zstore()
    vault = tmp_path / f"vault{next(_DIRS)}"
    items = register_citekey_map(fake_zotero,
                                 article_citekeys(existing, update))
    page = VaultPublisher(vault, store, today=TODAY).publish(existing)
    before = page.read_bytes()

    VaultPublisher(vault, store, today=LATER).publish(update)

    merged = expected_merge(existing, update)
    refs = refs_for(merged, items)
    unchanged = render_oracle(merged, refs, created=TODAY,
                              updated=TODAY).encode("utf-8")
    if unchanged == before:
        # no-op update: nothing rewritten, the old `updated` stands
        assert page.read_bytes() == before
    else:
        expected = render_oracle(merged, refs, created=TODAY, updated=LATER)
        assert page.read_bytes() == expected.encode("utf-8")
    assert parse_page(page.read_text(encoding="utf-8")) == merged
