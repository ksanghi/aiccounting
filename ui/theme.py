"""
Theme — Bento with light + dark modes.

Two palettes live here:
  • THEME_LIGHT — deep navy text on near-white canvas, teal accent.
  • THEME_DARK  — deep navy canvas, teal accent that glows on dark.

A module-level mode (`_THEME_MODE` = "light" / "dark") selects which
palette `THEME` mirrors. Pages import `THEME` and never know which
mode they're in. Call `set_theme_mode("dark")` and re-apply the
stylesheet to switch at runtime.

Status colour shorthand is exposed via the `status` helpers — keeps
"good", "warn", "bad", "info" semantics consistent across the app.
"""
from __future__ import annotations


# ── Palettes ──────────────────────────────────────────────────────────────

# Bento light — calm white-blue canvas, teal accent, semantic status.
THEME_LIGHT = {
    # Mode marker (used by widgets that need to render differently)
    "mode":            "light",

    # Backgrounds
    "bg_sidebar":      "#FFFFFF",        # white sidebar
    "bg_main":         "#F1F4F9",        # soft slate canvas
    "bg_card":         "#FFFFFF",        # cards/tiles
    "bg_card_2":       "#F8FAFC",        # nested cards
    "bg_input":        "#F8FAFC",
    "bg_hover":        "#EEF2F7",
    "bg_selected":     "#E0F2EF",        # teal-tinted selection
    "bg_dialog":       "#FFFFFF",

    # Accents — teal for AHQ, overridden per-app in rwagenie/app/theme.py
    "accent":          "#0EA5A5",        # teal
    "accent_hover":    "#0FB7B7",
    "accent_dim":      "#E0F2EF",
    "accent_soft":     "#E0F4F3",

    # Status colours — semantic
    "good":            "#057A55",
    "warn":            "#B45309",
    "bad":             "#C83A3A",
    "info":            "#1849A9",
    "good_bg":         "#D9F5E6",
    "warn_bg":         "#FDEBD0",
    "bad_bg":          "#FBE1E1",
    "info_bg":         "#D8E5FC",
    "good_soft":       "#EAF7EF",
    "warn_soft":       "#FCF1DC",
    "bad_soft":        "#FCEAEA",

    # Legacy aliases (kept so existing pages don't break)
    "success":         "#057A55",
    "warning":         "#B45309",
    "danger":          "#C83A3A",
    "danger_dim":      "#FBE1E1",

    # Text
    "text_primary":    "#0F172A",
    "text_secondary":  "#5A6B8B",
    "text_dim":        "#94A3B8",
    "text_accent":     "#0EA5A5",

    # Borders
    "border":          "#E5E9F1",
    "border_2":        "#D8DDE6",
    "border_focus":    "#0EA5A5",
    "border_error":    "#C83A3A",

    # Misc
    "btn_primary_text":"#FFFFFF",
    "shadow":          "rgba(15, 23, 42, 0.06)",

    # Voucher type colours — semantic, less saturated than the old palette
    "payment":         "#C83A3A",
    "receipt":         "#057A55",
    "contra":          "#0EA5A5",
    "journal":         "#B45309",
    "sales":           "#1849A9",
    "purchase":        "#6622CC",
    "debit_note":      "#C83A3A",
    "credit_note":     "#057A55",
}


