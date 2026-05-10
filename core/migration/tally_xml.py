"""
Tally Prime / Tally ERP 9 XML master export parser.

Standard Tally Master export shape (simplified):

    <ENVELOPE>
      <BODY><DATA>
        <COMPANY>
          <NAME>...</NAME>
          <GSTREGISTRATIONNUMBER>...</GSTREGISTRATIONNUMBER>
          <STATENAME>Maharashtra</STATENAME>
          ...
        </COMPANY>
        <GROUP NAME="Sundry Creditors">
          <PARENT>Current Liabilities</PARENT>
          <PRIMARYGROUP>Liabilities</PRIMARYGROUP>
          <ISBILLWISEON>Yes</ISBILLWISEON>
          ...
        </GROUP>
        <LEDGER NAME="Acme Corp">
          <PARENT>Sundry Creditors</PARENT>
          <OPENINGBALANCE>-1000.00</OPENINGBALANCE>     <!-- negative = Cr -->
          <PARTYGSTIN>27ABCDE1234F1Z5</PARTYGSTIN>
          <INCOMETAXNUMBER>ABCDE1234F</INCOMETAXNUMBER>
          <STATENAME>Maharashtra</STATENAME>
          <BANKDETAILS.LIST>
            <BANKACCOUNTNUMBER>50100012345</BANKACCOUNTNUMBER>
            <BANKIFSCODE>HDFC0001234</BANKIFSCODE>
            <BANKERSNAME>HDFC Bank</BANKERSNAME>
          </BANKDETAILS.LIST>
        </LEDGER>
      </DATA></BODY>
    </ENVELOPE>

The parser is liberal — fields that aren't present just leave the
LedgerSpec attribute None. Tally's opening balance sign convention:
positive = Dr, negative = Cr.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

from .payload import (
    MigrationPayload, GroupSpec, LedgerSpec, CompanySpec,
)


# ── Tally PRIMARYGROUP → our nature ─────────────────────────────────────────

_NATURE_MAP = {
    "assets":      "ASSET",
    "asset":       "ASSET",
    "liabilities": "LIABILITY",
    "liability":   "LIABILITY",
    "income":      "INCOME",
    "revenue":     "INCOME",
    "expenses":    "EXPENSE",
    "expense":     "EXPENSE",
}


# ── Indian state name → 2-digit GST state code ──────────────────────────────

_STATE_CODE = {
    "jammu and kashmir":             "01",
    "himachal pradesh":              "02",
    "punjab":                        "03",
    "chandigarh":                    "04",
    "uttarakhand":                   "05",
    "haryana":                       "06",
    "delhi":                         "07",
    "rajasthan":                     "08",
    "uttar pradesh":                 "09",
    "bihar":                         "10",
    "sikkim":                        "11",
    "arunachal pradesh":             "12",
    "nagaland":                      "13",
    "manipur":                       "14",
    "mizoram":                       "15",
    "tripura":                       "16",
    "meghalaya":                     "17",
    "assam":                         "18",
    "west bengal":                   "19",
    "jharkhand":                     "20",
    "odisha":                        "21",
    "chhattisgarh":                  "22",
    "madhya pradesh":                "23",
    "gujarat":                       "24",
    "daman and diu":                 "25",
    "dadra and nagar haveli":        "26",
    "maharashtra":                   "27",
    "karnataka":                     "29",
    "goa":                           "30",
    "lakshadweep":                   "31",
    "kerala":                        "32",
    "tamil nadu":                    "33",
    "puducherry":                    "34",
    "andaman and nicobar islands":   "35",
    "telangana":                     "36",
    "andhra pradesh":                "37",
    "ladakh":                        "38",
    "other territory":               "97",
}


def _state_code(name: Optional[str]) -> Optional[str]:
    if not name:
        return None
    key = str(name).strip().lower()
    return _STATE_CODE.get(key)


def _txt(el, *paths: str) -> str:
    """Return the text of the first matching child path, '' if missing."""
    if el is None:
        return ""
    for p in paths:
        node = el.find(p)
        if node is not None and node.text is not None:
            return node.text.strip()
    return ""


def _parse_float(raw: str) -> float:
    s = (raw or "").strip()
    if not s:
        return 0.0
    # Tally sometimes uses 'Dr'/'Cr' suffix
    suffix = ""
    for sx in (" Dr", " Cr", "Dr", "Cr"):
        if s.endswith(sx):
            suffix = sx.strip().upper()
            s = s[: -len(sx)].strip()
            break
    s = s.replace(",", "")
    try:
        v = float(s)
    except ValueError:
        return 0.0
    if suffix == "CR":
        v = -abs(v)
    elif suffix == "DR":
        v = abs(v)
    return v


# ── Top-level parser ────────────────────────────────────────────────────────

def parse_tally_xml(file_path: str) -> MigrationPayload:
    from .migrator import Migrator
    path = Path(file_path)
    if not path.exists():
        raise ValueError(f"File not found: {file_path}")

    try:
        tree = ET.parse(path)
    except ET.ParseError as e:
        raise ValueError(f"Could not parse Tally XML: {e}")
    root = tree.getroot()

    # Walk down — Tally exports nest under ENVELOPE/BODY/DATA but not always
    data = root.find(".//DATA") or root.find(".//BODY/DATA") or root

    payload = MigrationPayload(
        source_type="TALLY_XML",
        source_label="Tally Prime / ERP 9 export",
        file_name=path.name,
        file_hash=Migrator.sha256(path),
    )

    # ── Company metadata ──
    company_el = data.find(".//COMPANY")
    if company_el is not None:
        cspec = CompanySpec(
            name      = _txt(company_el, "NAME"),
            gstin     = _txt(company_el, "GSTREGISTRATIONNUMBER", "PARTYGSTIN")
                        or None,
            pan       = _txt(company_el, "INCOMETAXNUMBER") or None,
            state_code= _state_code(_txt(company_el, "STATENAME")),
            address   = _txt(company_el, "ADDRESS") or None,
        )
        payload.company = cspec

    # ── Groups ──
    for gel in data.iter("GROUP"):
        name = (gel.attrib.get("NAME") or _txt(gel, "NAME")).strip()
        if not name:
            continue
        primary = _txt(gel, "PRIMARYGROUP")
        payload.groups.append(GroupSpec(
            name        = name,
            parent_name = _txt(gel, "PARENT") or None,
            nature      = _NATURE_MAP.get(primary.lower(), ""),
            affects_gross_profit=_truthy(_txt(gel, "AFFECTSGROSSPROFIT", "ISTRADINGITEM")),
        ))

    # ── Ledger master ──
    for lel in data.iter("LEDGER"):
        name = (lel.attrib.get("NAME") or _txt(lel, "NAME")).strip()
        if not name:
            continue
        group_name = _txt(lel, "PARENT")
        ob = _parse_float(_txt(lel, "OPENINGBALANCE"))
        opening_type = "Dr" if ob >= 0 else "Cr"
        opening_balance = abs(ob)

        # Bank details
        bank_el = lel.find("BANKDETAILS.LIST") or lel.find(".//BANKDETAILS")
        account_number = _txt(bank_el, "BANKACCOUNTNUMBER") or None
        ifsc           = _txt(bank_el, "BANKIFSCODE", "BANKIFSC") or None
        bank_name      = _txt(bank_el, "BANKERSNAME", "BANKNAME") or None

        # Auto-derive flags from group
        glower = group_name.lower()
        is_bank = "bank accounts" in glower or bank_name is not None or account_number is not None
        is_cash = "cash-in-hand" in glower or "cash in hand" in glower
        is_gst  = "duties & taxes" in glower or "duties and taxes" in glower

        # TDS info — Tally stores under TDSDETAILS.LIST
        tds_el = lel.find("TDSDETAILS.LIST") or lel.find(".//TDSDETAILS")
        tds_section = _txt(tds_el, "SECTIONREFERENCE", "SECTION") or None
        tds_rate    = _parse_float(_txt(tds_el, "RATEOFTDS", "RATE")) or None
        is_tds      = bool(tds_section)

        payload.ledgers.append(LedgerSpec(
            name              = name,
            group_name        = group_name,
            opening_balance   = opening_balance,
            opening_type      = opening_type,
            gstin             = _txt(lel, "PARTYGSTIN") or None,
            pan               = _txt(lel, "INCOMETAXNUMBER", "PANNUMBER") or None,
            state_code        = _state_code(_txt(lel, "STATENAME")),
            is_bank           = is_bank,
            is_cash           = is_cash,
            is_gst_ledger     = is_gst,
            bank_name         = bank_name,
            account_number    = account_number,
            ifsc              = ifsc,
            is_tds_applicable = is_tds,
            tds_section       = tds_section,
            tds_rate          = tds_rate,
        ))

    if not payload.groups and not payload.ledgers:
        payload.notes.append(
            "No <GROUP> or <LEDGER> elements found. Verify the file is a "
            "Tally master export (Display More Reports → List of Accounts → "
            "Alt+E → Export → Format: XML)."
        )

    return payload


def _truthy(s: str) -> bool:
    return str(s or "").strip().lower() in ("yes", "true", "1")
