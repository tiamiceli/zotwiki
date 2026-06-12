"""M5 / Index.md maintenance (REQ-022): after every publish, Index.md exists,
is byte-exactly the contract SS6.7 layout (frontmatter per SS6.2 with title
"Index" and citekeys: [], then `# Index` and one sorted `- [[title]]` bullet
per entity page), lists exactly the entity pages (excluding Index.md and
Contradictions.md, including pages not written by the publisher), preserves
its `created`, bumps `updated` only when its rendering changes, and stays
byte-identical (no write at all) on no-op republishes and on content updates
that change no titles.

Black-box; fake Zotero on 127.0.0.1; vaults in tmp_path; `today` injected;
the byte oracle is the independent SS6.7 renderer in m5_helpers.
"""
from __future__ import annotations

import pytest

from zotwiki.models import Article, Claim, Contradiction, Quote, Section
from zotwiki.publisher import (
    CONTRADICTIONS_FILENAME,
    INDEX_FILENAME,
    VaultPublisher,
)

from m2_helpers import rand_word
from m3_helpers import render_oracle, stamp_mtimes, vault_snapshot
from m4_helpers import build_article, distinct_citekeys
from m5_helpers import (
    EVEN_LATER,
    LATER,
    TODAY,
    contradictions_oracle,
    distinct_titles,
    index_oracle,
    refs_for,
    register_citekey_map,
)


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_022__beta_then_alpha_yield_canonical_sorted_index(
    tmp_path, store
):
    vault = tmp_path / "vault"
    publisher = VaultPublisher(vault, store, today=TODAY)
    index = vault / INDEX_FILENAME

    publisher.publish(build_article([], title="Beta"))

    assert index.exists()
    assert index.read_bytes() == index_oracle(
        ["Beta"], created=TODAY, updated=TODAY).encode("utf-8")

    alpha = build_article([], title="Alpha")
    publisher.publish(alpha)

    expected = index_oracle(["Alpha", "Beta"], created=TODAY, updated=TODAY)
    assert index.read_bytes() == expected.encode("utf-8")
    text = index.read_text(encoding="utf-8")
    assert text.index("- [[Alpha]]") < text.index("- [[Beta]]")

    # Republishing without change leaves Index.md byte-identical (no write).
    stamp_mtimes(vault)
    before = vault_snapshot(vault)
    publisher.publish(alpha)
    assert vault_snapshot(vault) == before


def test_req_022__index_lists_exactly_entity_pages_sorted_after_each_publish(
    tmp_path, store
):
    vault = tmp_path / "vault"
    titles = distinct_titles(5)
    order = sorted(titles, reverse=True)  # publish order != sorted order
    publisher = VaultPublisher(vault, store, today=TODAY)
    index = vault / INDEX_FILENAME

    for i, title in enumerate(order):
        publisher.publish(build_article([], title=title))
        expected = index_oracle(order[: i + 1], created=TODAY, updated=TODAY)
        assert index.read_bytes() == expected.encode("utf-8")


def test_req_022__bullets_sorted_codepoint_wise_not_casefolded(
    tmp_path, store
):
    """SS2 DECISION: sorting is plain codepoint-wise str ordering, so an
    uppercase-first title sorts before a lowercase-first one."""
    vault = tmp_path / "vault"
    lower = f"aardvark {rand_word().capitalize()} 17"
    upper = f"Zebra {rand_word().capitalize()} 17"
    assert upper < lower  # codepoint order; casefold order would flip them
    publisher = VaultPublisher(vault, store, today=TODAY)

    publisher.publish(build_article([], title=lower))
    publisher.publish(build_article([], title=upper))

    expected = index_oracle([lower, upper], created=TODAY, updated=TODAY)
    assert (vault / INDEX_FILENAME).read_bytes() == expected.encode("utf-8")
    text = (vault / INDEX_FILENAME).read_text(encoding="utf-8")
    assert text.index(f"- [[{upper}]]") < text.index(f"- [[{lower}]]")


def test_req_022__missing_index_is_recreated_by_the_next_noop_publish(
    tmp_path, store
):
    """SS6.5: Index.md is regenerated after *any* publish, including one
    that does not rewrite the entity page."""
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    article = build_article([], title=title)
    VaultPublisher(vault, store, today=TODAY).publish(article)
    (vault / INDEX_FILENAME).unlink()

    VaultPublisher(vault, store, today=LATER).publish(article)  # page no-op

    expected = index_oracle([title], created=LATER, updated=LATER)
    assert (vault / INDEX_FILENAME).read_bytes() == expected.encode("utf-8")


def test_req_022__format_tampered_index_is_healed_byte_exactly(
    tmp_path, store
):
    """SS6.5: the Index change-detection rule is byte-level rendering, so
    even a same-membership formatting corruption is rewritten canonically
    (with `updated` bumped, `created` preserved)."""
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    article = build_article([], title=title)
    VaultPublisher(vault, store, today=TODAY).publish(article)
    index = vault / INDEX_FILENAME
    index.write_bytes(index.read_bytes() + b"\n")  # spurious trailing line

    VaultPublisher(vault, store, today=LATER).publish(article)  # page no-op

    expected = index_oracle([title], created=TODAY, updated=LATER)
    assert index.read_bytes() == expected.encode("utf-8")


