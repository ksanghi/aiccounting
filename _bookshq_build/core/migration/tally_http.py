"""
Tally Prime / Tally ERP 9 (release 5+) HTTP-XML client.

Pulls groups, ledger masters, and vouchers from a running Tally instance
by POSTing XML envelopes to its HTTP server (default localhost:9000).
Returns the same MigrationPayload shape every other parser produces, so
the Migrator consumes it unchanged.

Wire format references (developed blind, validated later):
  - help.tallysolutions.com/article/DeveloperReference/integration-capabilities/case_study_1.htm
  - help.tallysolutions.com/sample-xml/
  - github.com/ramajayam-CA/TallyConnector-V2.0 (field list)
  - github.com/NoumaanAhamed/tally-prime-api-docs (Day Book envelope)

Same envelope works on Tally Prime and ERP9 r5+; no dispatch needed.

Amount sign convention (load-bearing): Tally's <AMOUNT> is signed, but
the canonical Dr/Cr is determined by <ISDEEMEDPOSITIVE>:
    Yes -> Dr,  No -> Cr.
The wire amount can be negative on the Dr side as a redundant encoding.
We take abs(amount) and rely on ISDEEMEDPOSITIVE.
"""
from __future__ import annotations

import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date
from typing import Optional

from .payload import (
    CompanySpec, GroupSpec, LedgerSpec, MigrationPayload,
    VoucherLineSpec, VoucherSpec,
)
from .tally_xml import (
    _NATURE_MAP, _parse_float, _state_code, _txt, is_tally_reserved,
)


DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9000
DEFAULT_TIMEOUT = 60          # voucher dumps for a full FY can be slow
PROBE_TIMEOUT = 5


# Tally's built-in voucher type names -> our ALL_CAPS codes.
# Customer-defined voucher types (e.g. "Bank Receipt") inherit a parent
# class — we look up by parent name when present, else by the wire name.
_VTYPE_MAP = {
    "payment":     "PAYMENT",
    "receipt":     "RECEIPT",
    "journal":     "JOURNAL",
    "contra":      "CONTRA",
    "sales":       "SALES",
    "purchase":    "PURCHASE",
    "debit note":  "DEBIT_NOTE",
    "credit note": "CREDIT_NOTE",
}


class TallyHTTPError(Exception):
    """Raised when the Tally HTTP server is unreachable, returns a non-XML
    response, or rejects our request."""


# ── Transport ──────────────────────────────────────────────────────────

