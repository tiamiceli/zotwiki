"""Obsidian vault publisher (docs/contract.md SS6).

`render_page` / `parse_page` implement the byte-exact page grammar of
contract SS6.1-SS6.4 (restricted frontmatter subset + canonical body
blocks); `VaultPublisher` implements the SS6.5 publish semantics:
create path, idempotent re-publish, case-collision protection,
References resolution per SS6.6, `Index.md` regeneration per SS6.7 and
`Contradictions.md` appends per SS6.8.
"""
from __future__ import annotations

import datetime
import re
from collections.abc import Sequence
from pathlib import Path

from zotwiki.compiler import merge_articles
from zotwiki.errors import PageParseError, VaultError
from zotwiki.models import Article, Claim, Contradiction, Quote, Section, SourceItem
from zotwiki.zotero import ZoteroStore

__all__ = [
    "VaultPublisher",
    "render_page",
    "parse_page",
    "INDEX_FILENAME",
    "CONTRADICTIONS_FILENAME",
]

INDEX_FILENAME = "Index.md"
CONTRADICTIONS_FILENAME = "Contradictions.md"

_RESERVED_HEADINGS = ("Claims", "Links", "References")
_CITEKEY_RE = re.compile(r"[A-Za-z0-9_.:\-]+")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_QUOTE_LINE_RE = re.compile(r"  > \[@([A-Za-z0-9_.:\-]+)\] (.+)")
_LINK_LINE_RE = re.compile(r"- \[\[(.+)\]\]")
_REFERENCE_LINE_RE = re.compile(
    r"- \[@([A-Za-z0-9_.:\-]+)\] (.+) \((?:\d+|n\.d\.)\)\. \*(.+)\*\. "
    r"\[Zotero\]\(zotero://select/library/items/([^()\s]+)\)"
)


# ----- rendering (contract SS6.1-SS6.3) -----------------------------------


