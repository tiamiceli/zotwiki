"""Core datatypes and text normalization (docs/contract.md SS2).

All dataclasses are frozen; sequence-valued fields are tuples so
instances are hashable and compare by value.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

__all__ = [
    "SourceItem",
    "Section",
    "Quote",
    "Claim",
    "Article",
    "Contradiction",
    "normalize_text",
]


@dataclass(frozen=True)
class SourceItem:
    key: str                      # Zotero item key, 8 chars [A-Z0-9]
    citekey: str                  # Better BibTeX citekey; "" if absent
    title: str
    creators: tuple[str, ...]     # display names, e.g. ("Ada Lovelace",)
    year: int | None
    url: str | None
    has_fulltext: bool


@dataclass(frozen=True)
class Section:
    heading: str
    body: str                     # may contain blank lines; never '#' lines


@dataclass(frozen=True)
class Quote:
    citekey: str
    text: str                     # single line


@dataclass(frozen=True)
class Claim:
    text: str                     # single line
    citekeys: tuple[str, ...]     # sorted ascending, len >= 1
    quotes: tuple[Quote, ...]     # sorted by (citekey, text), len >= 1


@dataclass(frozen=True)
class Article:
    title: str
    summary: str
    sections: tuple[Section, ...]
    claims: tuple[Claim, ...]
    links: tuple[str, ...]        # sorted ascending, deduped


@dataclass(frozen=True)
class Contradiction:
    existing_claim: str
    new_claim: str
    citekeys: tuple[str, ...]     # sorted ascending, len >= 1


_PUNCTUATION_MAP = str.maketrans(
    {
        "‘": "'",   # left single curly quote
        "’": "'",   # right single curly quote
        "“": '"',   # left double curly quote
        "”": '"',   # right double curly quote
        "–": "-",   # en dash
        "—": "-",   # em dash
    }
)

_WHITESPACE_RUN = re.compile(r"\s+")


def normalize_text(text: str) -> str:
    """Normalize text for quote matching and claim identity (contract SS2.1).

    In order: NFKC; curly quotes -> straight, en/em dash -> '-';
    casefold; collapse every whitespace run to one space; strip.
    """
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(_PUNCTUATION_MAP)
    text = text.casefold()
    return _WHITESPACE_RUN.sub(" ", text).strip()
