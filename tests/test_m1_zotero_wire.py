"""M1 / Zotero adapter: search wire format, resolve, add.

Covers REQ-002, REQ-006, REQ-007 (docs/requirements.md SSA, docs/contract.md
SS3.2-SS3.3, SS4.1, SS4.6).
"""
from __future__ import annotations

import json
import random
import string

import pytest

from zotwiki.errors import (
    CitekeyNotFoundError,
    FulltextNotFoundError,
    ItemNotFoundError,
    ZoteroError,
    ZoteroUnavailableError,
)
from zotwiki.models import SourceItem


def _tok(n: int = 8, alphabet: str = string.ascii_lowercase) -> str:
    return "".join(random.choices(alphabet, k=n))


# ----------------------------------------------------------------- REQ-002


def test_req_002__search_sends_exact_wire_request_plus_fulltext_probes(fake_zotero, zstore):
    w1, w2 = _tok(5), _tok(5)
    query = f"{w1} {w2}"
    k1 = fake_zotero.add_item(title=f"alpha {query} beta", fulltext="some text")
    k2 = fake_zotero.add_item(title=f"{query} gamma")
    store, _ = zstore()

    got = store.search(query, limit=7)

    assert len(got) == 2
    searches = fake_zotero.search_requests()
    assert len(searches) == 1
    req = searches[0]
    assert req.path == fake_zotero.items_path
    assert req.params == {
        "q": [query],
        "qmode": ["titleCreatorYear"],
        "limit": ["7"],
        "format": ["json"],
    }
    # the query must arrive URL-encoded (space as + or %20), never raw
    assert f"q={w1}+{w2}" in req.raw_query or f"q={w1}%20{w2}" in req.raw_query
    # the only other traffic is exactly one fulltext probe per returned item
    other_paths = sorted(r.path for r in fake_zotero.requests if r is not req)
    assert other_paths == sorted(
        [fake_zotero.fulltext_path(k1), fake_zotero.fulltext_path(k2)]
    )


@pytest.mark.parametrize("bad_limit", [0, -1, 101, 1000])
def test_req_002__limit_out_of_range_raises_value_error_before_any_http(
    fake_zotero, zstore, bad_limit
):
    fake_zotero.add_item(title="anything at all")
    store, sleeps = zstore()

    with pytest.raises(ValueError):
        store.search("anything", limit=bad_limit)

    assert fake_zotero.requests == []
    assert sleeps == []


@pytest.mark.parametrize("ok_limit", [1, 100])
def test_req_002__limit_bounds_are_inclusive(fake_zotero, zstore, ok_limit):
    store, _ = zstore()

    got = store.search(_tok(12), limit=ok_limit)  # nothing matches

    assert got == []
    searches = fake_zotero.search_requests()
    assert len(searches) == 1
    assert searches[0].params["limit"] == [str(ok_limit)]
    assert len(fake_zotero.requests) == 1  # no items -> no probes


def test_req_002__default_limit_is_25_on_the_wire(fake_zotero, zstore):
    store, _ = zstore()

    store.search(_tok(12))

    assert fake_zotero.search_requests()[0].params["limit"] == ["25"]


# ----------------------------------------------------------------- REQ-006


def test_req_006__resolve_returns_exact_match_and_sends_contract_wire(fake_zotero, zstore):
    ck = f"doe2020attention{_tok(4)}"
    fake_zotero.add_item(title="superstring decoy", citekey=ck + "x")
    target = fake_zotero.add_item(
        title="the real one", citekey=ck, fulltext="exact match text"
    )
    fake_zotero.add_item(title="url decoy", url=f"https://example.test/{ck}")
    store, _ = zstore()

    item = store.resolve(ck)

    assert item.key == target
    assert item.citekey == ck
    assert item.has_fulltext is True
    searches = fake_zotero.search_requests()
    assert len(searches) == 1
    assert searches[0].params == {
        "q": [ck],
        "qmode": ["everything"],
        "limit": ["100"],
        "format": ["json"],
    }


def test_req_006__first_of_several_exact_matches_in_server_order_wins(fake_zotero, zstore):
    ck = f"dup2021citekey{_tok(4)}"
    first = fake_zotero.add_item(title="zz added first", citekey=ck)
    fake_zotero.add_item(title="aa added second", citekey=ck)
    store, _ = zstore()

    assert store.resolve(ck).key == first


def test_req_006__resolve_is_case_sensitive(fake_zotero, zstore):
    sfx = _tok(4)
    fake_zotero.add_item(title="cased", citekey=f"Doe2020Attn{sfx}")
    store, _ = zstore()

    # the server matches case-insensitively, so it returns the item; the
    # adapter's client-side exact filter must still reject it
    with pytest.raises(CitekeyNotFoundError):
        store.resolve(f"doe2020attn{sfx}")


def test_req_006__server_hit_on_other_field_or_substring_is_not_a_match(fake_zotero, zstore):
    ck = f"miss2019target{_tok(4)}"
    fake_zotero.add_item(title="superstring citekey", citekey=ck + "x")
    fake_zotero.add_item(title="mentioned in notes", extra=f"see also {ck}")
    fake_zotero.add_item(title="hit via url", url=f"https://example.test/{ck}")
    store, _ = zstore()

    with pytest.raises(CitekeyNotFoundError):
        store.resolve(ck)


