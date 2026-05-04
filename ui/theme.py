"""
Theme — warm dark professional palette with higher contrast and larger fonts.
All colours, fonts, and spacing defined here.
Change THEME dict to restyle the entire app.
"""

THEME = {
    # Backgrounds — warm dark, not cold grey
    "bg_sidebar":    "#0D1117",
    "bg_main":       "#161B22",
    "bg_card":       "#1C2333",
    "bg_input":      "#21283A",
    "bg_hover":      "#273044",
    "bg_selected":   "#1A3A5C",
    "bg_dialog":     "#1C2333",

    # Accents — warmer blue with teal complement
    "accent":        "#58A6FF",
    "accent_hover":  "#79B8FF",
    "accent_dim":    "#1A3A5C",
    "success":       "#3FB950",
    "warning":       "#D29922",
    "danger":        "#F85149",
    "danger_dim":    "#4A1515",

    # Text — higher contrast
    "text_primary":  "#F0F6FC",
    "text_secondary":"#9ECAFF",
    "text_dim":      "#484F58",
    "text_accent":   "#58A6FF",

    # Borders — subtle but visible
    "border":        "#30363D",
    "border_focus":  "#58A6FF",
    "border_error":  "#F85149",

    # Voucher type colours — more vivid
    "payment":       "#FF7B72",
    "receipt":       "#3FB950",
    "contra":        "#D2A8FF",
    "journal":       "#E3B341",
    "sales":         "#58A6FF",
    "purchase":      "#FFA657",
    "debit_note":    "#FF7B72",
    "credit_note":   "#39D353",
}

FONT = {
    "tiny":    10,
    "small":   11,
    "body":    12,
    "medium":  13,
    "large":   15,
    "title":   20,
    "display": 26,
}

VOUCHER_COLOURS = {
    "PAYMENT":     THEME["payment"],
    "RECEIPT":     THEME["receipt"],
    "CONTRA":      THEME["contra"],
    "JOURNAL":     THEME["journal"],
    "SALES":       THEME["sales"],
    "PURCHASE":    THEME["purchase"],
    "DEBIT_NOTE":  THEME["debit_note"],
    "CREDIT_NOTE": THEME["credit_note"],
}


