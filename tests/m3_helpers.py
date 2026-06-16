"""M3 test helpers: independent re-implementation of the contract SS6 page
format (the byte-exact oracle for render_page), pinned contract fixtures,
hypothesis strategies for references, and fake-Zotero registration helpers.

Everything here is derived from docs/contract.md SS6 (+ SS3.1/SS4.4 for the
fake-server registration) alone.  Only the frozen M1 surface
(zotwiki.models) is imported; zotwiki.publisher is imported by the test
modules themselves (via their module-scoped autouse fixtures) so that its
absence reads as a per-test contract failure, not a collection error.

Format decisions encoded here (all from contract SS6.1-SS6.3):

  - frontmatter: keys exactly (zotwiki, title, created, updated, citekeys,
    zotero_keys, tags) in that order; `zotwiki: 2` unquoted; strings
    double-quoted with only \\ and \" escapes; block lists indented two
    spaces; empty list inline as `citekeys: []` / `zotero_keys: []`.
  - body: blocks joined by exactly one blank line, starting with the block
    after the closing `---` (frontmatter is block zero of the join, per
    "each block separated by exactly one blank line"); LF only; no trailing
    whitespace; exactly one trailing newline.
  - claim suffix, quote lines, link bullets, reference lines: the literal
    formats of SS6.3.
"""
from __future__ import annotations

import random
import string

from hypothesis import strategies as st

from zotwiki.models import Article, Claim, Quote, Section, SourceItem

from m2_helpers import (
    expected_article_from_dict,
    make_article_dict,
    rand_key,
    rand_word,
)

# ----- independent SS6.2/SS6.3 renderer (the oracle) ----------------------


