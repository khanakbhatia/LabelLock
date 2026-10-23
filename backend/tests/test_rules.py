import json
from pathlib import Path

import pytest

from rules import allergens_in, decide_batch

RULES_DIR = Path(__file__).resolve().parents[1] / "rules"

SOY = [{"allergen": "soy", "rule_id": "ALG-SOY-LECITHIN"}]
STOCK = [{"location": "DC-EAST", "qty": 480, "status": "AVAILABLE"}]


def label(contains=(), may_contain=(), claims=()):
    return {"sku": "X", "version": "1", "ingredient_statement": "", "contains": list(contains),
            "may_contain": list(may_contain), "claims": list(claims)}


@pytest.mark.parametrize("text,expected", [
    ("soy lecithin", [("soy", "ALG-SOY-LECITHIN")]),
    ("Lecithin (soya lecithin)", [("soy", "ALG-SOY-LECITHIN")]),
    ("sunflower lecithin", []),
    ("whey powder, sodium caseinate", [("milk", "ALG-MILK-WHEY")]),
    ("tahini, albumin", [("sesame", "ALG-SESAME-TAHINI"), ("egg", "ALG-EGG-ALBUMIN")]),
    ("durum semolina", [("wheat", "ALG-WHEAT")]),
    ("cocoa butter, oat milk", []),
    ("peanut butter", [("peanuts", "ALG-PEANUT")]),
    ("eggplant, codeine-free", []),
    ("Skim Milk Powder, PEANUTS", [("milk", "ALG-MILK"), ("peanuts", "ALG-PEANUT")]),
    ("", []),
    (None, []),
])
def test_allergens_in(text, expected):
    assert [(a["allergen"], a["rule_id"]) for a in allergens_in(text)] == expected


def test_config_covers_the_nine_major_allergens_and_required_derivatives():
    cfg = json.loads((RULES_DIR.parent / "config" / "allergens.json").read_text())
    assert sorted(cfg["major_allergens"]) == sorted(
        ["milk", "egg", "fish", "crustacean shellfish", "tree nuts", "peanuts", "wheat", "soy", "sesame"])
    terms = {t["term"]: t["allergen"] for t in cfg["terms"]}
    for term, allergen in {"soy lecithin": "soy", "whey": "milk", "casein": "milk", "tahini": "sesame",
                           "albumin": "egg", "semolina": "wheat"}.items():
        assert terms[term] == allergen
    assert {t["allergen"] for t in cfg["terms"] if t["allergen"]} == set(cfg["major_allergens"])


def test_no_impact_when_nothing_added():
    d = decide_batch(label(contains=["milk"]), [], STOCK, [])
    assert (d.decision, d.rule_ids) == ("NO_IMPACT", ["NO-NEW-ALLERGEN"])


def test_no_impact_when_label_already_declares():
    d = decide_batch(label(contains=["Soybeans"]), SOY, STOCK, [])
    assert (d.decision, d.rule_ids) == ("NO_IMPACT", ["LBL-ALREADY-DECLARED"])


def test_hold_relabel_when_allergen_undeclared():
    d = decide_batch(label(contains=["milk"]), SOY, STOCK, [])
    assert (d.decision, d.rule_ids) == ("HOLD_RELABEL", ["LBL-MISSING-ALLERGEN"])
    assert "soy" in d.rationale


def test_hold_when_only_precautionary():
    d = decide_batch(label(may_contain=["soy"]), SOY, STOCK, [])
    assert (d.decision, d.rule_ids) == ("HOLD", ["LBL-PRECAUTIONARY-ONLY"])


def test_claim_conflict():
    d = decide_batch(label(claims=["Free from top 9 allergens"]), SOY, STOCK,
                     [{"shipment_id": "L-552", "status": "PLANNED", "qty": 240}])
    assert d.decision == "CLAIM_CONFLICT"
    assert d.rule_ids == ["CLM-FREE-FROM-TOP9", "LBL-MISSING-ALLERGEN"]


def test_claim_not_broken_by_unrelated_allergen():
    d = decide_batch(label(contains=["soy"], claims=["dairy-free"]), SOY, STOCK, [])
    assert d.decision == "NO_IMPACT"


