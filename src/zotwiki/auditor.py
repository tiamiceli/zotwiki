"""Vault auditor (docs/contract.md SS8).

Runs the seven SS8.1 checks over every ``*.md`` file directly in the vault
root.  ``Index.md`` and ``Contradictions.md`` are special pages; all other
``.md`` files are entity pages.  Entity pages are parsed with the public
``parse_page`` (SS6); special pages undergo only frontmatter parsing, and
``Contradictions.md`` additionally has its ``[[...]]`` links checked.

Hard failures (SS8.3): a missing/non-directory vault raises ``VaultError``;
``ZoteroUnavailableError`` from the store propagates.  Everything else is a
``Violation``, never an exception.  Reports are deterministic: violations
are deduplicated and sorted by ``(page, code, detail)``.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from zotwiki.errors import (
    PageParseError,
    VaultError,
    ZoteroError,
    ZoteroUnavailableError,
)
from zotwiki.models import SourceItem, normalize_text
from zotwiki.publisher import CONTRADICTIONS_FILENAME, INDEX_FILENAME, parse_page
from zotwiki.zotero import ZoteroStore

__all__ = ["Auditor", "AuditReport", "Violation", "AUDIT_CODES"]

AUDIT_CODES = (
    "CITEKEY_UNRESOLVED",
    "QUOTE_NOT_FOUND",
    "BROKEN_LINK",
    "ORPHAN_PAGE",
    "INDEX_STALE",
    "PAGE_UNPARSEABLE",
    "REFERENCE_MISSING",
)


@dataclass(frozen=True)
class Violation:
    code: str        # member of AUDIT_CODES
    page: str        # filename, e.g. "Transformer.md"
    detail: str      # human-readable specifics (citekey, target, quote prefix...)


@dataclass(frozen=True)
class AuditReport:
    violations: tuple[Violation, ...]   # sorted by (page, code, detail)
    pages_checked: int                  # entity pages successfully parsed

    @property
    def ok(self) -> bool:
        return self.violations == ()


_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_WIKILINK_RE = re.compile(r"\[\[(.*?)\]\]")
_INDEX_BULLET_RE = re.compile(r"- \[\[(.+)\]\]")
_REFERENCE_CITEKEY_RE = re.compile(r"- \[@([A-Za-z0-9_.:\-]+)\] ")


# ----- SS6.2 frontmatter (auditor's own strict reader) ---------------------


def _parse_quoted_scalar(s: str, key: str) -> str:
    """Parse a SS6.2 double-quoted scalar; only ``\\\\`` and ``\\"`` escapes."""
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


def _parse_frontmatter(lines: list[str]) -> dict:
    """Strict SS6.2 frontmatter: exact keys in exact order, nothing else."""

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
    return values


# ----- raw-text extraction helpers -----------------------------------------


def _reference_citekeys(text: str) -> set[str]:
    """Citekeys of the References block of an already-parsed entity page."""
    lines = text.split("\n")
    try:
        idx = len(lines) - 1 - lines[::-1].index("## References")
    except ValueError:  # pragma: no cover - parse_page guarantees the block
        return set()
    cks: set[str] = set()
    for line in lines[idx + 1:]:
        m = _REFERENCE_CITEKEY_RE.match(line)
        if m is not None:
            cks.add(m.group(1))
    return cks


def _link_violations(page: str, text: str, md_names: set[str]) -> set[Violation]:
    """SS8.1 check 4: every ``[[...]]`` occurrence anywhere in the text."""
    out: set[Violation] = set()
    for m in _WIKILINK_RE.finditer(text):
        target = m.group(1).split("|", 1)[0]
        if "#" in target or f"{target}.md" not in md_names:
            out.add(Violation("BROKEN_LINK", page, target))
    return out


# ----- the auditor -----------------------------------------------------------