def fm_quote(value: str) -> str:
    """SS6.2 quoted scalar: only \\ and \" are ever escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def cited_citekeys(article: Article) -> list[str]:
    """Sorted union of all claim citekeys (SS6.2 `citekeys`, SS6.6 refs)."""
    return sorted({ck for claim in article.claims for ck in claim.citekeys})


def frontmatter_block(title: str, created: str, updated: str,
                      citekeys: list[str], zotero_keys=()) -> str:
    lines = [
        "---",
        "zotwiki: 2",
        f"title: {fm_quote(title)}",
        f"created: {fm_quote(created)}",
        f"updated: {fm_quote(updated)}",
    ]
    if citekeys:
        lines.append("citekeys:")
        lines.extend(f"  - {fm_quote(ck)}" for ck in citekeys)
    else:
        lines.append("citekeys: []")
    zkeys = sorted(set(zotero_keys))
    if zkeys:
        lines.append("zotero_keys:")
        lines.extend(f"  - {fm_quote(zk)}" for zk in zkeys)
    else:
        lines.append("zotero_keys: []")
    lines.extend(["tags:", '  - "zotwiki"', "---"])
    return "\n".join(lines)


def claim_suffix(sorted_citekeys) -> str:
    """SS6.3, byte-exact: ' [' + '; '.join('@'+ck) + ']'."""
    return " [" + "; ".join("@" + ck for ck in sorted_citekeys) + "]"


def reference_line(item: SourceItem) -> str:
    creators = ", ".join(item.creators) if item.creators else "Unknown"
    year = str(item.year) if item.year is not None else "n.d."
    return (
        f"- [@{item.citekey}] {creators} ({year}). *{item.title}*. "
        f"[Zotero](zotero://select/library/items/{item.key})"
    )


def render_oracle(article: Article, references, *, created: str,
                  updated: str, zotero_keys=()) -> str:
    """Independent canonical rendering per contract SS6.1-SS6.3.

    `references` may arrive in any order; the References block is emitted
    sorted by citekey (SS6.3).  `zotero_keys` are the source Zotero keys
    recorded in frontmatter (SS6.2), emitted sorted and deduped.
    """
    cited = cited_citekeys(article)
    by_citekey = {item.citekey: item for item in references}
    blocks = [
        frontmatter_block(article.title, created, updated, cited, zotero_keys),
        f"# {article.title}",
        article.summary,
    ]
    for section in article.sections:
        blocks.append(f"## {section.heading}")
        blocks.append(section.body)
    blocks.append("## Claims")
    claim_lines: list[str] = []
    for claim in article.claims:
        claim_lines.append(f"- {claim.text}{claim_suffix(claim.citekeys)}")
        claim_lines.extend(f"  > [@{q.citekey}] {q.text}" for q in claim.quotes)
    if claim_lines:
        blocks.append("\n".join(claim_lines))
    blocks.append("## Links")
    if article.links:
        blocks.append("\n".join(f"- [[{target}]]" for target in article.links))
    blocks.append("## References")
    if cited:
        blocks.append("\n".join(reference_line(by_citekey[ck]) for ck in cited))
    return "\n\n".join(blocks) + "\n"


# ----- pinned contract SS6 fixture (built from the doc's own examples) -----

PINNED_TODAY = "2026-06-11"

PINNED_ARTICLE = Article(
    title="Transformer",
    summary="One-paragraph synthesis of what the page is about.",
    sections=(
        Section(heading="Architecture",
                body="Multi-line markdown without headings."),
    ),
    claims=(
        Claim(
            text="Self-attention replaces recurrence entirely.",
            citekeys=("doe2020attention", "vaswani2017attention"),
            quotes=(
                Quote(citekey="doe2020attention",
                      text="attention suffices for sequence transduction"),
                Quote(citekey="vaswani2017attention",
                      text="we propose a new simple network architecture, "
                           "the Transformer"),
            ),
        ),
    ),
    links=("Attention Mechanism", "Sequence Modeling"),
)

PINNED_REFS = (
    SourceItem(key="ABCD1234", citekey="doe2020attention",
               title="A Study of Attention", creators=("Jane Doe",),
               year=2020, url=None, has_fulltext=True),
    SourceItem(key="WXYZ7890", citekey="vaswani2017attention",
               title="Attention Is All You Need",
               creators=("Ashish Vaswani", "DeepThought Collective"),
               year=2017, url="https://arxiv.org/abs/1706.03762",
               has_fulltext=True),
)

# Byte-exact expected page, transcribed by hand from contract SS6.2 + SS6.3
# (NOT produced by running any zotwiki code).
PINNED_PAGE = (
    "---\n"
    "zotwiki: 2\n"
    'title: "Transformer"\n'
    'created: "2026-06-11"\n'
    'updated: "2026-06-11"\n'
    "citekeys:\n"
    '  - "doe2020attention"\n'
    '  - "vaswani2017attention"\n'
    "zotero_keys:\n"
    '  - "ABCD1234"\n'
    '  - "WXYZ7890"\n'
    "tags:\n"
    '  - "zotwiki"\n'
    "---\n"
    "\n"
    "# Transformer\n"
    "\n"
    "One-paragraph synthesis of what the page is about.\n"
    "\n"
    "## Architecture\n"
    "\n"
    "Multi-line markdown without headings.\n"
    "\n"
    "## Claims\n"
    "\n"
    "- Self-attention replaces recurrence entirely. "
    "[@doe2020attention; @vaswani2017attention]\n"
    "  > [@doe2020attention] attention suffices for sequence transduction\n"
    "  > [@vaswani2017attention] we propose a new simple network "
    "architecture, the Transformer\n"
    "\n"
    "## Links\n"
    "\n"
    "- [[Attention Mechanism]]\n"
    "- [[Sequence Modeling]]\n"
    "\n"
    "## References\n"
    "\n"
    "- [@doe2020attention] Jane Doe (2020). *A Study of Attention*. "
    "[Zotero](zotero://select/library/items/ABCD1234)\n"
    "- [@vaswani2017attention] Ashish Vaswani, DeepThought Collective "
    "(2017). *Attention Is All You Need*. "
    "[Zotero](zotero://select/library/items/WXYZ7890)\n"
)

# Pinned all-empty-blocks page: no sections, no claims (=> `citekeys: []`
# inline, empty Claims/Links/References render as bare heading lines).
EMPTY_ARTICLE = Article(
    title="Bare Notes",
    summary="Nothing is claimed yet.",
    sections=(),
    claims=(),
    links=(),
)

EMPTY_PAGE = (
    "---\n"
    "zotwiki: 2\n"
    'title: "Bare Notes"\n'
    'created: "2026-01-02"\n'
    'updated: "2026-03-04"\n'
    "citekeys: []\n"
    "zotero_keys: []\n"
    "tags:\n"
    '  - "zotwiki"\n'
    "---\n"
    "\n"
    "# Bare Notes\n"
    "\n"
    "Nothing is claimed yet.\n"
    "\n"
    "## Claims\n"
    "\n"
    "## Links\n"
    "\n"
    "## References\n"
)

# Internal consistency guard: the oracle must reproduce the hand-pinned
# bytes.  Plain asserts (not tests): they protect the tester's own helpers.
assert render_oracle(PINNED_ARTICLE, PINNED_REFS, created=PINNED_TODAY,
                     updated=PINNED_TODAY,
                     zotero_keys=("ABCD1234", "WXYZ7890")) == PINNED_PAGE
assert render_oracle(EMPTY_ARTICLE, (),
                     created="2026-01-02", updated="2026-03-04") == EMPTY_PAGE


# ----- runtime-random articles + locally built references -----------------


def random_publishable_article(**kwargs) -> Article:
    """A fresh canonical Article with runtime-random content (via the M2
    factory + independent SS5 canonicalization)."""
    article, _ = expected_article_from_dict(make_article_dict(**kwargs))
    return article


def local_references_for(article: Article) -> tuple[SourceItem, ...]:
    """One runtime-random SourceItem per cited citekey (for pure
    render/parse tests; no server involved)."""
    return tuple(
        SourceItem(
            key=rand_key(),
            citekey=ck,
            title=f"Source {rand_word().capitalize()} {rand_word()}",
            creators=(f"{rand_word().capitalize()} {rand_word().capitalize()}",),
            year=random.randint(1900, 2099),
            url=None,
            has_fulltext=True,
        )
        for ck in cited_citekeys(article)
    )


# ----- fake-Zotero registration (for VaultPublisher tests) ----------------


def creator_entry(first: str, last: str) -> dict:
    """A contract SS4.4 creator object."""
    return {"creatorType": "author", "firstName": first, "lastName": last}


def register_reference(fake, citekey: str, *, key: str | None = None,
                       title: str | None = None, first: str | None = None,
                       last: str | None = None,
                       year: int | None = None) -> SourceItem:
    """Register an item resolvable as `citekey` on the fake server and
    return the SourceItem the adapter must map it to (contract SS3.1)."""
    title = title if title is not None else f"Paper {rand_word().capitalize()} {rand_word()}"
    first = first if first is not None else rand_word().capitalize()
    last = last if last is not None else rand_word().capitalize()
    year = year if year is not None else random.randint(1900, 2099)
    key = fake.add_item(
        key,
        title=title,
        creators=[creator_entry(first, last)],
        date=str(year),
        citekey=citekey,
        fulltext=f"Quoted material {rand_word()} {rand_word()}.",
    )
    return SourceItem(
        key=key,
        citekey=citekey,
        title=title,
        creators=(f"{first} {last}",),
        year=year,
        url=None,
        has_fulltext=True,
    )


def register_article_references(fake, article: Article) -> tuple[SourceItem, ...]:
    """Register every citekey cited by `article`; returns the expected
    SourceItems sorted by citekey."""
    return tuple(register_reference(fake, ck) for ck in cited_citekeys(article))


# ----- vault snapshot helpers (byte + mtime no-write semantics) ------------

SENTINEL_MTIME_NS = 1_234_567_890_000_000_000  # fixed instant, no real time


def stamp_mtimes(vault, ns: int = SENTINEL_MTIME_NS) -> None:
    """Pin every vault file's mtime to a sentinel so that any later write
    is observable as an mtime change (no sleeps needed)."""
    import os

    for path in vault.glob("*.md"):
        os.utime(path, ns=(ns, ns))


def vault_snapshot(vault) -> dict[str, tuple[bytes, int]]:
    """filename -> (bytes, mtime_ns) for every .md file in the vault."""
    return {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in vault.glob("*.md")
    }


# ----- hypothesis strategies ------------------------------------------------

KEY_CHARS = string.ascii_uppercase + string.digits

# Reference titles / creator names: single-line unicode words (letters and
# numbers only, so the strict SS6.3 reference-line *shape* stays unambiguous).
_REF_WORD = st.text(
    alphabet=st.characters(categories=("L", "N")), min_size=1, max_size=8
)


def ref_titles_st():
    return st.lists(_REF_WORD, min_size=1, max_size=4).map(" ".join)


def creator_names_st():
    return st.lists(_REF_WORD, min_size=1, max_size=2).map(" ".join)


def item_keys_st():
    return st.text(alphabet=KEY_CHARS, min_size=8, max_size=8)


def dates_st():
    """Canonical YYYY-MM-DD strings, runtime-generated (never real time)."""
    from datetime import date

    return st.dates(date(1900, 1, 1), date(2099, 12, 31)).map(str)


@st.composite
def references_for(draw, article: Article) -> tuple[SourceItem, ...]:
    """Exactly one SourceItem per cited citekey, in a drawn (shuffled)
    order; render_page must sort the References block itself."""
    items = [
        SourceItem(
            key=draw(item_keys_st()),
            citekey=ck,
            title=draw(ref_titles_st()),
            creators=tuple(draw(st.lists(creator_names_st(), max_size=2))),
            year=draw(st.none() | st.integers(1000, 9999)),
            url=draw(st.none() | st.just("https://example.test/item")),
            has_fulltext=draw(st.booleans()),
        )
        for ck in cited_citekeys(article)
    ]
    return tuple(draw(st.permutations(items))) if items else ()
