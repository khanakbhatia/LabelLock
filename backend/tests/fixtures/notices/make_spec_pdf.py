"""Regenerate the demo spec PDF with the standard library only:
    python tests/fixtures/notices/make_spec_pdf.py
"""
from pathlib import Path

PAGES = [
    ["Valley Ingredients - Product Specification", "Product: Lecithin, code RM-114", "Revision: 4",
     "Composition: soy lecithin, effective from lot VL-2291 onward", "Previous composition: sunflower lecithin"],
    ["Allergen statement", "Contains: soy", "Storage: cool and dry, below 25 C"],
]


def make_pdf(pages: list[list[str]]) -> bytes:
    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

    page_ids = [4 + 2 * i for i in range(len(pages))]
    objs = {
        1: "<< /Type /Catalog /Pages 2 0 R >>",
        2: f"<< /Type /Pages /Kids [{' '.join(f'{p} 0 R' for p in page_ids)}] /Count {len(pages)} >>",
        3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    }
    for pid, lines in zip(page_ids, pages):
        stream = "BT /F1 12 Tf 16 TL 72 740 Td " + " ".join(f"({esc(line)}) Tj T*" for line in lines) + " ET"
        objs[pid] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                     f"/Resources << /Font << /F1 3 0 R >> >> /Contents {pid + 1} 0 R >>")
        objs[pid + 1] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n{objs[n]}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offsets[n]:010d} 00000 n \n" for n in sorted(objs)).encode()
    out += f"trailer << /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


if __name__ == "__main__":
    path = Path(__file__).with_name("RM-114_spec_rev4.pdf")
    path.write_bytes(make_pdf(PAGES))
    print(f"wrote {path}")
