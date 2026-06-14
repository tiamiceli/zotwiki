"""REQ-045 — fulltext child-attachment fallback.

Black-box tests against the public surface (contract §1.1).  Reads
docs/contract.md §3.1, §4.3, §4.5, §4.9 and docs/requirements.md §I.

The fake Zotero server (conftest FakeZotero) handles:
  GET {base}/items/{KEY}/fulltext  ->  {"content": "..."} | 404
  GET {base}/items/{KEY}           ->  item object | 404

We augment each test with ad-hoc handler overrides for the children endpoint:
  GET {base}/items/{KEY}/children?format=json  ->  [...] | []

Because FakeZotero.set_raw() maps (method, path) to verbatim bytes, we use it
to register children endpoint responses for each fixture item.  The children
path is {base}/items/{KEY}/children, not /children?format=json — pytest-
httpserver matches on path, query string is separate.

All four fixture keys are fixed strings so path arithmetic is straightforward.
"""
from __future__ import annotations

import json

import pytest

from zotwiki.errors import FulltextNotFoundError
from zotwiki.zotero import HTTPZoteroStore

# Fixed keys for all four fixture items (§4 format: 8 chars [A-Z0-9])
KEY_PARENT_HAS = "AAAA0001"     # parent fulltext -> 200 (regression guard)
KEY_CHILD_HAS  = "BBBB0002"     # parent 404, child CCCC0003 -> 200
KEY_CHILD_NONE = "DDDD0004"     # parent 404, child EEEE0005 -> 404
KEY_NO_CHILD   = "FFFF0006"     # parent 404, children endpoint -> []

CHILD_KEY      = "CCCC0003"     # child of BBBB0002 with fulltext
CHILD_KEY_NONE = "EEEE0005"     # child of DDDD0004 without fulltext

CHILD_CONTENT  = "child text"

BASE_PATH = "/api/users/0"


def _item_obj(key: str) -> dict:
    """Minimal item object in §4.4 shape."""
    return {
        "key": key,
        "version": 1,
        "data": {
            "key": key,
            "itemType": "webpage",
            "title": f"Test item {key}",
            "extra": f"Citation Key: test{key.lower()}",
        },
    }


def _children_path(key: str) -> str:
    return f"{BASE_PATH}/items/{key}/children"


def _register_item(fake_zotero, key: str, fulltext: str | None = None) -> None:
    """Put an item in the fake server; fulltext=None means no fulltext (404)."""
    fake_zotero.put_raw_item(key, _item_obj(key)["data"], fulltext=fulltext)


def _register_children(fake_zotero, parent_key: str, child_keys: list[str]) -> None:
    """Register the children endpoint for parent_key returning child_keys."""
    payload = [{"key": ck} for ck in child_keys]
    fake_zotero.set_raw(
        "GET",
        _children_path(parent_key),
        200,
        json.dumps(payload).encode(),
    )


def _make_store(fake_zotero) -> HTTPZoteroStore:
    return HTTPZoteroStore(
        fake_zotero.base_url,
        retries=0,
        sleep=lambda _: None,
    )


# ---------------------------------------------------------------- REQ-045a
# Parent-has-fulltext regression guard: AAAA0001 whose parent returns 200.
# The children endpoint must NOT be hit.


def test_req_045a__parent_fulltext_sets_has_fulltext_true(fake_zotero):
    """Item with parent fulltext: has_fulltext is True."""
    _register_item(fake_zotero, KEY_PARENT_HAS, fulltext="parent content")
    # do NOT register a children override — if it were hit, the test would
    # still pass but we check request log below to confirm it wasn't.
    store = _make_store(fake_zotero)

    item = store.get(KEY_PARENT_HAS)

    assert item.has_fulltext is True


def test_req_045a__parent_fulltext_returned_by_fulltext_method(fake_zotero):
    """store.fulltext() returns parent content when parent probe is 200."""
    _register_item(fake_zotero, KEY_PARENT_HAS, fulltext="parent content")
    store = _make_store(fake_zotero)

    result = store.fulltext(KEY_PARENT_HAS)

    assert result == "parent content"


def test_req_045a__children_endpoint_not_hit_when_parent_has_fulltext(fake_zotero):
    """Children endpoint must never be queried when parent probe succeeds."""
    _register_item(fake_zotero, KEY_PARENT_HAS, fulltext="parent content")
    store = _make_store(fake_zotero)

    store.get(KEY_PARENT_HAS)

    children_path = _children_path(KEY_PARENT_HAS)
    children_hits = fake_zotero.requests_for(children_path, "GET")
    assert children_hits == [], (
        f"Children endpoint {children_path!r} was hit even though parent fulltext "
        "was available"
    )


# ---------------------------------------------------------------- REQ-045b
# Child-fallback probe: BBBB0002 parent -> 404, child CCCC0003 -> 200.
# has_fulltext must be True.


def test_req_045b__child_fallback_sets_has_fulltext_true(fake_zotero):
    """has_fulltext is True when parent 404 but child attachment has fulltext."""
    _register_item(fake_zotero, KEY_CHILD_HAS, fulltext=None)   # no parent fulltext
    _register_item(fake_zotero, CHILD_KEY, fulltext=CHILD_CONTENT)
    _register_children(fake_zotero, KEY_CHILD_HAS, [CHILD_KEY])
    store = _make_store(fake_zotero)

    item = store.get(KEY_CHILD_HAS)

    assert item.has_fulltext is True


