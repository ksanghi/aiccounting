# AI Documents Inbox — turn bills, invoices and statements into entries

*(AI document reading is on the higher plans. It runs on either your Accounts HQ
wallet credits or your own Anthropic AI key — whichever you chose in Settings → AI.
Bank and ledger statements in a structured file are read locally, with no AI and no cost.)*

The **AI Documents Inbox** is one screen that collects your documents and turns them
into draft vouchers — or feeds statements into reconciliation. It replaces the older
separate "AI Doc Reader" and "Document Inbox".

## Getting documents in
- **Drop or add files** — drag a PDF, photo or scan onto the inbox, or use *Add Files*.
- **Scan a folder** — point the inbox at a folder; anything dropped there appears in the queue.
- **Connect email** — the app pulls invoices, bills and statements from a mailbox you set up.

## Processing a document
1. **Pick the document** on the left — its preview shows in the middle.
2. **Choose the type** (optional). The dropdown defaults to **"Auto — let AI decide"**. If you
   already know it (e.g. *Purchase Invoice*), pick it and the AI skips the guess step. Pick
   **Bank statement** or **Ledger statement** and it is read **locally, with no AI**.
3. **Process with AI** processes that one document now (it jumps the queue); **Process All**
   runs the whole inbox. The AI reads the document, drafts the voucher(s) and shows a
   **confidence score**.
4. **Review & approve** — check the draft against the preview, fix any field, add a ledger
   inline if the party is new, then **Approve & Post**. Nothing posts silently.
5. **Auto-post** (optional, off by default) — tick it and the confident, complete documents
   post on their own without review. The recommended way is still AI-assisted review.

## Bank & ledger statements
A bank or ledger statement isn't a voucher — it belongs in **Reconciliation**. Pick the
*Bank statement* or *Ledger statement* type and process it: it is read locally (CSV / Excel /
OFX), tells you how many transactions it found, and gives a **Send to Reconciliation** button
that opens the right reconciliation screen with the file ready to import. Importing dedups by
file, so it never disturbs a reconciliation already in progress.

## Good to know
- Documents created from AI carry a source tag and a confidence score, so you can tell them apart later.
- A photo or scanned PDF is read by AI (an image has no text to read locally). A clean CSV / Excel /
  OFX statement is read locally with no AI cost.
- If the inbox shows **Error** on an AI document, the usual cause is billing — your wallet is out of
  credit, or your own AI key is expired/wrong. The message says which; fix it in Settings → AI.
