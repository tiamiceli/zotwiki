"""M1 / Zotero adapter: item mapping, get, fulltext, citekey extraction.

Covers REQ-001, REQ-003, REQ-004, REQ-005 (docs/requirements.md SSA,
docs/contract.md SS3.1, SS4.2-SS4.4).  Black-box: only the public surface of
contract SS1.1 is imported; the server side is the conftest fake.
"""
from __future__ import annotations

import random
import string

import pytest

from zotwiki.errors import (
    FulltextNotFoundError,
    ItemNotFoundError,
    ZoteroError,
    ZoteroUnavailableError,
)
from zotwiki.models import SourceItem
from zotwiki.zotero import DEFAULT_BASE_URL, ZoteroStore


def _tok(n: int = 8, alphabet: str = string.ascii_lowercase) -> str:
    return "".join(random.choices(alphabet, k=n))


# ----------------------------------------------------------------- REQ-001


def test_req_001__search_returns_mapped_source_items_in_server_order(fake_zotero, zstore):
    sfx = _tok()
    ck = f"vaswani2017attention{sfx}"
    title1 = f"Zz Attention Is All You Need {sfx}"
    title2 = f"Aa attention survey {sfx}"  # sorts before title1: order must be server order
    k1 = fake_zotero.add_item(
        title=title1,
        creators=[
            fake_zotero.creator(first="Ashish", last="Vaswani"),
            fake_zotero.creator(name="DeepThought Collective"),
        ],
        date="2017-06-12",
        url="https://arxiv.org/abs/1706.03762",
        citekey=ck,
        fulltext=f"the dominant sequence transduction models {sfx}",
    )
    k2 = fake_zotero.add_item(
        title=title2,
        date="circa 1999, reprinted",
        url="",                       # empty url must map to None
        extra="no citation key in here",
        # no creators field at all: must map to ()
    )
    store, sleeps = zstore()

    got = store.search("attention")

    assert isinstance(got, list)
    assert got == [
        SourceItem(
            key=k1,
            citekey=ck,
            title=title1,
            creators=("Ashish Vaswani", "DeepThought Collective"),
            year=2017,
            url="https://arxiv.org/abs/1706.03762",
            has_fulltext=True,
        ),
        SourceItem(
            key=k2,
            citekey="",
            title=title2,
            creators=(),
            year=1999,
            url=None,
            has_fulltext=False,
        ),
    ]
    assert sleeps == []


def test_req_001__creator_display_name_rules(fake_zotero, zstore):
    key = fake_zotero.add_item(
        title=f"attention creators {_tok()}",
        creators=[
            fake_zotero.creator(first=" Ada", last="Lovelace "),  # stripped, one space
            fake_zotero.creator(last="Curie"),                    # lastName alone
            fake_zotero.creator(first="Blaise"),                  # firstName alone
            fake_zotero.creator(name="DeepThought Collective"),   # name field
            fake_zotero.creator(),                                # nothing: skipped
            fake_zotero.creator(first="", last="", name=""),      # empty: skipped
        ],
    )
    store, _ = zstore()

    item = store.get(key)

    assert item.creators == (
        "Ada Lovelace",
        "Curie",
        "Blaise",
        "DeepThought Collective",
    )


def test_req_001__year_is_first_four_digit_run_or_none(fake_zotero, zstore):
    cases = {
        "2017-06-12": 2017,
        "12/06/2017": 2017,
        "ca. 1999-2001 draft": 1999,
        "May twelve": None,
        "": None,
        "123": None,
    }
    keys = {
        fake_zotero.add_item(title=f"date case {_tok()}", date=date): year
        for date, year in cases.items()
    }
    no_date_key = fake_zotero.add_item(title=f"no date at all {_tok()}")
    store, _ = zstore()

    for key, year in keys.items():
        assert store.get(key).year == year
    assert store.get(no_date_key).year is None


def test_req_001__malformed_search_json_raises_zotero_error(fake_zotero, zstore):
    fake_zotero.set_raw("GET", fake_zotero.items_path, 200, b'{"this is": not json')
    store, sleeps = zstore()

    with pytest.raises(ZoteroError) as exc:
        store.search("anything")

    assert not isinstance(exc.value, ZoteroUnavailableError)  # 200 is not retryable
    assert sleeps == []


def test_req_001__store_satisfies_zoterostore_protocol_and_default_base_url(fake_zotero, zstore):
    # REQ-001's "the store" is an HTTPZoteroStore implementing the SS3 protocol.
    assert DEFAULT_BASE_URL == "http://127.0.0.1:23119/api/users/0"
    store, _ = zstore()
    assert isinstance(store, ZoteroStore)


def test_req_001__search_with_no_matches_returns_empty_list(fake_zotero, zstore):
    fake_zotero.add_item(title="completely unrelated")
    store, _ = zstore()

    got = store.search(_tok(12))

    assert got == []
    # no items materialized: the only request is the search itself, no probes
    assert len(fake_zotero.requests) == 1


# ----------------------------------------------------------------- REQ-003


