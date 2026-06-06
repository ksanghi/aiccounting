"""
One-shot transform: turn the cloned marketing/ files into AIC-branded copies.

Run once after the directory is cloned. Idempotent — re-running just
re-applies the same substitutions.

Brand model:
  Surface text:    "AI Consultants"
  Legal disclosure (footer small print on every page):
                   "AI Consultants is a proprietorship of Monika Sanghi.
                    Legal name: Analysis and Ideas Consultants."
  Razorpay link:   https://razorpay.me/@aiconsultants
"""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent

# Pages to transform (skip the rwahq/ sub-bundle and any non-pages).
PAGES = [
    "index.html", "pricing.html", "checkout.html", "contact.html",
    "privacy.html", "terms.html", "refund.html", "shipping.html",
]

# Replacements applied in order. Some patterns are crafted to avoid
# disturbing the disclosure line we add at the end.

AIC_BRAND_NAME = "AI Consultants"
AIC_LEGAL_NAME = "Analysis and Ideas Consultants"
AIC_PROPRIETOR = "Monika Sanghi"
RAZORPAY_LINK  = "https://razorpay.me/@aiconsultants"

# Step 1: swap entity names. The existing files have a mix:
#   - "Aashray Sanghi" (nav brand, footer copyright, body text)
#   - "Analysis and Ideas Consultants" (on legal pages we did earlier:
#     privacy.html, terms.html, contact.html — and as the operating-
#     entity disclosure on every page)
# We want the AIC site to read "AI Consultants" everywhere on the
# surface, with the proprietor disclosed only at the footer.

REPLACEMENTS_TEXT = [
    # 'Aashray Sanghi' (sole-prop; "we"  →  'AI Consultants' ("we"
    ('Aashray Sanghi</b>\n    (sole proprietor; "we"',
     f'{AIC_BRAND_NAME}</b> ("we"'),
    # Tagline + descriptive references
    ("Aashray Sanghi", AIC_BRAND_NAME),
    # Previously-AIC pages we did earlier — collapse the long form
    # to the short brand on the SURFACE of the AIC site. The
    # disclosure footer (added below) still carries the full legal
    # name for transparency.
    ("Analysis and Ideas Consultants", AIC_BRAND_NAME),
]

# Step 2: rewrite the operating-entity disclosure footer.
# The old line said "Operated by <b>Analysis and Ideas Consultants</b>".
# Replace with the proprietor disclosure model.

DISCLOSURE_OLD = ('Operated by <b>Analysis and Ideas Consultants</b>.')
DISCLOSURE_NEW = (f'{AIC_BRAND_NAME} is a proprietorship of {AIC_PROPRIETOR}. '
                  f'Legal name: {AIC_LEGAL_NAME}.')

# Step 3: rewrite checkout.html → razorpay.me link.
# We don't bother trying to keep the API-driven checkout — the AIC
# site uses the hosted Payment Page. Replace the whole interactive
# checkout with a static "buy via razorpay.me" landing.


def _transform_text(src: str) -> str:
    out = src
    for old, new in REPLACEMENTS_TEXT:
        out = out.replace(old, new)
    out = out.replace(DISCLOSURE_OLD, DISCLOSURE_NEW)
    return out


