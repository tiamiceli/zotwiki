"""M4 test helpers: clean-vault construction through the frozen M3 publisher
plus surgical corruption utilities for the contract SS8 audit checks.

Everything here is derived from docs/contract.md SS2.1 (normalize_text),
SS6 (vault/page format), SS8 (audit checks) and the SS4 fake-server
registration shapes.  Only frozen, green surfaces are imported at module
scope (zotwiki.models from M1, zotwiki.publisher from M3); zotwiki.auditor
is imported by the test modules themselves via their module-scoped autouse
fixtures so that its absence reads as a per-test contract failure rather
than a collection error.

Key facts encoded here (all from contract SS8):

  - AUDIT_CODES, transcribed by hand (EXPECTED_AUDIT_CODES below).
  - Reports are sorted by (page, code, detail).
  - A clean vault means: every cited citekey resolves, every quote is a
    normalized substring of its item's fulltext, every [[target]] exists,
    Index.md lists exactly the entity pages, and the three citekey sets of
    each page (claims / References block / frontmatter) coincide -- which is
    exactly what publishing through the M3 publisher with supporting
    references produces.
"""
from __future__ import annotations

import random
import socket
import string

from hypothesis import strategies as st

from zotwiki.models import (
    Article,
    Claim,
    Quote,
    Section,
    SourceItem,
    normalize_text,
)
from zotwiki.publisher import VaultPublisher

from m2_helpers import (
    RESERVED_HEADINGS,
    citekeys_st,
    rand_citekey,
    rand_word,
    titles_st,
)
from m3_helpers import (
    cited_citekeys,
    claim_suffix,
    creator_entry,
    frontmatter_block,
    reference_line,
)

TODAY = "2026-06-11"

# Transcribed by hand from contract SS8 (NOT imported from zotwiki).
EXPECTED_AUDIT_CODES = (
    "CITEKEY_UNRESOLVED",
    "QUOTE_NOT_FOUND",
    "BROKEN_LINK",
    "ORPHAN_PAGE",
    "INDEX_STALE",
    "PAGE_UNPARSEABLE",
    "REFERENCE_MISSING",
)


# ----- runtime-random article construction ---------------------------------


def distinct_citekeys(n: int) -> list[str]:
    """`n` distinct runtime-random citekeys, sorted ascending."""
    cks: set[str] = set()
    while len(cks) < n:
        cks.add(rand_citekey())
    return sorted(cks)


def build_article(claim_specs, *, title: str | None = None, links=(),
                  sections: int = 1) -> Article:
    """A canonical Article with one claim per spec (a tuple of citekeys,
    each backed by one runtime-random quote) and caller-controlled links so
    that a vault's link closure is always explicit."""
    claims = []
    for i, cks in enumerate(claim_specs):
        cks = tuple(sorted(cks))
        quotes = tuple(
            sorted(
                (
                    Quote(citekey=ck, text=f"evidence {rand_word()} {rand_word()} {i}")
                    for ck in cks
                ),
                key=lambda q: (q.citekey, q.text),
            )
        )
        claims.append(
            Claim(
                text=f"Claim {rand_word()} number {i} alters {rand_word()}.",
                citekeys=cks,
                quotes=quotes,
            )
        )
    return Article(
        title=title
        if title is not None
        else f"{rand_word().capitalize()} {rand_word().capitalize()}",
        summary=f"A synthesis about {rand_word()} and {rand_word()}.",
        sections=tuple(
            Section(
                heading=f"Background {rand_word()} {k}",
                body=f"Body {rand_word()} text {rand_word()}.",
            )
            for k in range(sections)
        ),
        claims=tuple(claims),
        links=tuple(sorted(set(links))),
    )


def quotes_by_citekey(articles) -> dict[str, list[str]]:
    """citekey -> every quote text attributed to it across `articles`
    (citekeys cited without quotes map to an empty list)."""
    out: dict[str, list[str]] = {}
    for article in articles:
        for claim in article.claims:
            for ck in claim.citekeys:
                out.setdefault(ck, [])
            for quote in claim.quotes:
                out.setdefault(quote.citekey, []).append(quote.text)
    return out


# ----- fake-Zotero registration with quote-supporting fulltexts -------------

_UNSET = object()


def fulltext_containing(quotes) -> str:
    """A runtime-random fulltext whose SS2.1 normalization contains every
    quote's normalization (each quote embedded verbatim between spaces)."""
    parts = [f"Preamble {rand_word()} {rand_word()}."]
    for quote in quotes:
        parts.append(quote)
        parts.append(f"Interlude {rand_word()}.")
    return " ".join(parts)