def _fm_quote(value: str) -> str:
    """SS6.2 quoted scalar: only ``\\`` and ``"`` are ever escaped."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _cited_citekeys(article: Article) -> list[str]:
    """Sorted union of all claim citekeys (SS6.2 frontmatter, SS6.6 refs)."""
    return sorted({ck for claim in article.claims for ck in claim.citekeys})


def _frontmatter_block(
    title: str, created: str, updated: str, citekeys: Sequence[str]
) -> str:
    lines = [
        "---",
        "zotwiki: 1",
        f"title: {_fm_quote(title)}",
        f"created: {_fm_quote(created)}",
        f"updated: {_fm_quote(updated)}",
    ]
    if citekeys:
        lines.append("citekeys:")
        lines.extend(f"  - {_fm_quote(ck)}" for ck in citekeys)
    else:
        lines.append("citekeys: []")
    lines.extend(["tags:", '  - "zotwiki"', "---"])
    return "\n".join(lines)


def _claim_suffix(citekeys: Sequence[str]) -> str:
    """SS6.3 claim-line suffix, byte exact."""
    return " [" + "; ".join("@" + ck for ck in citekeys) + "]"


def _reference_line(item: SourceItem) -> str:
    creators = ", ".join(item.creators) if item.creators else "Unknown"
    year = str(item.year) if item.year is not None else "n.d."
    return (
        f"- [@{item.citekey}] {creators} ({year}). *{item.title}*. "
        f"[Zotero](zotero://select/library/items/{item.key})"
    )


def render_page(
    article: Article,
    references: Sequence[SourceItem],
    *,
    created: str,
    updated: str,
) -> str:
    """Render an article to the canonical page bytes (contract SS6.4).

    `references` must contain exactly one SourceItem per citekey cited by
    the article's claims -- no missing, no extras, no duplicates -- else
    `VaultError`.  Pure and deterministic.
    """
    cited = _cited_citekeys(article)
    by_citekey: dict[str, SourceItem] = {}
    for item in references:
        if item.citekey in by_citekey:
            raise VaultError(f"duplicate reference for citekey {item.citekey!r}")
        by_citekey[item.citekey] = item
    missing = [ck for ck in cited if ck not in by_citekey]
    if missing:
        raise VaultError(f"references missing cited citekeys: {', '.join(missing)}")
    extra = sorted(set(by_citekey) - set(cited))
    if extra:
        raise VaultError(f"references include uncited citekeys: {', '.join(extra)}")

    blocks = [
        _frontmatter_block(article.title, created, updated, cited),
        f"# {article.title}",
        article.summary,
    ]
    for section in article.sections:
        blocks.append(f"## {section.heading}")
        blocks.append(section.body)
    blocks.append("## Claims")
    claim_lines: list[str] = []
    for claim in article.claims:
        claim_lines.append(f"- {claim.text}{_claim_suffix(claim.citekeys)}")
        claim_lines.extend(f"  > [@{q.citekey}] {q.text}" for q in claim.quotes)
    if claim_lines:
        blocks.append("\n".join(claim_lines))
    blocks.append("## Links")
    if article.links:
        blocks.append("\n".join(f"- [[{target}]]" for target in article.links))
    blocks.append("## References")
    if cited:
        blocks.append("\n".join(_reference_line(by_citekey[ck]) for ck in cited))
    return "\n\n".join(blocks) + "\n"


# ----- parsing (contract SS6.2/SS6.3, strict) ------------------------------


def _parse_quoted_scalar(s: str, key: str) -> str:
    """Parse a SS6.2 double-quoted scalar; only \\\\ and \\" escapes."""
    if len(s) < 2 or s[0] != '"':
        raise PageParseError(f"frontmatter {key!r} value must be double-quoted")
    out: list[str] = []
    j = 1
    while j < len(s):
        c = s[j]
        if c == "\\":
            if j + 1 >= len(s) or s[j + 1] not in ('\\', '"'):
                raise PageParseError(f"invalid escape in frontmatter {key!r}")
            out.append(s[j + 1])
            j += 2
        elif c == '"':
            if j != len(s) - 1:
                raise PageParseError(
                    f"trailing content after frontmatter {key!r} value"
                )
            return "".join(out)
        else:
            out.append(c)
            j += 1
    raise PageParseError(f"unterminated string in frontmatter {key!r}")


def _parse_frontmatter(lines: Sequence[str]) -> tuple[dict, int]:
    """Parse the SS6.2 frontmatter; returns (values, index past closing ---).

    Keys must appear in exactly the canonical order; anything else raises
    `PageParseError`.
    """

    def line_at(j: int, what: str) -> str:
        if j >= len(lines):
            raise PageParseError(f"unexpected end of page ({what})")
        return lines[j]

    if line_at(0, "frontmatter opening") != "---":
        raise PageParseError("page must open with a '---' frontmatter block")
    if line_at(1, "zotwiki key") != "zotwiki: 1":
        raise PageParseError("first frontmatter key must be exactly 'zotwiki: 1'")
    i = 2
    values: dict = {}
    for key in ("title", "created", "updated"):
        line = line_at(i, f"frontmatter key {key!r}")
        prefix = f"{key}: "
        if not line.startswith(prefix):
            raise PageParseError(f"expected frontmatter key {key!r}, got {line!r}")
        values[key] = _parse_quoted_scalar(line[len(prefix):], key)
        i += 1
    for key in ("created", "updated"):
        if not _DATE_RE.fullmatch(values[key]):
            raise PageParseError(f"frontmatter {key!r} must be a YYYY-MM-DD date")
    for key in ("citekeys", "tags"):
        line = line_at(i, f"frontmatter key {key!r}")
        if line == f"{key}: []":
            values[key] = []
            i += 1
        elif line == f"{key}:":
            i += 1
            items: list[str] = []
            while i < len(lines) and lines[i].startswith("  - "):
                items.append(_parse_quoted_scalar(lines[i][4:], key))
                i += 1
            if not items:
                raise PageParseError(f"frontmatter {key!r} block list is empty")
            values[key] = items
        else:
            raise PageParseError(
                f"expected frontmatter key {key!r} in canonical list form, "
                f"got {line!r}"
            )
    if line_at(i, "frontmatter closing") != "---":
        raise PageParseError("frontmatter must close with '---'")
    return values, i + 1


