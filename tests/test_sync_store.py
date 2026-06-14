"""Sync subcommand — store layer tests (REQ-040, REQ-043).

Tester reads docs/contract.md §3, §4.7, §4.8 and docs/requirements.md §H.
The fake Zotero server is extended in conftest.py with add_collection /
add_item_to_collection helpers (§4.7/§4.8).
"""
from __future__ import annotations

import pytest

from zotwiki.errors import CollectionNotFoundError, ZoteroUnavailableError


# ---------------------------------------------------------------- REQ-040


def test_req_040__collection_items_returns_mapped_items(fake_zotero, zstore):
    col = fake_zotero.add_collection("AI Papers")
    k1 = fake_zotero.add_item(title="Attention Is All You Need",
                               citekey="vaswani2017attention", date="2017")
    k2 = fake_zotero.add_item(title="BERT", citekey="devlin2019bert", date="2019")
    fake_zotero.add_collection("Other")          # second collection; should be ignored
    fake_zotero.add_item_to_collection(col, k1)
    fake_zotero.add_item_to_collection(col, k2)

    store, _ = zstore()
    items = store.collection_items("AI Papers")

    assert len(items) == 2
    assert items[0].citekey == "vaswani2017attention"
    assert items[0].title == "Attention Is All You Need"
    assert items[0].year == 2017
    assert items[1].citekey == "devlin2019bert"
    assert items[1].title == "BERT"


def test_req_040__collection_items_empty_collection(fake_zotero, zstore):
    fake_zotero.add_collection("Empty")
    store, _ = zstore()
    assert store.collection_items("Empty") == []


def test_req_040__collection_items_maps_has_fulltext(fake_zotero, zstore):
    col = fake_zotero.add_collection("Papers")
    k = fake_zotero.add_item(title="With Fulltext", citekey="auth2020ft",
                              fulltext="some text here")
    fake_zotero.add_item_to_collection(col, k)

    store, _ = zstore()
    items = store.collection_items("Papers")

    assert len(items) == 1
    assert items[0].has_fulltext is True


# ---------------------------------------------------------------- REQ-043


def test_req_043__collection_not_found_raises(fake_zotero, zstore):
    fake_zotero.add_collection("AI Papers")
    store, _ = zstore()

    with pytest.raises(CollectionNotFoundError):
        store.collection_items("Nonexistent")


def test_req_043__empty_library_raises_collection_not_found(fake_zotero, zstore):
    store, _ = zstore()

    with pytest.raises(CollectionNotFoundError):
        store.collection_items("Anything")


def test_req_043__collection_name_is_case_sensitive(fake_zotero, zstore):
    fake_zotero.add_collection("AI Papers")
    store, _ = zstore()

    with pytest.raises(CollectionNotFoundError):
        store.collection_items("ai papers")
