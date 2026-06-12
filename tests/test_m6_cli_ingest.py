"""M6 / `zotwiki ingest` (REQ-032): the item lands per REQ-007, stdout is
exactly `{citekey}\\t{key}\\n`, exit 0; unreachable Zotero exits 2 with one
`error:` line on stderr and empty stdout.

Black-box from docs/contract.md SS3.3 + SS4.6 + SS9; main() is called
in-process with an injected store; the fake Zotero serves on 127.0.0.1
only; the expected citekey comes from the independent SS3.3 oracle over
runtime-random ingredients (hypothesis property included).
"""
from __future__ import annotations

import random
import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from m2_helpers import rand_word
from m4_helpers import closed_port
from m6_helpers import (
    CITEKEY_STOPWORDS,
    assert_single_error_line,
    expected_citekey,
)

main = None  # bound by _require_m6_surface

SETTINGS = settings(
    deadline=None,
    max_examples=8,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)


@pytest.fixture(scope="module", autouse=True)
def _require_m6_surface():
    """Bind the M6 CLI surface (contract SS1.1) at test time, so its absence
    is a per-test contract failure rather than a collection error."""
    global main
    from zotwiki.cli import main as main_

    main = main_


@pytest.fixture
def store(zstore):
    s, _sleeps = zstore()
    return s


def test_req_032__ingest_prints_citekey_tab_key_and_returns_0(
    store, fake_zotero, capsys
):
    word = rand_word()
    title = f"A Study of {word.capitalize()} Owls"
    first, last = rand_word().capitalize(), rand_word().capitalize()
    year = random.randint(1900, 2099)
    url = f"https://{rand_word()}.example"

    rc = main(
        ["ingest", "--title", title, "--url", url,
         "--creator", f"{first} {last}", "--year", str(year)],
        store=store,
    )
    out = capsys.readouterr()

    citekey = expected_citekey(title=title, creators=(f"{first} {last}",),
                               year=year)
    assert citekey == f"{last.lower()}{year}study"  # oracle self-check
    [key] = fake_zotero.created_keys
    assert rc == 0
    assert out.out == f"{citekey}\t{key}\n"
    assert out.err == ""

    # The item really was added per REQ-007 / SS4.6.
    [posted] = fake_zotero.post_bodies
    [item_data] = posted
    assert item_data["itemType"] == "webpage"  # --type default
    assert item_data["title"] == title
    assert item_data["url"] == url
    assert item_data["date"] == str(year)
    assert item_data["extra"] == f"Citation Key: {citekey}"
    assert item_data["creators"] == [
        {"creatorType": "author", "firstName": first, "lastName": last}
    ]


def test_req_032__ingest_type_flag_and_optional_url_year(
    store, fake_zotero, capsys
):
    word = rand_word()
    while word in CITEKEY_STOPWORDS:  # keep the SS3.3 'word' unambiguous
        word = rand_word()
    title = f"The {word.capitalize()} Report"
    first1, last1 = rand_word().capitalize(), rand_word().capitalize()
    single = rand_word().capitalize()  # single-token creator -> "name" field

    rc = main(
        ["ingest", "--title", title, "--creator", f"{first1} {last1}",
         "--creator", single, "--type", "report"],
        store=store,
    )
    out = capsys.readouterr()

    # No --year -> "nd"; citekey uses the FIRST creator (SS3.3).
    citekey = expected_citekey(
        title=title, creators=(f"{first1} {last1}", single), year=None
    )
    assert citekey == f"{last1.lower()}nd{word.lower()}"
    [key] = fake_zotero.created_keys
    assert rc == 0
    assert out.out == f"{citekey}\t{key}\n"
    assert out.err == ""

    [posted] = fake_zotero.post_bodies
    [item_data] = posted
    assert item_data["itemType"] == "report"          # --type passthrough
    assert item_data["url"] == ""                     # SS4.6: "" when None
    assert item_data["date"] == ""                    # no year
    assert item_data["creators"] == [
        {"creatorType": "author", "firstName": first1, "lastName": last1},
        {"creatorType": "author", "name": single},
    ]


def test_req_032__ingest_unreachable_zotero_returns_2(zstore, capsys):
    dead_store, _ = zstore(
        base_url=f"http://127.0.0.1:{closed_port()}/api/users/0"
    )
    rc = main(
        ["ingest", "--title", f"Doomed {rand_word()}", "--year", "2001"],
        store=dead_store,
    )
    out = capsys.readouterr()
    assert rc == 2
    assert out.out == ""
    assert_single_error_line(out.err)


# ----- hypothesis: the stdout line tracks the SS3.3 generation rule ---------

_NAME_WORD = st.text(alphabet=string.ascii_letters, min_size=1, max_size=8)
_TITLE_WORD = st.one_of(
    st.sampled_from(sorted(CITEKEY_STOPWORDS)),
    st.text(alphabet=string.ascii_lowercase, min_size=1, max_size=8),
)
_TITLES = st.lists(_TITLE_WORD, min_size=1, max_size=5).map(" ".join)
_CREATORS = st.lists(
    st.lists(_NAME_WORD, min_size=1, max_size=3).map(" ".join),
    max_size=2,
)
_YEARS = st.none() | st.integers(1000, 9999)


@SETTINGS
@given(title=_TITLES, creators=_CREATORS, year=_YEARS)
def test_req_032__ingest_stdout_matches_citekey_oracle_property(
    fake_zotero, zstore, capsys, title, creators, year
):
    fake_zotero.reset()
    store, _ = zstore()
    argv = ["ingest", "--title", title]
    for name in creators:
        argv += ["--creator", name]
    if year is not None:
        argv += ["--year", str(year)]

    rc = main(argv, store=store)
    out = capsys.readouterr()

    [key] = fake_zotero.created_keys
    citekey = expected_citekey(title=title, creators=tuple(creators),
                               year=year)
    assert rc == 0
    assert out.out == f"{citekey}\t{key}\n"
    assert out.err == ""
