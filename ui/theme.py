"""
Theme — refined dark professional palette
All colours, fonts, and spacing defined here.
Change THEME dict to restyle the entire app.
"""

THEME = {
    # Backgrounds
    "bg_sidebar":    "#0F1117",
    "bg_main":       "#1A1D27",
    "bg_card":       "#21263A",
    "bg_input":      "#2A2F45",
    "bg_hover":      "#2E3450",
    "bg_selected":   "#1E3A5F",
    "bg_dialog":     "#1E2235",

    # Accents
    "accent":        "#4F8EF7",
    "accent_hover":  "#6BA3F9",
    "accent_dim":    "#1E3A6E",
    "success":       "#2ECC71",
    "warning":       "#F0A500",
    "danger":        "#E74C3C",
    "danger_dim":    "#4A1515",

    # Text
    "text_primary":  "#E8EAF0",
    "text_secondary":"#8A90A8",
    "text_dim":      "#4A5070",
    "text_accent":   "#4F8EF7",

    # Borders
    "border":        "#2E3450",
    "border_focus":  "#4F8EF7",
    "border_error":  "#E74C3C",

    # Voucher type colours
    "payment":       "#E74C3C",
    "receipt":       "#2ECC71",
    "contra":        "#9B59B6",
    "journal":       "#F0A500",
    "sales":         "#4F8EF7",
    "purchase":      "#E67E22",
    "debit_note":    "#E74C3C",
    "credit_note":   "#1ABC9C",
}

# Font sizes
FONT = {
    "tiny":    9,
    "small":   10,
    "body":    11,
    "medium":  12,
    "large":   14,
    "title":   18,
    "display": 24,
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
    font-size: 11px;
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
    min-width: 200px;
    max-width: 200px;
}}
#sidebar_logo {{
    background-color: {t['bg_sidebar']};
    padding: 18px 16px 12px 16px;
    border-bottom: 1px solid {t['border']};
}}
#logo_text {{
    font-size: 15px;
    font-weight: bold;
    color: {t['accent']};
    letter-spacing: 1px;
}}
#company_text {{
    font-size: 9px;
    color: {t['text_dim']};
    padding-top: 2px;
}}

/* ── Nav buttons ─────────────────────────── */
#nav_btn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 9px 14px;
    text-align: left;
    font-size: 11px;
    color: {t['text_secondary']};
    margin: 1px 8px;
}}
#nav_btn:hover {{
    background-color: {t['bg_hover']};
    color: {t['text_primary']};
}}
#nav_btn_active {{
    background-color: {t['accent_dim']};
    border: none;
    border-radius: 6px;
    border-left: 3px solid {t['accent']};
    padding: 9px 14px 9px 11px;
    text-align: left;
    font-size: 11px;
    color: {t['accent']};
    font-weight: bold;
    margin: 1px 8px;
}}
#nav_section {{
    color: {t['text_dim']};
    font-size: 9px;
    letter-spacing: 1.5px;
    padding: 14px 22px 4px 22px;
    font-weight: bold;
}}

/* ── Content area ────────────────────────── */
#content_area {{
    background-color: {t['bg_main']};
    padding: 0;
}}
#page_title {{
    font-size: 18px;
    font-weight: bold;
    color: {t['text_primary']};
    padding: 20px 24px 4px 24px;
}}
#page_subtitle {{
    font-size: 10px;
    color: {t['text_dim']};
    padding: 0 24px 16px 24px;
}}

/* ── Cards ───────────────────────────────── */
#card {{
    background-color: {t['bg_card']};
    border-radius: 10px;
    border: 1px solid {t['border']};
    padding: 16px;
    margin: 6px 0;
}}

/* ── Inputs ──────────────────────────────── */
QLineEdit, QComboBox, QDateEdit, QTextEdit, QSpinBox, QDoubleSpinBox {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 6px 10px;
    color: {t['text_primary']};
    font-size: 11px;
    selection-background-color: {t['accent_dim']};
}}
QLineEdit:focus, QComboBox:focus, QDateEdit:focus,
QTextEdit:focus, QDoubleSpinBox:focus {{
    border: 1px solid {t['border_focus']};
    background-color: {t['bg_hover']};
}}
QLineEdit[error="true"] {{
    border: 1px solid {t['border_error']};
}}
QComboBox::drop-down {{
    border: none;
    width: 20px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {t['text_secondary']};
    margin-right: 6px;
}}
QComboBox QAbstractItemView {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    selection-background-color: {t['accent_dim']};
    outline: none;
    padding: 4px;
}}
QDateEdit::up-button, QDateEdit::down-button {{
    width: 0;
}}
QCalendarWidget {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 8px;
}}

