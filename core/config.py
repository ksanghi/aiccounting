"""
App-wide config — label style, fiscal year, etc.
Kept in memory; call set_label_style() to change at runtime.
"""

_LABEL_STYLE = "natural"

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


def set_label_style(style: str):
    global _LABEL_STYLE
    if style in _STYLES:
        _LABEL_STYLE = style


def get_dr_label(short: bool = True) -> str:
    s = _STYLES.get(_LABEL_STYLE, _STYLES["natural"])
    return s["dr_short"] if short else s["dr_label"]


def get_cr_label(short: bool = True) -> str:
    s = _STYLES.get(_LABEL_STYLE, _STYLES["natural"])
    return s["cr_short"] if short else s["cr_label"]


def current_style() -> str:
    return _LABEL_STYLE