def get_stylesheet() -> str:
    t = THEME
    return f"""
/* ── Global ──────────────────────────────── */
* {{
    font-family: 'Segoe UI', 'Calibri', sans-serif;
    font-size: 12px;
    color: {t['text_primary']};
    border: none;
    outline: none;
}}
QWidget {{
    background-color: {t['bg_main']};
}}
QMainWindow {{
    background-color: {t['bg_sidebar']};
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
#logo_text {{
    font-size: 17px;
    font-weight: bold;
    color: {t['accent']};
    letter-spacing: 2px;
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
    font-size: 20px;
    font-weight: bold;
    color: {t['text_primary']};
    padding: 22px 26px 4px 26px;
}}
#page_subtitle {{
    font-size: 11px;
    color: {t['text_secondary']};
    padding: 0 26px 18px 26px;
}}

/* ── Cards ───────────────────────────────── */
#card {{
    background-color: {t['bg_card']};
    border-radius: 10px;
    border: 1px solid {t['border']};
    padding: 18px;
    margin: 6px 0;
}}

/* ── Inputs ──────────────────────────────── */
QLineEdit, QComboBox, QDateEdit, QTextEdit,
QSpinBox, QDoubleSpinBox {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 7px;
    padding: 7px 12px;
    color: {t['text_primary']};
    font-size: 12px;
    min-height: 34px;
    selection-background-color: {t['accent_dim']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
QTextEdit:focus, QDoubleSpinBox:focus {{
    border: 1.5px solid {t['border_focus']};
    background-color: {t['bg_hover']};
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
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {t['text_secondary']};
    margin-right: 8px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border_focus']};
    border-radius: 7px;
    selection-background-color: {t['accent_dim']};
    font-size: 12px;
    padding: 4px;
}}
QDateEdit::up-button, QDateEdit::down-button {{
    width: 0;
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
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 7px;
    padding: 8px 18px;
    color: {t['text_primary']};
    font-size: 12px;
    min-height: 34px;
}}
QPushButton:hover {{
    background-color: {t['bg_hover']};
    border-color: {t['accent']};
    color: {t['accent']};
}}
QPushButton:pressed {{
    background-color: {t['accent_dim']};
}}
#btn_primary {{
    background-color: {t['accent']};
    border: none;
    border-radius: 7px;
    padding: 9px 22px;
    color: #0D1117;
    font-size: 12px;
    font-weight: bold;
    min-height: 34px;
}}
#btn_primary:hover {{
    background-color: {t['accent_hover']};
}}
#btn_danger {{
    background-color: {t['danger']};
    border: none;
    border-radius: 7px;
    padding: 9px 22px;
    color: white;
    font-size: 12px;
    font-weight: bold;
}}
#btn_danger:hover {{
    background-color: #da3633;
}}
#btn_icon {{
    background: transparent;
    border: none;
    padding: 4px;
    border-radius: 5px;
    font-size: 14px;
    color: {t['text_secondary']};
    min-height: 0;
}}
#btn_icon:hover {{
    background-color: {t['bg_hover']};
    color: {t['text_primary']};
}}

/* ── Voucher type buttons ────────────────── */
#voucher_type_bar {{
    background-color: {t['bg_card']};
    border-radius: 10px;
    border: 1px solid {t['border']};
    padding: 10px 14px;
}}

/* ── Tables ──────────────────────────────── */
QTableWidget {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 10px;
    gridline-color: {t['border']};
    selection-background-color: {t['bg_selected']};
    selection-color: {t['text_primary']};
    alternate-background-color: {t['bg_hover']};
    font-size: 12px;
}}
QTableWidget::item {{
    padding: 8px 12px;
    border-bottom: 1px solid {t['border']};
}}
QTableWidget::item:selected {{
    background-color: {t['bg_selected']};
    color: {t['text_primary']};
}}
QHeaderView::section {{
    background-color: {t['bg_sidebar']};
    color: {t['text_secondary']};
    font-size: 11px;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding: 10px 12px;
    border: none;
    border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']};
}}

/* ── Scrollbars ──────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 7px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    border-radius: 3px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['text_secondary']};
}}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 7px;
}}
QScrollBar::handle:horizontal {{
    background: {t['border']};
    border-radius: 3px;
}}

/* ── Separators ──────────────────────────── */
QFrame[frameShape="4"], QFrame[frameShape="5"] {{
    color: {t['border']};
    background-color: {t['border']};
    max-height: 1px;
}}

/* ── Status bar ──────────────────────────── */
QStatusBar {{
    background-color: {t['bg_sidebar']};
    color: {t['text_secondary']};
    font-size: 11px;
    border-top: 1px solid {t['border']};
    padding: 4px 12px;
}}

/* ── Tooltips ────────────────────────────── */
QToolTip {{
    background-color: {t['bg_card']};
    color: {t['text_primary']};
    border: 1px solid {t['border_focus']};
    border-radius: 5px;
    padding: 5px 10px;
    font-size: 11px;
}}

/* ── Dialogs ─────────────────────────────── */
QDialog {{
    background-color: {t['bg_dialog']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}
QMessageBox {{
    background-color: {t['bg_dialog']};
    font-size: 12px;
}}

/* ── Tab widget ──────────────────────────── */
QTabWidget::pane {{
    border: 1px solid {t['border']};
    border-radius: 8px;
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
    border: 1px solid {t['border_focus']};
    border-radius: 7px;
    selection-background-color: {t['accent_dim']};
    selection-color: {t['text_primary']};
    padding: 4px;
    font-size: 12px;
    outline: none;
}}
QAbstractItemView::item {{
    padding: 7px 12px;
    border-radius: 5px;
    min-height: 28px;
}}

/* ── Splitter ────────────────────────────── */
QSplitter::handle {{
    background-color: {t['border']};
    width: 1px;
    height: 1px;
}}
"""
