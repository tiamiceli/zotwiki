"""Question answering over a ZotWiki vault (contract SS9.5).

`ask` reads every entity page, sends one prompt (containing the question and
the full text of every page) to the LLM, and validates the returned answer
JSON against both the SS9.5 schema and the vault itself: each cited page must
be an existing entity page and each cited citekey a member of that page's
frontmatter `citekeys`.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from zotwiki.errors import ArticleSchemaError, PageParseError, VaultError
from zotwiki.llm import LLMClient
from zotwiki.publisher import (
    CONTRADICTIONS_FILENAME,
    INDEX_FILENAME,
    _parse_frontmatter,
)

__all__ = ["Answer", "SourceRef", "ask"]


def _strip_fence(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:-1])
    return stripped

_SPECIAL_FILENAMES = (INDEX_FILENAME, CONTRADICTIONS_FILENAME)


@dataclass(frozen=True)
class SourceRef:
    page: str                       # page title (no ".md")
    citekeys: tuple[str, ...]       # sorted, len >= 1


@dataclass(frozen=True)
class Answer:
    text: str
    sources: tuple[SourceRef, ...]


def _read_entity_pages(vault: Path) -> dict[str, str]:
    """{title: full page text} for every entity page in the vault root."""
    pages: dict[str, str] = {}
    for path in sorted(vault.glob("*.md")):
        if path.name in _SPECIAL_FILENAMES or not path.is_file():
            continue
        pages[path.stem] = path.read_text(encoding="utf-8")
    return pages


def _build_prompt(question: str, pages: dict[str, str]) -> str:
    parts = [
        "You answer questions using only the wiki pages below.",
        f"Question: {question}",
        "",
        "Wiki pages:",
    ]
    for title in sorted(pages):
        parts.append(f"=== {title} ===")
        parts.append(pages[title])
    parts.append(
        "Return exactly one JSON object of the form "
        '{"answer": "...", "sources": [{"page": "...", '
        '"citekeys": ["..."]}]} and nothing else. Every cited page must be '
        "one of the wiki pages above and every citekey must appear in that "
        "page's frontmatter citekeys."
    )
    return "\n".join(parts)


def _fail(why: str) -> None:
    raise ArticleSchemaError(f"answer JSON: {why}")


def _parse_answer_json(raw: str) -> tuple[str, list[tuple[str, tuple[str, ...]]]]:
    """Validate the SS9.5 answer JSON shape; returns (text, [(page, cks)])."""
    try:
        obj = json.loads(_strip_fence(raw))
    except ValueError as exc:
        _fail(f"not valid JSON ({exc})")
    if not isinstance(obj, dict):
        _fail("top level must be a JSON object")
    if set(obj) != {"answer", "sources"}:
        _fail("top level must have exactly the keys 'answer' and 'sources'")
    answer = obj["answer"]
    if not isinstance(answer, str) or not answer:
        _fail("'answer' must be a non-empty string")
    sources = obj["sources"]
    if not isinstance(sources, list):
        _fail("'sources' must be an array")
    parsed: list[tuple[str, tuple[str, ...]]] = []
    for i, entry in enumerate(sources):
        path = f"sources[{i}]"
        if not isinstance(entry, dict):
            _fail(f"{path} must be an object")
        if set(entry) != {"page", "citekeys"}:
            _fail(f"{path} must have exactly the keys 'page' and 'citekeys'")
        page = entry["page"]
        if not isinstance(page, str) or not page:
            _fail(f"{path}.page must be a non-empty string")
        citekeys = entry["citekeys"]
        if not isinstance(citekeys, list) or len(citekeys) < 1:
            _fail(f"{path}.citekeys must be an array of length >= 1")
        for j, ck in enumerate(citekeys):
            if not isinstance(ck, str) or not ck:
                _fail(f"{path}.citekeys[{j}] must be a non-empty string")
        parsed.append((page, tuple(citekeys)))
    return answer, parsed


def _frontmatter_citekeys(page_text: str) -> set[str]:
    try:
        values, _ = _parse_frontmatter(page_text.split("\n"))
    except PageParseError as exc:
        _fail(f"cited page has unparseable frontmatter ({exc})")
    return set(values["citekeys"])


def ask(vault_dir: Path, question: str, llm: LLMClient) -> Answer:
    """Answer `question` from the vault's entity pages (contract SS9.5)."""
    vault = Path(vault_dir)
    if not vault.is_dir():
        raise VaultError(f"vault directory not found: {vault}")
    pages = _read_entity_pages(vault)
    if not pages:
        raise VaultError(f"vault has no entity pages: {vault}")

    raw = llm.complete(_build_prompt(question, pages))
    text, parsed_sources = _parse_answer_json(raw)

    refs: list[SourceRef] = []
    for page, citekeys in parsed_sources:
        if page not in pages:
            _fail(f"cited page {page!r} is not an entity page in the vault")
        known = _frontmatter_citekeys(pages[page])
        for ck in citekeys:
            if ck not in known:
                _fail(
                    f"citekey {ck!r} is not in the frontmatter citekeys "
                    f"of page {page!r}"
                )
        refs.append(SourceRef(page=page, citekeys=tuple(sorted(citekeys))))
    return Answer(text=text, sources=tuple(refs))