def _expect_blank(lines: Sequence[str], i: int, where: str) -> int:
    if i >= len(lines) or lines[i] != "":
        raise PageParseError(f"expected a blank line {where}")
    return i + 1


def _expect_line(lines: Sequence[str], i: int, expected: str) -> int:
    if i >= len(lines) or lines[i] != expected:
        got = lines[i] if i < len(lines) else "<end of page>"
        raise PageParseError(f"expected {expected!r}, got {got!r}")
    return i + 1


def _parse_claim_line(line: str) -> tuple[str, tuple[str, ...]]:
    rest = line[2:]
    pos = rest.find(" [@")
    if pos == -1:
        raise PageParseError(f"claim line missing its citekey suffix: {line!r}")
    text = rest[:pos]
    if not text or text != text.strip():
        raise PageParseError(f"malformed claim text: {line!r}")
    suffix = rest[pos + 1:]
    if not (suffix.startswith("[@") and suffix.endswith("]")):
        raise PageParseError(f"malformed claim citekey suffix: {line!r}")
    citekeys: list[str] = []
    for part in suffix[1:-1].split("; "):
        if not part.startswith("@") or not _CITEKEY_RE.fullmatch(part[1:]):
            raise PageParseError(f"malformed citekey in claim suffix: {line!r}")
        citekeys.append(part[1:])
    return text, tuple(sorted(set(citekeys)))


def _parse_quote_line(line: str) -> Quote:
    m = _QUOTE_LINE_RE.fullmatch(line)
    if m is None:
        raise PageParseError(f"malformed quote line: {line!r}")
    text = m.group(2)
    if text != text.strip():
        raise PageParseError(f"malformed quote text: {line!r}")
    return Quote(citekey=m.group(1), text=text)


def _finish_claim(text: str, citekeys: tuple[str, ...], quotes: list[Quote]) -> Claim:
    if not quotes:
        raise PageParseError(f"claim has no quote lines: {text!r}")
    ordered = tuple(sorted(quotes, key=lambda q: (q.citekey, q.text)))
    return Claim(text=text, citekeys=citekeys, quotes=ordered)