def test_req_022__membership_is_by_filename_over_the_flat_vault_root(
    tmp_path, store
):
    """SS6.7 + SS6.1: every vault-root *.md except the two specials is a
    bullet -- parseability is irrelevant -- and subdirectories are ignored."""
    vault = tmp_path / "vault"
    [title] = distinct_titles(1)
    garbage_title = f"Garbage {rand_word().capitalize()} 11"
    article = build_article([], title=title)
    publisher = VaultPublisher(vault, store, today=TODAY)
    publisher.publish(article)
    (vault / f"{garbage_title}.md").write_text("not a page\n",
                                               encoding="utf-8")
    sub = vault / "drafts"
    sub.mkdir()
    (sub / "Hidden Note.md").write_text("also not a page\n", encoding="utf-8")

    VaultPublisher(vault, store, today=LATER).publish(article)  # page no-op

    expected = index_oracle([title, garbage_title],
                            created=TODAY, updated=LATER)
    assert (vault / INDEX_FILENAME).read_bytes() == expected.encode("utf-8")


def test_req_022__index_created_preserved_and_updated_bumped_only_on_change(
    tmp_path, store
):
    vault = tmp_path / "vault"
    title_one, title_two = distinct_titles(2)
    index = vault / INDEX_FILENAME

    VaultPublisher(vault, store, today=TODAY).publish(
        build_article([], title=title_one)
    )
    assert index.read_bytes() == index_oracle(
        [title_one], created=TODAY, updated=TODAY).encode("utf-8")

    second = build_article([], title=title_two)
    VaultPublisher(vault, store, today=LATER).publish(second)

    # Membership changed: created keeps its first-write value, updated bumps.
    assert index.read_bytes() == index_oracle(
        [title_one, title_two], created=TODAY, updated=LATER).encode("utf-8")

    # No-op republish at an even later today: no write, dates untouched.
    stamp_mtimes(vault)
    before = vault_snapshot(vault)
    VaultPublisher(vault, store, today=EVEN_LATER).publish(second)
    assert vault_snapshot(vault) == before


def test_req_022__index_excludes_special_pages_and_covers_foreign_pages(
    tmp_path, store
):
    vault = tmp_path / "vault"
    title_one, title_two, foreign_title = distinct_titles(3)
    VaultPublisher(vault, store, today=TODAY).publish(
        build_article([], title=title_one)
    )

    # Hand-placed canonical files: a Contradictions.md (never indexed) and a
    # foreign entity page (must be indexed at the next regeneration).
    (vault / CONTRADICTIONS_FILENAME).write_bytes(
        contradictions_oracle(
            [(
                title_one,
                TODAY,
                [Contradiction(existing_claim=f"Old {rand_word()} holds.",
                               new_claim=f"New {rand_word()} differs.",
                               citekeys=(f"{rand_word()}2020{rand_word()}",))],
            )],
            created=TODAY,
            updated=TODAY,
        ).encode("utf-8")
    )
    foreign = build_article([], title=foreign_title)
    (vault / f"{foreign_title}.md").write_bytes(
        render_oracle(foreign, (), created=TODAY,
                      updated=TODAY).encode("utf-8")
    )

    VaultPublisher(vault, store, today=LATER).publish(
        build_article([], title=title_two)
    )

    expected = index_oracle([title_one, title_two, foreign_title],
                            created=TODAY, updated=LATER)
    assert (vault / INDEX_FILENAME).read_bytes() == expected.encode("utf-8")


def test_req_022__content_update_changing_no_titles_leaves_index_byte_identical(
    tmp_path, store, fake_zotero
):
    vault = tmp_path / "vault"
    ck_a, ck_b = distinct_citekeys(2)
    [title] = distinct_titles(1)
    existing = build_article([(ck_a,)], title=title)
    register_citekey_map(fake_zotero, [ck_a, ck_b])
    VaultPublisher(vault, store, today=TODAY).publish(existing)

    index = vault / INDEX_FILENAME
    expected = index_oracle([title], created=TODAY, updated=TODAY)
    assert index.read_bytes() == expected.encode("utf-8")

    stamp_mtimes(vault)
    index_state = (index.read_bytes(), index.stat().st_mtime_ns)

    update = Article(
        title=title,
        summary=f"Updated synthesis {rand_word()}.",
        sections=(),
        claims=(
            Claim(
                text=f"Fresh finding {rand_word()} emerges.",
                citekeys=(ck_b,),
                quotes=(Quote(citekey=ck_b,
                              text=f"fresh evidence {rand_word()}"),),
            ),
        ),
        links=(),
    )
    page = VaultPublisher(vault, store, today=LATER).publish(update)

    # The entity page changed, but the title set did not: Index.md must not
    # be rewritten (same bytes AND same sentinel mtime).
    assert f'updated: "{LATER}"' in page.read_text(encoding="utf-8")
    assert (index.read_bytes(), index.stat().st_mtime_ns) == index_state