# Bento dark — deep navy canvas, brighter teal, glowing status pills.
THEME_DARK = {
    "mode":            "dark",

    "bg_sidebar":      "#0F1424",
    "bg_main":         "#0B0F1A",
    "bg_card":         "#161C2E",
    "bg_card_2":       "#1B2238",
    "bg_input":        "#0F1424",
    "bg_hover":        "#1B2238",
    "bg_selected":     "#1B3938",
    "bg_dialog":       "#161C2E",

    "accent":          "#2DD4C3",        # bright teal
    "accent_hover":    "#45E3D2",
    "accent_dim":      "#1B3938",
    "accent_soft":     "#0F2A29",

    "good":            "#4ADE80",
    "warn":            "#FBBF24",
    "bad":             "#F87171",
    "info":            "#60A5FA",
    "good_bg":         "#1A3A24",         # soft solid (Qt QSS rgba on bg is iffy)
    "warn_bg":         "#3A2B0E",
    "bad_bg":          "#3A1A1A",
    "info_bg":         "#1A2A3F",
    "good_soft":       "#142A1B",
    "warn_soft":       "#2A2010",
    "bad_soft":        "#2A1515",

    "success":         "#4ADE80",
    "warning":         "#FBBF24",
    "danger":          "#F87171",
    "danger_dim":      "#3A1A1A",

    "text_primary":    "#E6ECF8",
    "text_secondary":  "#8895B8",
    "text_dim":        "#5C6789",
    "text_accent":     "#2DD4C3",

    "border":          "#232A44",
    "border_2":        "#2E3654",
    "border_focus":    "#2DD4C3",
    "border_error":    "#F87171",

    "btn_primary_text":"#06241F",         # dark navy on bright teal button
    "shadow":          "rgba(0, 0, 0, 0.30)",

    "payment":         "#F87171",
    "receipt":         "#4ADE80",
    "contra":          "#2DD4C3",
    "journal":         "#FBBF24",
    "sales":           "#60A5FA",
    "purchase":        "#C084FC",
    "debit_note":      "#F87171",
    "credit_note":     "#4ADE80",
}


# ── Active palette ─────────────────────────────────────────────────────────

_THEME_MODE = "light"
THEME: dict[str, str] = dict(THEME_LIGHT)


def set_theme_mode(mode: str) -> None:
    """Switch the active palette. Pages don't observe this directly —
    the main window re-applies `get_stylesheet()` to QApplication after
    calling this."""
    global _THEME_MODE, THEME
    mode = (mode or "light").lower()
    if mode not in ("light", "dark"):
        mode = "light"
    _THEME_MODE = mode
    THEME.clear()
    THEME.update(THEME_DARK if mode == "dark" else THEME_LIGHT)


def get_theme_mode() -> str:
    return _THEME_MODE


def is_dark() -> bool:
    return _THEME_MODE == "dark"


# ── Fonts ──────────────────────────────────────────────────────────────────

FONT = {
    "tiny":    10,
    "small":   11,
    "body":    12,
    "medium":  13,
    "large":   15,
    "title":   20,
    "display": 26,
}


# ── Voucher colours — read THEME live so they track mode switches ──────────

class _VoucherColourMap:
    """Lazy mapping that resolves through the live THEME dict.
    Keeps existing `VOUCHER_COLOURS["SALES"]` lookups working even
    after a theme switch."""
    _keys = {
        "PAYMENT":     "payment",
        "RECEIPT":     "receipt",
        "CONTRA":      "contra",
        "JOURNAL":     "journal",
        "SALES":       "sales",
        "PURCHASE":    "purchase",
        "DEBIT_NOTE":  "debit_note",
        "CREDIT_NOTE": "credit_note",
    }
    def __getitem__(self, k):
        return THEME[self._keys[k]]
    def get(self, k, default=None):
        try: return self[k]
        except KeyError: return default


VOUCHER_COLOURS = _VoucherColourMap()


# ── Status helpers ─────────────────────────────────────────────────────────

def status_colours(kind: str) -> tuple[str, str]:
    """Return (foreground, background) for a status kind:
    'good', 'warn', 'bad', 'info'. Used by status pills + KPI tiles."""
    k = (kind or "").lower()
    if k in ("good", "ok", "paid", "success", "clear"):
        return THEME["good"], THEME["good_bg"]
    if k in ("warn", "warning", "due"):
        return THEME["warn"], THEME["warn_bg"]
    if k in ("bad", "danger", "error", "overdue", "fail"):
        return THEME["bad"], THEME["bad_bg"]
    if k in ("info", "draft"):
        return THEME["info"], THEME["info_bg"]
    return THEME["text_secondary"], THEME["bg_hover"]


# ── Stylesheet ─────────────────────────────────────────────────────────────

