"""M3 / VaultPublisher create path: REQ-019 idempotent publish (byte- and
mtime-level no-write semantics, case-collision VaultError) and REQ-018
References resolution through the fake Zotero HTTP server (contract SS4) on
127.0.0.1, with HTTPZoteroStore as "the store" per the requirements ground
rules.  Vaults live in tmp_path; `today` is always injected.
"""
from __future__ import annotations

import pytest

from zotwiki.errors import CitekeyNotFoundError, VaultError
from zotwiki.models import Article, Claim, Quote, Section

from m2_helpers import rand_citekey, rand_word
from m3_helpers import (
    cited_citekeys,
    random_publishable_article,
    register_article_references,
    register_reference,
    render_oracle,
    stamp_mtimes,
    vault_snapshot,
)

TODAY = "2026-06-11"
LATER = "2026-07-01"

VaultPublisher = None  # bound by _require_m3_surface
parse_page = None
INDEX_FILENAME = None
CONTRADICTIONS_FILENAME = None


@pytest.fixture(scope="module", autouse=True)
def _require_m3_surface():
    """Bind the M3 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1+M2 suites)."""
    global VaultPublisher, parse_page, INDEX_FILENAME, CONTRADICTIONS_FILENAME
    from zotwiki.publisher import (
        CONTRADICTIONS_FILENAME as CONTRADICTIONS_FILENAME_,
        INDEX_FILENAME as INDEX_FILENAME_,
        VaultPublisher as VaultPublisher_,
        parse_page as parse_page_,
    )

    VaultPublisher = VaultPublisher_
    parse_page = parse_page_
    INDEX_FILENAME = INDEX_FILENAME_
    CONTRADICTIONS_FILENAME = CONTRADICTIONS_FILENAME_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_019__reserved_filename_constants():
    assert INDEX_FILENAME == "Index.md"
    assert CONTRADICTIONS_FILENAME == "Contradictions.md"


def test_req_019__constructor_creates_vault_dir_with_parents(tmp_path, store):
    vault = tmp_path / "deep" / "nested" / "vault"
    assert not vault.exists()

    VaultPublisher(vault, store, today=TODAY)

    assert vault.is_dir()