def test_shipped_escalate():
    d = decide_batch(label(contains=["milk"]), SOY, [], [{"shipment_id": "L-500", "status": "DEPARTED", "qty": 10}])
    assert d.decision == "SHIPPED_ESCALATE"
    assert d.rule_ids[0] == "SHP-ALREADY-SHIPPED" and "L-500" in d.rationale


def test_uncertain_escalate_on_missing_inputs_or_llm_flag():
    assert decide_batch(None, SOY, STOCK, []).decision == "UNCERTAIN_ESCALATE"
    assert decide_batch(label(), None, STOCK, []).decision == "UNCERTAIN_ESCALATE"
    d = decide_batch(label(contains=["milk"]), SOY, STOCK, [], uncertain=True)
    assert (d.decision, d.uncertainty_flags) == ("UNCERTAIN_ESCALATE", ["LLM_UNCERTAIN"])
    # an LLM flag cannot create impact where the rules find none
    assert decide_batch(label(contains=["soy"]), SOY, STOCK, [], uncertain=True).decision == "NO_IMPACT"


def test_not_in_scope_without_stock_or_open_shipments():
    d = decide_batch(label(contains=["milk"]), SOY, [{"location": "DC-EAST", "qty": 0, "status": "AVAILABLE"}], [])
    assert (d.decision, d.rule_ids[0]) == ("NOT_IN_SCOPE", "INV-NO-STOCK")


def test_every_batch_decision_value_is_reachable():
    enums = json.loads((RULES_DIR.parents[1] / "contracts" / "enums.json").read_text())["batch_decision"]
    reached = {
        decide_batch(label(contains=["milk"]), [], STOCK, []).decision,
        decide_batch(label(may_contain=["soy"]), SOY, STOCK, []).decision,
        decide_batch(label(contains=["milk"]), SOY, STOCK, []).decision,
        decide_batch(label(claims=["free from top 9 allergens"]), SOY, STOCK, []).decision,
        decide_batch(label(), SOY, [], [{"shipment_id": "L", "status": "DELIVERED", "qty": 1}]).decision,
        decide_batch(None, SOY, STOCK, []).decision,
        decide_batch(label(), SOY, [], []).decision,
    }
    assert reached == set(enums)


def test_rules_package_has_no_llm_imports():
    source = "\n".join(p.read_text() for p in RULES_DIR.rglob("*.py"))
    for forbidden in ("anthropic", "agent.llm", "openai", "import httpx", "requests"):
        assert forbidden not in source


PEANUT_PREC = [{"allergen": "peanuts", "rule_id": "ALG-PEANUT", "precautionary": True}]


def test_new_may_contain_missing_from_label_is_hold_relabel():
    d = decide_batch(label(contains=["milk"]), PEANUT_PREC, STOCK, [])
    assert (d.decision, d.rule_ids) == ("HOLD_RELABEL", ["LBL-MISSING-PRECAUTION"])
    assert "may contain peanuts" in d.rationale


@pytest.mark.parametrize("lbl", [label(may_contain=["peanuts"]), label(contains=["Peanut"])])
def test_new_may_contain_already_on_label_is_no_impact(lbl):
    assert decide_batch(lbl, PEANUT_PREC, STOCK, []).decision == "NO_IMPACT"


def test_may_contain_breaks_a_free_from_claim():
    d = decide_batch(label(claims=["nut-free"]), PEANUT_PREC, STOCK, [])
    assert d.decision == "CLAIM_CONFLICT" and d.rule_ids == ["CLM-NUT-FREE", "LBL-MISSING-PRECAUTION"]


def test_ingredient_wins_over_may_contain_for_the_same_allergen():
    both = SOY + [{"allergen": "soy", "rule_id": "ALG-SOY", "precautionary": True}]
    d = decide_batch(label(may_contain=["soy"]), both, STOCK, [])
    assert (d.decision, d.rule_ids) == ("HOLD", ["LBL-PRECAUTIONARY-ONLY"])  # an ingredient is not cured by may-contain


def test_precautionary_only_notice_is_not_missing_a_critical_field():
    from agent.extract import unresolved_critical
    found = {"status": "FOUND"}
    assert unresolved_critical({"material": found, "effective_lot": found, "may_contain": found,
                                "new_ingredient": {"status": "MISSING"}}) == []
    assert unresolved_critical({"material": found, "effective_lot": found,
                                "new_ingredient": {"status": "MISSING"}, "may_contain": {"status": "MISSING"}}) == ["new_ingredient"]
