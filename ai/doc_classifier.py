"""
DocumentClassifier — the FIRST AI step in the Document Inbox pipeline.

A document arrives (email / ADF scan / manual drop). Before we can extract
anything, we must know WHAT it is, because each type routes to a different
handler:

    purchase_invoice -> PURCHASE voucher draft
    sales_invoice    -> SALES voucher draft
    debit_note       -> DEBIT_NOTE voucher draft
    credit_note      -> CREDIT_NOTE voucher draft
    bank_statement   -> bank-reco import (MANY lines, not one voucher)
    other            -> hold for manual tagging; never guess-post

This module ONLY classifies + pulls a light summary (party, date, number,
amount) so the review queue can show the accountant a useful one-liner and
the AI's type guess. The heavy extraction is still done by
ai/voucher_ai.py once the accountant approves.

Routing is automatic via ai/ai_client. The feature id is
`document_inbox`, classed `byok` in config/ai_features.xlsx — i.e. it runs
on the CUSTOMER's own Anthropic key (a PRO/PREMIUM, bring-your-own-key
feature). Without a key the route resolves to 'locked' and ai_available
is False.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

# The doc types the pipeline knows how to route. Keep in sync with
# core/doc_inbox.ROUTABLE_TYPES and the voucher_ai document_type keys.
DOC_TYPES = (
    "purchase_invoice",
    "sales_invoice",
    "debit_note",
    "credit_note",
    "bank_statement",
    "ledger_statement",
    "other",
)

# Map a classified doc_type -> the document_type key VoucherAI understands.
# debit/credit notes reuse the invoice extractors (same field shape); the
# voucher TYPE is decided downstream from doc_type, not from the extractor.
VOUCHER_AI_DOCTYPE = {
    "purchase_invoice": "purchase_invoice",
    "sales_invoice":    "sales_invoice",
    "debit_note":       "purchase_invoice",
    "credit_note":      "sales_invoice",
    "bank_statement":   "bank_statement",
    "ledger_statement": "bank_statement",
    "other":            "expense_receipt",
}


class DocumentClassifier:

    MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str = "", feature: str = "document_inbox"):
        # api_key is the legacy direct-call override (tests / leftover
        # callers). In the app, leave it blank — routing is automatic.
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.feature = feature

    @property
    def ai_available(self) -> bool:
        if self.api_key:
            return True
        try:
            from core.ai_routing import routing, ROUTE_LOCKED
            return routing.resolve(self.feature) != ROUTE_LOCKED
        except Exception:
            return False

    def _call(self, payload: dict, timeout: int = 60) -> dict:
        if self.api_key:
            req = urllib.request.Request(
                "https://api.anthropic.com/v1/messages",
                data=json.dumps(payload).encode(),
                headers={
                    "Content-Type":      "application/json",
                    "x-api-key":         self.api_key,
                    "anthropic-version": "2023-06-01",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read())
        from ai.ai_client import call_messages
        return call_messages(self.feature, payload, timeout=timeout)

    def classify(self, document_text: str, company_name: str = "") -> dict:
        """
        Classify a document from its extracted text.

        Returns a dict (always — never raises for a 'can't tell' answer; an
        unreadable doc comes back as type 'other', confidence 0):

            {
                "doc_type":   one of DOC_TYPES,
                "confidence": 0.0 .. 1.0,
                "reason":     short human-readable why,
                "party":      counterparty name or "",
                "doc_number": invoice/note/statement number or "",
                "doc_date":   "YYYY-MM-DD" or "",
                "amount":     float or None,        # document total, best-effort
                "direction":  "incoming" | "outgoing" | "",  # ours-vs-theirs hint
            }

        Raises ValueError only if AI routing is not available at all.
        """
        if not self.ai_available:
            raise ValueError(
                "AI routing not configured. The Document Inbox needs your own "
                "Anthropic key (Settings -> AI / Anthropic Key) — it is a "
                "bring-your-own-key feature."
            )

        text = (document_text or "").strip()
        if not text:
            return {
                "doc_type": "other", "confidence": 0.0,
                "reason": "Document had no extractable text.",
                "party": "", "doc_number": "", "doc_date": "",
                "amount": None, "direction": "",
            }

        prompt = f"""You are an expert Indian accountant triaging an incoming document.
