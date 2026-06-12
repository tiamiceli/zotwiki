"""M1 / Zotero adapter: hypothesis property tests.

Expectations are derived independently from docs/contract.md SS3.1 (item
mapping), SS3.3 (citekey generation), SS4.1/SS4.6 (wire shapes) over
runtime-generated data (random keys, unicode titles/creators, random
citekeys and fulltexts), so a hardcoded or constant-returning adapter
cannot pass.  Covers REQ-001, REQ-002, REQ-004, REQ-005, REQ-007.
"""
from __future__ import annotations

import json
import re
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from zotwiki.models import SourceItem

SETTINGS = settings(
    deadline=None,
    max_examples=20,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

KEY_ST = st.text(alphabet=string.ascii_uppercase + string.digits, min_size=8, max_size=8)
CITEKEY_TOKEN = st.text(
    alphabet=string.ascii_letters + string.digits + "_.:-", min_size=1, max_size=12
)
NAME_WORD = st.text(
    alphabet=st.characters(categories=("Lu", "Ll", "Lo")), min_size=1, max_size=8
)

STOPWORDS = {"a", "an", "the", "on", "of", "in", "and", "for", "to"}


# ----- independent re-implementation of the contract SS3.1 mapping -------


def expected_source_item(key: str, data: dict, has_fulltext: bool) -> "SourceItem":
    creators = []
    for entry in data.get("creators", []):
        first = (entry.get("firstName") or "").strip()
        last = (entry.get("lastName") or "").strip()
        if first and last:
            display = f"{first} {last}"
        elif last:
            display = last
        elif first:
            display = first
        else:
            display = (entry.get("name") or "").strip()
            if not display:
                continue
        creators.append(display)
    match = re.search(r"\d{4}", data.get("date", ""))
    year = int(match.group()) if match else None
    citekey = ""
    for line in data.get("extra", "").splitlines():
        m = re.match(r"^Citation Key:\s*(\S+)\s*$", line)
        if m:
            citekey = m.group(1)
            break
    return SourceItem(
        key=key,
        citekey=citekey,
        title=data.get("title", ""),
        creators=tuple(creators),
        year=year,
        url=data.get("url") or None,
        has_fulltext=has_fulltext,
    )


# ----- item-object strategies (contract SS4.4 shapes) ---------------------


CREATOR_SPEC = st.one_of(
    st.tuples(st.just("both"), NAME_WORD, NAME_WORD),
    st.tuples(st.just("first"), NAME_WORD),
    st.tuples(st.just("last"), NAME_WORD),
    st.tuples(st.just("name"), NAME_WORD),
    st.just(("empty",)),
)


def creator_dict(spec) -> dict:
    kind = spec[0]
    if kind == "both":
        return {"creatorType": "author", "firstName": spec[1], "lastName": spec[2]}
    if kind == "first":
        return {"creatorType": "author", "firstName": spec[1]}
    if kind == "last":
        return {"creatorType": "author", "lastName": spec[1]}
    if kind == "name":
        return {"creatorType": "author", "name": spec[1]}
    return {"creatorType": "author"}


DATE_SPEC = st.one_of(
    st.none(),
    st.text(alphabet=string.ascii_letters + " ./-", max_size=10),  # no digits
    st.tuples(
        st.integers(1000, 9999),
        st.sampled_from(["", "c. ", "May "]),
        st.sampled_from(["", "-06-12", " AD", "?"]),
    ),
)


def date_value(spec):
    if spec is None or isinstance(spec, str):
        return spec
    year, prefix, suffix = spec
    return f"{prefix}{year}{suffix}"


URL_SPEC = st.one_of(
    st.none(),
    st.just(""),
    CITEKEY_TOKEN.map(lambda t: f"https://example.test/{t}"),
)

EXTRA_SPEC = st.one_of(
    st.none(),
    st.just("nothing relevant in this note"),
    st.tuples(
        CITEKEY_TOKEN,
        st.sampled_from(["", "Some note\n", "alpha\nbeta\n"]),  # lines before
        st.sampled_from(["", " ", "   ", "\t"]),                # ws after colon
        st.sampled_from(["", " ", "  "]),                       # trailing ws
        st.sampled_from(["", "\nMore lines"]),                  # lines after
    ),
)


def extra_value(spec):
    if spec is None or isinstance(spec, str):
        return spec
    token, before, ws, trailing, after = spec
    return f"{before}Citation Key:{ws}{token}{trailing}{after}"


@st.composite
def search_corpora(draw):
    n = draw(st.integers(min_value=1, max_value=4))
    keys = draw(st.lists(KEY_ST, min_size=n, max_size=n, unique=True))
    marker = draw(st.text(alphabet=string.ascii_lowercase, min_size=6, max_size=10))
    specs = []
    for key in keys:
        specs.append(
            {
                "key": key,
                "pad": draw(st.tuples(st.text(max_size=8), st.text(max_size=8))),
                "creators": draw(st.none() | st.lists(CREATOR_SPEC, max_size=3)),
                "date": draw(DATE_SPEC),
                "url": draw(URL_SPEC),
                "extra": draw(EXTRA_SPEC),
                "has_fulltext": draw(st.booleans()),
            }
        )
    return marker, specs


# ----------------------------------------------------------------- REQ-001


@SETTINGS
@given(corpus=search_corpora())
def test_req_001__search_maps_arbitrary_items_per_contract(fake_zotero, zstore, corpus):
    marker, specs = corpus
    fake_zotero.reset()
    expected = []
    for spec in specs:
        pre, post = spec["pad"]
        data = {
            "key": spec["key"],
            "itemType": "journalArticle",
            "title": f"{pre}{marker}{post}",
        }
        if spec["creators"] is not None:
            data["creators"] = [creator_dict(c) for c in spec["creators"]]
        date = date_value(spec["date"])
        if date is not None:
            data["date"] = date
        if spec["url"] is not None:
            data["url"] = spec["url"]
        extra = extra_value(spec["extra"])
        if extra is not None:
            data["extra"] = extra
        fake_zotero.put_raw_item(
            spec["key"],
            data,
            fulltext=f"fulltext of {spec['key']}" if spec["has_fulltext"] else None,
        )
        expected.append(expected_source_item(spec["key"], data, spec["has_fulltext"]))
    store, _ = zstore()

    assert store.search(marker, limit=100) == expected


# ----------------------------------------------------------------- REQ-002


@SETTINGS
@given(
    limit=st.integers(min_value=-10, max_value=200),
    query=st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=12),
)
def test_req_002__limit_validation_property(fake_zotero, zstore, limit, query):
    fake_zotero.reset()
    store, sleeps = zstore()

    if 1 <= limit <= 100:
        assert store.search(query, limit=limit) == []
        requests = fake_zotero.search_requests()
        assert len(requests) == 1
        assert requests[0].params["limit"] == [str(limit)]
    else:
        with pytest.raises(ValueError):
            store.search(query, limit=limit)
        assert fake_zotero.requests == []
    assert sleeps == []


