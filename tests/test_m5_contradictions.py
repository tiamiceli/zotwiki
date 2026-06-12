"""M5 / publish_contradictions and Contradictions.md (REQ-031): the page is
created on first use with the canonical SS6.8 layout, every call appends one
`## {page} ({today})` block with consecutive EXISTING/NEW pairs (NEW carrying
the SS6.3 citekey suffix), prior blocks are preserved verbatim and never
reordered, the targeted entity page (and the rest of the vault) stays
byte-identical, and an empty contradictions sequence raises ValueError with
nothing written.

Black-box; fake Zotero on 127.0.0.1; vaults in tmp_path; `today` injected;
the byte oracle is the independent SS6.8 renderer in m5_helpers.
"""
from __future__ import annotations

import pytest

from zotwiki.models import Contradiction
from zotwiki.publisher import CONTRADICTIONS_FILENAME, VaultPublisher

from m2_helpers import rand_word
from m3_helpers import stamp_mtimes, vault_snapshot
from m4_helpers import build_article, distinct_citekeys
from m5_helpers import (
    LATER,
    TODAY,
    contradiction_blocks,
    contradictions_oracle,
    distinct_titles,
    register_citekey_map,
)


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def _contradiction(existing_claim: str, citekeys) -> Contradiction:
    return Contradiction(
        existing_claim=existing_claim,
        new_claim=f"Contrary finding {rand_word()} {rand_word()} dominates.",
        citekeys=tuple(sorted(citekeys)),
    )


