"""Sync subcommand — CLI layer tests (REQ-041, REQ-042, REQ-043, REQ-044).

Tester reads docs/contract.md §9.6 and docs/requirements.md §H.
Uses a fake store (inline class) and fake LLM injected via main()'s seam.
No real Zotero, no real Claude, no network.
"""
from __future__ import annotations

import io
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import pytest

from zotwiki.errors import CollectionNotFoundError
from zotwiki.models import SourceItem


# ----- fake store --------------------------------------------------------


@dataclass
class FakeSyncStore:
    """Minimal ZoteroStore fake for sync CLI tests."""
    _collections: dict[str, list[SourceItem]] = field(default_factory=dict)
    _items: dict[str, SourceItem] = field(default_factory=dict)

    def add_collection(self, name: str, items: list[SourceItem]) -> None:
        self._collections[name] = list(items)
        for item in items:
            self._items[item.key] = item

    def collection_items(self, name: str) -> list[SourceItem]:
        if name not in self._collections:
            raise CollectionNotFoundError(f"collection {name!r} not found")
        return list(self._collections[name])

    def resolve(self, citekey: str) -> SourceItem:
        for item in self._items.values():
            if item.citekey == citekey:
                return item
        from zotwiki.errors import CitekeyNotFoundError
        raise CitekeyNotFoundError(citekey)

    def get(self, key: str) -> SourceItem:
        return self._items[key]

    def search(self, query: str, limit: int = 25) -> list[SourceItem]:  # pragma: no cover
        return []

    def fulltext(self, key: str) -> str:  # pragma: no cover
        from zotwiki.errors import FulltextNotFoundError
        raise FulltextNotFoundError(key)

    def add(self, *, title, url=None, item_type="webpage", creators=(), year=None):  # pragma: no cover
        raise NotImplementedError


def _item(key: str, title: str, citekey: str) -> SourceItem:
    return SourceItem(key=key, citekey=citekey, title=title,
                      creators=(), year=None, url=None, has_fulltext=False)


def _item_no_citekey(key: str, title: str) -> SourceItem:
    return SourceItem(key=key, citekey="", title=title,
                      creators=(), year=None, url=None, has_fulltext=False)


# ----- fake LLM ----------------------------------------------------------


