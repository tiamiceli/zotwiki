"""M6 test helpers: CLI-level oracles and offline fakes.

Everything here is derived from docs/contract.md alone:

  - ERROR_LINE_RE / assert_single_error_line
                       SS9.3: every nonzero exit except audit-violations
                       prints exactly one `error: {message}\\n` line to
                       stderr (and nothing extra to stdout).
  - expected_citekey   independent re-implementation of the SS3.3 citekey
                       generation rule (the REQ-032 stdout oracle).
  - ask_payload / expected_ask_stdout
                       the SS9.5 answer-JSON shape and the SS9.2 `ask`
                       stdout format (`{answer}\\n\\nSources:\\n` then one
                       `- [[page]] [@citekey]` line per pair).
  - assert_compiled_line
                       the SS9.2 `compiled\\t{title}\\t{path}` line.
  - InMemoryStore      a pure in-memory ZoteroStore (contract SS3 semantics,
                       structural protocol match, no sockets) that records
                       every call and supports per-method exception
                       injection -- the REQ-037/REQ-038 instrument.
  - install_network_guard
                       monkeypatch seam that fails the test on ANY outgoing
                       socket connection attempt (REQ-038's no-network law).
  - write_static_vault a hand-rendered contract-SS6 single-page vault built
                       without any zotwiki publisher call (for tests whose
                       store must be broken from the very first request).

Only frozen, green surfaces are imported at module scope (zotwiki.errors and
zotwiki.models from M1, earlier helper modules); zotwiki.cli / zotwiki.ask
are imported by the test modules themselves via their module-scoped autouse
fixtures so that their absence reads as a per-test contract failure rather
than a collection error.
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path

from zotwiki.errors import (
    CitekeyNotFoundError,
    FulltextNotFoundError,
    ItemNotFoundError,
)
from zotwiki.models import SourceItem

from m2_helpers import rand_key, rand_word
from m4_helpers import TODAY, build_article, fulltext_containing, render_page_with
from m5_helpers import index_oracle

# ----- SS9.3 stderr / stdout discipline -------------------------------------

ERROR_LINE_RE = re.compile(r"error: [^\n]+\n")


def assert_single_error_line(stderr: str) -> None:
    """SS9.3: exactly one `error: {message}\\n` line, nothing else."""
    assert ERROR_LINE_RE.fullmatch(stderr), (
        f"stderr must be exactly one 'error: ...' line, got {stderr!r}"
    )


def assert_compiled_line(line: str, *, title: str, vault) -> None:
    """SS9.2 step 4: `compiled\\t{title}\\t{path}\\n` where {path} is the
    published page path `{vault}/{title}.md`."""
    assert line.endswith("\n"), f"missing trailing newline: {line!r}"
    fields = line[:-1].split("\t")
    assert len(fields) == 3, f"expected 3 tab-separated fields: {line!r}"
    assert fields[0] == "compiled"
    assert fields[1] == title
    expected = Path(vault) / f"{title}.md"
    assert Path(fields[2]).resolve() == expected.resolve(), (
        f"path field {fields[2]!r} is not {expected}"
    )


# ----- independent SS3.3 citekey oracle --------------------------------------

CITEKEY_STOPWORDS = {"a", "an", "the", "on", "of", "in", "and", "for", "to"}


def _clean(token: str) -> str:
    return re.sub(r"[^a-z0-9]", "", token.lower())


def expected_citekey(*, title: str, creators=(), year=None) -> str:
    """Contract SS3.3 citekey generation, re-implemented from the doc."""
    author = "anon"
    if creators:
        tokens = creators[0].split()
        cleaned = _clean(tokens[-1]) if tokens else ""
        if cleaned:
            author = cleaned
    year_part = str(year) if year is not None else "nd"
    word = "item"
    for raw in title.split():
        cleaned = _clean(raw)
        if cleaned and cleaned not in CITEKEY_STOPWORDS:
            word = cleaned
            break
    return f"{author}{year_part}{word}"


# ----- SS9.5 answer JSON + SS9.2 `ask` stdout oracle -------------------------


def ask_payload(answer: str, sources) -> str:
    """The exact SS9.5 answer JSON; `sources` is [(page, citekeys), ...]."""
    return json.dumps(
        {
            "answer": answer,
            "sources": [
                {"page": page, "citekeys": list(citekeys)}
                for page, citekeys in sources
            ],
        }
    )


def expected_ask_stdout(answer: str, sources) -> str:
    """SS9.2 `ask`: answer, blank line, `Sources:`, one line per
    (page-in-given-order, citekey) pair."""
    out = f"{answer}\n\nSources:\n"
    for page, citekeys in sources:
        for ck in citekeys:
            out += f"- [[{page}]] [@{ck}]\n"
    return out


# ----- pure in-memory ZoteroStore (records calls; injects failures) ---------


class InMemoryStore:
    """Structural ZoteroStore (contract SS3) with zero I/O.

    - `put` registers a SourceItem (optionally with a fulltext).
    - every protocol call is recorded in `.calls` as (method, args, kwargs).
    - `raises[method] = exc` makes that method raise after recording.
    - `add` fabricates a runtime-random citekey/key pair and records the
      created item in `.added` -- the CLI must echo whatever the injected
      store returned (REQ-032 via the injection seam).
    """

    def __init__(self) -> None:
        self.items: dict[str, SourceItem] = {}
        self.fulltexts: dict[str, str] = {}
        self.calls: list[tuple[str, tuple, dict]] = []
        self.raises: dict[str, Exception] = {}
        self.added: list[SourceItem] = []

    # -- test-side configuration --

    def put(self, *, citekey: str, title: str | None = None, creators=None,
            year: int | None = None, url: str | None = None,
            fulltext: str | None = None) -> SourceItem:
        item = SourceItem(
            key=rand_key(),
            citekey=citekey,
            title=title if title is not None
            else f"Paper {rand_word().capitalize()} {rand_word()}",
            creators=tuple(creators) if creators is not None
            else (f"{rand_word().capitalize()} {rand_word().capitalize()}",),
            year=year if year is not None else random.randint(1900, 2099),
            url=url,
            has_fulltext=fulltext is not None,
        )
        self.items[item.key] = item
        if fulltext is not None:
            self.fulltexts[item.key] = fulltext
        return item

    def method_calls(self, name: str) -> list[tuple[str, tuple, dict]]:
        return [c for c in self.calls if c[0] == name]

    def _enter(self, method: str, *args, **kwargs) -> None:
        self.calls.append((method, args, kwargs))
        exc = self.raises.get(method)
        if exc is not None:
            raise exc

    # -- the SS3 protocol --

    def search(self, query: str, limit: int = 25) -> list[SourceItem]:
        self._enter("search", query, limit=limit)
        if not 1 <= limit <= 100:
            raise ValueError(f"limit out of range: {limit}")
        hits = [
            item for item in self.items.values()
            if query.lower() in item.title.lower()
        ]
        return hits[:limit]

    def get(self, key: str) -> SourceItem:
        self._enter("get", key)
        try:
            return self.items[key]
        except KeyError:
            raise ItemNotFoundError(f"no item {key}") from None

    def fulltext(self, key: str) -> str:
        self._enter("fulltext", key)
        try:
            return self.fulltexts[key]
        except KeyError:
            raise FulltextNotFoundError(f"no fulltext for {key}") from None

    def resolve(self, citekey: str) -> SourceItem:
        self._enter("resolve", citekey)
        for item in self.items.values():
            if item.citekey == citekey:
                return item
        raise CitekeyNotFoundError(f"no item with citekey {citekey}")

    def add(self, *, title: str, url: str | None = None,
            item_type: str = "webpage", creators=(), year: int | None = None
            ) -> SourceItem:
        self._enter("add", title=title, url=url, item_type=item_type,
                    creators=tuple(creators), year=year)
        item = SourceItem(
            key=rand_key(),
            citekey=f"fake{rand_word()}{random.randint(1900, 2099)}{rand_word()}",
            title=title,
            creators=tuple(creators),
            year=year,
            url=url or None,
            has_fulltext=False,
        )
        self.items[item.key] = item
        self.added.append(item)
        return item


# ----- the REQ-038 no-network tripwire ---------------------------------------


def install_network_guard(monkeypatch) -> list:
    """Make every outgoing socket connection attempt fail loudly and be
    recorded.  Incoming/accepted connections (the idle session fixture
    server) are unaffected; the in-memory fakes never reach here."""
    import socket as socket_module

    attempts: list = []

    def deny_connect(self, address, *args, **kwargs):
        attempts.append(("connect", address))
        raise AssertionError(f"REQ-038 violated: connect to {address!r}")

    def deny_create_connection(address, *args, **kwargs):
        attempts.append(("create_connection", address))
        raise AssertionError(f"REQ-038 violated: create_connection {address!r}")

    monkeypatch.setattr(socket_module.socket, "connect", deny_connect)
    monkeypatch.setattr(socket_module, "create_connection",
                        deny_create_connection)
    return attempts


def clear_llm_env(monkeypatch) -> None:
    """REQ-038: make 'claude' unfindable on PATH (SS9.4 condition)."""
    monkeypatch.setenv("PATH", "/no-such-directory-zotwiki-test")


# ----- hand-rendered single-page vault (no zotwiki involved) -----------------


def write_static_vault(vault, title: str, citekey: str, *,
                       today: str = TODAY):
    """Write a grammar-canonical one-page vault (page + Index.md) straight
    from the SS6 oracles, with one claim citing `citekey`.  Returns the
    article so callers can register matching store fixtures."""
    article = build_article([(citekey,)], title=title)
    ref_item = SourceItem(
        key=rand_key(),
        citekey=citekey,
        title=f"Paper {rand_word().capitalize()} {rand_word()}",
        creators=(f"{rand_word().capitalize()} {rand_word().capitalize()}",),
        year=random.randint(1900, 2099),
        url=None,
        has_fulltext=True,
    )
    vault = Path(vault)
    vault.mkdir(parents=True, exist_ok=True)
    (vault / f"{title}.md").write_text(
        render_page_with(article, [ref_item], created=today, updated=today),
        encoding="utf-8",
    )
    (vault / "Index.md").write_text(
        index_oracle([title], created=today, updated=today), encoding="utf-8"
    )
    return article


def article_quotes(article) -> list[str]:
    """Every quote text on `article` (for building supporting fulltexts)."""
    return [q.text for claim in article.claims for q in claim.quotes]


def supporting_fulltext(article) -> str:
    return fulltext_containing(article_quotes(article))