def test_req_031__first_call_creates_canonical_page_and_entity_page_is_untouched(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck, ck_x, ck_y = distinct_citekeys(3)
    [title] = distinct_titles(1)
    article = build_article([(ck,)], title=title)
    register_citekey_map(fake_zotero, [ck, ck_x, ck_y])
    publisher = VaultPublisher(vault, store, today=TODAY)
    page = publisher.publish(article)
    assert not (vault / CONTRADICTIONS_FILENAME).exists()

    stamp_mtimes(vault)
    before = vault_snapshot(vault)
    contradiction = _contradiction(article.claims[0].text, (ck_x, ck_y))

    returned = publisher.publish_contradictions(title, [contradiction])

    contra_path = vault / CONTRADICTIONS_FILENAME
    assert returned == contra_path
    expected = contradictions_oracle([(title, TODAY, [contradiction])],
                                     created=TODAY, updated=TODAY)
    assert contra_path.read_bytes() == expected.encode("utf-8")

    # Everything that existed before is byte- and mtime-identical: the
    # entity page is never modified, the contradicting claim never added.
    after = vault_snapshot(vault)
    after.pop(CONTRADICTIONS_FILENAME)
    assert after == before
    page_text = page.read_text(encoding="utf-8")
    assert contradiction.new_claim not in page_text
    assert article.claims[0].text in page_text


def test_req_031__later_calls_append_only_and_preserve_prior_blocks_verbatim(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    cks = distinct_citekeys(4)
    title_one, title_two = distinct_titles(2)
    article_one = build_article([(cks[0],)], title=title_one)
    article_two = build_article([(cks[1],)], title=title_two)
    register_citekey_map(fake_zotero, cks)
    first_publisher = VaultPublisher(vault, store, today=TODAY)
    first_publisher.publish(article_one)
    first_publisher.publish(article_two)

    first_call = [_contradiction(article_one.claims[0].text, (cks[2],))]
    first_publisher.publish_contradictions(title_one, first_call)
    contra_path = vault / CONTRADICTIONS_FILENAME
    first_text = contra_path.read_text(encoding="utf-8")
    first_tail = first_text.split("# Contradictions", 1)[1]

    stamp_mtimes(vault)
    entity_before = vault_snapshot(vault)
    entity_before.pop(CONTRADICTIONS_FILENAME)

    second_call = [
        _contradiction(article_two.claims[0].text, (cks[3],)),
        _contradiction(article_two.claims[0].text, (cks[2], cks[3])),
    ]
    VaultPublisher(vault, store, today=LATER).publish_contradictions(
        title_two, second_call
    )

    expected = contradictions_oracle(
        [(title_one, TODAY, first_call), (title_two, LATER, second_call)],
        created=TODAY,   # first-write created preserved
        updated=LATER,   # the file changed: updated == the appending today
    )
    assert contra_path.read_bytes() == expected.encode("utf-8")
    new_text = contra_path.read_text(encoding="utf-8")
    assert first_tail in new_text  # prior blocks verbatim, never reordered
    assert new_text.index(f"## {title_one} ({TODAY})") < new_text.index(
        f"## {title_two} ({LATER})"
    )

    after = vault_snapshot(vault)
    after.pop(CONTRADICTIONS_FILENAME)
    assert after == entity_before  # entity pages and Index never touched


def test_req_031__one_call_with_many_contradictions_keeps_pairs_consecutive(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck, ck_a, ck_b, ck_c = distinct_citekeys(4)
    [title] = distinct_titles(1)
    article = build_article([(ck,)], title=title)
    register_citekey_map(fake_zotero, [ck, ck_a, ck_b, ck_c])
    publisher = VaultPublisher(vault, store, today=TODAY)
    publisher.publish(article)

    contradictions = [
        _contradiction(article.claims[0].text, (ck_a,)),
        _contradiction(article.claims[0].text, (ck_b,)),
        _contradiction(article.claims[0].text, (ck_a, ck_c)),
    ]

    publisher.publish_contradictions(title, contradictions)

    contra_path = vault / CONTRADICTIONS_FILENAME
    expected = contradictions_oracle([(title, TODAY, contradictions)],
                                     created=TODAY, updated=TODAY)
    assert contra_path.read_bytes() == expected.encode("utf-8")

    text = contra_path.read_text(encoding="utf-8")
    assert text.count(f"## {title} ({TODAY})") == 1  # one heading per call
    _, pairs_block = contradiction_blocks(title, TODAY, contradictions)
    assert pairs_block in text  # all pairs consecutive, in call order


def test_req_031__identical_calls_append_duplicate_blocks_never_dedupe(
    tmp_path, store, fake_zotero
):
    """SS6.8: blocks are appended once per call and never rewritten -- an
    identical second call appends an identical second block (no change-gate,
    no dedupe)."""
    vault = tmp_path / "vault"
    ck, ck_x = distinct_citekeys(2)
    [title] = distinct_titles(1)
    article = build_article([(ck,)], title=title)
    register_citekey_map(fake_zotero, [ck, ck_x])
    publisher = VaultPublisher(vault, store, today=TODAY)
    publisher.publish(article)
    call = [_contradiction(article.claims[0].text, (ck_x,))]

    publisher.publish_contradictions(title, call)
    publisher.publish_contradictions(title, call)

    expected = contradictions_oracle(
        [(title, TODAY, call), (title, TODAY, call)],
        created=TODAY, updated=TODAY,
    )
    assert (vault / CONTRADICTIONS_FILENAME).read_bytes() == (
        expected.encode("utf-8")
    )
    text = (vault / CONTRADICTIONS_FILENAME).read_text(encoding="utf-8")
    assert text.count(f"## {title} ({TODAY})") == 2


def test_req_031__empty_sequence_raises_valueerror_and_writes_nothing(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck, ck_x = distinct_citekeys(2)
    [title] = distinct_titles(1)
    article = build_article([(ck,)], title=title)
    register_citekey_map(fake_zotero, [ck, ck_x])
    publisher = VaultPublisher(vault, store, today=TODAY)
    publisher.publish(article)

    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    with pytest.raises(ValueError):
        publisher.publish_contradictions(title, [])

    assert not (vault / CONTRADICTIONS_FILENAME).exists()  # not even created
    assert vault_snapshot(vault) == before

    # Same with an existing Contradictions.md: the file must stay untouched.
    publisher.publish_contradictions(
        title, [_contradiction(article.claims[0].text, (ck_x,))]
    )
    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    with pytest.raises(ValueError):
        publisher.publish_contradictions(title, [])

    assert vault_snapshot(vault) == before