def _checkout_static() -> str:
    """Replace the JS-driven checkout with a clean hosted-link landing."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Checkout — {AIC_BRAND_NAME}</title>
<meta name="description" content="Pay {AIC_BRAND_NAME} securely via Razorpay's hosted Payment Page.">
<style>
:root {{
  --bg:#0B1220; --bg-soft:#F8FAFC; --ink:#0F172A; --ink-mute:#475569;
  --line:#E2E8F0; --accent:#0EA5A5; --accent-2:#00D4AA;
}}
* {{ box-sizing:border-box; margin:0; padding:0; }}
html, body {{ font-family:-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; color:var(--ink); -webkit-font-smoothing:antialiased; }}
body {{ background:white; line-height:1.55; }}
a {{ color:var(--accent); text-decoration:none; }}
a:hover {{ text-decoration:underline; }}
.nav {{ position:sticky; top:0; z-index:50; background:rgba(255,255,255,0.95); backdrop-filter:blur(8px); border-bottom:1px solid var(--line); }}
.nav-inner {{ max-width:1120px; margin:0 auto; display:flex; align-items:center; justify-content:space-between; padding:14px 24px; }}
.brand {{ display:flex; align-items:center; gap:8px; font-weight:500; font-size:13px; color:var(--ink-mute); }}
.brand-dot {{ width:26px; height:26px; border-radius:7px; background:linear-gradient(135deg, var(--accent), var(--accent-2)); }}
.nav-links {{ display:flex; gap:24px; font-size:14px; }}
.nav-links a {{ color:var(--ink-mute); }}
.wrap {{ max-width:560px; margin:60px auto 60px; padding:0 24px; }}
.card {{ background:white; border:1px solid var(--line); border-radius:14px; padding:32px; box-shadow:0 8px 32px -16px rgba(0,0,0,0.08); }}
h1 {{ font-size:28px; font-weight:800; letter-spacing:-0.02em; margin-bottom:8px; }}
.subtitle {{ color:var(--ink-mute); font-size:14px; margin-bottom:24px; }}
.pay-btn {{ display:block; width:100%; padding:16px 20px; background:var(--accent); color:white; border:none; border-radius:10px; font-size:16px; font-weight:700; text-align:center; transition:background .15s; }}
.pay-btn:hover {{ background:#0B8585; text-decoration:none; color:white; }}
.note {{ font-size:12px; color:var(--ink-mute); margin-top:18px; line-height:1.5; text-align:center; }}
footer {{ background:var(--bg); color:#94A3B8; padding:40px 24px; text-align:center; font-size:13px; }}
footer a {{ color:#CBD5E1; margin:0 10px; }}
footer a:hover {{ color:white; text-decoration:none; }}
</style>
</head>
<body>

<nav class="nav">
  <div class="nav-inner">
    <a class="brand" href="index.html"><span class="brand-dot"></span><span>{AIC_BRAND_NAME}</span></a>
    <div class="nav-links">
      <a href="index.html">Home</a>
      <a href="pricing.html">Pricing</a>
      <a href="contact.html">Contact</a>
    </div>
  </div>
</nav>

<div class="wrap">
  <div class="card">
    <h1>Pay securely</h1>
    <p class="subtitle">
      Payments to {AIC_BRAND_NAME} are processed by Razorpay on their
      hosted Payment Page. Click below to open it.
    </p>
    <a class="pay-btn" href="{RAZORPAY_LINK}" target="_blank" rel="noopener">
      Open Razorpay Payment Page →
    </a>
    <p class="note">
      Pick the amount that matches your selected plan on the
      <a href="pricing.html">Pricing</a> page. Your licence key will be
      emailed once payment is confirmed (within 1 business day for the
      Payment Page tier).
    </p>
  </div>
</div>

<footer>
  <div>
    <a href="index.html">Home</a>
    <a href="pricing.html">Pricing</a>
    <a href="contact.html">Contact</a>
    <a href="privacy.html">Privacy</a>
    <a href="terms.html">Terms</a>
    <a href="refund.html">Refund Policy</a>
    <a href="shipping.html">Delivery</a>
  </div>
  <div style="margin-top:14px">&copy; 2026 {AIC_BRAND_NAME}. All rights reserved.</div>
  <p style="margin-top:8px;font-size:11px;color:#94A3B8">{DISCLOSURE_NEW}</p>
</footer>

</body>
</html>
"""


def main():
    for page in PAGES:
        p = ROOT / page
        if not p.exists():
            print(f"  skip (missing): {page}")
            continue
        if page == "checkout.html":
            p.write_text(_checkout_static(), encoding="utf-8")
            print("  rewrote checkout -> razorpay.me link")
            continue
        before = p.read_text(encoding="utf-8")
        after = _transform_text(before)
        if after != before:
            p.write_text(after, encoding="utf-8")
            print(f"  transformed: {page}")
        else:
            print(f"  no-op:       {page}")

    # Sanity — confirm Aashray refs are gone from the surface.
    print()
    print("Sanity:")
    import subprocess
    r = subprocess.run(
        ["grep", "-l", "Aashray Sanghi"] + PAGES,
        capture_output=True, text=True, cwd=str(ROOT),
    )
    print("  files still containing 'Aashray Sanghi':")
    print("    " + (r.stdout.strip() or "(none — clean)"))


if __name__ == "__main__":
    main()