# ----------------------------------------------------------------- REQ-004


@SETTINGS
@given(content=st.text(min_size=1, max_size=300), key=KEY_ST)
def test_req_004__fulltext_round_trips_arbitrary_unicode(fake_zotero, zstore, content, key):
    fake_zotero.reset()
    fake_zotero.put_raw_item(key, {"key": key, "title": "anything"}, fulltext=content)
    store, _ = zstore()

    assert store.fulltext(key) == content


# ----------------------------------------------------------------- REQ-005


LINE_SPEC = st.one_of(
    st.tuples(st.just("noise"), st.text(alphabet=string.ascii_letters + " ", max_size=20)),
    st.tuples(
        st.just("ck"),
        CITEKEY_TOKEN,
        st.sampled_from(["", " ", "   ", "\t"]),
        st.sampled_from(["", " ", "  "]),
    ),
)


@SETTINGS
@given(lines=st.lists(LINE_SPEC, max_size=6), key=KEY_ST)
def test_req_005__citekey_extraction_property(fake_zotero, zstore, lines, key):
    fake_zotero.reset()
    rendered = []
    expected = ""
    for spec in lines:
        if spec[0] == "noise":
            rendered.append(spec[1])  # no ':' in noise -> can never match
        else:
            _, token, ws, trailing = spec
            rendered.append(f"Citation Key:{ws}{token}{trailing}")
            if not expected:
                expected = token  # first matching line wins
    fake_zotero.put_raw_item(
        key, {"key": key, "title": "extra probe", "extra": "\n".join(rendered)}
    )
    store, _ = zstore()

    assert store.get(key).citekey == expected