Decide WHAT KIND of accounting document this is, then pull a light summary.

Our company (the books these will be posted into): {company_name or "(unknown)"}

Classify into EXACTLY ONE of:
- "purchase_invoice"  : a bill FROM a supplier/vendor TO us (we owe money). Look for "Tax Invoice", a seller that is NOT us, our name as the buyer/bill-to.
- "sales_invoice"     : an invoice WE issued to a customer (they owe us). Our company is the seller.
- "debit_note"        : a debit note (often to a supplier — purchase return / extra charge).
- "credit_note"       : a credit note (often to a customer — sales return / discount).
- "bank_statement"    : a bank or card account statement with many dated transaction rows and a running balance. NOT a single invoice.
- "other"             : anything else (quotation, delivery challan, salary slip, contract, unreadable, junk). When unsure, use "other" — never guess a voucher type.

Decide direction from whose name is the seller vs buyer relative to our company.

Return ONLY a JSON object, no markdown, no code fences:
{{
  "doc_type": "one of the six above",
  "confidence": 0.0 to 1.0,
  "reason": "one short sentence",
  "party": "the OTHER party's name, or empty string",
  "doc_number": "invoice/note/statement number, or empty string",
  "doc_date": "YYYY-MM-DD or empty string",
  "amount": number (document grand total) or null,
  "direction": "incoming" if from someone else to us, "outgoing" if we issued it, else ""
}}

DOCUMENT CONTENT (first 12000 chars):
{text[:12000]}"""

        payload = {
            "model":      self.MODEL,
            "max_tokens": 600,
            "messages":   [{"role": "user", "content": prompt}],
        }
        try:
            data = self._call(payload, timeout=60)
        except urllib.error.HTTPError as e:
            body = getattr(e, "body_text", "") or ""
            raise ValueError(f"Classifier API error {e.code}: {body[:300]}")
        except urllib.error.URLError as e:
            raise ValueError(f"Cannot reach the AI service: {e}")

        raw = (data.get("content") or [{}])[0].get("text", "").strip()
        return self._coerce(raw)

    @staticmethod
    def _coerce(raw: str) -> dict:
        """Parse the model's reply defensively into the contract dict."""
        if "```" in raw:
            for part in raw.split("```"):
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("{"):
                    raw = p
                    break
        start, end = raw.find("{"), raw.rfind("}") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]

        out = {
            "doc_type": "other", "confidence": 0.0, "reason": "",
            "party": "", "doc_number": "", "doc_date": "",
            "amount": None, "direction": "",
        }
        try:
            obj = json.loads(raw)
        except Exception:
            out["reason"] = "Could not parse the classifier response."
            return out
        if not isinstance(obj, dict):
            return out

        dt = str(obj.get("doc_type", "")).strip().lower()
        out["doc_type"] = dt if dt in DOC_TYPES else "other"
        try:
            out["confidence"] = max(0.0, min(1.0, float(obj.get("confidence", 0.0))))
        except Exception:
            out["confidence"] = 0.0
        out["reason"]     = str(obj.get("reason", ""))[:300]
        out["party"]      = str(obj.get("party", ""))[:200]
        out["doc_number"] = str(obj.get("doc_number", ""))[:100]
        out["doc_date"]   = str(obj.get("doc_date", ""))[:10]
        out["direction"]  = str(obj.get("direction", "")).strip().lower()
        if out["direction"] not in ("incoming", "outgoing"):
            out["direction"] = ""
        amt = obj.get("amount")
        try:
            out["amount"] = abs(float(amt)) if amt is not None else None
        except Exception:
            out["amount"] = None
        return out