def parse_page(text: str) -> Article:
    """Strict inverse of `render_page` on the body (contract SS6.4).

    Frontmatter dates are validated but ignored; References lines are
    validated for shape only.  Any violation of the SS6.2/SS6.3 grammar
    raises `PageParseError`.
    """
    if "\r" in text:
        raise PageParseError("page must use LF line endings only")
    if not text.endswith("\n"):
        raise PageParseError("page must end with a newline")
    lines = text.split("\n")[:-1]
    for num, line in enumerate(lines, start=1):
        if line != line.rstrip():
            raise PageParseError(f"trailing whitespace on line {num}")

    fm, i = _parse_frontmatter(lines)
    title = fm["title"]

    i = _expect_blank(lines, i, "after the frontmatter")
    i = _expect_line(lines, i, f"# {title}")
    i = _expect_blank(lines, i, "after the title heading")
    if i >= len(lines) or lines[i] == "":
        raise PageParseError("missing summary block")
    summary = lines[i]
    i += 1
    i = _expect_blank(lines, i, "after the summary")

    # Content sections, up to the mandatory '## Claims' heading.
    sections: list[Section] = []
    while True:
        if i >= len(lines):
            raise PageParseError("missing '## Claims' block")
        line = lines[i]
        if line == "## Claims":
            i += 1
            break
        if not line.startswith("## "):
            raise PageParseError(
                f"expected a section heading or '## Claims', got {line!r}"
            )
        heading = line[3:]
        if not heading or heading != heading.strip():
            raise PageParseError(f"malformed section heading: {line!r}")
        if heading in _RESERVED_HEADINGS:
            raise PageParseError(f"reserved block {heading!r} out of order")
        i += 1
        i = _expect_blank(lines, i, "after a section heading")
        body_lines: list[str] = []
        while True:
            if i >= len(lines):
                raise PageParseError("unexpected end of page in a section body")
            line = lines[i]
            if line == "":
                if not body_lines:
                    raise PageParseError("section body may not start blank")
                if i + 1 >= len(lines):
                    raise PageParseError("unexpected end of page in a section body")
                nxt = lines[i + 1]
                if nxt.startswith("## "):
                    i += 1
                    break
                if nxt == "":
                    raise PageParseError("run of blank lines in a section body")
                if nxt.startswith("#"):
                    raise PageParseError(
                        f"heading line inside a section body: {nxt!r}"
                    )
                body_lines.append("")
                i += 1
                continue
            if line.startswith("#"):
                raise PageParseError(f"heading line inside a section body: {line!r}")
            body_lines.append(line)
            i += 1
        if not body_lines:
            raise PageParseError(f"section {heading!r} has an empty body")
        sections.append(Section(heading=heading, body="\n".join(body_lines)))

    # Claims block.
    i = _expect_blank(lines, i, "after '## Claims'")
    claims: list[Claim] = []
    if i >= len(lines):
        raise PageParseError("missing '## Links' block")
    if lines[i] != "## Links":
        pending: tuple[str, tuple[str, ...], list[Quote]] | None = None
        while True:
            if i >= len(lines):
                raise PageParseError("unexpected end of page in the Claims block")
            line = lines[i]
            if line == "":
                break
            if line.startswith("- "):
                if pending is not None:
                    claims.append(_finish_claim(*pending))
                text, citekeys = _parse_claim_line(line)
                pending = (text, citekeys, [])
            elif line.startswith("  > "):
                if pending is None:
                    raise PageParseError("quote line before any claim line")
                quote = _parse_quote_line(line)
                if quote.citekey not in pending[1]:
                    raise PageParseError(
                        f"quote citekey {quote.citekey!r} not among the "
                        "claim's citekeys"
                    )
                pending[2].append(quote)
            else:
                raise PageParseError(f"unexpected line in the Claims block: {line!r}")
            i += 1
        if pending is not None:
            claims.append(_finish_claim(*pending))
        if not claims:
            raise PageParseError("Claims block opened but contains no claims")
        i += 1  # the blank line that ended the block

    # Links block.
    i = _expect_line(lines, i, "## Links")
    i = _expect_blank(lines, i, "after '## Links'")
    links: list[str] = []
    if i >= len(lines):
        raise PageParseError("missing '## References' block")
    if lines[i] != "## References":
        while True:
            if i >= len(lines):
                raise PageParseError("unexpected end of page in the Links block")
            line = lines[i]
            if line == "":
                break
            m = _LINK_LINE_RE.fullmatch(line)
            if m is None:
                raise PageParseError(f"malformed link line: {line!r}")
            links.append(m.group(1))
            i += 1
        i += 1  # the blank line that ended the block

    # References block: shape-validated only, runs to end of page.
    i = _expect_line(lines, i, "## References")
    if i < len(lines):
        i = _expect_blank(lines, i, "after '## References'")
        if i >= len(lines):
            raise PageParseError("References block opened but contains no lines")
        while i < len(lines):
            line = lines[i]
            if _REFERENCE_LINE_RE.fullmatch(line) is None:
                raise PageParseError(f"malformed reference line: {line!r}")
            i += 1

    return Article(
        title=title,
        summary=summary,
        sections=tuple(sections),
        claims=tuple(claims),
        links=tuple(sorted(set(links))),
    )


# ----- VaultPublisher (contract SS6.5-SS6.8) -------------------------------


def _write_text(path: Path, text: str) -> None:
    path.write_bytes(text.encode("utf-8"))


