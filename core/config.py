"""
App-wide config — label style, fiscal year, etc.
Kept in memory; call set_label_style() to change at runtime.
"""

_LABEL_STYLE = "modern"

_STYLES = {
    "modern":      {"dr": "Dr",  "cr": "Cr"},
    "traditional": {"dr": "By",  "cr": "To"},
}


def set_label_style(style: str):
    global _LABEL_STYLE
    if style in _STYLES:
        _LABEL_STYLE = style


def get_dr_label(short: bool = True) -> str:
    return _STYLES.get(_LABEL_STYLE, _STYLES["modern"])["dr"]


def get_cr_label(short: bool = True) -> str:
    return _STYLES.get(_LABEL_STYLE, _STYLES["modern"])["cr"]


def current_style() -> str:
    return _LABEL_STYLE
