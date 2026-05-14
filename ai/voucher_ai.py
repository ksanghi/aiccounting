"""
VoucherAI — universal document to voucher converter.
Works with any Indian bank — HDFC, Axis, SBI, ICICI, Union, Kotak, Yes, IndusInd etc.
Claude reads context not column names so format changes do not break extraction.
"""
import json
import os
import urllib.request
import urllib.error


class VoucherAI:

    MODEL = "claude-sonnet-4-6"

    def __init__(self, api_key: str = "", feature: str = "document_recognition"):
        # api_key is legacy — kept only so a leftover caller passing one
        # (or an ANTHROPIC_API_KEY env var in test runs) still works. In
        # the app, routing is automatic via ai/ai_client.
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.feature = feature

    @property
    def ai_available(self) -> bool:
        """True if this feature can make an AI call right now — i.e. its
        route resolves to something other than 'locked'."""
        if self.api_key:
            return True
        try:
            from core.ai_routing import routing, ROUTE_LOCKED
            return routing.resolve(self.feature) != ROUTE_LOCKED
        except Exception:
            return False

    def _call_anthropic(self, payload: dict, timeout: int = 120) -> dict:
        """Centralised call: legacy api_key → direct, else routed."""
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

    def extract_vouchers(
        self,
        document_text: str,
        ledger_names: list,
        document_type: str = "bank_statement",
        company_name: str = "",
    ) -> list:

        if not self.ai_available:
            raise ValueError(
                "AI routing not configured. Open Settings → AI Routing to "
                "paste your Anthropic key, or activate a paid license for "
                "pooled credits."
            )

        ledger_list = "\n".join(f"- {n}" for n in ledger_names[:150])

        type_instructions = {
            "bank_statement": """
BANK STATEMENT RULES:
- This could be from ANY Indian bank — HDFC, Axis, SBI, ICICI, Union, Kotak,
  Yes Bank, IndusInd, PNB, BOI, Canara, Federal, RBL, IDFC etc.
- Column names vary per bank. Use CONTEXT not column headers:
  * Money OUT = PAYMENT voucher
    (Debit / Dr / Withdrawal / Chq Amt / -Amount / debit amount)
  * Money IN = RECEIPT voucher
    (Credit / Cr / Deposit / +Amount / credit amount)
  * Bank to bank transfer = CONTRA
  * If single Amount column: negative = PAYMENT, positive = RECEIPT
- Skip: opening balance row, closing balance row, failed/bounced/reversed
  transactions, "To/From" balance summary rows, header rows
- Include: ALL actual debit/credit transaction rows
- Reference = cheque number, UTR, transaction ID, NEFT ref, UPI ref
- For narration guess the likely category:
  ATM withdrawal → Cash withdrawal
  NEFT/RTGS/IMPS to a name → Payment to [name]
  EMI → Loan EMI
  Salary credit → Salary received
  UPI → UPI payment/receipt to [merchant/person]
  NACH/ECS → NACH debit / standing instruction
""",
            "sales_invoice": """
SALES INVOICE / BILL RULES:
- Extract: invoice number, date, party name, line items with amounts, GST breakup
- Create: one SALES voucher
- Dr: party/customer ledger (gross amount including GST)
- Cr: Sales account (base/taxable amount)
- Cr: CGST Output / SGST Output or IGST Output (tax amounts)
- Reference = invoice number
""",
            "purchase_invoice": """
PURCHASE INVOICE / BILL RULES:
- Extract: bill number, date, vendor name, line items, GST breakup
- Create: one PURCHASE voucher
- Dr: Purchase account (base amount)
- Dr: Input CGST / Input SGST or Input IGST (ITC amounts)
- Cr: vendor/supplier ledger (gross amount)
- Reference = bill number
""",
            "broker_statement": """
BROKER / TRADING STATEMENT RULES:
- This could be Zerodha, ICICI Direct, HDFC Sec, Angel, Upstox, Groww etc.
- Identify: settlement credits/debits, brokerage charges, STT, GST on brokerage,
  dividend credits, mutual fund transactions
- Settlement credit = RECEIPT (money received from broker)
- Settlement debit = PAYMENT (funds transferred to broker)
- Charges (brokerage, STT, GST, DP charges) = PAYMENT to expense ledgers
- Reference = settlement number or trade ID
""",
            "expense_receipt": """
EXPENSE RECEIPT RULES:
- Extract: date, vendor/payee, amount, expense category
- Create: PAYMENT voucher
- Dr: appropriate expense ledger
- Cr: Cash or Bank account
- Suggest expense category from description
""",
        }

        type_hint = type_instructions.get(
            document_type, type_instructions["bank_statement"]
        )

        prompt = f"""You are an expert Indian accountant using double-entry bookkeeping.
Extract ALL financial transactions from this document and convert to vouchers.

Company: {company_name}
Document type: {document_type}

{type_hint}

LEDGER ACCOUNTS AVAILABLE IN THE SYSTEM:
{ledger_list}

LEDGER MATCHING RULES:
- Match Dr and Cr ledger names EXACTLY from the list above (case-sensitive)
- If no exact match: use closest match and add " (NEW)" suffix
  e.g. "Rent Expense (NEW)" — this alerts the user to create the ledger
- For bank accounts: look for the bank name in the list (e.g. "HDFC Current Account")
- For unknown parties: use "Sundry Creditors" or "Sundry Debtors" from the list
- Common mappings:
  * ATM / cash withdrawal → "Cash" ledger
  * Salary → "Salary" or "Salaries & Wages" ledger
  * EMI / loan repayment → loan account ledger
  * Utility bills → respective expense ledger

CONFIDENCE SCORING:
- 0.95+ : clear transaction, exact ledger match
- 0.80  : clear transaction, approximate ledger match
- 0.60  : transaction clear, ledger guessed
- 0.40  : transaction unclear or partial data

IMPORTANT: Return ONLY a valid JSON array. No markdown, no code fences, no explanation.
Start directly with [ and end with ].

[
  {{
    "date": "YYYY-MM-DD",
    "voucher_type": "PAYMENT|RECEIPT|JOURNAL|CONTRA",
    "dr_ledger": "exact name from list or Name (NEW)",
    "cr_ledger": "exact name from list or Name (NEW)",
    "amount": 1234.56,
    "narration": "clear human-readable description",
    "reference": "cheque/UTR/invoice number or empty string",
    "confidence": 0.95,
    "raw_line": "original text from document"
  }}
]

DOCUMENT CONTENT:
{document_text[:20000]}"""

        payload = {
            "model":      self.MODEL,
            "max_tokens": 8192,
            "messages":   [{"role": "user", "content": prompt}],
        }
        try:
            data = self._call_anthropic(payload, timeout=120)
        except urllib.error.HTTPError as e:
            body = getattr(e, "body_text", "") or ""
            raise ValueError(f"API error {e.code}: {body}")
        except urllib.error.URLError as e:
            raise ValueError(f"Cannot reach Claude API: {e}")

        raw = data["content"][0]["text"].strip()

        # Strip markdown fences if present
        if "```" in raw:
            for part in raw.split("```"):
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("["):
                    raw = p
                    break

        # Find JSON array boundaries
        start = raw.find("[")
        end   = raw.rfind("]") + 1
        if start >= 0 and end > start:
            raw = raw[start:end]

        try:
            result = json.loads(raw)
            if not isinstance(result, list):
                raise ValueError("Response is not a list")

            cleaned = []
            for item in result:
                if not isinstance(item, dict):
                    continue
                if not item.get("date"):
                    continue
                if not item.get("amount"):
                    continue
                # Normalise amount to positive float
                try:
                    item["amount"] = abs(float(item["amount"]))
                except Exception:
                    continue
                # Ensure valid voucher type
                if item.get("voucher_type") not in (
                    "PAYMENT", "RECEIPT", "JOURNAL", "CONTRA"
                ):
                    item["voucher_type"] = "JOURNAL"
                # Clamp confidence
                try:
                    item["confidence"] = max(0.0, min(1.0, float(item.get("confidence", 0.7))))
                except Exception:
                    item["confidence"] = 0.7
                cleaned.append(item)
            return cleaned

        except json.JSONDecodeError as e:
            raise ValueError(
                f"Could not parse Claude response as JSON.\n"
                f"Error: {e}\n"
                f"Response preview: {raw[:500]}"
            )

    def extract_bank_statement_lines(
        self,
        document_text: str,
        bank_ledger_name: str,
        ledger_names: list,
        company_name: str = "",
    ) -> dict:
        """
        Wrapper around extract_vouchers for bank reconciliation.
        Returns reconciliation-friendly statement lines instead of vouchers
        ready to post — the reconciler decides what to do with them.

        Returns:
            {
                "period_from": "YYYY-MM-DD" | None,
                "period_to":   "YYYY-MM-DD" | None,
                "statement_opening": float | None,    # v1: always None
                "statement_closing": float | None,    # v1: always None
                "lines": [
                    {
                        "txn_date": "YYYY-MM-DD",
                        "amount":   123.45,           # always positive
                        "sign":     "DR" | "CR",      # bank's POV: DR=out, CR=in
                        "narration": "...",
                        "reference": "...",
                        "raw_extracted": {...},       # original dict for audit
                    },
                    ...
                ],
            }
        """
        vouchers = self.extract_vouchers(
            document_text,
            ledger_names,
            document_type="bank_statement",
            company_name=company_name,
        )

        bank_lower = (bank_ledger_name or "").lower().strip()
        lines = []
        for v in vouchers:
            sign = self._infer_sign(v, bank_lower)
            if sign is None:
                # Could not place the bank ledger on either side — store anyway
                # as raw, the user will see it as UNMATCHED in the review tab.
                sign = "DR" if v.get("voucher_type") == "PAYMENT" else "CR"
            lines.append({
                "txn_date":      v["date"],
                "amount":        v["amount"],
                "sign":          sign,
                "narration":     v.get("narration", ""),
                "reference":     v.get("reference", ""),
                "raw_extracted": v,
            })

        dates = [l["txn_date"] for l in lines if l.get("txn_date")]
        return {
            "period_from":       min(dates) if dates else None,
            "period_to":         max(dates) if dates else None,
            "statement_opening": None,
            "statement_closing": None,
            "lines":             lines,
        }

    @staticmethod
    def _infer_sign(voucher: dict, bank_ledger_lower: str) -> str | None:
        """
        Bank-side sign convention:
            DR = money OUT of the bank (statement debit)
            CR = money INTO the bank (statement credit)
        """
        vt = voucher.get("voucher_type")
        dr = (voucher.get("dr_ledger") or "").lower().strip()
        cr = (voucher.get("cr_ledger") or "").lower().strip()
        if vt == "PAYMENT":
            return "DR"
        if vt == "RECEIPT":
            return "CR"
        if vt == "CONTRA":
            # If bank is on the Dr side, it received money → CR (credit) on stmt.
            if bank_ledger_lower and bank_ledger_lower in dr:
                return "CR"
            if bank_ledger_lower and bank_ledger_lower in cr:
                return "DR"
            return None
        # JOURNAL or anything else: place by which side mentions the bank.
        if bank_ledger_lower and bank_ledger_lower in dr:
            return "CR"
        if bank_ledger_lower and bank_ledger_lower in cr:
            return "DR"
        return None

    def suggest_ledger(
        self,
        narration: str,
        ledger_names: list,
        is_debit: bool = True,
    ) -> str:
        """Quick ledger suggestion for a single narration line."""
        if not self.ai_available or len(ledger_names) < 2:
            return ""
        try:
            ledger_list = "\n".join(f"- {n}" for n in ledger_names[:80])
            direction   = "debit (money going out)" if is_debit else "credit (money coming in)"
            prompt = (
                f"From this ledger list:\n{ledger_list}\n\n"
                f"Which ledger best matches this {direction} transaction:\n"
                f'"{narration}"\n\n'
                f"Reply with ONLY the exact ledger name from the list. Nothing else."
            )
            payload = {
                "model":      self.MODEL,
                "max_tokens": 30,
                "messages":   [{"role": "user", "content": prompt}],
            }
            data = self._call_anthropic(payload, timeout=15)
            return data["content"][0]["text"].strip()
        except Exception:
            return ""