def _read_text(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _render_index(titles: Sequence[str], *, created: str, updated: str) -> str:
    blocks = [_frontmatter_block("Index", created, updated, []), "# Index"]
    if titles:
        blocks.append("\n".join(f"- [[{title}]]" for title in titles))
    return "\n\n".join(blocks) + "\n"


class VaultPublisher:
    """Publish canonical pages into a flat Obsidian vault (contract SS6.5)."""

    def __init__(
        self, vault_dir: Path, store: ZoteroStore, *, today: str | None = None
    ) -> None:
        self._vault = Path(vault_dir)
        self._store = store
        self._today = (
            today if today is not None else datetime.date.today().isoformat()
        )
        self._vault.mkdir(parents=True, exist_ok=True)

    def page_path(self, title: str) -> Path:
        return self._vault / f"{title}.md"

    def _md_stems(self) -> list[str]:
        return [p.stem for p in self._vault.glob("*.md") if p.is_file()]

    def publish(self, article: Article) -> Path:
        title = article.title
        path = self.page_path(title)
        stems = self._md_stems()
        exists = title in stems

        if exists:
            current = _read_text(path)
            fm, _ = _parse_frontmatter(current.split("\n"))
            existing = parse_page(current)  # PageParseError -> file untouched
            merged = merge_articles(existing, article)
        else:
            merged = article

        # SS6.6: resolve the merged article's citekeys, sorted ascending.
        references = tuple(
            self._store.resolve(ck) for ck in _cited_citekeys(merged)
        )

        if exists:
            unchanged = render_page(
                merged, references, created=fm["created"], updated=fm["updated"]
            )
            if unchanged != current:
                _write_text(
                    path,
                    render_page(
                        merged,
                        references,
                        created=fm["created"],
                        updated=self._today,
                    ),
                )
        else:
            for stem in stems:
                if stem.casefold() == title.casefold():
                    raise VaultError(
                        f"case collision: {stem + '.md'!r} already exists "
                        f"for title {title!r}"
                    )
            _write_text(
                path,
                render_page(
                    article, references, created=self._today, updated=self._today
                ),
            )

        self._regenerate_index()
        return path

    def publish_contradictions(
        self, page_title: str, contradictions: Sequence[Contradiction]
    ) -> Path:
        items = tuple(contradictions)
        if not items:
            raise ValueError(
                "publish_contradictions requires at least one contradiction"
            )
        path = self._vault / CONTRADICTIONS_FILENAME
        pair_lines: list[str] = []
        for c in items:
            pair_lines.append(f"- EXISTING: {c.existing_claim}")
            pair_lines.append(f"- NEW: {c.new_claim}{_claim_suffix(c.citekeys)}")
        block = f"## {page_title} ({self._today})\n\n" + "\n".join(pair_lines)
        if path.is_file():
            current = _read_text(path)
            fm, _ = _parse_frontmatter(current.split("\n"))
            head, sep, body = current.partition("\n---\n\n")
            if not sep:
                raise PageParseError(
                    f"{CONTRADICTIONS_FILENAME} has no frontmatter/body boundary"
                )
            new_text = (
                _frontmatter_block("Contradictions", fm["created"], self._today, [])
                + "\n\n"
                + body[:-1]
                + "\n\n"
                + block
                + "\n"
            )
        else:
            new_text = (
                _frontmatter_block("Contradictions", self._today, self._today, [])
                + "\n\n# Contradictions\n\n"
                + block
                + "\n"
            )
        _write_text(path, new_text)
        return path

    def _regenerate_index(self) -> None:
        """SS6.7: rewrite Index.md only when its rendering would change."""
        index_path = self._vault / INDEX_FILENAME
        titles = sorted(
            p.stem
            for p in self._vault.glob("*.md")
            if p.is_file() and p.name not in (INDEX_FILENAME, CONTRADICTIONS_FILENAME)
        )
        if index_path.is_file():
            current = _read_text(index_path)
            fm, _ = _parse_frontmatter(current.split("\n"))
            unchanged = _render_index(
                titles, created=fm["created"], updated=fm["updated"]
            )
            if unchanged == current:
                return
            _write_text(
                index_path,
                _render_index(titles, created=fm["created"], updated=self._today),
            )
        else:
            _write_text(
                index_path,
                _render_index(titles, created=self._today, updated=self._today),
            )
