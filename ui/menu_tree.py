"""
Menu tree — the single source of truth for navigation hierarchy.

Both navigation modes read from here so they can never drift:
  • Mode A — the collapsible sidebar (ui/sidebar_sections.py)
  • Mode B — the tile launcher (ui/nav_launcher.py)

The hierarchy is three levels:  SECTION  ▸  GROUP  ▸  page.
Pages are matched to a (section, group) by a case-insensitive substring
rule — FIRST match wins, so order the rules most-specific first. Anything
unmatched lands in ("More", "") so a page is never dropped from the menu.

One unified rule table covers BOTH apps:
  • AccountsHQ pages match the Accounting / Reports / Tools / Settings rules.
  • RWA HQ pages additionally match the "RWA · Society" rules.
Sections with no pages simply don't render, so AHQ never shows an empty
"RWA · Society" band and RHQ never shows an empty section either.

To re-home a page, move its rule — do NOT scatter section logic into the
page-registration code.
"""
from __future__ import annotations

from collections import OrderedDict

# (needle_lower, section, group) — first substring match wins.
_RULES: list[tuple[str, str, str]] = [
    # ── RWA · Society (RWA HQ only) ──────────────────────────────────────────
    ("pending approval", "RWA · Society", "People"),
    ("members",          "RWA · Society", "People"),
    ("visitor",          "RWA · Society", "People"),
    ("notice",           "RWA · Society", "Community"),
    ("complaint",        "RWA · Society", "Community"),
    ("broadcast",        "RWA · Society", "Community"),
    ("poll",             "RWA · Society", "Community"),
    ("flats",            "RWA · Society", "Property"),
    ("plots",            "RWA · Society", "Property"),
    ("facilit",          "RWA · Society", "Property"),
    ("asset",            "RWA · Society", "Property"),
    ("vendor",           "RWA · Society", "Property"),
    ("documents",        "RWA · Society", "Property"),   # RWA "Documents" (plural)
    ("rwa report",       "RWA · Society", "Billing"),
    ("billing",          "RWA · Society", "Billing"),   # RWA auto-billing page
    ("wallet",           "RWA · Society", "Billing"),

    # ── Accounting ───────────────────────────────────────────────────────────
    ("post voucher",     "Accounting", "Entry"),
    ("auto post",        "Accounting", "Entry"),
    ("verbal",           "Accounting", "Entry"),
    ("bank reconcil",    "Accounting", "Reconciliation"),
    ("ledger reconcil",  "Accounting", "Reconciliation"),
    ("reconcil",         "Accounting", "Reconciliation"),

    # ── Reports ──────────────────────────────────────────────────────────────
    ("day book",         "Reports", "Books"),
    ("ledger balances",  "Reports", "Books"),
    ("trial balance",    "Reports", "Financial"),
    ("p & l",            "Reports", "Financial"),
    ("p&l",              "Reports", "Financial"),
    ("profit",           "Reports", "Financial"),
    ("balance sheet",    "Reports", "Financial"),
    ("cash book",        "Reports", "Financial"),
    ("bank book",        "Reports", "Financial"),
    ("ledger account",   "Reports", "Financial"),
    ("rcpt",             "Reports", "Financial"),
    ("receipt",          "Reports", "Financial"),
    ("aging",            "Reports", "Financial"),
    ("ageing",           "Reports", "Financial"),
    ("bill-wise",        "Reports", "Financial"),
    ("cash-flow",        "Reports", "Financial"),
    # Tax screens BEFORE the bare "reports" fallback, so "TDS Reports" lands
    # under Tax, not Financial.
    ("hsn",              "Reports", "Tax"),
    ("gst",              "Reports", "Tax"),
    ("tds",              "Reports", "Tax"),
    ("reports",          "Reports", "Financial"),        # bare locked "Reports" page

    # ── Tools ────────────────────────────────────────────────────────────────
    ("cloud sync",       "Tools", "Sync & Onboarding"),
    ("join link",        "Tools", "Sync & Onboarding"),
    ("verification",     "Tools", "Sync & Onboarding"),
    ("profile request",  "Tools", "Sync & Onboarding"),
    ("ai doc",           "Tools", "AI & Documents"),
    ("document inbox",   "Tools", "AI & Documents"),
    ("document reader",  "Tools", "AI & Documents"),
    ("backup",           "Tools", "Data"),
    ("migration",        "Tools", "Data"),
    ("period lock",      "Tools", "Data"),
    ("users",            "Tools", "Admin"),
    ("audit",            "Tools", "Admin"),

    # ── Settings ─────────────────────────────────────────────────────────────
    ("ai credits",       "Settings", ""),   # AI wallet — billing/account
    ("credits",          "Settings", ""),
    ("ai wallet",        "Settings", ""),
    ("society settings", "Settings", ""),
    ("company settings", "Settings", ""),
    ("settings hub",     "Settings", ""),
    ("settings",         "Settings", ""),
    ("license",          "Settings", ""),
    ("feedback",         "Settings", ""),
]

# Section render order, top → bottom. Empty sections are skipped at build time.
SECTION_ORDER: list[str] = [
    "RWA · Society", "Accounting", "Reports", "Tools", "Settings", "More",
]

# Group order within each section.
GROUP_ORDER: dict[str, list[str]] = {
    "RWA · Society": ["People", "Community", "Property", "Billing"],
    "Accounting":    ["Entry", "Reconciliation"],
    "Reports":       ["Books", "Financial", "Tax"],
    "Tools":         ["Sync & Onboarding", "AI & Documents", "Data", "Admin"],
    "Settings":      [""],
    "More":          [""],
}

# Which sections start expanded in the sidebar accordion (Mode A).
DEFAULT_EXPANDED: set[str] = {"RWA · Society", "Accounting"}


def resolve(label: str) -> tuple[str, str]:
    """Return (section, group) for a page label. Unmatched → ('More', '')."""
    low = (label or "").lower()
    for needle, section, group in _RULES:
        if needle in low:
            return section, group
    return "More", ""


def _section_rank(name: str) -> int:
    return SECTION_ORDER.index(name) if name in SECTION_ORDER else len(SECTION_ORDER)


def _group_rank(section: str, group: str) -> int:
    order = GROUP_ORDER.get(section, [])
    return order.index(group) if group in order else len(order)


def build_tree(items, label_of=lambda x: x):
    """Group `items` into the 3-level tree.

    `label_of(item)` must return the page label used for matching. Returns an
    ordered list of:
        [ (section, [ (group, [item, item, ...]), ... ]), ... ]
    following SECTION_ORDER / GROUP_ORDER, with any unknown section/group
    appended at the end (alphabetically) rather than dropped. Pages keep their
    original registration order within a group.
    """
    # section -> group -> [items]
    buckets: "OrderedDict[str, OrderedDict[str, list]]" = OrderedDict()
    for it in items:
        section, group = resolve(label_of(it))
        buckets.setdefault(section, OrderedDict()).setdefault(group, []).append(it)

    out = []
    for section in sorted(buckets.keys(),
                          key=lambda s: (_section_rank(s), s)):
        groups = buckets[section]
        ordered_groups = []
        for group in sorted(groups.keys(),
                            key=lambda g: (_group_rank(section, g), g)):
            ordered_groups.append((group, groups[group]))
        out.append((section, ordered_groups))
    return out
