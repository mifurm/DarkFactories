#!/usr/bin/env python
"""Render a .pptx to PDF (headless LibreOffice) and PNG pages (PyMuPDF) for visual QA.

    /Users/michalfu/Dev/SwarmAI/.venv/bin/python /Users/michalfu/Dev/SwarmAI/tools/deckkit/render.py deck.pptx --out /tmp/deckqa [--dpi 80] [--sheet]

Prints the PDF path and one PNG path per slide (look at them with an image-capable viewer).
--sheet also writes contact sheets (3x3 thumbnails) for a quick overview.
Never uses GUI automation of Office/Keynote: only `soffice --headless`.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

import pymupdf
from PIL import Image, ImageDraw


def _soffice(args: list[str]) -> None:
    soffice = shutil.which("soffice") or "/opt/homebrew/bin/soffice"
    res = subprocess.run([soffice, "--headless", *args], capture_output=True, text=True, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"soffice failed ({res.returncode}): {res.stdout}\n{res.stderr}")


def render(pptx: str | Path, out_dir: str | Path, dpi: int = 80, sheet: bool = False, keep_pdf_next_to_pptx: bool = False, roundtrip: bool = False) -> list[Path]:
    """pptx -> pdf -> png pages with headless LibreOffice + PyMuPDF. deckkit sets invertIfNegative=0 on bar series, so the direct
    export is faithful. (`roundtrip=True` goes pptx -> odp -> pdf: only needed for hand-made charts without that flag; it turns
    diagonal connectors into elbow lines, so don't use it for the shipped PDF.)"""
    pptx = Path(pptx).resolve()
    out = Path(out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    pdf = out / (pptx.stem + ".pdf")
    if not roundtrip:
        _soffice(["--convert-to", "pdf", "--outdir", str(out), str(pptx)])
    else:
        odp_dir = out / "_odp"
        odp_dir.mkdir(exist_ok=True)
        _soffice(["--convert-to", "odp", "--outdir", str(odp_dir), str(pptx)])
        _soffice(["--convert-to", "pdf", "--outdir", str(out), str(odp_dir / (pptx.stem + ".odp"))])
        shutil.rmtree(odp_dir, ignore_errors=True)
    if not pdf.exists():
        raise RuntimeError(f"no PDF produced at {pdf}")
    if keep_pdf_next_to_pptx:
        shutil.copy2(pdf, pptx.with_suffix(".pdf"))
    doc = pymupdf.open(pdf)
    pages: list[Path] = []
    for i, page in enumerate(doc, 1):
        pix = page.get_pixmap(dpi=dpi)
        p = out / f"{pptx.stem}-p{i:02d}.png"
        pix.save(p)
        pages.append(p)
    sheets: list[Path] = []
    if sheet and pages:
        cols, rows = 3, 3
        tw = 640
        for si in range(0, len(pages), cols * rows):
            chunk = pages[si : si + cols * rows]
            thumbs = []
            for p in chunk:
                im = Image.open(p).convert("RGB")
                th = int(im.height * tw / im.width)
                thumbs.append(im.resize((tw, th)))
            th = thumbs[0].height
            sheet_img = Image.new("RGB", (cols * (tw + 12) + 12, rows * (th + 12) + 12), (230, 232, 236))
            d = ImageDraw.Draw(sheet_img)
            for k, im in enumerate(thumbs):
                r, c = divmod(k, cols)
                x, y = 12 + c * (tw + 12), 12 + r * (th + 12)
                sheet_img.paste(im, (x, y))
                d.rectangle([x, y, x + 46, y + 22], fill=(0, 0, 0))
                d.text((x + 6, y + 5), f"{si + k + 1}", fill=(255, 255, 255))
            sp = out / f"{pptx.stem}-sheet-{si // (cols * rows) + 1}.png"
            sheet_img.save(sp)
            sheets.append(sp)
    print(f"PDF: {pdf}")
    for p in pages + sheets:
        print(p)
    return pages + sheets


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("pptx")
    ap.add_argument("--out", default="/tmp/deckqa")
    ap.add_argument("--dpi", type=int, default=80)
    ap.add_argument("--sheet", action="store_true")
    ap.add_argument("--pdf-next-to-pptx", action="store_true", help="also copy the PDF next to the .pptx")
    ap.add_argument("--roundtrip", action="store_true", help="pptx->odp->pdf (only for hand-made charts lacking invertIfNegative=0)")
    a = ap.parse_args()
    try:
        render(a.pptx, a.out, a.dpi, a.sheet, a.pdf_next_to_pptx, a.roundtrip)
    except Exception as e:  # noqa: BLE001
        print(f"render failed: {e}", file=sys.stderr)
        sys.exit(1)
