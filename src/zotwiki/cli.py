"""ZotWiki command-line interface (contract SS9).

Four subcommands -- ingest / compile / audit / ask -- over the injection seam

    main(argv, *, store=None, llm=None) -> int

`main` always *returns* its exit code (it never calls `sys.exit`; argparse
usage errors are trapped and converted to `EXIT_ENV`).  Every nonzero exit
except audit-violations prints exactly one `error: {message}` line to stderr
and nothing to stdout (SS9.3).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Sequence

from zotwiki.ask import ask
from zotwiki.auditor import Auditor
from zotwiki.compiler import Compiler
from zotwiki.errors import VaultError, ZotWikiError, ZoteroUnavailableError
from zotwiki.llm import ClaudeCodeLLMClient, LLMClient
from zotwiki.publisher import VaultPublisher, parse_page
from zotwiki.zotero import DEFAULT_BASE_URL, HTTPZoteroStore, ZoteroStore

__all__ = ["main", "EXIT_OK", "EXIT_FAIL", "EXIT_ENV"]

EXIT_OK, EXIT_FAIL, EXIT_ENV = 0, 1, 2

_NEEDS_LLM = ("compile", "ask")


class _UsageError(Exception):
    """Raised instead of argparse's print-usage-and-SystemExit behavior."""


class _Parser(argparse.ArgumentParser):
    def error(self, message: str):  # noqa: D102 - argparse override
        raise _UsageError(message)


def _build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="zotwiki", description="Zotero-backed wiki compiler")
    parser.add_argument("--zotero-url", default=DEFAULT_BASE_URL,
                        help="Zotero local API base URL")
    sub = parser.add_subparsers(dest="command", required=True)

    ingest = sub.add_parser("ingest", help="add an item to Zotero")
    ingest.add_argument("--title", required=True)
    ingest.add_argument("--url", default=None)
    ingest.add_argument("--creator", action="append", default=None,
                        metavar="NAME")
    ingest.add_argument("--year", type=int, default=None)
    ingest.add_argument("--type", dest="item_type", default="webpage",
                        metavar="ITEMTYPE")

    compile_ = sub.add_parser("compile", help="compile items into a page")
    compile_.add_argument("--vault", required=True, metavar="DIR")
    items = compile_.add_mutually_exclusive_group(required=True)
    items.add_argument("--key", action="append", dest="keys", metavar="KEY")
    items.add_argument("--query", default=None)
    compile_.add_argument("--limit", type=int, default=10, metavar="N")
    compile_.add_argument("--page", default=None, metavar="TITLE")
    compile_.add_argument("--today", default=None, metavar="YYYY-MM-DD")

    audit = sub.add_parser("audit", help="audit the vault")
    audit.add_argument("--vault", required=True, metavar="DIR")

    ask_ = sub.add_parser("ask", help="answer a question from the vault")
    ask_.add_argument("--vault", required=True, metavar="DIR")
    ask_.add_argument("question", metavar="QUESTION")

    return parser


def _fail(code: int, message: object) -> int:
    """SS9.3: exactly one single-line `error: {message}` on stderr."""
    text = " ".join(str(message).split()) or "unspecified failure"
    sys.stderr.write(f"error: {text}\n")
    return code


def _cmd_ingest(args: argparse.Namespace, store: ZoteroStore) -> int:
    item = store.add(
        title=args.title,
        url=args.url,
        item_type=args.item_type,
        creators=tuple(args.creator or ()),
        year=args.year,
    )
    sys.stdout.write(f"{item.citekey}\t{item.key}\n")
    return EXIT_OK


def _cmd_compile(
    args: argparse.Namespace, store: ZoteroStore, llm: LLMClient
) -> int:
    # SS9.2 compile step 1: materialize the items.
    if args.keys:
        items = [store.get(key) for key in args.keys]
    else:
        items = store.search(args.query, limit=args.limit)
    if not items:
        return _fail(EXIT_FAIL, "no items matched")
    keys = [item.key for item in items]

    # Step 2: the existing article, when --page names an existing page.
    vault = Path(args.vault)
    existing = None
    if args.page is not None:
        page_path = vault / f"{args.page}.md"
        if page_path.exists():
            existing = parse_page(page_path.read_text(encoding="utf-8"))

    # Step 3: compile; --page pins the resulting title.
    result = Compiler(store, llm).compile(keys, existing)
    title = result.article.title
    if args.page is not None and title != args.page:
        return _fail(
            EXIT_FAIL,
            f"compiled article title {title!r} does not match --page "
            f"{args.page!r}",
        )

    # Steps 4 + 5: publish, then route contradictions.
    publisher = VaultPublisher(vault, store, today=args.today)
    path = publisher.publish(result.article)
    sys.stdout.write(f"compiled\t{title}\t{path}\n")
    if result.contradictions:
        publisher.publish_contradictions(title, result.contradictions)
        sys.stdout.write(
            f"contradictions\t{title}\t{len(result.contradictions)}\n"
        )
    return EXIT_OK


def _cmd_audit(args: argparse.Namespace, store: ZoteroStore) -> int:
    report = Auditor(Path(args.vault), store).audit()
    if report.ok:
        sys.stdout.write(f"audit: ok ({report.pages_checked} pages)\n")
        return EXIT_OK
    for violation in report.violations:
        sys.stdout.write(
            f"{violation.code}\t{violation.page}\t{violation.detail}\n"
        )
    sys.stdout.write(f"audit: {len(report.violations)} violation(s)\n")
    return EXIT_FAIL


def _cmd_ask(args: argparse.Namespace, llm: LLMClient) -> int:
    answer = ask(Path(args.vault), args.question, llm)
    out = [answer.text, "\n\nSources:\n"]
    for source in answer.sources:
        for citekey in source.citekeys:
            out.append(f"- [[{source.page}]] [@{citekey}]\n")
    sys.stdout.write("".join(out))
    return EXIT_OK


def main(
    argv: Sequence[str] | None = None,
    *,
    store: ZoteroStore | None = None,
    llm: LLMClient | None = None,
) -> int:
    try:
        args = _build_parser().parse_args(argv)
    except _UsageError as exc:
        return _fail(EXIT_ENV, exc)
    except SystemExit as exc:  # e.g. --help; never propagate (SS9.1)
        if exc.code in (None, 0):
            return EXIT_OK
        return _fail(EXIT_ENV, "invalid usage")

    # SS9.4: construct the LLM only when needed and not injected.
    if llm is None and args.command in _NEEDS_LLM:
        if not shutil.which("claude"):
            return _fail(EXIT_ENV, "claude not found")
        llm = ClaudeCodeLLMClient()

    if store is None:
        store = HTTPZoteroStore(args.zotero_url)

    try:
        if args.command == "ingest":
            return _cmd_ingest(args, store)
        if args.command == "compile":
            return _cmd_compile(args, store, llm)
        if args.command == "audit":
            return _cmd_audit(args, store)
        return _cmd_ask(args, llm)
    except (ZoteroUnavailableError, VaultError) as exc:
        return _fail(EXIT_ENV, exc)
    except ZotWikiError as exc:
        return _fail(EXIT_FAIL, exc)