def get_stylesheet() -> str:
    t = THEME
    dark = is_dark()
    # Drop-arrow colour matches text in dark mode for better contrast.
    arrow_col = t['text_secondary']
    selection_bg = t['bg_selected']

    return f"""
/* ── Global ──────────────────────────────── */
* {{
    font-family: 'Segoe UI', 'Calibri', 'Inter', sans-serif;
    font-size: 12px;
    color: {t['text_primary']};
    border: none;
    outline: none;
}}
QWidget {{
    background-color: {t['bg_main']};
}}
QMainWindow {{
    background-color: {t['bg_main']};
}}

/* ── Sidebar ─────────────────────────────── */
#sidebar {{
    background-color: {t['bg_sidebar']};
    border-right: 1px solid {t['border']};
    min-width: 220px;
    max-width: 220px;
}}
#sidebar_logo {{
    background-color: {t['bg_sidebar']};
    padding: 20px 18px 14px 18px;
    border-bottom: 1px solid {t['border']};
}}
#company_text {{
    font-size: 11px;
    color: {t['text_secondary']};
    padding-top: 3px;
}}
#nav_section {{
    color: {t['text_dim']};
    font-size: 10px;
    letter-spacing: 1.5px;
    padding: 16px 22px 5px 22px;
    font-weight: bold;
}}

/* ── Content area ────────────────────────── */
#content_area {{
    background-color: {t['bg_main']};
}}
#page_title {{
    font-size: 22px;
    font-weight: 700;
    color: {t['text_primary']};
    padding: 22px 26px 4px 26px;
    letter-spacing: -0.02em;
}}
#page_subtitle {{
    font-size: 12px;
    color: {t['text_secondary']};
    padding: 0 26px 18px 26px;
}}

/* ── Cards ───────────────────────────────── */
/* #card is also worn by voucher-form line rows, so keep these
   values modest — every extra px of padding/margin here stacks
   into 5–10 rows of voucher overlap. */
#card {{
    background-color: {t['bg_card']};
    border-radius: 8px;
    border: 1px solid {t['border']};
    padding: 8px;
    margin: 2px 0;
}}

/* ── Bento KPI tile ─────────────────────── */
#bento_tile {{
    background-color: {t['bg_card']};
    border-radius: 10px;
    border: 1px solid {t['border']};
    padding: 10px 12px;
}}
#bento_tile_good {{
    background-color: {t['good_soft']};
    border-radius: 10px;
    border: 1px solid {t['good']};
    padding: 10px 12px;
}}
#bento_tile_warn {{
    background-color: {t['warn_soft']};
    border-radius: 10px;
    border: 1px solid {t['warn']};
    padding: 10px 12px;
}}
#bento_tile_bad {{
    background-color: {t['bad_soft']};
    border-radius: 10px;
    border: 1px solid {t['bad']};
    padding: 10px 12px;
}}
#bento_label {{
    font-size: 10px;
    font-weight: 700;
    color: {t['text_secondary']};
    letter-spacing: 0.08em;
}}
#bento_value {{
    font-size: 20px;
    font-weight: 700;
    color: {t['text_primary']};
    letter-spacing: -0.02em;
}}
#bento_value_good {{ font-size: 20px; font-weight: 700; color: {t['good']}; letter-spacing: -0.02em; }}
#bento_value_warn {{ font-size: 20px; font-weight: 700; color: {t['warn']}; letter-spacing: -0.02em; }}
#bento_value_bad  {{ font-size: 20px; font-weight: 700; color: {t['bad']};  letter-spacing: -0.02em; }}
#bento_delta {{
    font-size: 11px;
    color: {t['text_secondary']};
}}

/* ── Status pill ─────────────────────────── */
#status_pill_good {{
    background-color: {t['good_bg']};
    color: {t['good']};
    border-radius: 10px;
    padding: 2px 9px;
    font-weight: 600;
    font-size: 11px;
}}
#status_pill_warn {{
    background-color: {t['warn_bg']};
    color: {t['warn']};
    border-radius: 10px;
    padding: 2px 9px;
    font-weight: 600;
    font-size: 11px;
}}
#status_pill_bad {{
    background-color: {t['bad_bg']};
    color: {t['bad']};
    border-radius: 10px;
    padding: 2px 9px;
    font-weight: 600;
    font-size: 11px;
}}
#status_pill_info {{
    background-color: {t['info_bg']};
    color: {t['info']};
    border-radius: 10px;
    padding: 2px 9px;
    font-weight: 600;
    font-size: 11px;
}}

/* ── Action card (clickable quick action) ── */
#action_card {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 8px 10px;
}}
#action_card:hover {{
    border: 1px solid {t['accent']};
}}
#action_card_title {{
    font-size: 12px;
    font-weight: 700;
    color: {t['text_primary']};
}}
#action_card_subtitle {{
    font-size: 10px;
    color: {t['text_secondary']};
}}

/* ── Inputs ──────────────────────────────── */
QLineEdit, QComboBox, QDateEdit, QTextEdit,
QSpinBox, QDoubleSpinBox {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    padding: 4px 10px;
    color: {t['text_primary']};
    font-size: 12px;
    selection-background-color: {t['accent_soft']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
QTextEdit:focus, QDoubleSpinBox:focus {{
    border: 1px solid {t['border_focus']};
    background-color: {t['bg_card']};
}}
QLineEdit[error="true"] {{
    border: 1.5px solid {t['border_error']};
}}
QComboBox::drop-down {{
    border: none;
    width: 24px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 7px solid transparent;
    border-right: 7px solid transparent;
    border-top: 6px solid {arrow_col};
    margin-right: 8px;
    width: 14px;
}}
/* Comfortable, fully-readable height for dropdowns app-wide — the default
   render (~26px) was cramped, especially the period combos. ~30px reads
   cleanly and still fits inside the table rows (all >=32px). */
QComboBox, QDateEdit {{
    min-height: 20px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    selection-background-color: {t['accent_soft']};
    font-size: 12px;
    padding: 4px;
}}
/* Spin-style increment / decrement buttons on numeric + date editors.
   AG previously set width:0 to hide them; the Qt-default render still
   showed a thin un-clickable stub. Generous width so they're easy to
   click for date stepping in voucher forms. */
QDateEdit::up-button, QDateEdit::down-button,
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{
    width: 28px;
    background: transparent;
    border: none;
    border-left: 1px solid {t['border']};
}}
QDateEdit::up-button:hover, QDateEdit::down-button:hover,
QSpinBox::up-button:hover, QSpinBox::down-button:hover,
QDoubleSpinBox::up-button:hover, QDoubleSpinBox::down-button:hover {{
    background: {t['bg_hover']};
}}
QDateEdit::up-arrow, QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {{
    image: none;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 7px solid {arrow_col};
    width: 12px;
    height: 7px;
}}
QDateEdit::down-arrow, QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {{
    image: none;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-top: 7px solid {arrow_col};
    width: 12px;
    height: 7px;
}}

/* ── Labels ──────────────────────────────── */
#field_label {{
    font-size: 11px;
    color: {t['text_secondary']};
    font-weight: bold;
    letter-spacing: 0.5px;
    padding-bottom: 3px;
}}

/* ── Buttons ─────────────────────────────── */
QPushButton {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 4px 10px;
    color: {t['text_primary']};
    font-size: 12px;
    font-weight: 500;
    min-height: 26px;
}}
QPushButton:hover {{
    background-color: {t['bg_hover']};
    border-color: {t['border_2']};
    color: {t['text_primary']};
}}
QPushButton:pressed {{
    background-color: {t['accent_soft']};
}}
#btn_primary {{
    background-color: {t['accent']};
    border: none;
    border-radius: 6px;
    padding: 5px 14px;
    color: {t['btn_primary_text']};
    font-size: 12px;
    font-weight: 700;
    min-height: 28px;
}}
#btn_primary:hover {{
    background-color: {t['accent_hover']};
}}
#btn_danger {{
    background-color: {t['bad']};
    border: none;
    border-radius: 8px;
    padding: 9px 20px;
    color: white;
    font-size: 13px;
    font-weight: 700;
}}
#btn_danger:hover {{
    background-color: {t['bad']};
}}
#btn_icon {{
    background: transparent;
    border: 1px solid transparent;
    padding: 6px;
    border-radius: 8px;
    font-size: 14px;
    color: {t['text_secondary']};
    min-height: 0;
}}
#btn_icon:hover {{
    background-color: {t['bg_hover']};
    border-color: {t['border']};
    color: {t['text_primary']};
}}

/* ── Voucher type buttons ────────────────── */
#voucher_type_bar {{
    background-color: {t['bg_card']};
    border-radius: 12px;
    border: 1px solid {t['border']};
    padding: 10px 14px;
}}

/* ── Tables ──────────────────────────────── */
QTableWidget {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    gridline-color: {t['border']};
    selection-background-color: {selection_bg};
    selection-color: {t['text_primary']};
    alternate-background-color: {t['bg_card_2']};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 10px 12px;
    border-bottom: 1px solid {t['border']};
}}
QTableWidget::item:selected {{
    background-color: {selection_bg};
    color: {t['text_primary']};
}}
QHeaderView::section {{
    background-color: {t['bg_card_2']};
    color: {t['text_secondary']};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid {t['border']};
}}

/* ── Scrollbars ──────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 12px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border_2']};
    border-radius: 6px;
    min-height: 32px;
    margin: 2px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['text_dim']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical {{
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 12px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border_2']};
    border-radius: 6px;
    min-width: 32px;
    margin: 2px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {t['text_dim']};
}}

/* ── Separators ──────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {t['border']};
    background-color: {t['border']};
    max-height: 1px;
}}

/* ── Status bar ──────────────────────────── */
QStatusBar {{
    background-color: {t['bg_card']};
    color: {t['text_secondary']};
    font-size: 11px;
    border-top: 1px solid {t['border']};
    padding: 4px 12px;
}}

/* ── Tooltips ────────────────────────────── */
QToolTip {{
    background-color: {t['bg_card']};
    color: {t['text_primary']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 5px 10px;
    font-size: 11px;
}}

/* ── Dialogs ─────────────────────────────── */
QDialog {{
    background-color: {t['bg_dialog']};
    border: 1px solid {t['border']};
    border-radius: 12px;
}}
QMessageBox {{
    background-color: {t['bg_dialog']};
    font-size: 12px;
}}

/* ── Tab widget ──────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t['border']};
    border-radius: 10px;
    background-color: {t['bg_card']};
}}
QTabBar::tab {{
    background-color: transparent;
    color: {t['text_secondary']};
    padding: 9px 20px;
    border-bottom: 2px solid transparent;
    font-size: 12px;
}}
QTabBar::tab:selected {{
    color: {t['accent']};
    border-bottom: 2px solid {t['accent']};
    font-weight: bold;
}}
QTabBar::tab:hover {{
    color: {t['text_primary']};
}}

/* ── Completer popup ─────────────────────── */
QAbstractItemView {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    selection-background-color: {t['accent_soft']};
    selection-color: {t['text_primary']};
    padding: 4px;
    font-size: 12px;
    outline: none;
}}
QAbstractItemView::item {{
    padding: 7px 12px;
    border-radius: 6px;
    min-height: 28px;
}}

/* ── Splitter ────────────────────────────── */
QSplitter::handle {{
    background-color: {t['border']};
    width: 1px;
    height: 1px;
}}

/* ── Checkbox / RadioButton (used in forms) ── */
QCheckBox, QRadioButton {{
    background-color: transparent;
    color: {t['text_primary']};
    spacing: 6px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 16px;
    height: 16px;
    border: 1px solid {t['border_2']};
    border-radius: 4px;
    background: {t['bg_card']};
}}
QCheckBox::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}
QRadioButton::indicator {{
    border-radius: 8px;
}}
QRadioButton::indicator:checked {{
    background: {t['accent']};
    border-color: {t['accent']};
}}

/* ── Group box ─────────────────────────── */
QGroupBox {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 12px;
    margin-top: 10px;
    padding-top: 16px;
    font-weight: 600;
    color: {t['text_primary']};
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {t['text_secondary']};
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.06em;
}}
"""
