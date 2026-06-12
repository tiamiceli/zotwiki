"""M2 / article schema: parse_article_json on valid, invalid, and fenced
input.  Black-box against docs/contract.md SS5.2-SS5.4; covers REQ-010,
REQ-011 (the complete invalid-input matrix -> ArticleSchemaError), and
REQ-012 (code-fence tolerance).
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from zotwiki.errors import ArticleSchemaError
from zotwiki.models import Article, Claim, Contradiction, Quote, Section

from m2_helpers import (
    expected_article_from_dict,
    make_article_dict,
    rand_citekey,
)

parse_article_json = None  # bound by _require_m2_surface


@pytest.fixture(scope="module", autouse=True)
def _require_m2_surface():
    """Bind the M2 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1 suite)."""
    global parse_article_json
    from zotwiki.llm import parse_article_json as parse_article_json_

    parse_article_json = parse_article_json_

# ====================================================================
# REQ-010 - valid article JSON parses to an Article
# ====================================================================


def test_req_010__valid_random_json_parses_to_expected_article():
    d = make_article_dict()
    article, contradictions = parse_article_json(json.dumps(d))
    assert isinstance(article, Article)
    assert (article, contradictions) == expected_article_from_dict(d)
    assert contradictions == ()


def test_req_010__pinned_example_normalizes_whitespace_and_canonicalizes():
    text = json.dumps(
        {
            "title": "Transformer Notes",
            "summary": "  Self-attention\nis   the\tcore idea.  ",
            "sections": [
                {
                    "heading": "  Architecture   overview ",
                    "body": "\n\nFirst line.   \n\n\n\nSecond line.\n  \n",
                }
            ],
            "claims": [
                {
                    "text": " Attention  replaces   recurrence. ",
                    "citekeys": ["zz2021b", "aa2020a"],
                    "quotes": [
                        {"citekey": "zz2021b", "text": "  later   quote "},
                        {"citekey": "aa2020a", "text": " we   propose  attention "},
                    ],
                }
            ],
            "links": ["Beta Topic", "Alpha Topic", "Beta Topic"],
        }
    )
    article, contradictions = parse_article_json(text)
    assert article == Article(
        title="Transformer Notes",
        summary="Self-attention is the core idea.",
        sections=(
            Section(heading="Architecture overview", body="First line.\n\nSecond line."),
        ),
        claims=(
            Claim(
                text="Attention replaces recurrence.",
                citekeys=("aa2020a", "zz2021b"),
                quotes=(
                    Quote(citekey="aa2020a", text="we propose attention"),
                    Quote(citekey="zz2021b", text="later quote"),
                ),
            ),
        ),
        links=("Alpha Topic", "Beta Topic"),
    )
    assert contradictions == ()


def test_req_010__empty_collections_are_valid():
    d = make_article_dict()
    d["sections"] = []
    d["claims"] = []
    d["links"] = []
    article, contradictions = parse_article_json(json.dumps(d))
    assert article.sections == ()
    assert article.claims == ()
    assert article.links == ()
    assert contradictions == ()


def test_req_010__returned_article_is_frozen():
    article, _ = parse_article_json(json.dumps(make_article_dict()))
    with pytest.raises(dataclasses.FrozenInstanceError):
        article.title = "Hijacked"


def test_req_010__contradictions_key_parsed_and_canonicalized():
    d = make_article_dict(
        contradictions=[
            {
                "existing_claim": " X  holds  under load. ",
                "new_claim": "X  does not\thold.",
                "citekeys": ["zz2020b", "aa2019a"],
            }
        ]
    )
    article, contradictions = parse_article_json(json.dumps(d))
    assert contradictions == (
        Contradiction(
            existing_claim="X holds under load.",
            new_claim="X does not hold.",
            citekeys=("aa2019a", "zz2020b"),
        ),
    )
    assert article == expected_article_from_dict(d)[0]


# ====================================================================
# REQ-011 - invalid article JSON always raises ArticleSchemaError
# ====================================================================
#
# Each case mutates a fresh, runtime-random valid payload.  A mutator
# either edits the dict in place (then the test serializes it) or returns
# the raw text to parse.


def _top(key, value):
    def mutate(d):
        d[key] = value

    return mutate


def _drop(key):
    def mutate(d):
        del d[key]

    return mutate


def _claim(field, value, idx=0):
    def mutate(d):
        d["claims"][idx][field] = value

    return mutate


def _section(field, value, idx=0):
    def mutate(d):
        d["sections"][idx][field] = value

    return mutate


def _quote(field, value):
    def mutate(d):
        d["claims"][0]["quotes"][0][field] = value

    return mutate


def _raw(text):
    def mutate(d):
        return text

    return mutate


def _duplicate_citekeys(d):
    ck = d["claims"][0]["citekeys"][0]
    d["claims"][0]["citekeys"] = [ck, ck]
    d["claims"][0]["quotes"] = [{"citekey": ck, "text": "duplicated citekey probe"}]


def _duplicate_headings(d):
    first = dict(d["sections"][0])
    d["sections"] = [first, dict(first)]


def _quote_unknown_key(d):
    d["claims"][0]["quotes"][0]["page"] = 3


def _claim_unknown_key(d):
    d["claims"][0]["note"] = "extra"


def _section_unknown_key(d):
    d["sections"][0]["level"] = 2


def _section_drop_body(d):
    del d["sections"][0]["body"]


def _section_drop_heading(d):
    del d["sections"][0]["heading"]


def _claim_drop(field):
    def mutate(d):
        del d["claims"][0][field]

    return mutate


def _quote_drop(field):
    def mutate(d):
        del d["claims"][0]["quotes"][0][field]

    return mutate


def _contra(entry):
    def mutate(d):
        d["contradictions"] = [entry]

    return mutate


INVALID_CASES = [
    # -- not a JSON object at the top level --------------------------------
    ("non_json_text", _raw("this is definitely not JSON {")),
    ("truncated_json", lambda d: json.dumps(d)[:25]),
    ("top_level_array", lambda d: json.dumps([d])),
    ("top_level_string", _raw(json.dumps("an article"))),
    ("top_level_number", _raw(json.dumps(7))),
    ("top_level_null", _raw(json.dumps(None))),
    # -- required / unknown top-level keys ---------------------------------
    ("missing_title", _drop("title")),
    ("missing_summary", _drop("summary")),
    ("missing_sections", _drop("sections")),
    ("missing_claims", _drop("claims")),
    ("missing_links", _drop("links")),
    ("unknown_top_level_key", _top("meta", {})),
    # -- title rule ----------------------------------------------------------
    ("title_empty", _top("title", "")),
    ("title_wrong_type", _top("title", 42)),
    ("title_bad_char_question_mark", _top("title", "What is attention?")),
    ("title_bad_char_slash", _top("title", "A/B Testing")),
    ("title_bad_char_unicode", _top("title", "Tötle")),
    ("title_bad_char_underscore", _top("title", "Snake_Case")),
    ("title_leading_space", _top("title", " Owls")),
    ("title_trailing_space", _top("title", "Owls ")),
    ("title_starts_with_punctuation", _top("title", "-Owls")),
    ("title_over_120_chars", _top("title", "A" * 121)),
    ("title_reserved_index", _top("title", "Index")),
    ("title_reserved_contradictions", _top("title", "Contradictions")),
    # -- summary -------------------------------------------------------------
    ("summary_empty", _top("summary", "")),
    ("summary_wrong_type", _top("summary", ["text"])),
    # -- sections -------------------------------------------------------------
    ("sections_wrong_type", _top("sections", {})),
    ("section_not_an_object", _top("sections", ["plain string"])),
    ("section_missing_heading", _section_drop_heading),
    ("section_missing_body", _section_drop_body),
    ("section_unknown_key", _section_unknown_key),
    ("section_heading_empty", _section("heading", "")),
    ("section_heading_multiline", _section("heading", "two\nlines")),
    ("section_heading_reserved_claims", _section("heading", "Claims")),
    ("section_heading_reserved_links", _section("heading", "Links")),
    ("section_heading_reserved_references", _section("heading", "References")),
    ("section_duplicate_headings", _duplicate_headings),
    ("section_body_empty", _section("body", "")),
    ("section_body_line_starts_with_hash", _section("body", "fine line\n# sneaky heading")),
    ("section_body_only_hash_line", _section("body", "# Top")),
    # -- claims ----------------------------------------------------------------
    ("claims_wrong_type", _top("claims", "claims")),
    ("claim_not_an_object", _top("claims", ["plain string"])),
    ("claim_missing_text", _claim_drop("text")),
    ("claim_missing_citekeys", _claim_drop("citekeys")),
    ("claim_missing_quotes", _claim_drop("quotes")),
    ("claim_unknown_key", _claim_unknown_key),
    ("claim_text_empty", _claim("text", "")),
    ("claim_text_multiline", _claim("text", "first\nsecond")),
    ("claim_text_contains_citation_marker", _claim("text", "supported claim [@aa2020a] inline")),
    ("claim_text_starts_with_dash", _claim("text", "- bulleted claim")),
    ("claim_text_starts_with_gt", _claim("text", "> quoted claim")),
    ("claim_zero_citekeys", _claim("citekeys", [])),
    ("claim_citekeys_wrong_type", _claim("citekeys", "aa2020a")),
    ("claim_citekey_bad_charset", _claim("citekeys", ["bad citekey!"])),
    ("claim_citekey_empty_string", _claim("citekeys", [""])),
    ("claim_duplicate_citekeys", _duplicate_citekeys),
    ("claim_zero_quotes", _claim("quotes", [])),
    ("claim_quotes_wrong_type", _claim("quotes", {})),
    # -- quotes -----------------------------------------------------------------
    ("quote_not_an_object", _claim("quotes", ["plain string"])),
    ("quote_missing_citekey", _quote_drop("citekey")),
    ("quote_missing_text", _quote_drop("text")),
    ("quote_unknown_key", _quote_unknown_key),
    ("quote_citekey_not_in_claim", _quote("citekey", "FOREIGN2099key")),
    ("quote_text_empty", _quote("text", "")),
    ("quote_text_multiline", _quote("text", "first\nsecond")),
    # -- links --------------------------------------------------------------------
    ("links_wrong_type", _top("links", 7)),
    ("link_entry_wrong_type", _top("links", [3])),
    ("link_entry_empty", _top("links", [""])),
    ("link_entry_bad_charset", _top("links", ["Bad/Link"])),
    ("link_entry_leading_space", _top("links", [" Padded"])),
    ("link_entry_trailing_space", _top("links", ["Padded "])),
    # -- contradictions --------------------------------------------------------------
    ("contradictions_wrong_type", _top("contradictions", "x")),
    ("contradiction_not_an_object", _top("contradictions", ["plain string"])),
    (
        "contradiction_missing_citekeys",
        _contra({"existing_claim": "Old stands.", "new_claim": "New differs."}),
    ),
    (
        "contradiction_unknown_key",
        _contra(
            {
                "existing_claim": "Old stands.",
                "new_claim": "New differs.",
                "citekeys": ["aa2020a"],
                "note": "extra",
            }
        ),
    ),
    (
        "contradiction_zero_citekeys",
        _contra({"existing_claim": "Old stands.", "new_claim": "New differs.", "citekeys": []}),
    ),
    (
        "contradiction_citekey_bad_charset",
        _contra(
            {
                "existing_claim": "Old stands.",
                "new_claim": "New differs.",
                "citekeys": ["no good"],
            }
        ),
    ),
    (
        "contradiction_existing_claim_empty",
        _contra({"existing_claim": "", "new_claim": "New differs.", "citekeys": ["aa2020a"]}),
    ),
    (
        "contradiction_new_claim_with_citation_marker",
        _contra(
            {
                "existing_claim": "Old stands.",
                "new_claim": "New differs [@aa2020a] inline.",
                "citekeys": ["aa2020a"],
            }
        ),
    ),
    (
        "contradiction_new_claim_multiline",
        _contra(
            {
                "existing_claim": "Old stands.",
                "new_claim": "first\nsecond",
                "citekeys": ["aa2020a"],
            }
        ),
    ),
]


@pytest.mark.parametrize("case", INVALID_CASES, ids=[c[0] for c in INVALID_CASES])
def test_req_011__invalid_input_raises_article_schema_error(case):
    _, mutate = case
    d = make_article_dict()
    out = mutate(d)
    text = out if isinstance(out, str) else json.dumps(d)
    with pytest.raises(ArticleSchemaError):
        parse_article_json(text)


def test_req_011__error_message_names_offending_claim_and_quote_path():
    d = make_article_dict(n_claims=2)
    d["claims"][1]["quotes"][0]["citekey"] = "FOREIGN" + rand_citekey()
    with pytest.raises(ArticleSchemaError) as excinfo:
        parse_article_json(json.dumps(d))
    message = str(excinfo.value)
    assert "claims[1]" in message
    assert "quotes[0]" in message


def test_req_011__error_message_names_title_path():
    d = make_article_dict()
    d["title"] = ""
    with pytest.raises(ArticleSchemaError) as excinfo:
        parse_article_json(json.dumps(d))
    assert "title" in str(excinfo.value)


def test_req_011__error_message_names_section_path():
    d = make_article_dict()
    first = dict(d["sections"][0])
    d["sections"] = [first, dict(first)]
    with pytest.raises(ArticleSchemaError) as excinfo:
        parse_article_json(json.dumps(d))
    assert "sections[" in str(excinfo.value)


# ====================================================================
# REQ-012 - code-fence tolerance
# ====================================================================


def test_req_012__json_tagged_fence_parses_identically():
    d = make_article_dict()
    text = json.dumps(d)
    plain = parse_article_json(text)
    assert parse_article_json(f"```json\n{text}\n```") == plain
    assert plain == expected_article_from_dict(d)


def test_req_012__bare_fence_parses_identically():
    d = make_article_dict()
    text = json.dumps(d)
    assert parse_article_json(f"```\n{text}\n```") == parse_article_json(text)


def test_req_012__outer_whitespace_around_fence_is_tolerated():
    d = make_article_dict()
    text = json.dumps(d)
    fenced = f"\n  \n```json\n{text}\n```\n\n  "
    assert parse_article_json(fenced) == expected_article_from_dict(d)


def test_req_012__prose_before_fence_raises():
    text = json.dumps(make_article_dict())
    with pytest.raises(ArticleSchemaError):
        parse_article_json(f"Here is the article you asked for:\n```json\n{text}\n```")


def test_req_012__prose_after_fence_raises():
    text = json.dumps(make_article_dict())
    with pytest.raises(ArticleSchemaError):
        parse_article_json(f"```json\n{text}\n```\nHope that helps!")


def test_req_012__unclosed_fence_raises():
    text = json.dumps(make_article_dict())
    with pytest.raises(ArticleSchemaError):
        parse_article_json(f"```json\n{text}")


def test_req_012__double_fence_pair_raises():
    text = json.dumps(make_article_dict())
    with pytest.raises(ArticleSchemaError):
        parse_article_json(f"```\n```json\n{text}\n```\n```")
