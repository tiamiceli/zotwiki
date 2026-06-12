"""M2 / compiler with a fake LLM: prompt construction, update mode, and
citekey gating.  Black-box per docs/contract.md SS7.1 and SS5; the store is
an HTTPZoteroStore against the M1 fake server (conftest), the LLM is the
prompt-recording FakeLLM.  Covers REQ-013, REQ-014, REQ-015.
"""
from __future__ import annotations

import dataclasses
import json
import random
import string

import pytest

from zotwiki.errors import ArticleSchemaError, CitekeyNotFoundError

from m2_helpers import (
    FakeLLM,
    expected_article_from_dict,
    make_article_dict,
    rand_citekey,
    rand_key,
    rand_word,
)

FULLTEXT_PROMPT_LIMIT = None  # bound by _require_m2_surface
Compiler = None
CompileResult = None
LLMClient = None
article_to_json_dict = None


@pytest.fixture(scope="module", autouse=True)
def _require_m2_surface():
    """Bind the M2 surface (contract SS1.1) at test time, so its absence is
    a per-test contract failure rather than a collection error that would
    abort the whole run (including the green M1 suite)."""
    global FULLTEXT_PROMPT_LIMIT, Compiler, CompileResult, LLMClient, article_to_json_dict
    from zotwiki.compiler import (
        FULLTEXT_PROMPT_LIMIT as limit_,
        Compiler as compiler_,
        CompileResult as compile_result_,
    )
    from zotwiki.llm import LLMClient as llm_client_, article_to_json_dict as a2j_

    FULLTEXT_PROMPT_LIMIT = limit_
    Compiler = compiler_
    CompileResult = compile_result_
    LLMClient = llm_client_
    article_to_json_dict = a2j_

# ====================================================================
# REQ-013 - compile a new article
# ====================================================================


def test_req_013__fulltext_prompt_limit_is_contract_constant():
    assert FULLTEXT_PROMPT_LIMIT == 20000


def test_req_013__fake_llm_satisfies_the_llmclient_protocol():
    assert isinstance(FakeLLM("x"), LLMClient)
    assert not isinstance(object(), LLMClient)


def test_req_013__prompt_has_citekey_title_and_truncated_fulltext(fake_zotero, zstore):
    key = rand_key()
    citekey = rand_citekey()
    title = f"Study of {rand_word()} {rand_word()}"
    head = "".join(random.choices(string.ascii_lowercase, k=FULLTEXT_PROMPT_LIMIT))
    tail_marker = "XTAILMARKERX" + rand_word(8, string.ascii_uppercase)
    fake_zotero.add_item(
        key, title=title, citekey=citekey, date="2020", fulltext=head + " " + tail_marker
    )
    store, _ = zstore()
    article_dict = make_article_dict()
    llm = FakeLLM(json.dumps(article_dict))

    result = Compiler(store, llm).compile([key])

    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    assert citekey in prompt
    assert title in prompt
    assert head in prompt  # exactly the first FULLTEXT_PROMPT_LIMIT chars
    assert tail_marker not in prompt  # ...and nothing beyond them
    expected_article, _ = expected_article_from_dict(article_dict)
    assert isinstance(result, CompileResult)
    assert result.article == expected_article
    assert result.contradictions == ()
    assert result == CompileResult(article=expected_article, contradictions=())


def test_req_013__short_fulltext_is_included_whole(fake_zotero, zstore):
    key = rand_key()
    citekey = rand_citekey()
    fulltext = f"Sphinx of {rand_word()} quartz, judge my {rand_word()} vow."
    fake_zotero.add_item(key, title="Short Fulltext Item", citekey=citekey, fulltext=fulltext)
    store, _ = zstore()
    llm = FakeLLM(json.dumps(make_article_dict()))

    Compiler(store, llm).compile([key])

    assert fulltext in llm.prompts[0]


def test_req_013__prompt_covers_every_item(fake_zotero, zstore):
    items = []
    for _ in range(3):
        key = rand_key()
        citekey = rand_citekey()
        title = f"Paper {rand_word().capitalize()} {rand_word()}"
        fulltext = f"unique {rand_word()} fulltext {rand_word()} body"
        fake_zotero.add_item(key, title=title, citekey=citekey, fulltext=fulltext)
        items.append((key, citekey, title, fulltext))
    store, _ = zstore()
    llm = FakeLLM(json.dumps(make_article_dict()))

    Compiler(store, llm).compile([key for key, *_ in items])

    assert len(llm.prompts) == 1
    prompt = llm.prompts[0]
    for _, citekey, title, fulltext in items:
        assert citekey in prompt
        assert title in prompt
        assert fulltext in prompt


def test_req_013__item_without_fulltext_still_compiles(fake_zotero, zstore):
    key = rand_key()
    citekey = rand_citekey()
    title = f"No Fulltext {rand_word()}"
    fake_zotero.add_item(key, title=title, citekey=citekey)  # no fulltext: probe -> 404
    store, _ = zstore()
    article_dict = make_article_dict()
    llm = FakeLLM(json.dumps(article_dict))

    result = Compiler(store, llm).compile([key])

    assert citekey in llm.prompts[0]
    assert title in llm.prompts[0]
    assert result.article == expected_article_from_dict(article_dict)[0]
    assert result.contradictions == ()