def test_req_003__get_by_key_returns_mapped_item(fake_zotero, zstore):
    sfx = _tok()
    ck = f"doe2020attention{_tok(4)}"
    title = f"A Treatise on Owls {sfx}"
    key = fake_zotero.add_item(
        title=title,
        creators=[fake_zotero.creator(first="Jane", last="Doe")],
        date="2020-01-01",
        url=f"https://example.test/{sfx}",
        citekey=ck,
        fulltext="owls are silent fliers",
    )
    store, _ = zstore()

    item = store.get(key)

    assert item == SourceItem(
        key=key,
        citekey=ck,
        title=title,
        creators=("Jane Doe",),
        year=2020,
        url=f"https://example.test/{sfx}",
        has_fulltext=True,
    )
    item_reqs = fake_zotero.item_requests(key)
    assert len(item_reqs) == 1
    assert item_reqs[0].params.get("format") == ["json"]  # contract SS4.2


def test_req_003__unknown_key_raises_item_not_found_without_retry(fake_zotero, zstore):
    store, sleeps = zstore(retries=3, backoff=0.5)
    missing = "QQQQ" + _tok(4, string.ascii_uppercase)

    with pytest.raises(ItemNotFoundError):
        store.get(missing)

    assert len(fake_zotero.item_requests(missing)) == 1  # 404 never retried
    assert sleeps == []


def test_req_003__base_url_trailing_slash_is_stripped(fake_zotero, zstore):
    key = fake_zotero.add_item(title=f"slash tolerance {_tok()}")
    store, _ = zstore(base_url=fake_zotero.base_url + "/")

    assert store.get(key).key == key


def test_req_003__unicode_titles_creators_and_citekeys_round_trip(fake_zotero, zstore):
    title = f"Über die Quantenmechanik 量子力学 — naïveté {_tok()}"
    ck = f"žižek1925über{_tok(3)}"
    key = fake_zotero.add_item(
        title=title,
        creators=[fake_zotero.creator(first="Łukasz", last="Žižek")],
        date="1925",
        citekey=ck,
    )
    store, _ = zstore()

    item = store.get(key)

    assert item.title == title
    assert item.creators == ("Łukasz Žižek",)
    assert item.citekey == ck
    assert item.year == 1925


# ----------------------------------------------------------------- REQ-004


def test_req_004__fulltext_returns_exact_content(fake_zotero, zstore):
    content = "Sphinx of black quartz."
    key = fake_zotero.add_item(title="quartz", fulltext=content)
    unicode_content = f"It’s a “quartz—sphinx”. {_tok()}\nline two ¶"
    key2 = fake_zotero.add_item(title="quartz two", fulltext=unicode_content)
    store, _ = zstore()

    assert store.fulltext(key) == content
    assert store.fulltext(key2) == unicode_content


def test_req_004__missing_fulltext_raises_fulltext_not_found_without_retry(fake_zotero, zstore):
    key = fake_zotero.add_item(title=f"no fulltext here {_tok()}")
    store, sleeps = zstore(retries=3, backoff=0.5)

    with pytest.raises(FulltextNotFoundError):
        store.fulltext(key)

    assert len(fake_zotero.probe_requests(key)) == 1  # 404 never retried
    assert sleeps == []


def test_req_004__fulltext_for_unknown_key_raises_fulltext_not_found(fake_zotero, zstore):
    store, sleeps = zstore()

    with pytest.raises(FulltextNotFoundError):
        store.fulltext("ZZZZ" + _tok(4, string.ascii_uppercase))

    assert sleeps == []


# ----------------------------------------------------------------- REQ-005


def test_req_005__citekey_extracted_from_multiline_extra(fake_zotero, zstore):
    ck = f"doe2020attention{_tok(4)}"
    key = fake_zotero.add_item(
        title="extra block",
        extra=f"Some note\nCitation Key: {ck}\nMore",
    )
    store, _ = zstore()

    assert store.get(key).citekey == ck


def test_req_005__first_matching_line_wins_and_whitespace_is_tolerated(fake_zotero, zstore):
    ck1, ck2 = f"first{_tok(4)}", f"second{_tok(4)}"
    key = fake_zotero.add_item(
        title="two citekey lines",
        extra=f"Citation Key:\t {ck1}  \nCitation Key: {ck2}",
    )
    store, _ = zstore()

    assert store.get(key).citekey == ck1


@pytest.mark.parametrize(
    "extra",
    [
        None,                              # extra absent entirely
        "",                                # empty extra
        "no key in this note",             # no matching line
        "citation key: lower2020case",     # case-sensitive prefix: no match
        "Citation Key: two words",         # citekey must be \S+ to end of line
        "Citation Key:",                   # no token at all
        " Citation Key: indented2020key",  # pattern is anchored at line start
    ],
)
def test_req_005__non_matching_extra_yields_empty_citekey(fake_zotero, zstore, extra):
    kwargs = {} if extra is None else {"extra": extra}
    key = fake_zotero.add_item(title=f"no usable citekey {_tok()}", **kwargs)
    store, _ = zstore()

    item = store.get(key)  # must not raise

    assert item.citekey == ""
