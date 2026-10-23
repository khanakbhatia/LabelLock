"""PDF text with page numbers, and the deterministic evidence check on LLM output."""
import copy
from pathlib import Path

from pypdf import PdfReader

CRITICAL_FIELDS = ("material", "new_ingredient", "effective_lot")


def pdf_pages(paths: list[str | Path]) -> list[str]:
    """Text of every page of every PDF, in order. Page N in evidence is index N-1 of this list."""
    pages = []
    for path in paths:
        pages.extend(page.extract_text() or "" for page in PdfReader(path).pages)
    return pages


def _norm(text: str) -> str:
    # PDF extraction breaks lines arbitrarily; only whitespace is normalised, wording must match exactly.
    return " ".join(text.split())


def check_evidence(fields: dict, email_text: str, pages: list[str]) -> tuple[dict, list[str]]:
    """Downgrade FOUND fields whose quote is not verbatim in the cited source to AMBIGUOUS.

    Returns (checked fields, names of downgraded fields). Input is not modified.
    """
    checked, downgraded = copy.deepcopy(fields), []
    for name, f in checked.items():
        if f.get("status") != "FOUND":
            continue
        ev = f.get("evidence") or {}
        quote = _norm(ev.get("quote") or "")
        if ev.get("source") == "email":
            source_text = email_text
        elif ev.get("source") == "attachment" and isinstance(ev.get("page"), int) and 1 <= ev["page"] <= len(pages):
            source_text = pages[ev["page"] - 1]
        else:
            source_text = ""
        if not quote or quote not in _norm(source_text):
            f["status"] = "AMBIGUOUS"
            downgraded.append(name)
    return checked, downgraded


def unresolved_critical(fields: dict) -> list[str]:
    """A notice may change only the precautionary statement; then no new_ingredient is needed."""
    found = {name for name, f in fields.items() if f.get("status") == "FOUND"}
    required = [n for n in CRITICAL_FIELDS if not (n == "new_ingredient" and "may_contain" in found)]
    return [name for name in required if name not in found]