# ---------------------------------------------------------------- REQ-045c
# Child-fallback fetch: store.fulltext("BBBB0002") returns child content.


def test_req_045c__fulltext_returns_child_content_when_parent_404(fake_zotero):
    """store.fulltext() returns child attachment content on parent 404."""
    _register_item(fake_zotero, KEY_CHILD_HAS, fulltext=None)
    _register_item(fake_zotero, CHILD_KEY, fulltext=CHILD_CONTENT)
    _register_children(fake_zotero, KEY_CHILD_HAS, [CHILD_KEY])
    store = _make_store(fake_zotero)

    result = store.fulltext(KEY_CHILD_HAS)

    assert result == CHILD_CONTENT


# ---------------------------------------------------------------- REQ-045d
# No-fulltext anywhere: DDDD0004 parent -> 404, child EEEE0005 -> 404.
# has_fulltext must be False; fulltext() raises FulltextNotFoundError.


def test_req_045d__no_fulltext_anywhere_has_fulltext_false(fake_zotero):
    """has_fulltext is False when neither parent nor any child has fulltext."""
    _register_item(fake_zotero, KEY_CHILD_NONE, fulltext=None)   # no parent fulltext
    _register_item(fake_zotero, CHILD_KEY_NONE, fulltext=None)   # no child fulltext
    _register_children(fake_zotero, KEY_CHILD_NONE, [CHILD_KEY_NONE])
    store = _make_store(fake_zotero)

    item = store.get(KEY_CHILD_NONE)

    assert item.has_fulltext is False


def test_req_045d__fulltext_raises_when_no_fulltext_anywhere(fake_zotero):
    """store.fulltext() raises FulltextNotFoundError when all probes return 404."""
    _register_item(fake_zotero, KEY_CHILD_NONE, fulltext=None)
    _register_item(fake_zotero, CHILD_KEY_NONE, fulltext=None)
    _register_children(fake_zotero, KEY_CHILD_NONE, [CHILD_KEY_NONE])
    store = _make_store(fake_zotero)

    with pytest.raises(FulltextNotFoundError):
        store.fulltext(KEY_CHILD_NONE)


# ---------------------------------------------------------------- REQ-045e
# No children at all: FFFF0006 parent -> 404, children endpoint -> [].
# has_fulltext must be False; fulltext() raises FulltextNotFoundError.


def test_req_045e__no_children_has_fulltext_false(fake_zotero):
    """has_fulltext is False when parent 404 and children list is empty."""
    _register_item(fake_zotero, KEY_NO_CHILD, fulltext=None)
    _register_children(fake_zotero, KEY_NO_CHILD, [])
    store = _make_store(fake_zotero)

    item = store.get(KEY_NO_CHILD)

    assert item.has_fulltext is False


def test_req_045e__fulltext_raises_when_no_children(fake_zotero):
    """store.fulltext() raises FulltextNotFoundError when children list is empty."""
    _register_item(fake_zotero, KEY_NO_CHILD, fulltext=None)
    _register_children(fake_zotero, KEY_NO_CHILD, [])
    store = _make_store(fake_zotero)

    with pytest.raises(FulltextNotFoundError):
        store.fulltext(KEY_NO_CHILD)


# ---------------------------------------------------------------- REQ-045 lazy
# Children endpoint is only fetched when parent returns 404 (lazy).
# (Already covered by 045a regression guard, but we also confirm 045b/c/d/e
# actually do hit the children endpoint when parent is 404.)


def test_req_045__children_endpoint_hit_when_parent_404(fake_zotero):
    """Children endpoint is queried when and only when parent fulltext is 404."""
    _register_item(fake_zotero, KEY_CHILD_HAS, fulltext=None)
    _register_item(fake_zotero, CHILD_KEY, fulltext=CHILD_CONTENT)
    _register_children(fake_zotero, KEY_CHILD_HAS, [CHILD_KEY])
    store = _make_store(fake_zotero)

    store.get(KEY_CHILD_HAS)

    children_path = _children_path(KEY_CHILD_HAS)
    children_hits = fake_zotero.requests_for(children_path, "GET")
    assert len(children_hits) >= 1, (
        f"Children endpoint {children_path!r} was never queried even though "
        "parent fulltext returned 404"
    )


# ---------------------------------------------------------------- REQ-045 404 children endpoint -> empty list


def test_req_045__children_404_treated_as_empty(fake_zotero):
    """A 404 from the children endpoint is treated as an empty child list (no error)."""
    _register_item(fake_zotero, KEY_NO_CHILD, fulltext=None)
    # Register the children endpoint as 404 (not empty array — literal 404)
    fake_zotero.set_raw(
        "GET",
        _children_path(KEY_NO_CHILD),
        404,
        b"no children",
    )
    store = _make_store(fake_zotero)

    # Must not raise; has_fulltext must be False
    item = store.get(KEY_NO_CHILD)
    assert item.has_fulltext is False


def test_req_045__children_404_fulltext_raises_not_found(fake_zotero):
    """store.fulltext() raises FulltextNotFoundError when children endpoint is 404."""
    _register_item(fake_zotero, KEY_NO_CHILD, fulltext=None)
    fake_zotero.set_raw(
        "GET",
        _children_path(KEY_NO_CHILD),
        404,
        b"no children",
    )
    store = _make_store(fake_zotero)

    with pytest.raises(FulltextNotFoundError):
        store.fulltext(KEY_NO_CHILD)
