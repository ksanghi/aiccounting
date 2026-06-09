# AI Document Inbox — turn bills into draft vouchers

*(AI features are on the higher plans and use your own Anthropic AI key — "BYOK". Add the
key in Settings → AI key first.)*

There are two AI screens:
- **AI Doc Reader** — quick, one-off: drop a single invoice and it fills a Sales/Purchase
  form for you to review and post.
- **Document Inbox** — a queue/workflow for many documents (below).

## Document Inbox — the flow
1. **Get documents in**, either way:
   - **Watch a folder** — set a folder in Settings; files dropped there appear in the queue.
   - **Pull from email** — set up an email inbox; the app polls it and pulls attachments
     (invoices, bills, statements).
2. **The queue** lists each document with a status: *Pending → Classified → Approved →
   Posted* (or *Rejected / Error*). Click a row to open it in the **3-pane review**: the
   document preview, its details, and the draft voucher — side by side.
3. **Process** — the AI reads the document once: it **classifies** it (purchase invoice,
   sales invoice, debit/credit note, bank statement, other) **and** drafts a voucher. If the
   classification is wrong, change it from the dropdown.
4. **Review & approve** — check the draft against the preview. Edit ledgers, amounts and
   narration as needed. Create a new ledger inline if the party isn't in your books yet.
5. **Post** — posts it to the Day Book and marks the document *Posted*. Nothing is posted
   silently — you approve every voucher.
6. **Process All** — runs extraction on all pending documents in the background; you still
   review and post each.

## Good to know
- The AI drafts the common 2-line voucher types (Payment, Receipt, Journal, Contra). Sales/
  Purchase with line items and notes are still entered through the normal form.
- Vouchers created from AI carry a source tag and a confidence score, so you can tell them
  apart later.
- If the inbox shows **Error**, the most common cause is the **AI key** — expired, wrong, or
  out of credit. Re-check it in Settings.