class FakeLLM:
    """Returns a minimal valid article JSON for any item key."""
    def __init__(self, responses: dict[str, str] | None = None) -> None:
        self._responses = responses or {}
        self.calls: list[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        for key, response in self._responses.items():
            if key in prompt:
                return response
        return self._default_response(prompt)

    @staticmethod
    def _default_response(prompt: str) -> str:
        import json
        # Extract a title hint from the prompt (first quoted title-like word)
        import re
        m = re.search(r'"title":\s*"([^"]+)"', prompt)
        title = m.group(1) if m else "Synthesized Article"
        # find a citekey
        ck_m = re.search(r'"citekey":\s*"([^"]+)"', prompt)
        citekey = ck_m.group(1) if ck_m else "author2020word"
        return json.dumps({
            "title": title,
            "summary": "A summary.",
            "sections": [{"heading": "Background", "body": "Some background."}],
            "claims": [{
                "text": "This is a claim.",
                "citekeys": [citekey],
                "quotes": [{"citekey": citekey, "text": "A quote."}],
            }],
            "links": [],
        })


# ----- helpers -----------------------------------------------------------


def _run(argv: list[str], store, llm, capsys) -> tuple[int, str, str]:
    from zotwiki.cli import main
    code = main(argv, store=store, llm=llm)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


# ----- REQ-041 -----------------------------------------------------------


def test_req_041__sync_compiles_new_and_skips_existing(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()

    transformer_item = _item("KEY00001", "Transformer", "vaswani2017attention")
    bert_item = _item("KEY00002", "BERT", "devlin2019bert")

    # Pre-write the Transformer page so it counts as existing
    from zotwiki.publisher import render_page
    transformer_page = vault / "Transformer.md"
    # Build a minimal valid page using render_page
    from zotwiki.models import Article, Claim, Quote, Section
    existing_article = Article(
        title="Transformer",
        summary="The Transformer model.",
        sections=(Section(heading="Architecture", body="Encoder-decoder."),),
        claims=(Claim(
            text="Self-attention replaces recurrence.",
            citekeys=("vaswani2017attention",),
            quotes=(Quote(citekey="vaswani2017attention", text="A quote."),),
        ),),
        links=(),
    )
    transformer_page.write_text(
        render_page(existing_article, [transformer_item],
                    created="2026-06-01", updated="2026-06-01"),
        encoding="utf-8",
    )
    # Also write Index.md so audit doesn't care
    from zotwiki.publisher import INDEX_FILENAME
    (vault / INDEX_FILENAME).write_text(
        render_page(
            Article(title="Index", summary="Index.", sections=(), claims=(), links=()),
            [], created="2026-06-01", updated="2026-06-01",
        ),
        encoding="utf-8",
    )

    store = FakeSyncStore()
    store.add_collection("AI Papers", [transformer_item, bert_item])
    llm = FakeLLM()

    code, out, err = _run(
        ["sync", "--vault", str(vault), "--collection", "AI Papers", "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, f"stderr: {err!r}"
    lines = out.splitlines()
    # Last line is summary
    assert lines[-1] == "sync: 1 compiled, 1 skipped"
    # compiled line for BERT
    compiled_lines = [l for l in lines if l.startswith("compiled\t")]
    assert len(compiled_lines) == 1
    assert compiled_lines[0].startswith("compiled\tBERT\t")
    # skipped line for Transformer
    skipped_lines = [l for l in lines if l.startswith("skipped\t")]
    assert len(skipped_lines) == 1
    assert skipped_lines[0] == "skipped\tTransformer"
    # BERT.md written
    assert (vault / "BERT.md").exists()


# ----- REQ-042 -----------------------------------------------------------


def test_req_042__sync_update_recompiles_existing(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()

    transformer_item = _item("KEY00001", "Transformer", "vaswani2017attention")
    bert_item = _item("KEY00002", "BERT", "devlin2019bert")

    from zotwiki.publisher import render_page
    from zotwiki.models import Article, Claim, Quote, Section
    for item in (transformer_item, bert_item):
        art = Article(
            title=item.title,
            summary=f"Summary of {item.title}.",
            sections=(Section(heading="Intro", body="Introduction."),),
            claims=(Claim(
                text="A claim.",
                citekeys=(item.citekey,),
                quotes=(Quote(citekey=item.citekey, text="A quote."),),
            ),),
            links=(),
        )
        (vault / f"{item.title}.md").write_text(
            render_page(art, [item], created="2026-06-01", updated="2026-06-01"),
            encoding="utf-8",
        )

    store = FakeSyncStore()
    store.add_collection("AI Papers", [transformer_item, bert_item])
    llm = FakeLLM()

    code, out, err = _run(
        ["sync", "--vault", str(vault), "--collection", "AI Papers",
         "--update", "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, f"stderr: {err!r}"
    lines = out.splitlines()
    assert lines[-1] == "sync: 2 compiled, 0 skipped"
    compiled_lines = [l for l in lines if l.startswith("compiled\t")]
    assert len(compiled_lines) == 2


# ----- REQ-043 -----------------------------------------------------------


def test_req_043__collection_not_found_exits_2(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()

    store = FakeSyncStore()
    store.add_collection("AI Papers", [])
    llm = FakeLLM()

    code, out, err = _run(
        ["sync", "--vault", str(vault), "--collection", "Nonexistent"],
        store, llm, capsys,
    )

    assert code == 2
    assert err.strip() == "error: collection 'Nonexistent' not found"
    assert out == ""


# ----- REQ-044 -----------------------------------------------------------


def test_req_044__items_without_citekeys_skipped_silently(tmp_path, capsys):
    vault = tmp_path / "wiki"
    vault.mkdir()

    good_item = _item("KEY00001", "BERT", "devlin2019bert")
    no_ck_item = _item_no_citekey("KEY00002", "Untitled Paper")

    store = FakeSyncStore()
    store.add_collection("AI Papers", [good_item, no_ck_item])
    llm = FakeLLM()

    code, out, err = _run(
        ["sync", "--vault", str(vault), "--collection", "AI Papers", "--today", "2026-06-14"],
        store, llm, capsys,
    )

    assert code == 0, f"stderr: {err!r}"
    lines = out.splitlines()
    # Summary: 1 compiled, 0 skipped (no-citekey item not counted either way)
    assert lines[-1] == "sync: 1 compiled, 0 skipped"
    # No line mentions the no-citekey item
    assert not any("Untitled Paper" in l for l in lines)
    # BERT compiled
    assert any(l.startswith("compiled\tBERT\t") for l in lines)
