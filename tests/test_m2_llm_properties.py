"""M2 / LLM boundary: hypothesis property tests.

Expectations are derived independently from docs/contract.md SS5.2-SS5.5
over runtime-generated canonical Articles (random unicode summaries, claim
and quote texts, citekeys, titles), so a hardcoded or constant-returning
implementation cannot pass.  Covers REQ-010 (parse + canonicalization),
REQ-011 (missing/unknown keys always raise), REQ-012 (fence tolerance),
and the contract SS5.5 round-trip law consumed by REQ-014.
"""
from __future__ import annotations

import json
import string

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from zotwiki.errors import ArticleSchemaError

from m2_helpers import (
    REQUIRED_KEYS,
    article_to_plain_dict,
    articles_st,
    expected_article_from_dict,
    messy_article_payloads,
)

SETTINGS = settings(deadline=None, max_examples=40)

article_to_json_dict = None  # bound by _require_m2_surface
parse_article_json = None


@pytest.fixture(scope="module", autouse=True)
def _require_m2_surface():
    """Bind the M2 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1 suite)."""
    global article_to_json_dict, parse_article_json
    from zotwiki.llm import article_to_json_dict as a2j, parse_article_json as paj

    article_to_json_dict = a2j
    parse_article_json = paj


# ----- contract SS5.5 round-trip law (used by REQ-014's prompt embedding) --


@SETTINGS
@given(article=articles_st())
def test_req_014__article_to_json_dict_roundtrip_law(article):
    d = article_to_json_dict(article)
    assert isinstance(d, dict)
    parsed, contradictions = parse_article_json(json.dumps(d))
    assert parsed == article
    assert contradictions == ()


@SETTINGS
@given(article=articles_st())
def test_req_014__article_to_json_dict_has_exactly_the_five_required_keys(article):
    d = article_to_json_dict(article)
    assert set(d.keys()) == set(REQUIRED_KEYS)


@SETTINGS
@given(article=articles_st())
def test_req_014__article_to_json_dict_matches_independent_schema_reading(article):
    # Serialize with the unit under test, re-read with the test suite's own
    # SS5.2-SS5.4 re-implementation: must reproduce the article exactly.
    plain = json.loads(json.dumps(article_to_json_dict(article)))
    rebuilt, contradictions = expected_article_from_dict(plain)
    assert rebuilt == article
    assert contradictions == ()


# ----- REQ-010: parse normalizes and canonicalizes arbitrary valid input ---


@SETTINGS
@given(payload=messy_article_payloads())
def test_req_010__parse_canonicalizes_messy_valid_payloads(payload):
    article, d = payload
    parsed, contradictions = parse_article_json(json.dumps(d))
    assert parsed == article
    assert contradictions == ()


@SETTINGS
@given(article=articles_st())
def test_req_010__parse_accepts_independently_serialized_articles(article):
    # The dict here is built by the test suite, not by article_to_json_dict,
    # so parse_article_json is exercised on its own.
    parsed, contradictions = parse_article_json(json.dumps(article_to_plain_dict(article)))
    assert parsed == article
    assert contradictions == ()


# ----- REQ-012: fence tolerance as a property ------------------------------


@SETTINGS
@given(
    article=articles_st(),
    tag=st.sampled_from(["json", ""]),
    lead=st.sampled_from(["", "\n", "  \n"]),
    trail=st.sampled_from(["", "\n", "\n  "]),
)
def test_req_012__fence_wrapping_parses_identically_property(article, tag, lead, trail):
    text = json.dumps(article_to_plain_dict(article))
    fenced = f"{lead}```{tag}\n{text}\n```{trail}"
    assert parse_article_json(fenced) == parse_article_json(text) == (article, ())


# ----- REQ-011: structural violations always raise, whatever the article ---


@SETTINGS
@given(article=articles_st(), key=st.sampled_from(REQUIRED_KEYS))
def test_req_011__missing_required_key_always_raises(article, key):
    d = article_to_plain_dict(article)
    del d[key]
    with pytest.raises(ArticleSchemaError):
        parse_article_json(json.dumps(d))


@SETTINGS
@given(
    article=articles_st(),
    extra=st.text(alphabet=string.ascii_lowercase + "_", min_size=1, max_size=10).filter(
        lambda name: name not in REQUIRED_KEYS and name != "contradictions"
    ),
)
def test_req_011__unknown_top_level_key_always_raises(article, extra):
    d = article_to_plain_dict(article)
    d[extra] = "surprise"
    with pytest.raises(ArticleSchemaError):
        parse_article_json(json.dumps(d))