def register_supporting_reference(fake, citekey: str, quotes=(), *,
                                  fulltext=_UNSET) -> SourceItem:
    """Register an item resolvable as `citekey` whose fulltext contains all
    `quotes` (or exactly `fulltext` when given; fulltext=None registers the
    item with no fulltext at all, i.e. the SS4.5 probe will 404)."""
    if fulltext is _UNSET:
        fulltext = fulltext_containing(quotes)
    title = f"Paper {rand_word().capitalize()} {rand_word()}"
    first = rand_word().capitalize()
    last = rand_word().capitalize()
    year = random.randint(1900, 2099)
    key = fake.add_item(
        title=title,
        creators=[creator_entry(first, last)],
        date=str(year),
        citekey=citekey,
        fulltext=fulltext,
    )
    return SourceItem(
        key=key,
        citekey=citekey,
        title=title,
        creators=(f"{first} {last}",),
        year=year,
        url=None,
        has_fulltext=fulltext is not None,
    )


def register_supporting_references(fake, articles) -> dict[str, SourceItem]:
    """Register every citekey cited anywhere in `articles`, each with a
    fulltext containing all of its quotes; citekey -> SourceItem."""
    return {
        ck: register_supporting_reference(fake, ck, quotes)
        for ck, quotes in sorted(quotes_by_citekey(articles).items())
    }


def publish_clean_vault(fake, store, vault, articles, *,
                        today: str = TODAY) -> dict[str, SourceItem]:
    """Register supporting references for every article, then publish them
    all through the real M3 publisher (which also maintains Index.md).
    Returns citekey -> SourceItem for later targeted corruption."""
    refs = register_supporting_references(fake, articles)
    publisher = VaultPublisher(vault, store, today=today)
    for article in articles:
        publisher.publish(article)
    return refs


# ----- targeted corruptions --------------------------------------------------


def unregister(fake, item: SourceItem) -> None:
    """Remove the server item backing `item.citekey`: resolve() will fail
    with CitekeyNotFoundError from now on."""
    del fake.items[item.key]
    fake.fulltext.pop(item.key, None)


def drop_line(path, prefix: str) -> str:
    """Delete the unique line starting with `prefix`; returns that line."""
    lines = path.read_text(encoding="utf-8").split("\n")
    hits = [line for line in lines if line.startswith(prefix)]
    assert len(hits) == 1, f"expected exactly one line {prefix!r}, got {hits!r}"
    lines.remove(hits[0])
    path.write_text("\n".join(lines), encoding="utf-8")
    return hits[0]


