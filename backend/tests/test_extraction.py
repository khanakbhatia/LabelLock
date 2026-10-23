from pathlib import Path

import pytest

from agent.extract import check_evidence, pdf_pages, unresolved_critical
from agent.llm import FIELDS, MockLLM, get_llm

NOTICES = Path(__file__).parent / "fixtures" / "notices"
BODY = (NOTICES / "vl2291_body.txt").read_text(encoding="utf-8")
PAGES = pdf_pages([NOTICES / "RM-114_spec_rev4.pdf"])


def found(quote, source="email", page=None):
    return {"value": "v", "status": "FOUND", "confidence": 0.9, "evidence": {"source": source, "page": page, "quote": quote}}


def test_pdf_pages_keep_page_numbers():
    assert len(PAGES) == 2
    assert "Product: Lecithin, code RM-114" in PAGES[0]
    assert "Contains: soy" in PAGES[1] and "RM-114" not in PAGES[1]


def test_verbatim_quotes_stay_found():
    fields = {"a": found("will be supplied as soy lecithin"), "b": found("Product: Lecithin, code RM-114", "attachment", 1)}
    checked, downgraded = check_evidence(fields, BODY, PAGES)
    assert downgraded == [] and checked == fields


@pytest.mark.parametrize("field", [
    found("will be supplied as SOY lecithin"),             # not verbatim
    found("Product: Lecithin, code RM-114", "attachment", 2),  # wrong page
    found("Product: Lecithin, code RM-114", "attachment", 9),  # page out of range
    found("Contains: soy", "email"),                       # wrong source
    found(""),                                             # empty quote
    {"value": "v", "status": "FOUND", "confidence": 0.9, "evidence": None},
])
def test_unverifiable_found_fields_become_ambiguous(field):
    checked, downgraded = check_evidence({"f": field}, BODY, PAGES)
    assert checked["f"]["status"] == "AMBIGUOUS" and downgraded == ["f"]
    assert field["status"] == "FOUND"  # input untouched


def test_whitespace_differences_are_tolerated():
    checked, _ = check_evidence({"f": found("Composition:   soy lecithin,\neffective", "attachment", 1)}, BODY, PAGES)
    assert checked["f"]["status"] == "FOUND"


def test_unresolved_critical_fields():
    fields = {"material": found("x"), "new_ingredient": {"status": "AMBIGUOUS"}, "may_contain": {"status": "MISSING"}}
    assert unresolved_critical(fields) == ["new_ingredient", "effective_lot"]


def test_mock_llm_replays_fixture_and_defaults_to_missing():
    llm = get_llm("mock")
    rec = llm.extract(content_hash="sha256:dba3a429b302a5c6e7acc5d39f422106cc007d5a251532a9bc6b284afc4f1ee0",
                      email_text=BODY, pages=PAGES)
    assert rec["fields"]["effective_lot"]["value"] == "VL-2291"
    assert rec["model"] == "mock:claude-opus-5-5"  # real Claude recording, replayed
    assert check_evidence(rec["fields"], BODY, PAGES)[1] == []  # its quotes are verbatim
    unknown = MockLLM().extract(content_hash="sha256:unknown", email_text="", pages=[])
    assert set(unknown["fields"]) == set(FIELDS)
    assert all(f["status"] == "MISSING" for f in unknown["fields"].values())