def test_req_006__unknown_citekey_raises_citekey_not_found(fake_zotero, zstore):
    store, sleeps = zstore()

    with pytest.raises(CitekeyNotFoundError):
        store.resolve(f"ghost2024nothing{_tok(4)}")

    assert sleeps == []


# ----------------------------------------------------------------- REQ-007


def test_req_007__add_posts_contract_body_and_returns_built_item(fake_zotero, zstore):
    store, _ = zstore()

    item = store.add(
        title="A Study of Owls",
        url="https://owl.example",
        creators=["Ada Lovelace"],
        year=2021,
    )

    posts = fake_zotero.post_requests()
    assert len(posts) == 1
    assert json.loads(posts[0].body.decode("utf-8")) == [
        {
            "itemType": "webpage",
            "title": "A Study of Owls",
            "creators": [
                {"creatorType": "author", "firstName": "Ada", "lastName": "Lovelace"}
            ],
            "date": "2021",
            "url": "https://owl.example",
            "extra": "Citation Key: lovelace2021study",
        }
    ]
    new_key = fake_zotero.created_keys[-1]
    assert item == SourceItem(
        key=new_key,
        citekey="lovelace2021study",
        title="A Study of Owls",
        creators=("Ada Lovelace",),
        year=2021,
        url="https://owl.example",
        has_fulltext=False,
    )
    assert len(fake_zotero.probe_requests(new_key)) == 1  # SS4.5 probe applies


def test_req_007__creator_encoding_and_empty_defaults_in_posted_body(fake_zotero, zstore):
    store, _ = zstore()

    store.add(
        title="The Owl",
        creators=["Plato", "Ada Augusta Lovelace"],
        item_type="report",
    )

    body = json.loads(fake_zotero.post_requests()[0].body.decode("utf-8"))
    assert body == [
        {
            "itemType": "report",
            "title": "The Owl",
            "creators": [
                {"creatorType": "author", "name": "Plato"},  # single token -> name
                {  # display name splits at the LAST space
                    "creatorType": "author",
                    "firstName": "Ada Augusta",
                    "lastName": "Lovelace",
                },
            ],
            "date": "",   # year None -> ""
            "url": "",    # url None -> "" (contract SS4.6 DECISION)
            "extra": "Citation Key: platondowl",
        }
    ]


def test_req_007__citekey_unicode_author_falls_back_to_anon(fake_zotero, zstore):
    store, _ = zstore()

    item = store.add(title="The Échantillon Set", creators=["李 明"], year=2023)

    # author token "明" cleans to "" -> "anon"; "the" is a stopword;
    # "échantillon" cleans to "chantillon"
    assert item.citekey == "anon2023chantillon"
    body = json.loads(fake_zotero.post_requests()[0].body.decode("utf-8"))
    assert body[0]["extra"] == "Citation Key: anon2023chantillon"


def test_req_007__citekey_word_falls_back_to_item_when_all_stopwords(fake_zotero, zstore):
    store, _ = zstore()

    item = store.add(title="Of The And", creators=["Bo Hu"], year=1999)

    assert item.citekey == "hu1999item"


def test_req_007__citekey_collision_appends_first_free_suffix(fake_zotero, zstore):
    ln, w = _tok(6), _tok(5)
    base = f"{ln}2021{w}"
    for existing in (base, base + "a", base + "b"):
        fake_zotero.add_item(title=f"occupant of {existing}", citekey=existing)
    store, _ = zstore()

    item = store.add(
        title=f"The {w.capitalize()} Papers",
        creators=[f"Ada {ln.capitalize()}"],
        year=2021,
    )

    assert item.citekey == base + "c"
    posts = fake_zotero.post_requests()
    assert len(posts) == 1
    body = json.loads(posts[0].body.decode("utf-8"))
    assert body[0]["extra"] == f"Citation Key: {base}c"


def test_req_007__citekey_suffix_exhaustion_raises_and_posts_nothing(fake_zotero, zstore):
    ln, w = _tok(6), _tok(5)
    base = f"{ln}2021{w}"
    for suffix in [""] + list(string.ascii_lowercase):
        fake_zotero.add_item(title=f"occupant {suffix or 'bare'}", citekey=base + suffix)
    store, _ = zstore()

    with pytest.raises(ZoteroError) as exc:
        store.add(
            title=f"The {w.capitalize()} Papers",
            creators=[f"Ada {ln.capitalize()}"],
            year=2021,
        )

    assert not isinstance(
        exc.value,
        (ItemNotFoundError, CitekeyNotFoundError, FulltextNotFoundError,
         ZoteroUnavailableError),
    )
    assert fake_zotero.post_requests() == []


def test_req_007__server_reported_failure_raises_zotero_error(fake_zotero, zstore):
    fake_zotero.post_response = {
        "successful": {},
        "failed": {"0": {"code": 400, "message": "invalid item"}},
    }
    store, _ = zstore()

    with pytest.raises(ZoteroError) as exc:
        store.add(title=f"The {_tok(5).capitalize()} Papers")

    assert not isinstance(
        exc.value,
        (ItemNotFoundError, CitekeyNotFoundError, FulltextNotFoundError,
         ZoteroUnavailableError),
    )