/* ── Labels ──────────────────────────────── */
#field_label {{
    font-size: 10px;
    color: {t['text_secondary']};
    font-weight: bold;
    letter-spacing: 0.5px;
    padding-bottom: 2px;
}}
#required_star {{
    color: {t['danger']};
}}

/* ── Buttons ─────────────────────────────── */
QPushButton {{
    background-color: {t['bg_input']};
    border: 1px solid {t['border']};
    border-radius: 6px;
    padding: 7px 16px;
    color: {t['text_primary']};
    font-size: 11px;
}}
QPushButton:hover {{
    background-color: {t['bg_hover']};
    border-color: {t['text_secondary']};
}}
QPushButton:pressed {{
    background-color: {t['accent_dim']};
}}
#btn_primary {{
    background-color: {t['accent']};
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    color: white;
    font-size: 11px;
    font-weight: bold;
}}
#btn_primary:hover {{
    background-color: {t['accent_hover']};
}}
#btn_primary:pressed {{
    background-color: {t['accent_dim']};
}}
#btn_danger {{
    background-color: {t['danger']};
    border: none;
    border-radius: 6px;
    padding: 8px 20px;
    color: white;
    font-size: 11px;
    font-weight: bold;
}}
#btn_danger:hover {{
    background-color: #c0392b;
}}
#btn_icon {{
    background: transparent;
    border: none;
    padding: 4px;
    border-radius: 4px;
    font-size: 13px;
    color: {t['text_secondary']};
}}
#btn_icon:hover {{
    background-color: {t['bg_hover']};
    color: {t['text_primary']};
}}

/* ── Tables ──────────────────────────────── */
QTableWidget {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border']};
    border-radius: 8px;
    gridline-color: {t['border']};
    selection-background-color: {t['bg_selected']};
    selection-color: {t['text_primary']};
    alternate-background-color: {t['bg_hover']};
}}
QTableWidget::item {{
    padding: 6px 10px;
    border-bottom: 1px solid {t['border']};
}}
QTableWidget::item:selected {{
    background-color: {t['bg_selected']};
}}
QHeaderView::section {{
    background-color: {t['bg_sidebar']};
    color: {t['text_secondary']};
    font-size: 10px;
    font-weight: bold;
    letter-spacing: 0.5px;
    padding: 8px 10px;
    border: none;
    border-bottom: 1px solid {t['border']};
    border-right: 1px solid {t['border']};
}}

/* ── Scrollbars ──────────────────────────── */
QScrollBar:vertical {{
    background: transparent;
    width: 6px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {t['border']};
    border-radius: 3px;
    min-height: 20px;
}}
QScrollBar::handle:vertical:hover {{
    background: {t['text_dim']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 6px;
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
    color: {t['text_dim']};
    font-size: 10px;
    border-top: 1px solid {t['border']};
    padding: 3px 10px;
}}

/* ── Tooltips ────────────────────────────── */
QToolTip {{
    background-color: {t['bg_card']};
    color: {t['text_primary']};
    border: 1px solid {t['border']};
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 10px;
}}

/* ── Dialogs ─────────────────────────────── */
QDialog {{
    background-color: {t['bg_dialog']};
    border: 1px solid {t['border']};
    border-radius: 10px;
}}
QMessageBox {{
    background-color: {t['bg_dialog']};
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
    padding: 8px 18px;
    border-bottom: 2px solid transparent;
    font-size: 11px;
}}
QTabBar::tab:selected {{
    color: {t['accent']};
    border-bottom: 2px solid {t['accent']};
    font-weight: bold;
}}
QTabBar::tab:hover {{
    color: {t['text_primary']};
}}

/* ── Splitter ────────────────────────────── */
QSplitter::handle {{
    background-color: {t['border']};
    width: 1px;
    height: 1px;
}}

/* ── Completer popup ─────────────────────── */
QAbstractItemView {{
    background-color: {t['bg_card']};
    border: 1px solid {t['border_focus']};
    border-radius: 6px;
    selection-background-color: {t['accent_dim']};
    selection-color: {t['text_primary']};
    padding: 4px;
    outline: none;
}}
QAbstractItemView::item {{
    padding: 6px 10px;
    border-radius: 4px;
}}
"""
