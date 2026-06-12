"""LLM boundary: `LLMClient` protocol and the compiled-article JSON schema.

Implements docs/contract.md SS5: the schema of SS5.2, the parsing algorithm
of SS5.3, the whitespace normalization of SS5.4, and the serialization of
SS5.5 — stdlib only.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Protocol, runtime_checkable

from zotwiki.errors import ArticleSchemaError
from zotwiki.models import Article, Claim, Contradiction, Quote, Section

__all__ = [
    "LLMClient",
    "AnthropicLLMClient",
    "parse_article_json",
    "article_to_json_dict",
]


@runtime_checkable
class LLMClient(Protocol):
    """One method, one string in, one string out (contract SS5.1)."""

    def complete(self, prompt: str) -> str: ...


_ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_API_VERSION = "2023-06-01"
_ANTHROPIC_MAX_TOKENS = 16000


class AnthropicLLMClient:
    """Production `LLMClient`: stdlib-urllib client for the Anthropic
    Messages API (contract SS5.1).

    Never imported by the hermetic test suite.  No model id is hardcoded
    anywhere -- the CLI passes `ZOTWIKI_MODEL` from the environment (SS9.4).
    """

    def __init__(self, api_key: str, model: str) -> None:
        self._api_key = api_key
        self._model = model

    def complete(self, prompt: str) -> str:
        body = json.dumps(
            {
                "model": self._model,
                "max_tokens": _ANTHROPIC_MAX_TOKENS,
                "messages": [{"role": "user", "content": prompt}],
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            _ANTHROPIC_MESSAGES_URL,
            data=body,
            headers={
                "x-api-key": self._api_key,
                "anthropic-version": _ANTHROPIC_API_VERSION,
                "content-type": "application/json",
            },
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return "".join(
            block.get("text", "")
            for block in payload.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        )


_REQUIRED_KEYS = ("title", "summary", "sections", "claims", "links")
_OPTIONAL_KEYS = ("contradictions",)
# Contract SS5.2: the safe-filename charset for titles and link targets.
_TITLE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ,()'\-]*$")
_CITEKEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]+$")
_RESERVED_HEADINGS = frozenset({"Claims", "Links", "References"})
# Contract SS6.1 DECISION: reserved page names are forbidden article titles.
_RESERVED_TITLES = frozenset({"Index", "Contradictions"})
_WS_RUN = re.compile(r"\s+")


def _fail(path: str, why: str) -> None:
    raise ArticleSchemaError(f"{path}: {why}")


def _collapse(text: str) -> str:
    """SS5.4 single-line rule: strip; collapse whitespace runs to one space."""
    return _WS_RUN.sub(" ", text).strip()


def _normalize_body(body: str) -> str:
    """SS5.4 body rule: strip trailing whitespace per line; drop leading and
    trailing blank lines; collapse runs of >= 2 blank lines to one."""
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


def _str_at(value: object, path: str) -> str:
    if not isinstance(value, str):
        _fail(path, "must be a string")
    return value


def _inline(value: object, path: str) -> str:
    """A required single-line text field: validate, then SS5.4-normalize."""
    raw = _str_at(value, path)
    if "\n" in raw or "\r" in raw:
        _fail(path, "must be a single line")
    collapsed = _collapse(raw)
    if not collapsed:
        _fail(path, "must be non-empty")
    return collapsed


def _claim_text(value: object, path: str) -> str:
    text = _inline(value, path)
    if " [@" in text:
        _fail(path, 'must not contain the substring " [@"')
    if text[0] in "->":
        _fail(path, "must not start with '-' or '>'")
    return text


def _title_like(value: object, path: str) -> str:
    raw = _str_at(value, path)
    if not raw:
        _fail(path, "must be non-empty")
    if len(raw) > 120:
        _fail(path, "must be at most 120 characters")
    if not _TITLE_RE.fullmatch(raw):
        _fail(path, "must match the safe-filename charset "
                    "^[A-Za-z0-9][A-Za-z0-9 ,()'\\-]*$")
    if raw.endswith(" "):
        _fail(path, "must not have a trailing space")
    return _collapse(raw)


def _citekeys(value: object, path: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail(path, "must be an array")
    if not value:
        _fail(path, "must contain at least one citekey")
    for j, citekey in enumerate(value):
        if not isinstance(citekey, str) or not _CITEKEY_RE.fullmatch(citekey):
            _fail(f"{path}[{j}]", "must be a string matching ^[A-Za-z0-9_.:\\-]+$")
    if len(set(value)) != len(value):
        _fail(path, "must not contain duplicates")
    return tuple(sorted(value))


def _exact_keys(obj: object, keys: tuple[str, ...], path: str) -> dict:
    if not isinstance(obj, dict):
        _fail(path, "must be an object")
    for key in obj:
        if key not in keys:
            _fail(f"{path}.{key}", "unknown key")
    for key in keys:
        if key not in obj:
            _fail(f"{path}.{key}", "missing key")
    return obj


def _sections(value: object) -> tuple[Section, ...]:
    if not isinstance(value, list):
        _fail("sections", "must be an array")
    out: list[Section] = []
    seen: set[str] = set()
    for i, entry in enumerate(value):
        path = f"sections[{i}]"
        section = _exact_keys(entry, ("heading", "body"), path)
        heading = _inline(section["heading"], f"{path}.heading")
        if heading in _RESERVED_HEADINGS:
            _fail(f"{path}.heading", "is a reserved heading")
        if heading in seen:
            _fail(f"{path}.heading", "duplicates an earlier section heading")
        seen.add(heading)
        raw_body = _str_at(section["body"], f"{path}.body")
        if not raw_body:
            _fail(f"{path}.body", "must be non-empty")
        body = _normalize_body(raw_body)
        if not body:
            _fail(f"{path}.body", "must be non-empty after normalization")
        for line in body.split("\n"):
            if line.startswith("#"):
                _fail(f"{path}.body", "no body line may start with '#'")
        out.append(Section(heading=heading, body=body))
    return tuple(out)


def _claims(value: object) -> tuple[Claim, ...]:
    if not isinstance(value, list):
        _fail("claims", "must be an array")
    out: list[Claim] = []
    for i, entry in enumerate(value):
        path = f"claims[{i}]"
        claim = _exact_keys(entry, ("text", "citekeys", "quotes"), path)
        text = _claim_text(claim["text"], f"{path}.text")
        citekeys = _citekeys(claim["citekeys"], f"{path}.citekeys")
        raw_quotes = claim["quotes"]
        if not isinstance(raw_quotes, list):
            _fail(f"{path}.quotes", "must be an array")
        if not raw_quotes:
            _fail(f"{path}.quotes", "must contain at least one quote")
        members = set(citekeys)
        quotes: list[Quote] = []
        for j, quote_entry in enumerate(raw_quotes):
            qpath = f"{path}.quotes[{j}]"
            quote = _exact_keys(quote_entry, ("citekey", "text"), qpath)
            citekey = _str_at(quote["citekey"], f"{qpath}.citekey")
            if citekey not in members:
                _fail(f"{qpath}.citekey", "is not a member of the claim's citekeys")
            quotes.append(Quote(citekey=citekey, text=_inline(quote["text"], f"{qpath}.text")))
        quotes.sort(key=lambda q: (q.citekey, q.text))
        out.append(Claim(text=text, citekeys=citekeys, quotes=tuple(quotes)))
    return tuple(out)


def _links(value: object) -> tuple[str, ...]:
    if not isinstance(value, list):
        _fail("links", "must be an array")
    out: set[str] = set()
    for i, link in enumerate(value):
        out.add(_title_like(link, f"links[{i}]"))
    return tuple(sorted(out))


def _contradictions(value: object) -> tuple[Contradiction, ...]:
    if not isinstance(value, list):
        _fail("contradictions", "must be an array")
    out: list[Contradiction] = []
    for i, entry in enumerate(value):
        path = f"contradictions[{i}]"
        contradiction = _exact_keys(
            entry, ("existing_claim", "new_claim", "citekeys"), path
        )
        out.append(
            Contradiction(
                existing_claim=_claim_text(
                    contradiction["existing_claim"], f"{path}.existing_claim"
                ),
                new_claim=_claim_text(contradiction["new_claim"], f"{path}.new_claim"),
                citekeys=_citekeys(contradiction["citekeys"], f"{path}.citekeys"),
            )
        )
    return tuple(out)


def _strip_fence(text: str) -> str:
    """SS5.3 step 1: strip outer whitespace; remove one outer code fence."""
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.split("\n")
        stripped = "\n".join(lines[1:-1])
    return stripped


def parse_article_json(text: str) -> tuple[Article, tuple[Contradiction, ...]]:
    """Parse and validate compiled-article JSON (contract SS5.2-SS5.4).

    Returns a canonical frozen `Article` plus the parsed contradictions;
    any violation raises `ArticleSchemaError` naming the offending JSON path.
    """
    try:
        obj = json.loads(_strip_fence(text))
    except ValueError as exc:
        raise ArticleSchemaError(f"$: not a JSON object ({exc})") from exc
    if not isinstance(obj, dict):
        _fail("$", "top level must be a JSON object")
    known = set(_REQUIRED_KEYS) | set(_OPTIONAL_KEYS)
    for key in obj:
        if key not in known:
            _fail(str(key), "unknown top-level key")
    for key in _REQUIRED_KEYS:
        if key not in obj:
            _fail(key, "missing required key")

    title = _title_like(obj["title"], "title")
    if title in _RESERVED_TITLES:
        _fail("title", "is a reserved page name")
    summary = _collapse(_str_at(obj["summary"], "summary"))
    if not summary:
        _fail("summary", "must be non-empty")

    article = Article(
        title=title,
        summary=summary,
        sections=_sections(obj["sections"]),
        claims=_claims(obj["claims"]),
        links=_links(obj["links"]),
    )
    return article, _contradictions(obj.get("contradictions", []))


def article_to_json_dict(article: Article) -> dict:
    """Serialize a canonical Article to the SS5.2 JSON shape (contract SS5.5).

    Exactly the five required keys; round-trip law:
    `parse_article_json(json.dumps(article_to_json_dict(a)))[0] == a`.
    """
    return {
        "title": article.title,
        "summary": article.summary,
        "sections": [
            {"heading": section.heading, "body": section.body}
            for section in article.sections
        ],
        "claims": [
            {
                "text": claim.text,
                "citekeys": list(claim.citekeys),
                "quotes": [
                    {"citekey": quote.citekey, "text": quote.text}
                    for quote in claim.quotes
                ],
            }
            for claim in article.claims
        ],
        "links": list(article.links),
    }
