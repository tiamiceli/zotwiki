"""M2 test helpers: FakeLLM + article factories/strategies + independent
re-implementations of contract rules.

Everything in this module is derived from docs/contract.md alone:

  - FakeLLM            implements the LLMClient protocol of contract SS5.1
                       structurally (no zotwiki.llm import needed).
  - collapse_ws /
    normalize_body /
    expected_article_from_dict
                       independent re-implementation of the SS5.2 schema
                       reading plus the SS5.4 whitespace normalization and
                       the SS2/SS5.3 canonicalization, used as the oracle
                       for parse_article_json on *valid* input.
  - article_to_plain_dict
                       independent serializer of a canonical Article to the
                       SS5.2 JSON shape (oracle for article_to_json_dict).
  - expected_merge     independent re-implementation of the SS7.2 merge.
  - hypothesis strategies generating *canonical* Articles (contract SS2)
                       with runtime-random unicode content, plus messy
                       payload perturbations whose SS5.4 normalization is
                       known by construction.

Only the M1-frozen surface (zotwiki.models) is imported here; the M2
surfaces (zotwiki.llm / zotwiki.compiler) are imported by the test modules
themselves so that their absence reads as a contract failure there.
"""
from __future__ import annotations

import random
import re
import string

from hypothesis import strategies as st

from zotwiki.models import (
    Article,
    Claim,
    Contradiction,
    Quote,
    Section,
    normalize_text,
)

REQUIRED_KEYS = ("title", "summary", "sections", "claims", "links")
RESERVED_HEADINGS = ("Claims", "Links", "References")
RESERVED_TITLES = ("Index", "Contradictions")

CITEKEY_ALPHABET = string.ascii_letters + string.digits + "_.:-"
TITLE_FIRST_CHARS = string.ascii_letters + string.digits
TITLE_WORD_CHARS = TITLE_FIRST_CHARS + ",()'-"
KEY_ALPHABET = string.ascii_uppercase + string.digits


# ----- FakeLLM (contract SS5.1) -----------------------------------------


class FakeLLM:
    """LLMClient fake: records every prompt, returns scripted responses.

    With one scripted response it is returned for every call; with several,
    they are consumed in order (the last one then repeats).
    """

    def __init__(self, *responses: str) -> None:
        if not responses:
            raise ValueError("FakeLLM needs at least one scripted response")
        self.prompts: list[str] = []
        self._responses: list[str] = list(responses)

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        if len(self._responses) > 1:
            return self._responses.pop(0)
        return self._responses[0]


# ----- runtime-random raw material ---------------------------------------


def rand_word(max_len: int = 6, alphabet: str = string.ascii_lowercase) -> str:
    return "".join(random.choices(alphabet, k=random.randint(2, max(2, max_len))))


def rand_citekey() -> str:
    return f"{rand_word()}{random.randint(1900, 2099)}{rand_word()}"


def rand_key() -> str:
    """A runtime-generated Zotero item key: 8 chars of [A-Z0-9]."""
    return "".join(random.choices(KEY_ALPHABET, k=8))


def make_article_dict(*, title: str | None = None, n_claims: int = 2,
                      contradictions: list | None = None) -> dict:
    """A fresh, valid contract SS5.2 JSON object with runtime-random content.

    Always has >= 1 section, exactly `n_claims` claims (each with >= 1
    citekey and one quote per citekey), and >= 1 link, so mutation-based
    invalid cases can index into claims[0] / sections[0] / quotes[0].
    """
    pool = sorted({rand_citekey() for _ in range(4)})
    while len(pool) < 3:  # astronomically unlikely, but keep it total
        pool = sorted(set(pool) | {rand_citekey()})
    claims = []
    for i in range(n_claims):
        cks = sorted(random.sample(pool, k=random.randint(1, 2)))
        claims.append(
            {
                "text": f"Finding {rand_word()} alters {rand_word()} number {i}.",
                "citekeys": cks,
                "quotes": [
                    {"citekey": ck, "text": f"quoted {rand_word()} evidence {rand_word()}"}
                    for ck in cks
                ],
            }
        )
    d = {
        "title": title
        if title is not None
        else f"{rand_word().capitalize()} {rand_word().capitalize()}",
        "summary": f"A synthesis about {rand_word()} and {rand_word()}.",
        "sections": [
            {
                "heading": f"Background {rand_word()}",
                "body": f"First {rand_word()} line.\n\nSecond {rand_word()} line.",
            }
        ],
        "claims": claims,
        "links": [f"Topic {rand_word().capitalize()}", f"Area {rand_word().capitalize()}"],
    }
    if contradictions is not None:
        d["contradictions"] = contradictions
    return d


