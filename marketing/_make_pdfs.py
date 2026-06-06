"""
Render every marketing page to PDF for offline review.

Uses headless Chrome (--print-to-pdf), which honours the live CSS.
Falls back to Edge if Chrome isn't found.

Output: marketing/_pdf/
  - 01_index.pdf, 02_pricing.pdf, ... (one PDF per page)
  - 00_all_marketing_pages.pdf         (merged, for one-shot printing)
"""
from __future__ import annotations
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

MARKETING = Path(__file__).resolve().parent
OUT       = MARKETING / "_pdf"

PAGES = [
    "index.html",
    "pricing.html",
    "checkout.html",
    "contact.html",
    "privacy.html",
    "terms.html",
    "refund.html",
    "shipping.html",
]

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_browser() -> str:
    for path in BROWSERS:
        if Path(path).exists():
            return path
    sys.exit("No Chrome or Edge found in standard locations.")


def render_one(browser: str, page: str, out_pdf: Path) -> bool:
    src_url = "file:///" + str((MARKETING / page).resolve()).replace("\\", "/")
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={out_pdf}",
        src_url,
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True, timeout=60)
        return out_pdf.exists() and out_pdf.stat().st_size > 0
    except subprocess.CalledProcessError as e:
        sys.stderr.write(f"  Chrome failed for {page}: {e.stderr[:300] if e.stderr else e}\n")
        return False
    except subprocess.TimeoutExpired:
        sys.stderr.write(f"  Timed out rendering {page}\n")
        return False


def merge(pdfs: list[Path], out: Path) -> None:
    from pypdf import PdfWriter
    w = PdfWriter()
    for p in pdfs:
        w.append(str(p))
    with out.open("wb") as f:
        w.write(f)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    # Clean prior output so old pages don't linger
    for old in OUT.glob("*.pdf"):
        old.unlink()

    browser = find_browser()
    print(f"Using: {browser}")
    print()

    rendered: list[Path] = []
    for i, page in enumerate(PAGES, start=1):
        out_pdf = OUT / f"{i:02d}_{page.replace('.html', '.pdf')}"
        ok = render_one(browser, page, out_pdf)
        marker = "  " if ok else "!!"
        size = out_pdf.stat().st_size if out_pdf.exists() else 0
        print(f"  {marker} {page:18}  ->  {out_pdf.name:30}  {size:>7} bytes")
        if ok:
            rendered.append(out_pdf)

    print()
    if len(rendered) >= 2:
        merged = OUT / "00_all_marketing_pages.pdf"
        merge(rendered, merged)
        print(f"Merged: {merged}  ({merged.stat().st_size:,} bytes)")

    print()
    print(f"All output in: {OUT}")

    # Open the folder so the user can grab the PDFs
    try:
        os.startfile(str(OUT))
    except Exception:
        pass


if __name__ == "__main__":
    main()
