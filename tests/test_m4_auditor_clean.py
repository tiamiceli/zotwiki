"""M4 / Auditor, clean vaults (REQ-023): a vault built by the real M3
publisher against the fake Zotero server audits ok -- correct `pages_checked`
counting (entity pages only), special pages and non-vault files out of
scope, and the pinned SS8 surface (AUDIT_CODES, Violation, AuditReport.ok).

Vaults live in tmp_path; the fake Zotero serves on 127.0.0.1 only; `today`
is always injected; all article content is runtime-random.
"""
from __future__ import annotations

import pytest

from m4_helpers import (
    EXPECTED_AUDIT_CODES,
    TODAY,
    build_article,
    claim_suffix,
    contradictions_page_text,
    distinct_citekeys,
    publish_clean_vault,
    rand_word,
)

Auditor = None  # bound by _require_m4_surface
AuditReport = None
Violation = None
AUDIT_CODES = None


@pytest.fixture(scope="module", autouse=True)
def _require_m4_surface():
    """Bind the M4 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1-M3 suites)."""
    global Auditor, AuditReport, Violation, AUDIT_CODES
    from zotwiki.auditor import (
        AUDIT_CODES as AUDIT_CODES_,
        AuditReport as AuditReport_,
        Auditor as Auditor_,
        Violation as Violation_,
    )

    Auditor = Auditor_
    AuditReport = AuditReport_
    Violation = Violation_
    AUDIT_CODES = AUDIT_CODES_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_023__audit_surface_codes_and_report_shape():
    assert AUDIT_CODES == EXPECTED_AUDIT_CODES

    clean = AuditReport(violations=(), pages_checked=7)
    assert clean.ok is True
    assert clean.pages_checked == 7

    violation = Violation(code="BROKEN_LINK", page="Some Page.md",
                          detail="Some Target")
    assert violation.code == "BROKEN_LINK"
    assert violation.page == "Some Page.md"
    assert violation.detail == "Some Target"
    dirty = AuditReport(violations=(violation,), pages_checked=1)
    assert dirty.ok is False


def test_req_023__publisher_built_interlinked_vault_audits_ok(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    cks = distinct_citekeys(5)
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    title_c = f"Charlie {rand_word().capitalize()}"
    articles = [
        build_article([(cks[0],), (cks[1], cks[2])], title=title_a,
                      links=(title_b,)),
        build_article([(cks[2], cks[3])], title=title_b,
                      links=(title_a, title_c)),
        build_article([(cks[4],)], title=title_c, links=()),
    ]

    publish_clean_vault(fake_zotero, store, vault, articles)
    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == 3


def test_req_023__empty_vault_audits_ok_with_zero_pages(tmp_path, store):
    vault = tmp_path / "vault"
    vault.mkdir()

    report = Auditor(vault, store).audit()

    assert report.ok is True
    assert report.violations == ()
    assert report.pages_checked == 0


def test_req_023__special_pages_are_not_entity_pages(
    tmp_path, store, fake_zotero
):
    """Index.md and a canonical Contradictions.md are special: neither is
    counted in pages_checked, neither needs an Index entry, and the
    Contradictions claims are exempt from claim-level checks (SS8.1)."""
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    title_a = f"Alpha {rand_word().capitalize()}"
    title_b = f"Bravo {rand_word().capitalize()}"
    articles = [
        build_article([(ck_a,)], title=title_a),
        build_article([(ck_b,)], title=title_b, links=(title_a,)),
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)
    (vault / "Contradictions.md").write_text(
        contradictions_page_text([
            f"## {title_a} ({TODAY})",
            f"- EXISTING: Original claim about {rand_word()}.\n"
            f"- NEW: Updated claim about {rand_word()}.{claim_suffix([ck_a])}",
        ]),
        encoding="utf-8",
    )

    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == 2


def test_req_023__subdirectories_and_non_md_files_are_ignored(
    tmp_path, store, fake_zotero
):
    """SS6.1: the vault is flat -- only {vault}/*.md counts.  Garbage in a
    subdirectory or in non-.md files must not produce violations."""
    vault = tmp_path / "vault"
    article = build_article([(distinct_citekeys(1)[0],)])
    publish_clean_vault(fake_zotero, store, vault, [article])

    sub = vault / "drafts"
    sub.mkdir()
    (sub / "Evil.md").write_text(
        f"not a page at all [[Nowhere {rand_word().capitalize()}]]\n",
        encoding="utf-8",
    )
    (vault / "scratch.txt").write_text(
        f"[[Nowhere {rand_word().capitalize()}]] [@{rand_word()}9999bogus]\n",
        encoding="utf-8",
    )

    report = Auditor(vault, store).audit()

    assert report.violations == ()
    assert report.ok is True
    assert report.pages_checked == 1