class Auditor:
    """Run the seven contract SS8.1 checks over a flat vault."""

    def __init__(self, vault_dir: Path, store: ZoteroStore) -> None:
        self._vault = Path(vault_dir)
        self._store = store

    def audit(self) -> AuditReport:
        if not self._vault.is_dir():
            raise VaultError(f"vault directory does not exist: {self._vault}")

        md_paths = sorted(
            (p for p in self._vault.glob("*.md") if p.is_file()),
            key=lambda p: p.name,
        )
        md_names = {p.name for p in md_paths}

        violations: set[Violation] = set()
        pages_checked = 0
        entity_names: list[str] = []
        resolve_cache: dict[str, SourceItem | None] = {}
        fulltext_cache: dict[str, str | None] = {}

        for path in md_paths:
            name = path.name
            if name in (INDEX_FILENAME, CONTRADICTIONS_FILENAME):
                continue
            entity_names.append(name)
            try:
                text = path.read_bytes().decode("utf-8")
                article = parse_page(text)
                frontmatter = _parse_frontmatter(text.split("\n"))
            except (PageParseError, UnicodeDecodeError) as exc:
                # Check 1; unparseable pages skip checks 2-4 and 7 but still
                # count for checks 5/6 by filename.
                violations.add(Violation("PAGE_UNPARSEABLE", name, str(exc)))
                continue
            pages_checked += 1

            claim_citekeys = {
                ck for claim in article.claims for ck in claim.citekeys
            }
            reference_citekeys = _reference_citekeys(text)
            frontmatter_citekeys = set(frontmatter["citekeys"])

            # Check 2: one violation per distinct (page, citekey) among the
            # citekeys in claims, quotes, and the References block.
            for ck in sorted(claim_citekeys | reference_citekeys):
                if self._resolve(ck, resolve_cache) is None:
                    violations.add(Violation("CITEKEY_UNRESOLVED", name, ck))

            # Check 3: quote verification under SS2.1 normalization.
            for claim in article.claims:
                for quote in claim.quotes:
                    item = resolve_cache.get(quote.citekey)
                    if item is None:
                        continue  # check 2 already fired for this citekey
                    detail = f"{quote.citekey}: {quote.text[:60]}"
                    if not item.has_fulltext:
                        violations.add(Violation("QUOTE_NOT_FOUND", name, detail))
                        continue
                    fulltext = self._fetch_fulltext(item.key, fulltext_cache)
                    if fulltext is None or (
                        normalize_text(quote.text)
                        not in normalize_text(fulltext)
                    ):
                        violations.add(Violation("QUOTE_NOT_FOUND", name, detail))

            # Check 4: wiki-links anywhere in the page text.
            violations.update(_link_violations(name, text, md_names))

            # Check 7: the three citekey sets must all be equal.
            if not (claim_citekeys == reference_citekeys == frontmatter_citekeys):
                union = claim_citekeys | reference_citekeys | frontmatter_citekeys
                common = claim_citekeys & reference_citekeys & frontmatter_citekeys
                violations.add(
                    Violation(
                        "REFERENCE_MISSING", name, ", ".join(sorted(union - common))
                    )
                )

        violations |= self._audit_index(md_names, entity_names)
        violations |= self._audit_contradictions(md_names)

        ordered = tuple(
            sorted(violations, key=lambda v: (v.page, v.code, v.detail))
        )
        return AuditReport(violations=ordered, pages_checked=pages_checked)

    # ----- special pages ---------------------------------------------------

    def _audit_index(
        self, md_names: set[str], entity_names: list[str]
    ) -> set[Violation]:
        """Checks 1 (frontmatter), 5 and 6 for Index.md."""
        out: set[Violation] = set()
        index_path = self._vault / INDEX_FILENAME
        if INDEX_FILENAME not in md_names:
            # Check 5: a missing Index.md orphans every entity page.
            for name in entity_names:
                out.add(
                    Violation(
                        "ORPHAN_PAGE", name, f"{INDEX_FILENAME} is missing"
                    )
                )
            return out

        try:
            text = index_path.read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            out.add(Violation("PAGE_UNPARSEABLE", INDEX_FILENAME, str(exc)))
            return out
        try:
            _parse_frontmatter(text.split("\n"))
        except PageParseError as exc:
            out.add(Violation("PAGE_UNPARSEABLE", INDEX_FILENAME, str(exc)))

        targets = [
            m.group(1)
            for line in text.split("\n")
            if (m := _INDEX_BULLET_RE.fullmatch(line)) is not None
        ]
        # Check 6: index bullets whose target file does not exist.
        for target in targets:
            if f"{target}.md" not in md_names:
                out.add(Violation("INDEX_STALE", INDEX_FILENAME, target))
        # Check 5: entity pages (by filename) not listed in Index.md.
        listed = set(targets)
        for name in entity_names:
            if name[: -len(".md")] not in listed:
                out.add(
                    Violation(
                        "ORPHAN_PAGE", name, f"not listed in {INDEX_FILENAME}"
                    )
                )
        return out

    def _audit_contradictions(self, md_names: set[str]) -> set[Violation]:
        """Checks 1 (frontmatter) and 4 for Contradictions.md; its claims
        are intentionally conflicting and exempt from checks 2/3/7."""
        out: set[Violation] = set()
        if CONTRADICTIONS_FILENAME not in md_names:
            return out
        path = self._vault / CONTRADICTIONS_FILENAME
        try:
            text = path.read_bytes().decode("utf-8")
            _parse_frontmatter(text.split("\n"))
        except (PageParseError, OSError, UnicodeDecodeError) as exc:
            out.add(Violation("PAGE_UNPARSEABLE", CONTRADICTIONS_FILENAME, str(exc)))
            return out
        out |= _link_violations(CONTRADICTIONS_FILENAME, text, md_names)
        return out

    # ----- store access (caches live per audit() run) -----------------------

    def _resolve(
        self, citekey: str, cache: dict[str, SourceItem | None]
    ) -> SourceItem | None:
        if citekey not in cache:
            try:
                cache[citekey] = self._store.resolve(citekey)
            except ZoteroUnavailableError:
                raise
            except ZoteroError:
                cache[citekey] = None
        return cache[citekey]

    def _fetch_fulltext(
        self, key: str, cache: dict[str, str | None]
    ) -> str | None:
        if key not in cache:
            try:
                cache[key] = self._store.fulltext(key)
            except ZoteroUnavailableError:
                raise
            except ZoteroError:
                cache[key] = None
        return cache[key]