@pytest.mark.parametrize(
    "bad_output",
    [
        "I could not produce JSON, sorry.",
        json.dumps({"title": "Almost"}),  # schema-invalid JSON object
    ],
    ids=["non_json", "schema_invalid"],
)
def test_req_013__invalid_llm_output_raises_article_schema_error(
    fake_zotero, zstore, bad_output
):
    key = rand_key()
    fake_zotero.add_item(key, title="Bad Output Probe", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()

    with pytest.raises(ArticleSchemaError):
        Compiler(store, FakeLLM(bad_output)).compile([key])


def test_req_013__compile_result_is_frozen(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(key, title="Frozen Probe", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()
    article_dict = make_article_dict()

    result = Compiler(store, FakeLLM(json.dumps(article_dict))).compile([key])

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.article = None


# ====================================================================
# REQ-014 - compile in update mode
# ====================================================================


def _existing_article():
    """A runtime-random canonical Article to pass as `existing`."""
    return expected_article_from_dict(make_article_dict())[0]


def test_req_014__update_prompt_embeds_existing_article_json(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(key, title="Update Source", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()
    existing = _existing_article()
    response = make_article_dict(
        title=existing.title,
        contradictions=[
            {
                "existing_claim": "The old result holds.",
                "new_claim": "The old result fails at scale.",
                "citekeys": [rand_citekey()],
            }
        ],
    )
    llm = FakeLLM(json.dumps(response))

    Compiler(store, llm).compile([key], existing=existing)

    assert len(llm.prompts) == 1
    embedded = json.dumps(article_to_json_dict(existing), sort_keys=True)
    assert embedded in llm.prompts[0]


def test_req_014__contradictions_are_parsed_in_order(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(key, title="Contra Source", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()
    existing = _existing_article()
    contradictions = [
        {
            "existing_claim": f"Existing {rand_word()} stands.",
            "new_claim": f"New {rand_word()} disagrees.",
            # distinct by construction, deliberately unsorted in the payload
            "citekeys": [f"z{rand_citekey()}", f"a{rand_citekey()}"],
        },
        {
            "existing_claim": f"Existing {rand_word()} persists.",
            "new_claim": f"New {rand_word()} contradicts.",
            "citekeys": [rand_citekey()],
        },
    ]
    response = make_article_dict(title=existing.title, contradictions=contradictions)
    llm = FakeLLM(json.dumps(response))

    result = Compiler(store, llm).compile([key], existing=existing)

    expected_article, expected_contradictions = expected_article_from_dict(response)
    assert len(expected_contradictions) == 2  # non-vacuous: both survive parsing
    assert result.contradictions == expected_contradictions
    assert result.article == expected_article  # compiler does not merge


def test_req_014__contradictions_without_existing_raise(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(key, title="Illegal Contra", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()
    response = make_article_dict(
        contradictions=[
            {
                "existing_claim": "Nothing pre-exists.",
                "new_claim": "Yet here is a contradiction.",
                "citekeys": [rand_citekey()],
            }
        ]
    )

    with pytest.raises(ArticleSchemaError):
        Compiler(store, FakeLLM(json.dumps(response))).compile([key])


def test_req_014__empty_contradictions_array_is_fine_without_existing(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(key, title="Empty Contra", citekey=rand_citekey(), fulltext="text")
    store, _ = zstore()
    response = make_article_dict(contradictions=[])

    result = Compiler(store, FakeLLM(json.dumps(response))).compile([key])

    assert result.contradictions == ()
    assert result.article == expected_article_from_dict(response)[0]


# ====================================================================
# REQ-015 - items without citekeys cannot be compiled
# ====================================================================


def test_req_015__missing_citekey_raises_before_any_llm_call(fake_zotero, zstore):
    key = rand_key()
    fake_zotero.add_item(
        key, title="Keyless Item", extra="just a note, no citation key here", fulltext="text"
    )
    store, _ = zstore()
    llm = FakeLLM(json.dumps(make_article_dict()))

    with pytest.raises(CitekeyNotFoundError) as excinfo:
        Compiler(store, llm).compile([key])

    assert key in str(excinfo.value)  # names the offending Zotero key
    assert llm.prompts == []  # no LLM call was made


def test_req_015__one_keyless_item_among_good_ones_still_blocks(fake_zotero, zstore):
    good_key = rand_key()
    fake_zotero.add_item(good_key, title="Good Item", citekey=rand_citekey(), fulltext="text")
    bad_key = rand_key()
    fake_zotero.add_item(bad_key, title="Bad Item", extra="nothing useful", fulltext="text")
    store, _ = zstore()
    llm = FakeLLM(json.dumps(make_article_dict()))

    with pytest.raises(CitekeyNotFoundError) as excinfo:
        Compiler(store, llm).compile([good_key, bad_key])

    assert bad_key in str(excinfo.value)
    assert llm.prompts == []
