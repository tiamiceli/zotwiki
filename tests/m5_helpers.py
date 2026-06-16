"""M5 test helpers: byte-exact oracles for Index.md (contract SS6.7) and
Contradictions.md (SS6.8), plus citekey/title generation and fake-Zotero
registration conveniences for the incremental-maintenance tests.

Everything here is derived from docs/contract.md alone:

  - index_oracle           independent rendering of SS6.7 (frontmatter per
                           SS6.2 with title "Index", citekeys: [], then
                           `# Index` and one sorted `- [[title]]` bullet per
                           entity page).
  - contradiction_blocks /
    contradictions_oracle  independent rendering of SS6.8 (heading block
                           `## {page} ({today})`, then one consecutive
                           EXISTING/NEW line pair per Contradiction, the NEW
                           line carrying the SS6.3 claim-citekey suffix;
                           blocks append-only across calls).
  - register_citekey_map / refs_for / article_citekeys
                           SourceItem bookkeeping so merged pages can be
                           byte-compared against the m3 render oracle.

Both oracles are guarded below against hand-transcribed fixtures taken
straight from the contract document (SS6.7 example and the SS6.8 block shape
with REQ-031's Gravity example) -- plain asserts, not tests.  Only frozen,
green surfaces are imported (zotwiki.models from M1, m2/m3/m4 helpers).
"""
from __future__ import annotations

import random

from zotwiki.models import Contradiction, SourceItem

from m2_helpers import rand_word
from m3_helpers import (
    cited_citekeys,
    claim_suffix,
    frontmatter_block,
    register_reference,
)
from m4_helpers import TODAY, contradictions_page_text

LATER = "2026-07-01"
EVEN_LATER = "2026-08-15"


# ----- independent SS6.7 Index.md oracle -----------------------------------


def index_oracle(titles, *, created: str, updated: str) -> str:
    """Canonical Index.md bytes for a vault whose entity pages are exactly
    `titles` (any order; the bullets are emitted sorted per SS6.7)."""
    blocks = [frontmatter_block("Index", created, updated, []), "# Index"]
    entries = sorted(titles)
    if entries:
        blocks.append("\n".join(f"- [[{title}]]" for title in entries))
    return "\n\n".join(blocks) + "\n"


# ----- independent SS6.8 Contradictions.md oracle ---------------------------


def contradiction_blocks(page_title: str, today: str,
                         contradictions) -> list[str]:
    """The two SS6.8 body blocks one publish_contradictions call appends:
    the `## {page} ({today})` heading and the consecutive EXISTING/NEW
    pairs (one pair per Contradiction, in call order)."""
    lines: list[str] = []
    for c in contradictions:
        lines.append(f"- EXISTING: {c.existing_claim}")
        lines.append(f"- NEW: {c.new_claim}{claim_suffix(c.citekeys)}")
    return [f"## {page_title} ({today})", "\n".join(lines)]


def contradictions_oracle(calls, *, created: str, updated: str) -> str:
    """Canonical Contradictions.md bytes after the given sequence of
    publish_contradictions calls, each `(page_title, today, contradictions)`,
    appended in order and never rewritten (SS6.8)."""
    blocks: list[str] = []
    for page_title, today, contradictions in calls:
        blocks.extend(contradiction_blocks(page_title, today, contradictions))
    return contradictions_page_text(blocks, created=created, updated=updated)


# ----- internal consistency guards (hand-pinned from the contract text) -----

_PINNED_INDEX = (
    "---\n"
    "zotwiki: 2\n"
    'title: "Index"\n'
    'created: "2026-06-11"\n'
    'updated: "2026-06-11"\n'
    "citekeys: []\n"
    "zotero_keys: []\n"
    "tags:\n"
    '  - "zotwiki"\n'
    "---\n"
    "\n"
    "# Index\n"
    "\n"
    "- [[Alpha]]\n"
    "- [[Beta]]\n"
)
assert index_oracle(["Beta", "Alpha"], created="2026-06-11",
                    updated="2026-06-11") == _PINNED_INDEX

_PINNED_CONTRADICTIONS = (
    "---\n"
    "zotwiki: 2\n"
    'title: "Contradictions"\n'
    'created: "2026-06-11"\n'
    'updated: "2026-06-11"\n'
    "citekeys: []\n"
    "zotero_keys: []\n"
    "tags:\n"
    '  - "zotwiki"\n'
    "---\n"
    "\n"
    "# Contradictions\n"
    "\n"
    "## Gravity (2026-06-11)\n"
    "\n"
    "- EXISTING: X holds.\n"
    "- NEW: X does not hold. [@doe2020counter]\n"
)
assert contradictions_oracle(
    [(
        "Gravity",
        "2026-06-11",
        [Contradiction(existing_claim="X holds.",
                       new_claim="X does not hold.",
                       citekeys=("doe2020counter",))],
    )],
    created="2026-06-11",
    updated="2026-06-11",
) == _PINNED_CONTRADICTIONS


# ----- registration / reference bookkeeping ---------------------------------


def register_citekey_map(fake, citekeys) -> dict[str, SourceItem]:
    """Register one resolvable item per distinct citekey on the fake server;
    citekey -> the SourceItem the adapter must map it to (contract SS3.1)."""
    return {ck: register_reference(fake, ck) for ck in sorted(set(citekeys))}


def article_citekeys(*articles) -> set[str]:
    """Every citekey cited by any claim of any of `articles`."""
    return {
        ck
        for article in articles
        for claim in article.claims
        for ck in claim.citekeys
    }


def refs_for(article, by_citekey) -> tuple[SourceItem, ...]:
    """Exactly one SourceItem per citekey cited by `article` (for the m3
    render oracle), pulled from a citekey -> SourceItem mapping."""
    return tuple(by_citekey[ck] for ck in cited_citekeys(article))


# ----- runtime-random, filesystem-safe, casefold-distinct titles ------------


def distinct_titles(n: int) -> list[str]:
    """`n` runtime-random titles in the SS5.2 safe charset, casefold-distinct
    from each other and from the reserved special-page names."""
    out: list[str] = []
    seen = {"index", "contradictions"}
    while len(out) < n:
        title = (f"{rand_word().capitalize()} {rand_word().capitalize()} "
                 f"{random.randint(10, 99)}")
        if title.casefold() not in seen:
            seen.add(title.casefold())
            out.append(title)
    return out
