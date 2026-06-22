"""LLM boundary: `LLMClient` protocol and the compiled-article JSON schema.

Implements docs/contract.md SS5: the schema of SS5.2, the parsing algorithm
of SS5.3, the whitespace normalization of SS5.4, and the serialization of
SS5.5 — stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol, runtime_checkable

from zotwiki.errors import ArticleSchemaError, ZotWikiError
from zotwiki.models import Article, Claim, Contradiction, Quote, Section

__all__ = [
    "LLMClient",
    "ClaudeCodeLLMClient",
    "ARTICLE_SCHEMA",
    "parse_article_json",
    "article_to_json_dict",
]


@runtime_checkable
class LLMClient(Protocol):
    """One method, one string in, one string out (contract SS5.1)."""

    def complete(self, prompt: str) -> str: ...


# Loose JSON-Schema shape hint for the compiled-article JSON (contract SS5.6).
# A decoding aid only -- `parse_article_json` remains the sole authoritative
# validator/canonicalizer (Ruling 9; REQ-010/011 unchanged), so this echoes the
# top-level required keys and the claim/quote/section/link shape, not the full
# validator's rules.
ARTICLE_SCHEMA: dict = {
    "type": "object",
    "additionalProperties": True,
    "required": ["title", "summary", "sections", "claims", "links"],
    "properties": {
        "title": {"type": "string"},
        "summary": {"type": "string"},
        "sections": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["heading", "body"],
                "properties": {
                    "heading": {"type": "string"},
                    "body": {"type": "string"},
                },
            },
        },
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["text", "citekeys", "quotes"],
                "properties": {
                    "text": {"type": "string"},
                    "citekeys": {"type": "array", "items": {"type": "string"}},
                    "quotes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "required": ["citekey", "text"],
                            "properties": {
                                "citekey": {"type": "string"},
                                "text": {"type": "string"},
                            },
                        },
                    },
                },
            },
        },
        "links": {"type": "array", "items": {"type": "string"}},
    },
}

# Diagnostic fields recorded in a failure artifact when present (contract SS5.6).
_DIAGNOSTIC_FIELDS = (
    "subtype", "errors", "stop_reason",
    "session_id", "usage", "num_turns", "total_cost_usd",
)


class ClaudeCodeLLMClient:
    """Production `LLMClient`: shells out to the `claude` CLI via subprocess,
    constraining the model to schema-shaped JSON via structured output
    (contract SS5.6, Ruling 9).

    Never imported by the injected-fake suite (contract SS5.1); its only direct
    test drives a fake `claude` binary on PATH.
    """

    def __init__(
        self,
        output_schema: dict | None = None,
        *,
        dump_dir: Path | None = None,
    ) -> None:
        self._output_schema = output_schema
        self._dump_dir = Path(dump_dir) if dump_dir is not None else None

    def complete(self, prompt: str) -> str:
        argv = [
            "claude", "--print",
            "--output-format", "json",
            "--exclude-dynamic-system-prompt-sections",
        ]
        if self._output_schema is not None:
            argv += ["--json-schema", json.dumps(self._output_schema)]

        # Defense in depth (SS5.6): a nested invocation must not inherit the
        # session's conversational context. Strip CLAUDECODE and every
        # CLAUDE_CODE_* key; preserve everything else (PATH, HOME, OAuth, ...).
        env = {
            key: value
            for key, value in os.environ.items()
            if key != "CLAUDECODE" and not key.startswith("CLAUDE_CODE_")
        }

        try:
            result = subprocess.run(
                argv,
                input=prompt.encode("utf-8"),
                capture_output=True,
                env=env,
            )
        except FileNotFoundError:
            # No subprocess ran, no artifact (SS5.6).
            raise ZotWikiError("claude not found") from None

        stdout = result.stdout.decode("utf-8", errors="replace")
        stderr = result.stderr.decode("utf-8", errors="replace")

        envelope: dict | None = None
        try:
            parsed = json.loads(stdout)
        except ValueError:
            parsed = None
        if isinstance(parsed, dict):
            envelope = parsed

        # Success: exit 0, a JSON object, subtype "success", field present.
        if result.returncode != 0:
            reason = f"claude exited {result.returncode}"
        elif envelope is None:
            reason = "claude output was not a JSON object"
        elif envelope.get("subtype") != "success":
            reason = f"subtype {envelope.get('subtype')!r}"
        else:
            field = "structured_output" if self._output_schema is not None else "result"
            if field not in envelope:
                reason = f"missing {field!r} field"
            elif self._output_schema is not None:
                return json.dumps(envelope[field])
            else:
                return envelope[field]

        # Failure: fail closed, dump verbatim, raise a single-line message.
        artifact = self._write_failure_artifact(
            argv, prompt, stdout, stderr, result.returncode, envelope
        )
        subtype = envelope.get("subtype") if envelope is not None else None
        if isinstance(subtype, str) and "subtype" not in reason:
            reason = f"subtype {subtype!r}, {reason}"
        raise ZotWikiError(
            f"structured-output LLM failure ({reason}); failure artifact: {artifact}"
        )

    def _write_failure_artifact(
        self,
        argv: list[str],
        prompt: str,
        stdout: str,
        stderr: str,
        returncode: int,
        envelope: dict | None,
    ) -> Path:
        dump_dir = self._dump_dir or (Path.home() / ".zotwiki" / "failures")
        dump_dir.mkdir(parents=True, exist_ok=True)

        base = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%f")
        path = dump_dir / f"{base}.txt"
        suffix = 1
        while path.exists():
            path = dump_dir / f"{base}_{suffix}.txt"
            suffix += 1

        sections = [
            "=== argv ===",
            json.dumps(argv),
            "",
            "=== prompt (stdin) ===",
            prompt,
            "",
            "=== exit code ===",
            str(returncode),
            "",
            "=== stdout (verbatim envelope) ===",
            stdout,
            "",
            "=== stderr ===",
            stderr,
            "",
            "=== diagnostics ===",
        ]
        if envelope is not None:
            for name in _DIAGNOSTIC_FIELDS:
                if name in envelope:
                    value = envelope[name]
                    rendered = value if isinstance(value, str) else json.dumps(value)
                    sections.append(f"{name}: {rendered}")
        path.write_text("\n".join(sections) + "\n", encoding="utf-8")
        return path


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