def _post(envelope: str, host: str, port: int, timeout: float) -> ET.Element:
    url = f"http://{host}:{port}/"
    req = urllib.request.Request(
        url,
        data=envelope.encode("utf-8"),
        method="POST",
        headers={"Content-Type": "text/xml; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except (urllib.error.URLError, socket.timeout, ConnectionError, OSError) as e:
        raise TallyHTTPError(
            f"Could not reach Tally at {host}:{port} — {e}"
        ) from e

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        raise TallyHTTPError(
            f"Tally at {host}:{port} returned non-XML. The port responded "
            f"but doesn't look like a Tally HTTP server."
        ) from e
    if root.tag != "ENVELOPE":
        raise TallyHTTPError(
            f"Expected <ENVELOPE> root, got <{root.tag}>. The port answered "
            f"but it isn't Tally."
        )
    return root


# ── Public utilities (called by the wizard's connectivity step) ────────

def probe(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
          timeout: float = PROBE_TIMEOUT) -> str:
    """Liveness check. Returns the name of the currently-loaded company
    (or '' if none is loaded). Raises TallyHTTPError on connection or
    protocol failure."""
    envelope = (
        '<ENVELOPE>'
        '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
        '<TYPE>Function</TYPE><ID>$$CmpName</ID></HEADER>'
        '<BODY><DESC><STATICVARIABLES>'
        '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
        '</STATICVARIABLES></DESC></BODY>'
        '</ENVELOPE>'
    )
    root = _post(envelope, host, port, timeout)
    result = root.find(".//RESULT")
    return (result.text or "").strip() if result is not None else ""


def list_companies(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
                   timeout: float = DEFAULT_TIMEOUT) -> list[str]:
    """Returns names of all companies currently loaded in Tally."""
    envelope = (
        '<ENVELOPE>'
        '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
        '<TYPE>Collection</TYPE><ID>List of Companies</ID></HEADER>'
        '<BODY><DESC>'
        '<STATICVARIABLES>'
        '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
        '<SVISLOADED>YES</SVISLOADED>'
        '</STATICVARIABLES>'
        '<TDL><TDLMESSAGE>'
        '<COLLECTION NAME="List of Companies" ISINITIALIZE="Yes">'
        '<TYPE>Company</TYPE>'
        '<NATIVEMETHOD>Name</NATIVEMETHOD>'
        '<NATIVEMETHOD>StartingFrom</NATIVEMETHOD>'
        '<NATIVEMETHOD>EndingAt</NATIVEMETHOD>'
        '<FILTER>IsLoadedCmp</FILTER>'
        '</COLLECTION>'
        '<SYSTEM TYPE="Formulae" NAME="IsLoadedCmp">$$IsCurrentCompany:$Name</SYSTEM>'
        '</TDLMESSAGE></TDL>'
        '</DESC></BODY>'
        '</ENVELOPE>'
    )
    root = _post(envelope, host, port, timeout)
    names: list[str] = []
    for cel in root.iter("COMPANY"):
        name = cel.attrib.get("NAME")
        if not name:
            name = _txt(cel, "LANGUAGENAME.LIST/NAME.LIST/NAME", "NAME")
        if name:
            names.append(name.strip())
    return names


# ── Main entry point ───────────────────────────────────────────────────

def pull(company: str, fy_from: date, fy_to: date,
         host: str = DEFAULT_HOST, port: int = DEFAULT_PORT,
         timeout: float = DEFAULT_TIMEOUT) -> MigrationPayload:
    """Pull groups + ledgers + vouchers (over the given date range) from a
    running Tally instance. Returns a MigrationPayload ready for the
    Migrator to validate and apply."""
    payload = MigrationPayload(
        source_type="TALLY_HTTP",
        source_label=f"Tally live ({company})",
        file_name=f"{host}:{port}/{company}",
        file_hash="",  # not file-based
    )

    payload.company = CompanySpec(name=company)
    payload.groups = _pull_groups(company, host, port, timeout)
    ledgers, skipped = _pull_ledgers(company, host, port, timeout)
    payload.ledgers = ledgers
    payload.vouchers = _pull_vouchers(company, fy_from, fy_to, host, port, timeout)

    if not payload.groups and not payload.ledgers:
        payload.notes.append(
            f"No groups or ledgers returned for company '{company}'. "
            f"Verify the company is loaded in Tally and the name matches "
            f"exactly (case-sensitive)."
        )
    if skipped:
        payload.notes.append(
            f"Skipped {len(skipped)} Tally reserved ledger(s) "
            f"({', '.join(skipped)}) — system fixtures, not user ledgers."
        )
    if not payload.vouchers:
        payload.notes.append(
            f"No vouchers in range {fy_from.isoformat()} -> {fy_to.isoformat()}."
        )
    return payload


# ── Groups ─────────────────────────────────────────────────────────────

def _pull_groups(company: str, host: str, port: int,
                 timeout: float) -> list[GroupSpec]:
    envelope = (
        '<ENVELOPE>'
        '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
        '<TYPE>Collection</TYPE><ID>List of Groups</ID></HEADER>'
        '<BODY><DESC>'
        '<STATICVARIABLES>'
        '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
        f'<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>'
        '</STATICVARIABLES>'
        '<TDL><TDLMESSAGE>'
        '<COLLECTION NAME="List of Groups" ISINITIALIZE="Yes">'
        '<TYPE>Group</TYPE>'
        '<FETCH>Name, Parent, Primary, IsRevenue, IsDeemedPositive,'
        ' IsReserved, AffectsGrossProfit</FETCH>'
        '</COLLECTION>'
        '</TDLMESSAGE></TDL>'
        '</DESC></BODY>'
        '</ENVELOPE>'
    )
    root = _post(envelope, host, port, timeout)
    groups: list[GroupSpec] = []
    for gel in root.iter("GROUP"):
        name = (gel.attrib.get("NAME") or _txt(gel, "NAME")).strip()
        if not name:
            continue
        primary = _txt(gel, "PRIMARY", "PRIMARYGROUP")
        groups.append(GroupSpec(
            name        = name,
            parent_name = _txt(gel, "PARENT") or None,
            nature      = _NATURE_MAP.get(primary.lower(), ""),
            affects_gross_profit = _truthy(_txt(gel, "AFFECTSGROSSPROFIT")),
        ))
    return groups


# ── Ledgers ────────────────────────────────────────────────────────────

def _pull_ledgers(company: str, host: str, port: int,
                  timeout: float) -> tuple[list[LedgerSpec], list[str]]:
    envelope = (
        '<ENVELOPE>'
        '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
        '<TYPE>Collection</TYPE><ID>FullLedgerColl</ID></HEADER>'
        '<BODY><DESC>'
        '<STATICVARIABLES>'
        '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
        f'<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>'
        '</STATICVARIABLES>'
        '<TDL><TDLMESSAGE>'
        '<COLLECTION NAME="FullLedgerColl" ISINITIALIZE="Yes">'
        '<TYPE>Ledger</TYPE>'
        '<FETCH>Name, Parent, OpeningBalance, PartyGSTIN,'
        ' GSTRegistrationType, IncomeTaxNumber, LedStateName,'
        ' MailingName, Address,'
        ' LedgerBankDetails, BankAccountHolderName, BankName,'
        ' BankAccountNumber, BankIFSCCode, BranchName,'
        ' TDSDeducteeType, IsTDSDeductable</FETCH>'
        '</COLLECTION>'
        '</TDLMESSAGE></TDL>'
        '</DESC></BODY>'
        '</ENVELOPE>'
    )
    root = _post(envelope, host, port, timeout)
    ledgers: list[LedgerSpec] = []
    skipped: list[str] = []
    for lel in root.iter("LEDGER"):
        name = (lel.attrib.get("NAME") or _txt(lel, "NAME")).strip()
        if not name:
            continue
        if is_tally_reserved(name):
            skipped.append(name)
            continue
        group_name = _txt(lel, "PARENT")
        # Tally's OPENINGBALANCE sign convention is OPPOSITE to accounting
        # Dr/Cr: positive = Cr, negative = Dr. Verified on real exports —
        # see comment in tally_xml.py for evidence.
        ob = _parse_float(_txt(lel, "OPENINGBALANCE"))
        opening_type = "Cr" if ob >= 0 else "Dr"
        opening_balance = abs(ob)

        bank_el = lel.find("LEDGERBANKDETAILS.LIST") or lel.find(".//LEDGERBANKDETAILS")
        bank_name      = _txt(bank_el, "BANKNAME", "BANKERSNAME") or None
        account_number = _txt(bank_el, "BANKACCOUNTNUMBER") or None
        ifsc           = _txt(bank_el, "IFSCCODE", "BANKIFSCODE", "BANKIFSC") or None

        glower = group_name.lower()
        is_bank = ("bank accounts" in glower
                   or bank_name is not None or account_number is not None)
        is_cash = "cash-in-hand" in glower or "cash in hand" in glower
        is_gst  = "duties & taxes" in glower or "duties and taxes" in glower

        tds_section = _txt(lel, "TDSDEDUCTEETYPE") or None
        is_tds = _truthy(_txt(lel, "ISTDSDEDUCTABLE")) or bool(tds_section)

        ledgers.append(LedgerSpec(
            name              = name,
            group_name        = group_name,
            opening_balance   = opening_balance,
            opening_type      = opening_type,
            gstin             = _txt(lel, "PARTYGSTIN") or None,
            pan               = _txt(lel, "INCOMETAXNUMBER", "PANNUMBER") or None,
            state_code        = _state_code(_txt(lel, "LEDSTATENAME", "STATENAME")),
            is_bank           = is_bank,
            is_cash           = is_cash,
            is_gst_ledger     = is_gst,
            bank_name         = bank_name,
            account_number    = account_number,
            ifsc              = ifsc,
            is_tds_applicable = is_tds,
            tds_section       = tds_section,
            tds_rate          = None,  # not on the master in Tally; per-section
        ))
    return ledgers, skipped


# ── Vouchers ───────────────────────────────────────────────────────────

def _pull_vouchers(company: str, fy_from: date, fy_to: date,
                   host: str, port: int, timeout: float) -> list[VoucherSpec]:
    envelope = (
        '<ENVELOPE>'
        '<HEADER><VERSION>1</VERSION><TALLYREQUEST>Export</TALLYREQUEST>'
        '<TYPE>Data</TYPE><ID>Day Book</ID></HEADER>'
        '<BODY><DESC>'
        '<STATICVARIABLES>'
        '<SVEXPORTFORMAT>$$SysName:XML</SVEXPORTFORMAT>'
        f'<SVCURRENTCOMPANY>{_xml_escape(company)}</SVCURRENTCOMPANY>'
        f'<SVFROMDATE TYPE="Date">{_fmt_tally_date(fy_from)}</SVFROMDATE>'
        f'<SVTODATE TYPE="Date">{_fmt_tally_date(fy_to)}</SVTODATE>'
        '</STATICVARIABLES>'
        '</DESC></BODY>'
        '</ENVELOPE>'
    )
    root = _post(envelope, host, port, timeout)

    vouchers: list[VoucherSpec] = []
    for vel in root.iter("VOUCHER"):
        # Skip cancelled and optional (draft) vouchers — these are not
        # posted in Tally's books and shouldn't migrate.
        if _truthy(_txt(vel, "ISCANCELLED")) or _truthy(_txt(vel, "ISOPTIONAL")):
            continue

        wire_type = (
            vel.attrib.get("VCHTYPE")
            or _txt(vel, "VOUCHERTYPENAME")
            or ""
        ).strip()
        # Look up canonical type; for custom voucher types we'd need a
        # separate FETCH on VoucherType.Parent to resolve — for v1 fall
        # back to JOURNAL with a note in the narration.
        canon = _VTYPE_MAP.get(wire_type.lower())
        if not canon:
            # Custom voucher type — best-effort match by substring on the
            # canonical class names before giving up.
            wt = wire_type.lower()
            canon = next(
                (v for k, v in _VTYPE_MAP.items() if k in wt),
                "JOURNAL",
            )

        date_str = _parse_tally_date(_txt(vel, "DATE"))
        if not date_str:
            continue  # vouchers without a date are malformed; skip

        # Voucher number: VOUCHERNUMBER preferred, GUID-prefix as fallback
        # so the dedupe key (voucher_number, fy) remains unique.
        vch_no = _txt(vel, "VOUCHERNUMBER")
        if not vch_no:
            guid = _txt(vel, "GUID")
            vch_no = (guid.split("-")[-1] if guid else "")[:12] or "AUTO"

        ref_date_raw = _txt(vel, "REFERENCEDATE")
        lines = _parse_voucher_lines(vel)
        if not lines:
            continue  # voucher with no accounting legs — skip

        vouchers.append(VoucherSpec(
            voucher_type     = canon,
            voucher_number   = vch_no,
            date             = date_str,
            fy               = _fy_for(date_str),
            narration        = _txt(vel, "NARRATION"),
            party_ledger     = _txt(vel, "PARTYLEDGERNAME", "PARTYNAME") or None,
            reference_number = _txt(vel, "REFERENCE") or None,
            reference_date   = _parse_tally_date(ref_date_raw) or None,
            lines            = lines,
        ))
    return vouchers


def _parse_voucher_lines(vel: ET.Element) -> list[VoucherLineSpec]:
    """Read every <ALLLEDGERENTRIES.LIST> block in a voucher and emit a
    VoucherLineSpec. Sign convention: ISDEEMEDPOSITIVE=Yes -> Dr."""
    lines: list[VoucherLineSpec] = []
    for lel in vel.iter("ALLLEDGERENTRIES.LIST"):
        ledger_name = _txt(lel, "LEDGERNAME").strip()
        if not ledger_name:
            continue
        raw_amt = _txt(lel, "AMOUNT")
        amt = abs(_parse_float(raw_amt))
        if amt == 0:
            continue  # zero-value padding lines from Tally — drop
        dr_cr = "Dr" if _truthy(_txt(lel, "ISDEEMEDPOSITIVE")) else "Cr"
        lines.append(VoucherLineSpec(
            ledger_name = ledger_name,
            amount      = amt,
            dr_cr       = dr_cr,
            # GST/TDS line metadata is inferred by the Migrator from the
            # ledger master flags — we don't try to second-guess here.
        ))
    return lines


# ── Helpers ────────────────────────────────────────────────────────────

def _fmt_tally_date(d: date) -> str:
    return d.strftime("%Y%m%d")


def _parse_tally_date(raw: str) -> str:
    """YYYYMMDD -> YYYY-MM-DD. Returns '' if unparseable."""
    s = (raw or "").strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[0:4]}-{s[4:6]}-{s[6:8]}"
    return ""


def _fy_for(date_str: str) -> str:
    """India FY (Apr-Mar). '2025-04-15' -> '2025-26'."""
    try:
        y, m, _ = date_str.split("-")
        yy, mm = int(y), int(m)
    except ValueError:
        return ""
    start = yy if mm >= 4 else yy - 1
    return f"{start}-{str(start + 1)[2:]}"


def _truthy(s: str) -> bool:
    return str(s or "").strip().lower() in ("yes", "true", "1")


def _xml_escape(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&apos;")
    )