# ----- independent SS5.4 normalization + SS5.2/SS5.3 canonical reading ----


def collapse_ws(text: str) -> str:
    """SS5.4 single-line rule: strip; collapse whitespace runs to one space."""
    return re.sub(r"\s+", " ", text).strip()


def normalize_body(body: str) -> str:
    """SS5.4 body rule: rstrip lines; drop leading/trailing blank lines;
    collapse runs of >= 2 blank lines to one."""
    lines = [line.rstrip() for line in body.split("\n")]
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()
    out: list[str] = []
    pending_blank = False
    for line in lines:
        if line == "":
            pending_blank = True
            continue
        if pending_blank:
            out.append("")
            pending_blank = False
        out.append(line)
    return "\n".join(out)


def expected_article_from_dict(d: dict) -> tuple[Article, tuple[Contradiction, ...]]:
    """The (Article, contradictions) that parse_article_json must return for
    a *valid* SS5.2 payload, computed independently of zotwiki.llm."""
    sections = tuple(
        Section(heading=collapse_ws(s["heading"]), body=normalize_body(s["body"]))
        for s in d.get("sections", [])
    )
    claims = []
    for c in d.get("claims", []):
        quotes = tuple(
            sorted(
                (Quote(citekey=q["citekey"], text=collapse_ws(q["text"])) for q in c["quotes"]),
                key=lambda q: (q.citekey, q.text),
            )
        )
        claims.append(
            Claim(
                text=collapse_ws(c["text"]),
                citekeys=tuple(sorted(c["citekeys"])),
                quotes=quotes,
            )
        )
    contradictions = tuple(
        Contradiction(
            existing_claim=collapse_ws(x["existing_claim"]),
            new_claim=collapse_ws(x["new_claim"]),
            citekeys=tuple(sorted(x["citekeys"])),
        )
        for x in d.get("contradictions", [])
    )
    article = Article(
        title=collapse_ws(d["title"]),
        summary=collapse_ws(d["summary"]),
        sections=sections,
        claims=tuple(claims),
        links=tuple(sorted({collapse_ws(link) for link in d["links"]})),
    )
    return article, contradictions


def article_to_plain_dict(article: Article) -> dict:
    """Independent serializer of a canonical Article to the SS5.2 shape
    (what article_to_json_dict must be equivalent to, per SS5.5)."""
    return {
        "title": article.title,
        "summary": article.summary,
        "sections": [{"heading": s.heading, "body": s.body} for s in article.sections],
        "claims": [
            {
                "text": c.text,
                "citekeys": list(c.citekeys),
                "quotes": [{"citekey": q.citekey, "text": q.text} for q in c.quotes],
            }
            for c in article.claims
        ],
        "links": list(article.links),
    }


# ----- independent SS7.2 merge re-implementation --------------------------


def expected_merge(existing: Article, update: Article) -> Article:
    """merge_articles per contract SS7.2, re-implemented from the doc."""
    if existing.title != update.title:
        raise AssertionError("expected_merge requires equal titles")
    update_by_heading = {s.heading: s for s in update.sections}
    existing_headings = {s.heading for s in existing.sections}
    sections: list[Section] = []
    for s in existing.sections:
        replacement = update_by_heading.get(s.heading)
        if replacement is None:
            sections.append(s)
        else:
            sections.append(Section(heading=s.heading, body=replacement.body))
    for s in update.sections:
        if s.heading not in existing_headings:
            sections.append(s)

    update_by_key: dict[str, Claim] = {}
    for c in update.claims:
        update_by_key.setdefault(normalize_text(c.text), c)
    matched: set[str] = set()
    claims: list[Claim] = []
    for c in existing.claims:
        key = normalize_text(c.text)
        u = update_by_key.get(key)
        if u is None:
            claims.append(c)
            continue
        matched.add(key)
        citekeys = tuple(sorted(set(c.citekeys) | set(u.citekeys)))
        quote_map: dict[tuple[str, str], Quote] = {}
        for q in list(c.quotes) + list(u.quotes):  # first-seen text wins
            quote_map.setdefault((q.citekey, normalize_text(q.text)), q)
        quotes = tuple(sorted(quote_map.values(), key=lambda q: (q.citekey, q.text)))
        claims.append(Claim(text=c.text, citekeys=citekeys, quotes=quotes))
    for c in update.claims:
        if normalize_text(c.text) not in matched:
            claims.append(c)

    return Article(
        title=existing.title,
        summary=update.summary,
        sections=tuple(sections),
        claims=tuple(claims),
        links=tuple(sorted(set(existing.links) | set(update.links))),
    )


