"""Regenerate the demo spec PDF with the standard library only:
    python tests/fixtures/notices/make_spec_pdf.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))  # backend/
from scenarios.pdf import make_pdf  # noqa: E402

PAGES = [
    ["Valley Ingredients - Product Specification", "Product: Lecithin, code RM-114", "Revision: 4",
     "Composition: soy lecithin, effective from lot VL-2291 onward", "Previous composition: sunflower lecithin"],
    ["Allergen statement", "Contains: soy", "Storage: cool and dry, below 25 C"],
]


if __name__ == "__main__":
    path = Path(__file__).with_name("RM-114_spec_rev4.pdf")
    path.write_bytes(make_pdf(PAGES))
    print(f"wrote {path}")
