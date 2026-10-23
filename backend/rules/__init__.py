"""Deterministic allergen and label rules. Pure functions over config/; no LLM, no I/O beyond config."""
import json
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

CONFIG = Path(__file__).resolve().parents[1] / "config"

AFFECTED = {"HOLD", "HOLD_RELABEL", "CLAIM_CONFLICT", "SHIPPED_ESCALATE", "UNCERTAIN_ESCALATE"}
HOLDABLE = {"HOLD", "HOLD_RELABEL", "CLAIM_CONFLICT"}
SHIPPED_STATUSES = {"DEPARTED", "DELIVERED"}


@lru_cache
def _allergen_config() -> dict:
    return json.loads((CONFIG / "allergens.json").read_text(encoding="utf-8"))


@lru_cache
def _claims() -> list[dict]:
    return json.loads((CONFIG / "claims.json").read_text(encoding="utf-8"))["claims"]


@lru_cache
def _patterns() -> list[tuple[re.Pattern, dict]]:
    terms = sorted(_allergen_config()["terms"], key=lambda t: len(t["term"]), reverse=True)
    return [(re.compile(rf"\b{re.escape(t['term'])}(?:s|es)?\b", re.IGNORECASE), t) for t in terms]


def allergens_in(ingredient_text: str | None) -> list[dict]:
    """Major allergens named in `ingredient_text`: [{allergen, term, rule_id}], one per allergen, in text order."""
    text = ingredient_text or ""
    hits = []
    for pattern, term in _patterns():
        for m in pattern.finditer(text):
            text = text[:m.start()] + " " * (m.end() - m.start()) + text[m.end():]  # mask the span
            if term["allergen"]:
                hits.append((m.start(), term))
    seen, out = set(), []
    for _, term in sorted(hits, key=lambda h: h[0]):
        if term["allergen"] not in seen:
            seen.add(term["allergen"])
            out.append({"allergen": term["allergen"], "term": term["term"], "rule_id": term["rule_id"]})
    return out


def canonical(allergen: str) -> str:
    found = allergens_in(allergen)
    return found[0]["allergen"] if found else allergen.strip().lower()


@dataclass
class Decision:
    decision: str
    rule_ids: list[str]
    rationale: str
    uncertainty_flags: list[str] = field(default_factory=list)


def decide_batch(label: dict | None, added_allergens: list[dict] | None, location_state: list[dict],
                 shipment_state: list[dict], *, uncertain: bool = False) -> Decision:
    """Decide one finished batch.

    label: sim label row or None if unknown. added_allergens: [{allergen, rule_id}] from the notice, or
    None if they could not be determined. location_state: [{location, qty, status}].
    shipment_state: [{shipment_id, status, qty, ...}] lines carrying this batch.
    uncertain: the extraction carried an uncertainty flag (the only way the LLM can influence this).
    """
    if label is None or added_allergens is None:
        missing = "label" if label is None else "added allergens"
        return Decision("UNCERTAIN_ESCALATE", ["UNC-INPUT-MISSING"], f"Cannot decide: {missing} unknown.")
    if not added_allergens:
        return Decision("NO_IMPACT", ["NO-NEW-ALLERGEN"], "The change adds no major allergen.")

    added = {canonical(a["allergen"]): a for a in added_allergens}
    declared = {canonical(a) for a in label["contains"]}
    precautionary = {canonical(a) for a in label["may_contain"]}
    undeclared = [a for a in added if a not in declared]
    only_precautionary = [a for a in undeclared if a in precautionary]
    missing = [a for a in undeclared if a not in precautionary]
    broken = [
        c for c in _claims()
        if any(claim.strip().lower() in c["label_text"] for claim in label["claims"]) and any(a in c["broken_by"] for a in added)
    ]
    if not undeclared and not broken:
        return Decision("NO_IMPACT", ["LBL-ALREADY-DECLARED"],
                        f"Label already declares {', '.join(sorted(added))}.")

    label_rules = [c["rule_id"] for c in broken] + (["LBL-MISSING-ALLERGEN"] if missing else []) \
        + (["LBL-PRECAUTIONARY-ONLY"] if only_precautionary else [])
    problem = "; ".join(
        ([f"{', '.join(c['label_text'][0] for c in broken)} claim broken by {', '.join(sorted(added))}"] if broken else [])
        + ([f"label does not declare {', '.join(missing)}"] if missing else [])
        + ([f"{', '.join(only_precautionary)} only in may-contain"] if only_precautionary else [])
    )

    if uncertain:
        return Decision("UNCERTAIN_ESCALATE", ["UNC-LLM-FLAG", *label_rules],
                        f"Extraction is uncertain; {problem}.", ["LLM_UNCERTAIN"])
    shipped = [s["shipment_id"] for s in shipment_state if s["status"] in SHIPPED_STATUSES]
    if shipped:
        return Decision("SHIPPED_ESCALATE", ["SHP-ALREADY-SHIPPED", *label_rules],
                        f"{problem.capitalize()}; already shipped on {', '.join(shipped)}.")
    on_hand = sum(loc["qty"] for loc in location_state)
    open_lines = [s for s in shipment_state if s["status"] not in SHIPPED_STATUSES]
    if on_hand <= 0 and not open_lines:
        return Decision("NOT_IN_SCOPE", ["INV-NO-STOCK", *label_rules], f"{problem.capitalize()}; no stock or open shipments.")
    if broken:
        return Decision("CLAIM_CONFLICT", label_rules, f"{problem.capitalize()}.")
    if missing:
        return Decision("HOLD_RELABEL", label_rules, f"{problem.capitalize()}.")
    return Decision("HOLD", label_rules, f"{problem.capitalize()}; hold for QA review.")