def render_page_with(article: Article, ref_items, *, created: str,
                     updated: str, fm_citekeys=None) -> str:
    """Contract SS6 page bytes with independently chosen frontmatter
    citekeys and References entries.  Grammar-canonical (so parse_page
    accepts it) but the three SS8-check-7 citekey sets need not coincide."""
    if fm_citekeys is None:
        fm_citekeys = cited_citekeys(article)
    blocks = [
        frontmatter_block(article.title, created, updated, sorted(fm_citekeys)),
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
    items = sorted(ref_items, key=lambda item: item.citekey)
    if items:
        blocks.append("\n".join(reference_line(item) for item in items))
    return "\n\n".join(blocks) + "\n"


def contradictions_page_text(body_blocks, *, created: str = TODAY,
                             updated: str = TODAY) -> str:
    """A canonical SS6.8 Contradictions.md: frontmatter with
    title "Contradictions" and citekeys: [], then `# Contradictions`,
    then the given blocks, one blank line between blocks."""
    blocks = [
        frontmatter_block("Contradictions", created, updated, []),
        "# Contradictions",
        *body_blocks,
    ]
    return "\n\n".join(blocks) + "\n"


def closed_port() -> int:
    """A 127.0.0.1 TCP port that nothing is listening on (bound once to
    reserve it from the ephemeral range, then released)."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# ----- report views -----------------------------------------------------------


def violation_triples(report) -> list[tuple[str, str, str]]:
    return [(v.code, v.page, v.detail) for v in report.violations]


def violation_pairs(report) -> list[tuple[str, str]]:
    return [(v.code, v.page) for v in report.violations]


# ----- hypothesis strategies ----------------------------------------------------

# Inline text that can never form a wiki-link or a heading by accident:
# printable unicode minus '[', ']' (kills accidental [[...]]) and '#'.
_SAFE_CHARS = st.characters(categories=("L", "N", "P", "S"),
                            exclude_characters="[]#")
_SAFE_WORD = st.text(alphabet=_SAFE_CHARS, min_size=1, max_size=8)


def safe_inline_texts(min_words: int = 1, max_words: int = 6):
    """Canonical (whitespace-collapse fixpoint) single-line unicode text."""
    return st.lists(_SAFE_WORD, min_size=min_words,
                    max_size=max_words).map(" ".join)


def _safe_claim_texts():
    return safe_inline_texts().filter(lambda t: t[0] not in "->")


@st.composite
def _safe_claims(draw) -> Claim:
    cks = tuple(sorted(draw(
        st.lists(citekeys_st(), min_size=1, max_size=2, unique=True)
    )))
    quote_map: dict[tuple[str, str], Quote] = {}
    for _ in range(draw(st.integers(1, 2))):
        ck = draw(st.sampled_from(cks))
        text = draw(safe_inline_texts(max_words=6))
        quote_map.setdefault((ck, normalize_text(text)),
                             Quote(citekey=ck, text=text))
    quotes = tuple(sorted(quote_map.values(), key=lambda q: (q.citekey, q.text)))
    return Claim(text=draw(_safe_claim_texts()), citekeys=cks, quotes=quotes)


@st.composite
def clean_vault_articles(draw, max_articles: int = 3) -> tuple[Article, ...]:
    """1..max_articles canonical Articles with casefold-distinct titles and
    links closed over the drawn title set, so the vault the M3 publisher
    builds from them (with supporting references) must audit clean."""
    n = draw(st.integers(1, max_articles))
    # casefold-distinct (the publisher's SS6.5 case-collision guard) and
    # never colliding with the special pages' filenames either.
    titles = draw(st.lists(
        titles_st().filter(
            lambda t: t.casefold() not in ("index", "contradictions")),
        min_size=n, max_size=n, unique_by=str.casefold,
    ))
    articles = []
    for title in titles:
        headings = draw(st.lists(
            safe_inline_texts(max_words=3).filter(
                lambda h: h not in RESERVED_HEADINGS),
            max_size=2, unique=True,
        ))
        sections = tuple(
            Section(heading=h, body=draw(safe_inline_texts(max_words=8)))
            for h in headings
        )
        raw_claims = draw(st.lists(_safe_claims(), max_size=3))
        seen: set[str] = set()
        claims: list[Claim] = []
        for claim in raw_claims:
            key = normalize_text(claim.text)
            if key and key not in seen:
                seen.add(key)
                claims.append(claim)
        links = tuple(sorted(set(draw(
            st.lists(st.sampled_from(titles), max_size=2)
        ))))
        articles.append(Article(
            title=title,
            summary=draw(safe_inline_texts()),
            sections=sections,
            claims=tuple(claims),
            links=links,
        ))
    return tuple(articles)


@st.composite
def equivalent_quote_pairs(draw) -> tuple[str, str]:
    """(page_quote, fulltext_snippet): two surface forms with equal SS2.1
    normalization.  The page quote stays a canonical single line; the
    fulltext side may additionally stretch whitespace into runs/newlines.
    Curly quotes, dash variants and letter case differ freely per side."""
    words = draw(st.lists(
        st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=6),
        min_size=2, max_size=6,
    ))
    tail = draw(st.sampled_from(["", ".", "?", "!"]))
    # Ensure every SS2.1-mapped character class actually occurs.
    base = f"it's a \"{' '.join(words)}\" x-y{tail}"

    def variant(allow_ws_runs: bool) -> str:
        out = []
        for ch in base:
            if ch == "'":
                out.append(draw(st.sampled_from(("'", "‘", "’"))))
            elif ch == '"':
                out.append(draw(st.sampled_from(('"', "“", "”"))))
            elif ch == "-":
                out.append(draw(st.sampled_from(("-", "–", "—"))))
            elif ch == " " and allow_ws_runs:
                out.append(draw(st.sampled_from((" ", "  ", "\t", "\n", " \t "))))
            elif ch.isalpha() and draw(st.booleans()):
                out.append(ch.upper())
            else:
                out.append(ch)
        return "".join(out)

    return variant(allow_ws_runs=False), variant(allow_ws_runs=True)


# Internal consistency guards for the tester's own helpers (plain asserts,
# not tests): supporting fulltexts must contain their quotes under SS2.1.
_probe_quotes = [f"sample {rand_word()} quote", "it's a “Q—q” test"]
_probe_full = fulltext_containing(_probe_quotes)
for _q in _probe_quotes:
    assert normalize_text(_q) in normalize_text(_probe_full)
del _probe_quotes, _probe_full, _q