def test_req_019__first_publish_creates_canonical_page_at_page_path(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = random_publishable_article()
    refs = register_article_references(fake_zotero, article)
    publisher = VaultPublisher(vault, store, today=TODAY)

    path = publisher.publish(article)

    assert path == vault / f"{article.title}.md"
    assert publisher.page_path(article.title) == vault / f"{article.title}.md"
    expected = render_oracle(article, refs, created=TODAY, updated=TODAY)
    assert path.read_bytes() == expected.encode("utf-8")
    assert parse_page(path.read_text(encoding="utf-8")) == article


def test_req_019__double_publish_same_today_writes_nothing(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = random_publishable_article()
    register_article_references(fake_zotero, article)
    publisher = VaultPublisher(vault, store, today=TODAY)

    first_path = publisher.publish(article)
    text = first_path.read_text(encoding="utf-8")
    assert f'created: "{TODAY}"' in text  # created == updated == today
    assert f'updated: "{TODAY}"' in text

    stamp_mtimes(vault)  # sentinel mtimes: any later write is observable
    before = vault_snapshot(vault)

    second_path = publisher.publish(article)

    assert second_path == first_path
    assert vault_snapshot(vault) == before  # bytes AND mtimes: nothing written


def test_req_019__republish_with_later_today_keeps_updated_unchanged(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = random_publishable_article()
    register_article_references(fake_zotero, article)

    VaultPublisher(vault, store, today=TODAY).publish(article)
    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    path = VaultPublisher(vault, store, today=LATER).publish(article)

    assert vault_snapshot(vault) == before  # byte-identical vault, no writes
    text = path.read_text(encoding="utf-8")
    assert f'updated: "{TODAY}"' in text  # the old `updated` stands
    assert LATER not in text


def test_req_019__case_colliding_title_raises_vault_error_and_writes_nothing(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = random_publishable_article()
    register_article_references(fake_zotero, article)
    publisher = VaultPublisher(vault, store, today=TODAY)
    publisher.publish(article)

    variant_title = article.title.swapcase()
    assert variant_title != article.title
    assert variant_title.casefold() == article.title.casefold()
    variant = Article(
        title=variant_title,
        summary=article.summary,
        sections=article.sections,
        claims=article.claims,  # same citekeys: all resolvable on the fake
        links=article.links,
    )
    stamp_mtimes(vault)
    before = vault_snapshot(vault)

    with pytest.raises(VaultError):
        publisher.publish(variant)

    assert vault_snapshot(vault) == before  # no file written, none touched
    assert not (vault / f"{variant_title}.md").exists()


def test_req_019__publish_article_citing_nothing(tmp_path, store):
    vault = tmp_path / "vault"
    article = Article(
        title=f"Quiet {rand_word().capitalize()}",
        summary=f"Nothing cited about {rand_word()}.",
        sections=(Section(heading=f"Notes {rand_word()}",
                          body=f"Plain {rand_word()} prose."),),
        claims=(),
        links=(),
    )
    publisher = VaultPublisher(vault, store, today=TODAY)

    path = publisher.publish(article)

    expected = render_oracle(article, (), created=TODAY, updated=TODAY)
    assert path.read_bytes() == expected.encode("utf-8")
    assert "citekeys: []" in path.read_text(encoding="utf-8")


def test_req_019__unicode_content_is_published_as_utf8_and_idempotent(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck = rand_citekey()
    ref = register_reference(
        fake_zotero, ck,
        title="Größe und Ψυχή 注意力", first="José", last="Ångström",
        year=2019,
    )
    article = Article(
        title="Memoire Etudes",
        summary="Étude — mémoire ‘active’ étendue.",
        sections=(Section(heading="Übersicht Ψ",
                          body="日本語のテキスト行。\n\nDeuxième ligne — ça va."),),
        claims=(
            Claim(
                text="Mémoire enhances 学習 ability.",
                citekeys=(ck,),
                quotes=(Quote(citekey=ck, text="l'effet de mémoire 学習"),),
            ),
        ),
        links=("Memory",),
    )
    publisher = VaultPublisher(vault, store, today=TODAY)

    path = publisher.publish(article)

    raw = path.read_bytes()
    expected = render_oracle(article, (ref,), created=TODAY, updated=TODAY)
    assert raw == expected.encode("utf-8")
    assert "注意力".encode("utf-8") in raw
    assert "José Ångström".encode("utf-8") in raw

    stamp_mtimes(vault)
    before = vault_snapshot(vault)
    publisher.publish(article)
    assert vault_snapshot(vault) == before


# ----- REQ-018: References resolution through the fake Zotero ---------------


def test_req_018__publish_resolves_references_via_fake_zotero(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    register_reference(
        fake_zotero, "doe2020attention", key="ABCD1234",
        title="A Study of Attention", first="Jane", last="Doe", year=2020,
    )
    article = Article(
        title="Attention",
        summary="What attention does.",
        sections=(),
        claims=(
            Claim(
                text="Attention is learnable.",
                citekeys=("doe2020attention",),
                quotes=(Quote(citekey="doe2020attention",
                              text="attention can be learned"),),
            ),
        ),
        links=(),
    )

    path = VaultPublisher(vault, store, today=TODAY).publish(article)

    text = path.read_text(encoding="utf-8")
    assert "zotero://select/library/items/ABCD1234" in text
    assert (
        "\n- [@doe2020attention] Jane Doe (2020). *A Study of Attention*. "
        "[Zotero](zotero://select/library/items/ABCD1234)\n"
    ) in text
    # The reference was built by resolving the citekey against the server
    # (contract SS6.6 via SS3/SS4.1: qmode=everything search for the citekey).
    resolve_queries = [
        r.params["q"][0]
        for r in fake_zotero.search_requests()
        if r.params.get("qmode") == ["everything"]
    ]
    assert "doe2020attention" in resolve_queries


def test_req_018__publish_resolves_citekeys_sorted_ascending(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    # Four distinct citekeys; claim encounter order deliberately != sorted.
    cks = sorted(f"{rand_word()}{2010 + i}{rand_word()}" for i in range(4))
    article = Article(
        title=f"Ordering {rand_word().capitalize()}",
        summary="Resolution order is sorted, not encounter order.",
        sections=(),
        claims=(
            Claim(
                text="Later citekeys arrive first.",
                citekeys=(cks[1], cks[3]),
                quotes=(Quote(citekey=cks[1], text="quote b"),
                        Quote(citekey=cks[3], text="quote d")),
            ),
            Claim(
                text="Earlier citekeys arrive last.",
                citekeys=(cks[0], cks[2]),
                quotes=(Quote(citekey=cks[0], text="quote a"),
                        Quote(citekey=cks[2], text="quote c")),
            ),
        ),
        links=(),
    )
    assert cited_citekeys(article) == cks
    refs = register_article_references(fake_zotero, article)

    path = VaultPublisher(vault, store, today=TODAY).publish(article)

    expected = render_oracle(article, refs, created=TODAY, updated=TODAY)
    assert path.read_bytes() == expected.encode("utf-8")

    resolve_queries = [
        r.params["q"][0]
        for r in fake_zotero.search_requests()
        if r.params.get("qmode") == ["everything"]
        and r.params["q"][0] in set(cks)
    ]
    first_seen = list(dict.fromkeys(resolve_queries))
    assert first_seen == cks  # SS6.6: resolved in sorted ascending order


def test_req_018__unresolvable_citekey_propagates_and_writes_nothing(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    article = random_publishable_article()
    # Register every citekey but one: that one cannot resolve.
    missing = cited_citekeys(article)[-1]
    for ck in cited_citekeys(article):
        if ck != missing:
            register_reference(fake_zotero, ck)
    publisher = VaultPublisher(vault, store, today=TODAY)

    with pytest.raises(CitekeyNotFoundError):
        publisher.publish(article)

    assert list(vault.glob("*.md")) == []  # fail-fast: nothing was written
