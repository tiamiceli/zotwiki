"""Vault syncer: compile all new items from a Zotero collection (contract §9.6)."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path

from zotwiki.compiler import Compiler
from zotwiki.llm import LLMClient
from zotwiki.models import Contradiction
from zotwiki.publisher import VaultPublisher, parse_page
from zotwiki.zotero import ZoteroStore

__all__ = ["Syncer", "SyncReport"]


@dataclass(frozen=True)
class SyncReport:
    compiled: int
    skipped: int


class Syncer:
    def __init__(
        self,
        store: ZoteroStore,
        llm: LLMClient,
        vault: Path,
        *,
        today: str | None = None,
    ) -> None:
        self._store = store
        self._llm = llm
        self._vault = Path(vault)
        self._today = today

    def sync(
        self,
        name: str,
        *,
        update: bool = False,
        on_compiled: Callable[[str, Path, tuple[Contradiction, ...]], None] | None = None,
        on_skipped: Callable[[str], None] | None = None,
    ) -> SyncReport:
        """Sync collection `name` into the vault; return a SyncReport.

        Raises CollectionNotFoundError if the collection does not exist.
        Raises ArticleSchemaError on bad LLM output (mid-sync).
        """
        items = self._store.collection_items(name)
        publisher = VaultPublisher(self._vault, self._store, today=self._today)
        known = publisher.compiled_keys()
        compiled = 0
        skipped = 0
        for item in items:
            if not item.citekey:
                continue
            existing_path = known.get(item.key)
            if existing_path is not None and not update:
                skipped += 1
                if on_skipped is not None:
                    on_skipped(item.title)
                continue
            existing = None
            if existing_path is not None:
                existing = parse_page(existing_path.read_text(encoding="utf-8"))
            result = Compiler(self._store, self._llm).compile([item.key], existing)
            article = result.article
            if existing is not None:
                article = replace(article, title=existing.title)
            path = publisher.publish(article, zotero_keys=result.zotero_keys)
            if result.contradictions:
                publisher.publish_contradictions(article.title, result.contradictions)
            compiled += 1
            if on_compiled is not None:
                on_compiled(article.title, path, result.contradictions)
        return SyncReport(compiled=compiled, skipped=skipped)