# ----- hypothesis strategies for canonical Articles -----------------------

# Non-whitespace printable unicode: letters, numbers, punctuation, symbols.
INLINE_CHARS = st.characters(categories=("L", "N", "P", "S"))
INLINE_WORD = st.text(alphabet=INLINE_CHARS, min_size=1, max_size=8)


def inline_texts(min_words: int = 1, max_words: int = 6):
    """Canonical single-line text: whitespace-collapse fixpoints."""
    return st.lists(INLINE_WORD, min_size=min_words, max_size=max_words).map(" ".join)


def claim_texts():
    return inline_texts().filter(lambda t: " [@" not in t and t[0] not in "->")


def quote_texts():
    return inline_texts(max_words=8)


def heading_texts():
    return inline_texts(max_words=4).filter(lambda h: h not in RESERVED_HEADINGS)


def citekeys_st():
    return st.text(alphabet=CITEKEY_ALPHABET, min_size=1, max_size=12)


@st.composite
def _titles(draw) -> str:
    first = draw(st.text(alphabet=TITLE_FIRST_CHARS, min_size=1, max_size=1))
    head = first + draw(st.text(alphabet=TITLE_WORD_CHARS, max_size=7))
    rest = draw(st.lists(st.text(alphabet=TITLE_WORD_CHARS, min_size=1, max_size=7), max_size=3))
    return " ".join([head] + rest)


def titles_st():
    return _titles().filter(lambda t: t not in RESERVED_TITLES and len(t) <= 120)


def _body_lines():
    return (
        st.lists(INLINE_WORD, min_size=1, max_size=5)
        .map(" ".join)
        .filter(lambda line: not line.startswith("#"))
    )


@st.composite
def bodies_st(draw) -> str:
    paragraphs = draw(
        st.lists(st.lists(_body_lines(), min_size=1, max_size=3), min_size=1, max_size=3)
    )
    return "\n\n".join("\n".join(p) for p in paragraphs)


def _draw_claim(draw, text: str) -> Claim:
    cks = tuple(sorted(draw(st.lists(citekeys_st(), min_size=1, max_size=3, unique=True))))
    quote_map: dict[tuple[str, str], Quote] = {}
    for _ in range(draw(st.integers(1, 3))):
        ck = draw(st.sampled_from(cks))
        qt = draw(quote_texts())
        quote_map.setdefault((ck, normalize_text(qt)), Quote(citekey=ck, text=qt))
    quotes = tuple(sorted(quote_map.values(), key=lambda q: (q.citekey, q.text)))
    return Claim(text=text, citekeys=cks, quotes=quotes)


@st.composite
def claims_st(draw) -> Claim:
    return _draw_claim(draw, draw(claim_texts()))


@st.composite
def articles_st(draw, max_sections: int = 3, max_claims: int = 3, max_links: int = 3) -> Article:
    headings = draw(st.lists(heading_texts(), max_size=max_sections, unique=True))
    sections = tuple(Section(heading=h, body=draw(bodies_st())) for h in headings)
    raw_claims = draw(st.lists(claims_st(), max_size=max_claims))
    seen: set[str] = set()
    claims: list[Claim] = []
    for c in raw_claims:  # keep claim identity (normalize_text) unambiguous
        key = normalize_text(c.text)
        if key and key not in seen:
            seen.add(key)
            claims.append(c)
    links = tuple(sorted(set(draw(st.lists(titles_st(), max_size=max_links)))))
    return Article(
        title=draw(titles_st()),
        summary=draw(inline_texts()),
        sections=sections,
        claims=tuple(claims),
        links=links,
    )


# ----- messy-but-valid payloads with a known SS5.4 normalization -----------


def _messy_inline(draw, text: str, ws_options: tuple[str, ...] = (" ", "  ", "\t ")) -> str:
    pad_left = draw(st.sampled_from(["", " ", "  "]))
    pad_right = draw(st.sampled_from(["", " ", "  "]))
    run = draw(st.sampled_from(ws_options))
    return pad_left + text.replace(" ", run) + pad_right


