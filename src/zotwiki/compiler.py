"""Compiler and incremental merge semantics (docs/contract.md SS7).

The compiler turns Zotero items plus an `LLMClient` into a `CompileResult`;
it never merges and never touches the vault.  `merge_articles` is the pure
SS7.2 merge used by the publisher's update path.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass

from zotwiki.errors import ArticleSchemaError, CitekeyNotFoundError
from zotwiki.llm import LLMClient, article_to_json_dict, parse_article_json
from zotwiki.models import (
    Article,
    Claim,
    Contradiction,
    Quote,
    Section,
    SourceItem,
    normalize_text,
)
from zotwiki.zotero import ZoteroStore

__all__ = ["Compiler", "CompileResult", "merge_articles", "FULLTEXT_PROMPT_LIMIT"]

# Contract SS7: characters of fulltext included in the prompt, per item.
FULLTEXT_PROMPT_LIMIT = 20000

_BASE_INSTRUCTIONS = (
    "You are ZotWiki's article compiler. Synthesize the source items below "
    "into one encyclopedia-style article. Return exactly one JSON object "
    'with the keys "title", "summary", "sections", "claims", and "links" '
    "(docs/contract.md SS5.2) and nothing else: no commentary, at most one "
    "outer code fence. Every claim must cite its sources by citekey and "
    "carry verbatim supporting quotes from their fulltexts."
)

_UPDATE_INSTRUCTIONS = (
    "Update mode: the current article is given below as JSON. Return the "
    "full revised article. If a new finding contradicts a claim of the "
    'existing article, report it in the optional "contradictions" array '
    "(existing_claim, new_claim, citekeys) and do NOT also include the "
    'contradicting claim in "claims".'
)


@dataclass(frozen=True)
class CompileResult:
    article: Article
    contradictions: tuple[Contradiction, ...]


class Compiler:
    """Compile Zotero items into an article via an LLM (contract SS7.1)."""

    def __init__(self, store: ZoteroStore, llm: LLMClient) -> None:
        self._store = store
        self._llm = llm

    def compile(
        self, keys: Sequence[str], existing: Article | None = None
    ) -> CompileResult:
        items: list[tuple[SourceItem, str | None]] = []
        for key in keys:
            item = self._store.get(key)
            if item.citekey == "":
                raise CitekeyNotFoundError(
                    f"Zotero item {key} has no citekey "
                    "(no 'Citation Key:' line in its extra field)"
                )
            fulltext: str | None = None
            if item.has_fulltext:
                fulltext = self._store.fulltext(key)[:FULLTEXT_PROMPT_LIMIT]
            items.append((item, fulltext))

        raw = self._llm.complete(_build_prompt(items, existing))
        article, contradictions = parse_article_json(raw)
        if existing is None and contradictions:
            raise ArticleSchemaError(
                "contradictions: not permitted when compiling without an "
                "existing article"
            )
        return CompileResult(article=article, contradictions=contradictions)


def _build_prompt(
    items: Sequence[tuple[SourceItem, str | None]], existing: Article | None
) -> str:
    parts = [_BASE_INSTRUCTIONS]
    if existing is not None:
        parts.append(_UPDATE_INSTRUCTIONS)
        parts.append(
            "EXISTING ARTICLE JSON:\n"
            + json.dumps(article_to_json_dict(existing), sort_keys=True)
        )
    for item, fulltext in items:
        lines = [
            "SOURCE ITEM",
            f"citekey: {item.citekey}",
            f"title: {item.title}",
        ]
        if fulltext is not None:
            lines.append("fulltext:")
            lines.append(fulltext)
        parts.append("\n".join(lines))
    return "\n\n".join(parts)


def merge_articles(existing: Article, update: Article) -> Article:
    """Merge an update into an existing article (contract SS7.2).

    Pure and deterministic; content present only in `existing` survives
    byte-identically (never-clobber).
    """
    if existing.title != update.title:
        raise ArticleSchemaError(
            f"title: cannot merge {update.title!r} into {existing.title!r}"
        )

    # Sections: keyed by exact heading; existing order preserved, matching
    # bodies replaced in place, new headings appended in update order.
    update_by_heading = {s.heading: s for s in update.sections}
    existing_headings = {s.heading for s in existing.sections}
    sections: list[Section] = []
    for section in existing.sections:
        replacement = update_by_heading.get(section.heading)
        if replacement is None:
            sections.append(section)
        else:
            sections.append(Section(heading=section.heading, body=replacement.body))
    sections.extend(
        s for s in update.sections if s.heading not in existing_headings
    )

    # Claims: keyed by normalize_text(text); existing order preserved, the
    # existing text survives, citekeys union sorted, quotes union deduped by
    # (citekey, normalized text) keeping first-seen text; unmatched update
    # claims appended in update order.
    update_by_key: dict[str, Claim] = {}
    for claim in update.claims:
        update_by_key.setdefault(normalize_text(claim.text), claim)
    matched: set[str] = set()
    claims: list[Claim] = []
    for claim in existing.claims:
        key = normalize_text(claim.text)
        counterpart = update_by_key.get(key)
        if counterpart is None:
            claims.append(claim)
            continue
        matched.add(key)
        citekeys = tuple(sorted(set(claim.citekeys) | set(counterpart.citekeys)))
        quote_map: dict[tuple[str, str], Quote] = {}
        for quote in (*claim.quotes, *counterpart.quotes):
            quote_map.setdefault((quote.citekey, normalize_text(quote.text)), quote)
        quotes = tuple(sorted(quote_map.values(), key=lambda q: (q.citekey, q.text)))
        claims.append(Claim(text=claim.text, citekeys=citekeys, quotes=quotes))
    claims.extend(
        c for c in update.claims if normalize_text(c.text) not in matched
    )

    return Article(
        title=existing.title,
        summary=update.summary,
        sections=tuple(sections),
        claims=tuple(claims),
        links=tuple(sorted(set(existing.links) | set(update.links))),
    )
