"""Compiler and incremental merge semantics (docs/contract.md SS7).

The compiler turns Zotero items plus an `LLMClient` into a `CompileResult`;
it never merges and never touches the vault.  `merge_articles` is the pure
SS7.2 merge used by the publisher's update path.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import asdict, dataclass

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

def _schema_example_json() -> str:
    """Render the required-JSON-shape example from the real dataclasses, so it
    can never drift from what `parse_article_json` accepts (plan-v1.2 B1)."""
    example = Article(
        title="Article Title",
        summary="One-paragraph summary.",
        sections=(Section(heading="Section Name", body="Section text."),),
        claims=(
            Claim(
                text="A factual claim.",
                citekeys=("authoryearword",),
                quotes=(
                    Quote(
                        citekey="authoryearword",
                        text="verbatim quote from fulltext",
                    ),
                ),
            ),
        ),
        links=("Related Topic",),
    )
    return json.dumps(article_to_json_dict(example), indent=2)


def _render_validation_rules() -> str:
    """Derive the schema rules from the canonical regexes in `llm.py`, so the
    prompt can never diverge from what the validator enforces (plan-v1.2 B2)."""
    from zotwiki.llm import _CITEKEY_RE, _TITLE_RE

    return (
        "Rules:\n"
        '- Every claim needs at least one entry in both "citekeys" (array of '
        'strings) and "quotes" (array of {"citekey", "text"} objects).\n'
        '- Each quote "text" must be a SINGLE LINE — no newlines or line '
        "breaks inside a quote; choose a single continuous sentence or "
        "phrase.\n"
        "- Quotes must be verbatim substrings of the provided fulltext.\n"
        f"- Title and link targets must match {_TITLE_RE.pattern}\n"
        f"- Every citekey must match {_CITEKEY_RE.pattern}"
    )


_BASE_INSTRUCTIONS = (
    "You are ZotWiki's article compiler. Synthesize the source items below "
    "into one encyclopedia-style article. Return exactly one JSON object "
    "and nothing else: no commentary, at most one outer code fence.\n\n"
    "Required JSON shape (follow exactly — wrong key names are rejected):\n"
    + _schema_example_json()
    + "\n\n"
    + _render_validation_rules()
)


@dataclass(frozen=True)
class CompileResult:
    article: Article
    contradictions: tuple[Contradiction, ...]
    zotero_keys: tuple[str, ...]


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
        return CompileResult(
            article=article,
            contradictions=contradictions,
            zotero_keys=tuple(sorted(set(keys))),
        )


def _update_instructions_with_schema() -> str:
    """Update-mode instructions with a concrete `Contradiction` example, so the
    LLM has a shape to follow rather than prose alone (plan-v1.2 B5)."""
    example = asdict(
        Contradiction(
            existing_claim="The prior article's claim, verbatim.",
            new_claim="The conflicting new finding.",
            citekeys=("authoryearword",),
        )
    )
    return (
        "Update mode: the current article is given below as JSON. Return the "
        "full revised article. If a new finding contradicts a claim of the "
        'existing article, report it in the optional "contradictions" array '
        'and do NOT also include the contradicting claim in "claims". Each '
        "contradiction is an object of this shape:\n"
        + json.dumps(example, indent=2)
    )


def _format_source_item(item: SourceItem, fulltext: str | None) -> str:
    """Render one source-item block for the prompt (plan-v1.2 B3)."""
    lines = [
        "SOURCE ITEM",
        f"citekey: {item.citekey}",
        f"title: {item.title}",
    ]
    if fulltext is not None:
        lines.append("fulltext:")
        lines.append(fulltext)
        lines.append("[END FULLTEXT]")
    return "\n".join(lines)


def _format_existing_article(article: Article) -> str:
    """Render the update-mode existing-article JSON block (plan-v1.2 B4).

    Contract §7.1 requires `json.dumps(article_to_json_dict(existing),
    sort_keys=True)` to appear verbatim as a substring of the prompt, so the
    serialization stays compact (no `indent`); `sort_keys` keeps it
    deterministic across Python versions.
    """
    body = json.dumps(article_to_json_dict(article), sort_keys=True)
    return "EXISTING ARTICLE JSON:\n" + body


def _build_prompt(
    items: Sequence[tuple[SourceItem, str | None]], existing: Article | None
) -> str:
    parts = [_BASE_INSTRUCTIONS]
    if existing is not None:
        parts.append(_update_instructions_with_schema())
        parts.append(_format_existing_article(existing))
    for item, fulltext in items:
        parts.append(_format_source_item(item, fulltext))
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