def _messy_body(draw, body: str) -> str:
    out: list[str] = []
    for _ in range(draw(st.integers(0, 2))):
        out.append(draw(st.sampled_from(["", " ", "\t"])))
    for line in body.split("\n"):
        if line == "":
            for _ in range(draw(st.integers(1, 3))):
                out.append(draw(st.sampled_from(["", "  "])))
        else:
            out.append(line + draw(st.sampled_from(["", " ", "   ", "\t"])))
    for _ in range(draw(st.integers(0, 2))):
        out.append(draw(st.sampled_from(["", " "])))
    return "\n".join(out)


@st.composite
def messy_article_payloads(draw) -> tuple[Article, dict]:
    """(canonical_article, valid-but-messy SS5.2 dict) pairs: shuffled claim
    citekeys/quotes, duplicated+shuffled links, padded/expanded whitespace
    everywhere SS5.4 normalizes it.  parse_article_json over the dict must
    give back exactly the canonical article."""
    article = draw(articles_st())
    claims = []
    for c in article.claims:
        quotes = [
            {"citekey": q.citekey, "text": _messy_inline(draw, q.text)}
            for q in draw(st.permutations(c.quotes))
        ]
        claims.append(
            {
                "text": _messy_inline(draw, c.text),
                "citekeys": list(draw(st.permutations(c.citekeys))),
                "quotes": quotes,
            }
        )
    links = list(article.links)
    if links:
        duplicates = draw(
            st.lists(st.sampled_from(links), max_size=2)
        )
        links = list(draw(st.permutations(links + duplicates)))
    payload = {
        "title": article.title,
        "summary": _messy_inline(draw, article.summary, ws_options=(" ", "  ", "\n", "\t", " \n ")),
        "sections": [
            {"heading": _messy_inline(draw, s.heading), "body": _messy_body(draw, s.body)}
            for s in article.sections
        ],
        "claims": claims,
        "links": links,
    }
    return article, payload


# ----- merge pairs ---------------------------------------------------------


def _ascii_claim_texts():
    return st.lists(
        st.text(alphabet=string.ascii_lowercase, min_size=2, max_size=8),
        min_size=1,
        max_size=5,
    ).map(" ".join)


@st.composite
def merge_pairs(draw) -> tuple[Article, Article]:
    """(existing, update) canonical Articles with the same title, sharing
    some section headings (replaced bodies) and some claims (same identity
    under normalize_text, via case perturbation) so every SS7.2 branch is
    exercised."""
    title = draw(titles_st())

    existing_headings = draw(st.lists(heading_texts(), max_size=3, unique=True))
    existing_sections = tuple(
        Section(heading=h, body=draw(bodies_st())) for h in existing_headings
    )
    replaced = [h for h in existing_headings if draw(st.booleans())]
    fresh_headings = [
        h
        for h in draw(st.lists(heading_texts(), max_size=2, unique=True))
        if h not in existing_headings
    ]
    update_sections = tuple(
        Section(heading=h, body=draw(bodies_st())) for h in replaced + fresh_headings
    )

    existing_texts = draw(
        st.lists(_ascii_claim_texts(), max_size=3, unique_by=normalize_text)
    )
    existing_claims = tuple(_draw_claim(draw, t) for t in existing_texts)
    existing_keys = {normalize_text(t) for t in existing_texts}
    update_claims: list[Claim] = []
    for t in existing_texts:
        if draw(st.booleans()):
            variant = t.upper() if draw(st.booleans()) else t
            update_claims.append(_draw_claim(draw, variant))
    fresh_texts = [
        t
        for t in draw(st.lists(_ascii_claim_texts(), max_size=2, unique_by=normalize_text))
        if normalize_text(t) not in existing_keys
    ]
    update_claims.extend(_draw_claim(draw, t) for t in fresh_texts)

    existing = Article(
        title=title,
        summary=draw(inline_texts()),
        sections=existing_sections,
        claims=existing_claims,
        links=tuple(sorted(set(draw(st.lists(titles_st(), max_size=3))))),
    )
    update = Article(
        title=title,
        summary=draw(inline_texts()),
        sections=update_sections,
        claims=tuple(update_claims),
        links=tuple(sorted(set(draw(st.lists(titles_st(), max_size=3))))),
    )
    return existing, update