# ----------------------------------------------------------------- REQ-007


WORD_CORE = st.text(
    alphabet=string.ascii_lowercase + string.digits, min_size=1, max_size=6
)
DECOR = st.sampled_from(["", "'", "-", "é", "Ø", "ß", "漢", "’"])


@st.composite
def words(draw):
    """A word whose cleaned form (lowercase, non-[a-z0-9] removed) is its core."""
    core = draw(WORD_CORE)
    cased = core.upper() if draw(st.booleans()) else core
    pre, mid, post = draw(DECOR), draw(DECOR), draw(DECOR)
    return f"{pre}{cased[:1]}{mid}{cased[1:]}{post}"


DISPLAY_NAME = st.lists(words(), min_size=1, max_size=3).map(" ".join)


def _clean(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def expected_citekey(creators, year, title) -> str:
    author = "anon"
    if creators:
        author = _clean(creators[0].split()[-1]) or "anon"
    year_part = str(year) if year is not None else "nd"
    word = "item"
    for candidate in title.split():
        cleaned = _clean(candidate)
        if cleaned and cleaned not in STOPWORDS:
            word = cleaned
            break
    return f"{author}{year_part}{word}"


def expected_creator_entries(creators) -> list:
    entries = []
    for display in creators:
        if " " in display:
            first, _, last = display.rpartition(" ")
            entries.append(
                {"creatorType": "author", "firstName": first, "lastName": last}
            )
        else:
            entries.append({"creatorType": "author", "name": display})
    return entries


@SETTINGS
@given(
    creators=st.lists(DISPLAY_NAME, max_size=2),
    year=st.none() | st.integers(1000, 2100),
    title_words=st.lists(
        words() | st.sampled_from(sorted(STOPWORDS)), min_size=1, max_size=4
    ),
    item_type=st.sampled_from([None, "webpage", "report", "book"]),
    url=st.none() | WORD_CORE.map(lambda t: f"https://x.example/{t}"),
)
def test_req_007__add_generates_citekey_and_body_per_contract(
    fake_zotero, zstore, creators, year, title_words, item_type, url
):
    fake_zotero.reset()
    title = " ".join(title_words)
    citekey = expected_citekey(creators, year, title)
    store, _ = zstore()

    kwargs = {"title": title, "creators": list(creators), "year": year, "url": url}
    if item_type is not None:
        kwargs["item_type"] = item_type
    item = store.add(**kwargs)

    posts = fake_zotero.post_requests()
    assert len(posts) == 1
    assert json.loads(posts[0].body.decode("utf-8")) == [
        {
            "itemType": item_type or "webpage",
            "title": title,
            "creators": expected_creator_entries(creators),
            "date": str(year) if year is not None else "",
            "url": url or "",
            "extra": f"Citation Key: {citekey}",
        }
    ]
    assert item == SourceItem(
        key=fake_zotero.created_keys[-1],
        citekey=citekey,
        title=title,
        creators=tuple(creators),
        year=year,
        url=url,
        has_fulltext=False,
    )
