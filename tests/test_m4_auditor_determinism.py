"""M4 / Auditor, REQ-030: report determinism (violations sorted by
(page, code, detail), equal vault + store state => equal reports), the hard
failure modes (missing/non-directory vault -> VaultError; unreachable
Zotero -> ZoteroUnavailableError), and the Contradictions.md exemption
(claims/quotes/references exempt, [[links]] still checked).

The dead-Zotero case uses a 127.0.0.1 port with nothing listening; the
store's sleep seam is injected, so nothing ever really sleeps.
"""
from __future__ import annotations

import pytest

from zotwiki.errors import VaultError, ZoteroUnavailableError

from m4_helpers import (
    TODAY,
    build_article,
    claim_suffix,
    closed_port,
    contradictions_page_text,
    distinct_citekeys,
    drop_line,
    publish_clean_vault,
    rand_citekey,
    rand_word,
    unregister,
    violation_pairs,
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


def test_req_030__multi_violation_report_is_sorted_and_repeatable(
    tmp_path, store, fake_zotero
):
    """Five distinct corruptions across five pages; the report must come
    back sorted by (page, code, detail) and byte-equal on every re-run,
    from the same Auditor and from a fresh one."""
    vault = tmp_path / "vault"
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    title_c = f"Charlie {rand_word().capitalize()}"
    title_d = f"Delta {rand_word().capitalize()}"
    title_e = f"Echo {rand_word().capitalize()}"
    ghost_1 = f"Ghost A {rand_word().capitalize()}"
    ghost_2 = f"Ghost B {rand_word().capitalize()}"
    cks = distinct_citekeys(5)
    articles = [
        build_article([(cks[0],)], title=title_a, links=(ghost_1, ghost_2)),
        build_article([(cks[1],), (cks[2],)], title=title_b),
        build_article([(cks[3],)], title=title_c),
        build_article([], title=title_d),
        build_article([(cks[4],)], title=title_e),
    ]
    refs = publish_clean_vault(fake_zotero, store, vault, articles)

    # One targeted corruption per page (Alpha's dangling links are already
    # in place): unresolvable citekey, orphan, garbage, stale index bullet.
    unregister(fake_zotero, refs[cks[1]])
    drop_line(vault / "Index.md", f"- [[{title_c}]]")
    (vault / f"{title_d}.md").write_text("totally not a page\n",
                                         encoding="utf-8")
    (vault / f"{title_e}.md").unlink()

    auditor = Auditor(vault, store)
    first = auditor.audit()
    second = auditor.audit()
    fresh = Auditor(vault, store).audit()

    assert first == second == fresh
    assert list(first.violations) == sorted(
        first.violations, key=lambda v: (v.page, v.code, v.detail)
    )
    assert violation_pairs(first) == [
        ("BROKEN_LINK", f"{title_a}.md"),
        ("BROKEN_LINK", f"{title_a}.md"),
        ("CITEKEY_UNRESOLVED", f"{title_b}.md"),
        ("ORPHAN_PAGE", f"{title_c}.md"),
        ("PAGE_UNPARSEABLE", f"{title_d}.md"),
        ("INDEX_STALE", "Index.md"),
    ]
    broken_details = [v.detail for v in first.violations
                      if v.code == "BROKEN_LINK"]
    assert broken_details == [ghost_1, ghost_2]  # detail-sorted within page
    assert first.violations[2].detail == cks[1]
    assert first.violations[5].detail == title_e
    assert first.ok is False
    assert first.pages_checked == 3  # Alpha, Bravo, Charlie parse; Delta
    #                                  is garbage and Echo's file is gone


def test_req_030__contradictions_links_checked_but_claims_exempt(
    tmp_path, store, fake_zotero
):
    """Contradictions.md: its unresolvable [@citekey] is exempt from checks
    2/3/7, it needs no Index entry and is not counted as an entity page --
    but its broken [[link]] is still reported (SS8.1, REQ-030)."""
    vault = tmp_path / "vault"
    article = build_article([(rand_citekey(),)],
                            title=f"Alpha {rand_word().capitalize()}")
    publish_clean_vault(fake_zotero, store, vault, [article])

    ghost = f"Ghost {rand_word().capitalize()}"
    bogus = "0" + rand_citekey()  # never registered: would not resolve
    (vault / "Contradictions.md").write_text(
        contradictions_page_text([
            f"## {article.title} ({TODAY})",
            f"- EXISTING: Original {rand_word()} claim.\n"
            f"- NEW: Counter per [[{ghost}]] data.{claim_suffix([bogus])}",
        ]),
        encoding="utf-8",
    )
    report = Auditor(vault, store).audit()

    assert [(v.code, v.page, v.detail) for v in report.violations] == [
        ("BROKEN_LINK", "Contradictions.md", ghost)
    ]
    assert report.pages_checked == 1


def test_req_030__missing_vault_dir_raises_vault_error(tmp_path, store):
    with pytest.raises(VaultError):
        Auditor(tmp_path / f"no-such-vault-{rand_word()}", store).audit()


def test_req_030__vault_path_that_is_a_file_raises_vault_error(
    tmp_path, store
):
    not_a_dir = tmp_path / "vault"
    not_a_dir.write_text("not a directory\n", encoding="utf-8")

    with pytest.raises(VaultError):
        Auditor(not_a_dir, store).audit()


def test_req_030__unreachable_zotero_raises_unavailable(
    tmp_path, fake_zotero, zstore
):
    """Audit a real vault (built against the live fake) with a store
    pointed at a closed 127.0.0.1 port: after the REQ-008 retry schedule is
    exhausted, ZoteroUnavailableError must propagate -- no report."""
    live_store, _ = zstore()
    vault = tmp_path / "vault"
    article = build_article([(rand_citekey(),)])
    publish_clean_vault(fake_zotero, live_store, vault, [article])

    dead_store, sleeps = zstore(
        base_url=f"http://127.0.0.1:{closed_port()}/api/users/0"
    )
    with pytest.raises(ZoteroUnavailableError):
        Auditor(vault, dead_store).audit()
    assert sleeps  # it really retried -- through the injected sleep seam
