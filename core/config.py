"""
App-wide config — label style etc.

Backed by `core.user_prefs` so the setting persists across restarts. Earlier
versions kept this in a module global, which silently dropped the user's
choice on every app close.
"""
from __future__ import annotations

from core.user_prefs import prefs

DEFAULT_STYLE = "natural"

_STYLES = {
    "natural": {
        "dr_label": "Paid To / Given To",
        "cr_label": "Received From / Paid By",
        "dr_short": "Paid To",
        "cr_short": "Recd From",
    },
    "traditional": {
        "dr_label": "By",
        "cr_label": "To",
        "dr_short": "By",
        "cr_short": "To",
    },
    "accounting": {
        "dr_label": "Debit (Dr)",
        "cr_label": "Credit (Cr)",
        "dr_short": "Dr",
        "cr_short": "Cr",
    },
}


def set_label_style(style: str) -> None:
    if style in _STYLES:
        prefs.set("label_style", style)


def get_dr_label(short: bool = True) -> str:
    s = _STYLES.get(current_style(), _STYLES[DEFAULT_STYLE])
    return s["dr_short"] if short else s["dr_label"]


def get_cr_label(short: bool = True) -> str:
    s = _STYLES.get(current_style(), _STYLES[DEFAULT_STYLE])
    return s["cr_short"] if short else s["cr_label"]


def current_style() -> str:
    return prefs.get("label_style", DEFAULT_STYLE)


# ── Theme mode (bento light / dark) ────────────────────────────────────────

DEFAULT_THEME_MODE = "light"
_VALID_THEME_MODES = ("light", "dark")


def set_theme_mode(mode: str) -> None:
    """Persist the theme mode preference. The app shell must apply
    `ui.theme.set_theme_mode(mode)` + re-set the QApplication
    stylesheet to take effect immediately; otherwise the new mode
    activates on the next launch."""
    m = (mode or DEFAULT_THEME_MODE).lower()
    if m in _VALID_THEME_MODES:
        prefs.set("theme_mode", m)


def current_theme_mode() -> str:
    return prefs.get("theme_mode", DEFAULT_THEME_MODE)
