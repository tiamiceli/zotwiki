"""REQ-046/047/048 — zotero_keys frontmatter tracking + sync de-dup by key.

BUG-1 fix (Ruling 6). Tester reads docs/contract.md §6.2/§6.4/§6.5/§7/§9.6
and docs/requirements.md §J only.

  REQ-046: render_page emits a sorted/deduped `zotero_keys` frontmatter block
           (schema `zotwiki: 2`); parse_page ignores it (round-trip) but
           rejects v1 / missing-field pages.
  REQ-047: CompileResult.zotero_keys carries the sorted/deduped input keys;
           publish writes them on a new page and unions them on update.
  REQ-048: sync recognizes already-compiled items by Zotero key (not title),
           so a re-sync whose LLM title drifts creates no duplicate page.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from zotwiki.errors import (
    CitekeyNotFoundError,
    CollectionNotFoundError,
    FulltextNotFoundError,
    PageParseError,
)
from zotwiki.models import Article, Claim, Quote, SourceItem

from m3_helpers import EMPTY_ARTICLE, PINNED_ARTICLE, PINNED_REFS, render_oracle


# ----- fakes (inline; no real Zotero/Claude) -----------------------------


def _item(key, title, citekey, *, has_fulltext=False):
    return SourceItem(key=key, citekey=citekey, title=title, creators=(),
                      year=None, url=None, has_fulltext=has_fulltext)


@dataclass
class FakeStore:
    """Minimal ZoteroStore fake (contract §3) for these tests."""
    _items: dict = field(default_factory=dict)
    _collections: dict = field(default_factory=dict)

    def add_item(self, item: SourceItem) -> None:
        self._items[item.key] = item

    def add_collection(self, name, items) -> None:
        self._collections[name] = list(items)
        for it in items:
            self._items[it.key] = it

    def collection_items(self, name):
        if name not in self._collections:
            raise CollectionNotFoundError(name)
        return list(self._collections[name])

    def get(self, key):
        return self._items[key]

    def resolve(self, citekey):
        for it in self._items.values():
            if it.citekey == citekey:
                return it
        raise CitekeyNotFoundError(citekey)

    def fulltext(self, key):  # pragma: no cover - items here have no fulltext
        raise FulltextNotFoundError(key)

    def search(self, query, limit=25):  # pragma: no cover
        return []

    def add(self, **kw):  # pragma: no cover
        raise NotImplementedError


class FakeLLM:
    """Valid article JSON. Title is the source block's title unless
    `force_title` is set (used to simulate LLM title drift); claims cite the
    source item's citekey so publish's resolve() succeeds. Records calls."""
    def __init__(self, force_title: str | None = None) -> None:
        self._force_title = force_title
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        ck_m = re.search(r"^citekey: (\S+)$", prompt, re.MULTILINE)
        ck = ck_m.group(1) if ck_m else "anon2020item"
        if self._force_title is not None:
            title = self._force_title
        else:
            t_m = re.search(r"^title: (.+)$", prompt, re.MULTILINE)
            title = t_m.group(1).strip() if t_m else "Synth"
        return json.dumps({
            "title": title,
            "summary": "A summary.",
            "sections": [{"heading": "Background", "body": "Body."}],
            "claims": [{"text": "A claim.", "citekeys": [ck],
                        "quotes": [{"citekey": ck, "text": "A quote."}]}],
            "links": [],
        })


def _simple_article(title: str, citekey: str) -> Article:
    return Article(
        title=title, summary="S.", sections=(),
        claims=(Claim(text="C.", citekeys=(citekey,),
                      quotes=(Quote(citekey=citekey, text="q"),)),),
        links=(),
    )


# ===== REQ-046: zotero_keys frontmatter (render / parse) ==================


def test_req046_render_emits_sorted_deduped_zotero_keys():
    from zotwiki.publisher import render_page
    page = render_page(PINNED_ARTICLE, PINNED_REFS, created="2026-06-11",
                       updated="2026-06-11",
                       zotero_keys=["WXYZ7890", "ABCD1234", "ABCD1234"])
    assert page.split("\n", 2)[1] == "zotwiki: 2"
    assert ('citekeys:\n  - "doe2020attention"\n  - "vaswani2017attention"\n'
            'zotero_keys:\n  - "ABCD1234"\n  - "WXYZ7890"\n'
            'tags:\n  - "zotwiki"\n') in page
    # equals the tester's independent oracle for the same inputs
    assert page == render_oracle(PINNED_ARTICLE, PINNED_REFS,
                                 created="2026-06-11", updated="2026-06-11",
                                 zotero_keys=["ABCD1234", "WXYZ7890"])


def test_req046_empty_zotero_keys_render_inline():
    from zotwiki.publisher import render_page
    page = render_page(EMPTY_ARTICLE, (), created="2026-01-02",
                       updated="2026-03-04", zotero_keys=())
    assert "citekeys: []\nzotero_keys: []\ntags:\n" in page


def test_req046_roundtrip_ignores_zotero_keys():
    from zotwiki.publisher import parse_page, render_page
    page = render_page(PINNED_ARTICLE, PINNED_REFS, created="2026-06-11",
                       updated="2026-06-11",
                       zotero_keys=["ABCD1234", "WXYZ7890"])
    assert parse_page(page) == PINNED_ARTICLE  # field is frontmatter-only


def test_req046_parse_rejects_legacy_v1_schema():
    from zotwiki.publisher import parse_page, render_page
    page = render_page(PINNED_ARTICLE, PINNED_REFS, created="2026-06-11",
                       updated="2026-06-11", zotero_keys=["ABCD1234"])
    v1 = page.replace("zotwiki: 2\n", "zotwiki: 1\n", 1)
    assert v1 != page
    with pytest.raises(PageParseError):
        parse_page(v1)


def test_req046_parse_rejects_missing_zotero_keys():
    from zotwiki.publisher import parse_page, render_page
    page = render_page(PINNED_ARTICLE, PINNED_REFS, created="2026-06-11",
                       updated="2026-06-11",
                       zotero_keys=["ABCD1234", "WXYZ7890"])
    bad = re.sub(r'zotero_keys:\n(?:  - "[^"\n]*"\n)+', "", page, count=1)
    assert bad != page
    with pytest.raises(PageParseError):
        parse_page(bad)


# ===== REQ-047: CompileResult.zotero_keys + publish writes / unions =======


def test_req047_compileresult_has_sorted_deduped_keys():
    from zotwiki.compiler import Compiler
    store = FakeStore()
    a = _item("KEYAAAA1", "Alpha", "alpha2020x")
    b = _item("KEYBBBB2", "Beta", "beta2021y")
    store.add_item(a)
    store.add_item(b)
    result = Compiler(store, FakeLLM()).compile([b.key, a.key, a.key])
    assert result.zotero_keys == tuple(sorted({a.key, b.key}))


def test_req047_publish_new_page_records_keys(tmp_path):
    from zotwiki.publisher import VaultPublisher
    store = FakeStore()
    store.add_item(_item("SRCKEY01", "Src", "alpha2020x"))
    pub = VaultPublisher(tmp_path / "v", store, today="2026-06-14")
    path = pub.publish(_simple_article("Topic", "alpha2020x"),
                       zotero_keys=["SRCKEY01"])
    assert 'zotero_keys:\n  - "SRCKEY01"\n' in path.read_text(encoding="utf-8")


def test_req047_publish_update_unions_keys(tmp_path):
    from zotwiki.publisher import VaultPublisher
    store = FakeStore()
    store.add_item(_item("SRCKEY01", "Src", "alpha2020x"))
    pub = VaultPublisher(tmp_path / "v", store, today="2026-06-14")
    art = _simple_article("Topic", "alpha2020x")
    pub.publish(art, zotero_keys=["KEYFIRST"])
    path = pub.publish(art, zotero_keys=["KEYSCND2"])  # update, same title
    assert 'zotero_keys:\n  - "KEYFIRST"\n  - "KEYSCND2"\n' in path.read_text(
        encoding="utf-8")


# ===== REQ-048: sync de-dup by Zotero key (BUG-1) ========================


def _write_existing_page(vault: Path, page_title: str, item: SourceItem,
                         *, created="2026-06-01") -> None:
    """Write an entity page (as if compiled earlier) recording item.key in
    zotero_keys, so compiled_keys() will find it."""
    from zotwiki.publisher import render_page
    art = _simple_article(page_title, item.citekey)
    (vault / f"{page_title}.md").write_text(
        render_page(art, [item], created=created, updated=created,
                    zotero_keys=[item.key]),
        encoding="utf-8",
    )


def _run_sync(argv, store, llm, capsys):
    from zotwiki.cli import main
    code = main(argv, store=store, llm=llm)
    cap = capsys.readouterr()
    return code, cap.out, cap.err


def _entity_pages(vault: Path) -> list[str]:
    from zotwiki.publisher import CONTRADICTIONS_FILENAME, INDEX_FILENAME
    return sorted(p.name for p in vault.glob("*.md")
                  if p.name not in (INDEX_FILENAME, CONTRADICTIONS_FILENAME))


def test_req048_resync_skips_by_key_no_duplicate_on_title_drift(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()
    # Compiled earlier under an LLM title that differs from the Zotero title.
    item = _item("KEY00001", "Zotero Title", "vaswani2017attention")
    _write_existing_page(vault, "LLM Chosen Title", item)
    store = FakeStore()
    store.add_collection("C", [item])
    llm = FakeLLM(force_title="Yet Another Title")  # would drift if called

    code, out, err = _run_sync(
        ["sync", "--vault", str(vault), "--collection", "C",
         "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, err
    assert _entity_pages(vault) == ["LLM Chosen Title.md"]  # no duplicate
    assert llm.calls == []  # skipped item is never recompiled
    assert "skipped\tZotero Title" in out
    assert "sync: 0 compiled, 1 skipped" in out


def test_req048_update_pins_title_no_duplicate(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()
    item = _item("KEY00001", "Zotero Title", "vaswani2017attention")
    _write_existing_page(vault, "Page Title", item)
    store = FakeStore()
    store.add_collection("C", [item])
    llm = FakeLLM(force_title="Drifted Title")  # drifts on recompile

    code, out, err = _run_sync(
        ["sync", "--vault", str(vault), "--collection", "C",
         "--update", "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, err
    # Updated in place under the existing page title; no drifted duplicate.
    assert _entity_pages(vault) == ["Page Title.md"]
    assert not (vault / "Drifted Title.md").exists()
    assert "compiled\tPage Title\t" in out


def test_req048_new_item_compiled_records_its_key(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()
    item = _item("KEY00009", "Fresh Paper", "fresh2022paper")
    store = FakeStore()
    store.add_collection("C", [item])
    llm = FakeLLM()  # title taken from the source block -> "Fresh Paper"

    code, out, err = _run_sync(
        ["sync", "--vault", str(vault), "--collection", "C",
         "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, err
    page = vault / "Fresh Paper.md"
    assert page.exists()
    assert 'zotero_keys:\n  - "KEY00009"\n' in page.read_text(encoding="utf-8")
