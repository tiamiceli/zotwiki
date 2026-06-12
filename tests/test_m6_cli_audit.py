"""M6 / `zotwiki audit` (REQ-035): clean vault -> exactly
`audit: ok ({n} pages)\\n` and exit 0; violations -> one
`{code}\\t{page}\\t{detail}` line per violation in report order plus the
`audit: {n} violation(s)` trailer on stdout and exit 1; missing vault or
unreachable Zotero -> exit 2.

Black-box; vaults built through the frozen M3/M5 publisher surface against
the 127.0.0.1 fake Zotero; expected violation lines derived independently
from contract SS8 (codes, details, (page, code, detail) sort order).
"""
from __future__ import annotations

import pytest

from zotwiki.models import Contradiction
from zotwiki.publisher import VaultPublisher

from m2_helpers import rand_word
from m4_helpers import (
    TODAY,
    build_article,
    closed_port,
    distinct_citekeys,
    publish_clean_vault,
    unregister,
)
from m5_helpers import distinct_titles
from m6_helpers import assert_single_error_line

main = None  # bound by _require_m6_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main
    from zotwiki.cli import main as main_

    main = main_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_035__clean_vault_prints_ok_with_entity_page_count(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    title_a, title_b, title_c = distinct_titles(3)
    ck_a, ck_b, ck_c = distinct_citekeys(3)
    articles = [
        build_article([(ck_a,)], title=title_a, links=(title_b,)),
        build_article([(ck_b,)], title=title_b, links=(title_a, title_c)),
        build_article([(ck_c,)], title=title_c),
    ]
    publish_clean_vault(fake_zotero, store, vault, articles)
    # Special pages never count toward `pages_checked` (SS8.1 scope).
    VaultPublisher(vault, store, today=TODAY).publish_contradictions(
        title_a,
        [Contradiction(
            existing_claim=f"Old result {rand_word()} stands.",
            new_claim=f"New result {rand_word()} differs.",
            citekeys=(ck_b,),
        )],
    )

    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 0
    assert out.out == "audit: ok (3 pages)\n"
    assert out.err == ""


def test_req_035__violations_print_lines_in_report_order_exit_1(
    tmp_path, store, fake_zotero, capsys
):
    vault = tmp_path / "vault"
    title_a, title_b, ghost = distinct_titles(3)
    ck_a, ck_b = distinct_citekeys(2)
    articles = [
        build_article([(ck_a,)], title=title_a),
        build_article([(ck_b,)], title=title_b, links=(ghost,)),
    ]
    refs = publish_clean_vault(fake_zotero, store, vault, articles)
    unregister(fake_zotero, refs[ck_a])  # CITEKEY_UNRESOLVED on page A

    expected = sorted(
        [
            (f"{title_a}.md", "CITEKEY_UNRESOLVED", ck_a),
            (f"{title_b}.md", "BROKEN_LINK", ghost),
        ]
    )  # SS8: report sorted by (page, code, detail)

    rc = main(["audit", "--vault", str(vault)], store=store)
    out = capsys.readouterr()
    assert rc == 1
    assert out.err == ""  # audit violations go to stdout (REQ-037 exception)
    assert out.out == (
        "".join(f"{code}\t{page}\t{detail}\n" for page, code, detail in expected)
        + "audit: 2 violation(s)\n"
    )


def test_req_035__missing_vault_dir_returns_2(tmp_path, store, capsys):
    rc = main(
        ["audit", "--vault", str(tmp_path / f"never{rand_word()}")],
        store=store,
    )
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert_single_error_line(out.err)


def test_req_035__unreachable_zotero_returns_2(
    tmp_path, store, fake_zotero, zstore, capsys
):
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    [ck] = distinct_citekeys(1)
    publish_clean_vault(fake_zotero, store, vault,
                        [build_article([(ck,)], title=title)])

    dead_store, _ = zstore(
        base_url=f"http://127.0.0.1:{closed_port()}/api/users/0"
    )
    rc = main(["audit", "--vault", str(vault)], store=dead_store)
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert_single_error_line(out.err)
