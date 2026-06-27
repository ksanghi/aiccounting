"""
Bank-feed orchestrator — links a provider connection to an AccGenie bank ledger
and pulls transactions into the reconciler. Provider-agnostic facade.

SimpleFIN is implemented first (free to us — the customer pays the Bridge).
Plaid / Teller slot in later behind the same three calls:
    begin_*(...)        -> (token/access, [accounts])     # for the link UI
    save_connection(...)                                  # persist the mapping
    refresh(...)        -> [{account, statement_id, lines}]  # pull + import

Imported transactions land as a FEED statement and flow through the existing
reconcile -> AI-categorize -> post pipeline, deduped by reference so repeated
refreshes never double-import.
"""
from __future__ import annotations

from core import simplefin_client as sf


# ── linking ──────────────────────────────────────────────────────────────────
def begin_simplefin(setup_token: str):
    """Claim a SimpleFIN setup token and return (access_url, [account summaries])
    so the UI can let the user map each account to a bank ledger. Not persisted."""
    access_url = sf.claim_setup_token(setup_token)
    data = sf.fetch_accounts(access_url)
    return access_url, sf.list_accounts(data)


def save_connection(db, company_id: int, bank_ledger_id: int, provider: str,
                    access_token: str, feed_account_id: str | None,
                    label: str = "") -> None:
    db.execute(
        "INSERT OR REPLACE INTO bank_feed_connections "
        "(company_id, bank_ledger_id, provider, access_token, feed_account_id, label) "
        "VALUES (?,?,?,?,?,?)",
        (company_id, bank_ledger_id, provider, access_token, feed_account_id, label),
    )
    db.commit()


def connections_for(db, company_id: int, bank_ledger_id: int | None = None) -> list[dict]:
    q = "SELECT * FROM bank_feed_connections WHERE company_id=?"
    args: list = [company_id]
    if bank_ledger_id is not None:
        q += " AND bank_ledger_id=?"
        args.append(bank_ledger_id)
    q += " ORDER BY id"
    return [dict(r) for r in db.execute(q, args).fetchall()]


def remove_connection(db, company_id: int, connection_id: int) -> None:
    db.execute("DELETE FROM bank_feed_connections WHERE id=? AND company_id=?",
               (connection_id, company_id))
    db.commit()


# ── pulling ──────────────────────────────────────────────────────────────────
def refresh(reconciler, db, company_id: int, connection: dict,
            start_date: str | None = None, end_date: str | None = None,
            user_id: int | None = None) -> list[dict]:
    """Pull + import one connection. Returns one result row per account touched:
    {account, statement_id, lines}. statement_id==0 means nothing new (deduped)."""
    provider = connection.get("provider")
    if provider != "simplefin":
        raise ValueError(f"Refresh not yet implemented for provider '{provider}'.")

    data = sf.fetch_accounts(connection["access_token"], start_date, end_date)
    target = connection.get("feed_account_id")
    out: list[dict] = []
    for acct in data.get("accounts", []) or []:
        if target and str(acct.get("id")) != str(target):
            continue
        pr = sf.account_to_parse_result(acct)
        if not pr.success:
            out.append({"account": acct.get("name") or "", "statement_id": 0, "lines": 0})
            continue
        label = f"SimpleFIN · {pr.bank_name or ''} · {acct.get('name', '')}".strip()
        stmt_id = reconciler.import_feed_account(
            bank_ledger_id=connection["bank_ledger_id"],
            parse_result=pr,
            source_label=label,
            user_id=user_id,
        )
        # Auto-match the freshly imported statement (same as a dropped file),
        # so it lands matched/ready-to-review, not just sitting there.
        result = reconciler.auto_match(stmt_id) if stmt_id else None
        out.append({"account": acct.get("name") or "", "statement_id": stmt_id,
                    "lines": len(pr.lines), "result": result})

    db.execute("UPDATE bank_feed_connections SET last_pulled_at=datetime('now') WHERE id=?",
               (connection["id"],))
    db.commit()
    return out
