"""M1 / Zotero adapter: retry, backoff, error taxonomy, fulltext probes.

Covers REQ-008 and REQ-009 (docs/requirements.md SSA, docs/contract.md
SS3.2 retry policy, SS4.3/SS4.5 probe).  The contract's injectable `sleep`
seam is always used: no test ever sleeps for real.
"""
from __future__ import annotations

import random
import socket
import string

import pytest

from zotwiki.errors import (
    CitekeyNotFoundError,
    FulltextNotFoundError,
    ItemNotFoundError,
    ZotWikiError,
    ZoteroError,
    ZoteroUnavailableError,
)


def _tok(n: int = 8, alphabet: str = string.ascii_lowercase) -> str:
    return "".join(random.choices(alphabet, k=n))


# ----------------------------------------------------------------- REQ-008


def test_req_008__get_retries_5xx_and_sleeps_doubling_backoff(fake_zotero, zstore):
    key = fake_zotero.add_item(title=f"flaky item {_tok()}", fulltext="recovered")
    fake_zotero.fail(2, status=500, path=fake_zotero.item_path(key))
    store, sleeps = zstore(retries=2, backoff=0.1)

    item = store.get(key)

    assert item.key == key
    assert item.has_fulltext is True
    assert len(fake_zotero.item_requests(key)) == 3  # exactly 1 + 2 attempts
    assert sleeps == pytest.approx([0.1, 0.2])


@pytest.mark.parametrize("retries,backoff", [(0, 0.3), (1, 0.05), (3, 0.1)])
def test_req_008__exhausted_5xx_attempts_raise_unavailable(
    fake_zotero, zstore, retries, backoff
):
    key = fake_zotero.add_item(title="always failing")
    # exactly 1 + retries failures: one extra attempt would succeed, so an
    # implementation that over-retries cannot pass
    fake_zotero.fail(retries + 1, status=503, path=fake_zotero.item_path(key))
    store, sleeps = zstore(retries=retries, backoff=backoff)

    with pytest.raises(ZoteroUnavailableError):
        store.get(key)

    assert len(fake_zotero.item_requests(key)) == retries + 1
    assert sleeps == pytest.approx([backoff * (2 ** i) for i in range(retries)])


@pytest.mark.parametrize("status", [400, 403, 410, 429])
def test_req_008__non_404_4xx_raises_zotero_error_immediately(
    fake_zotero, zstore, status
):
    key = fake_zotero.add_item(title="forbidden fruit")
    fake_zotero.fail(1, status=status, path=fake_zotero.item_path(key))
    store, sleeps = zstore(retries=3, backoff=0.1)

    with pytest.raises(ZoteroError) as exc:
        store.get(key)

    assert not isinstance(
        exc.value,
        (ItemNotFoundError, CitekeyNotFoundError, FulltextNotFoundError,
         ZoteroUnavailableError),
    )
    assert len(fake_zotero.item_requests(key)) == 1
    assert sleeps == []


def test_req_008__connection_errors_retry_then_raise_unavailable(zstore):
    # reserve an ephemeral 127.0.0.1 port and close it: nothing listens there
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    store, sleeps = zstore(
        base_url=f"http://127.0.0.1:{port}/api/users/0", retries=2, backoff=0.25
    )

    with pytest.raises(ZoteroUnavailableError):
        store.get("AAAA0001")

    assert sleeps == pytest.approx([0.25, 0.5])


def test_req_008__post_requests_are_retried_on_5xx(fake_zotero, zstore):
    w = _tok(5)
    fake_zotero.fail(1, status=502, path=fake_zotero.items_path, method="POST")
    store, sleeps = zstore(retries=2, backoff=0.1)

    item = store.add(title=f"The {w.capitalize()} Papers")

    assert item.citekey == f"anonnd{w}"
    assert len(fake_zotero.post_requests()) == 2
    assert sleeps == pytest.approx([0.1])


def test_req_008__error_hierarchy_and_message_constructors():
    for leaf in (
        ItemNotFoundError,
        CitekeyNotFoundError,
        FulltextNotFoundError,
        ZoteroUnavailableError,
    ):
        assert issubclass(leaf, ZoteroError)
    assert issubclass(ZoteroError, ZotWikiError)
    assert issubclass(ZotWikiError, Exception)
    message = f"zotero is down {_tok()}"
    assert message in str(ZoteroUnavailableError(message))
    assert message in str(ZoteroError(message))


# ----------------------------------------------------------------- REQ-009


def test_req_009__get_materialization_probes_fulltext_endpoint_once(fake_zotero, zstore):
    k_with = fake_zotero.add_item(title=f"has fulltext {_tok()}", fulltext="present")
    k_without = fake_zotero.add_item(title=f"no fulltext {_tok()}")
    store, _ = zstore()

    assert store.get(k_with).has_fulltext is True
    assert store.get(k_without).has_fulltext is False
    assert len(fake_zotero.probe_requests(k_with)) == 1
    assert len(fake_zotero.probe_requests(k_without)) == 1


def test_req_009__search_probes_each_result_exactly_once(fake_zotero, zstore):
    marker = _tok()
    k1 = fake_zotero.add_item(title=f"{marker} one", fulltext="text one")
    k2 = fake_zotero.add_item(title=f"{marker} two")
    store, _ = zstore()

    got = store.search(marker)

    assert [(i.key, i.has_fulltext) for i in got] == [(k1, True), (k2, False)]
    assert len(fake_zotero.probe_requests(k1)) == 1
    assert len(fake_zotero.probe_requests(k2)) == 1


def test_req_009__resolve_probes_the_matched_item(fake_zotero, zstore):
    ck_with, ck_without = f"with{_tok(6)}", f"without{_tok(6)}"
    k_with = fake_zotero.add_item(title="resolved with", citekey=ck_with, fulltext="t")
    fake_zotero.add_item(title="resolved without", citekey=ck_without)
    store, _ = zstore()

    assert store.resolve(ck_with).has_fulltext is True
    assert store.resolve(ck_without).has_fulltext is False
    assert len(fake_zotero.probe_requests(k_with)) == 1


def test_req_009__probe_5xx_failures_follow_retry_policy(fake_zotero, zstore):
    key = fake_zotero.add_item(title=f"flaky probe {_tok()}", fulltext="present")
    fake_zotero.fail(2, status=500, path=fake_zotero.fulltext_path(key), method="GET")
    store, sleeps = zstore(retries=2, backoff=0.1)

    item = store.get(key)

    assert item.has_fulltext is True
    assert len(fake_zotero.probe_requests(key)) == 3
    assert sleeps == pytest.approx([0.1, 0.2])


def test_req_009__probe_exhaustion_raises_unavailable(fake_zotero, zstore):
    key = fake_zotero.add_item(title=f"dead probe {_tok()}", fulltext="present")
    fake_zotero.fail(2, status=500, path=fake_zotero.fulltext_path(key), method="GET")
    store, sleeps = zstore(retries=1, backoff=0.1)

    with pytest.raises(ZoteroUnavailableError):
        store.get(key)

    assert len(fake_zotero.probe_requests(key)) == 2
    assert sleeps == pytest.approx([0.1])
