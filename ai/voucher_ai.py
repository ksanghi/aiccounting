"""
VoucherAI — sends extracted text to Claude API
and gets back structured voucher drafts.
"""
import json
import os
import urllib.request


class VoucherAI:

    MODEL = "claude-sonnet-4-20250514"

    def __init__(self, api_key: str = ""):
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    def extract_vouchers(
        self,
        document_text: str,
        ledger_names: list,
        document_type: str = "bank_statement",
        company_name: str = "",
    ) -> list:
        if not self.api_key:
            raise ValueError(
                "Claude API key not set. Go to Settings -> API Key."
            )

        ledger_list = "\n".join(f"- {n}" for n in ledger_names[:120])

        prompt = f"""You are an expert Indian accountant using double-entry bookkeeping.

Company: {company_name}
Document type: {document_type}

Available ledger accounts:
{ledger_list}

Analyze the document and extract ALL financial transactions. Rules:
- Bank statement DEBIT = money out = PAYMENT voucher
- Bank statement CREDIT = money in = RECEIPT voucher
- Transfer between bank accounts = CONTRA voucher
- Non-cash adjustments = JOURNAL voucher
- Match ledger names EXACTLY from the list above
- If no match exists add "(NEW)" suffix to name
- Skip opening/closing balance summary rows
- Skip failed/reversed/bounced transactions
- For GST transactions note the tax component
- Date format must be YYYY-MM-DD

Return ONLY a valid JSON array, no markdown, no explanation, just the array:
[
  {{
    "date": "YYYY-MM-DD",
    "voucher_type": "PAYMENT",
    "dr_ledger": "Rent A/c",
    "cr_ledger": "HDFC Current Account",
    "amount": 25000.00,
    "narration": "Rent payment May 2025",
    "reference": "CHQ001",
    "confidence": 0.95,
    "raw_line": "original text from document"
  }}
]

Document content:
{document_text[:15000]}"""

        payload = json.dumps({
            "model": self.MODEL,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()

        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "Content-Type":      "application/json",
                "x-api-key":         self.api_key,
                "anthropic-version": "2023-06-01"
            }
        )

        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())

        text = data["content"][0]["text"].strip()

        # Strip markdown code fence if present
        if "```" in text:
            for part in text.split("```"):
                p = part.strip()
                if p.startswith("json"):
                    p = p[4:].strip()
                if p.startswith("["):
                    text = p
                    break

        try:
            vouchers = json.loads(text)
            return vouchers if isinstance(vouchers, list) else []
        except json.JSONDecodeError:
            raise ValueError(
                "Claude returned an invalid response. Please try again."
            )
