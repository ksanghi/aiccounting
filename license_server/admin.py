"""
Admin CLI for the license server. Talks to the DB directly.

Usage:
  python -m license_server.admin mint --plan PRO --email x@y.com --expires 2027-05-10
  python -m license_server.admin list [--plan PRO] [--revoked]
  python -m license_server.admin show ACCG-XXXX-XXXX-XXXX
  python -m license_server.admin revoke ACCG-XXXX-XXXX-XXXX
  python -m license_server.admin extend ACCG-XXXX-XXXX-XXXX --to 2028-05-10
  python -m license_server.admin unbind ACCG-XXXX-XXXX-XXXX [--machine MID]
"""
import argparse
import sys
from datetime import date

from sqlalchemy import select, func, delete

from license_server.db import SessionLocal, init_db
from license_server.keys import generate_key
from license_server.models import License, MachineBinding, ValidationLog
from license_server.plans import PLANS, PLAN_LIMITS, PLAN_USER_LIMITS


def _parse_date(s: str) -> date:
    try:
        return date.fromisoformat(s)
    except ValueError:
        sys.exit(f"Bad date: {s} (expected YYYY-MM-DD)")


def cmd_mint(args):
    from license_server.plans import VALID_PRODUCTS
    from license_server.services.license_mint import (
        mint_license as _mint, MintError,
    )

    if args.plan not in PLANS:
        sys.exit(f"Unknown plan: {args.plan}")
    if args.product not in VALID_PRODUCTS:
        sys.exit(f"Unknown product: {args.product} "
                 f"(must be one of {VALID_PRODUCTS})")

    expires = _parse_date(args.expires)
    if expires < date.today():
        sys.exit("Expiry is in the past")

    if not args.email:
        sys.exit("--email is required so the customer can be contacted")

    with SessionLocal() as db:
        try:
            lic = _mint(
                db,
                product       = args.product,
                plan          = args.plan,
                customer_email= args.email,
                company_name  = args.company or "",
                expires_at    = expires,
                txn_limit     = args.txn_limit,
                user_limit    = args.user_limit,
                notes         = args.notes or "",
            )
        except MintError as e:
            sys.exit(str(e))
        db.commit()

        print(f"\n  License key:  {lic.license_key}")
        print(f"  Product:      {lic.product}")
        print(f"  Plan:         {lic.plan}")
        print(f"  Email:        {lic.customer_email or '-'}")
        print(f"  Company:      {lic.company_name or '-'}")
        print(f"  Expires:      {lic.expires_at.isoformat()}")
        print(f"  Txn limit:    {lic.txn_limit:,}")
        print(f"  User limit:   {lic.user_limit}")
        print()


def cmd_list(args):
    with SessionLocal() as db:
        stmt = select(License).order_by(License.created_at.desc())
        if args.plan:
            stmt = stmt.where(License.plan == args.plan)
        if args.revoked:
            stmt = stmt.where(License.revoked.is_(True))
        rows = db.scalars(stmt).all()

        if not rows:
            print("(no keys)")
            return

        print(f"{'KEY':25}  {'PLAN':9}  {'EXPIRES':12}  "
              f"{'STATUS':8}  {'MACH':5}  EMAIL")
        for lic in rows:
            mc = db.scalar(
                select(func.count()).select_from(MachineBinding)
                .where(MachineBinding.license_id == lic.id)
            ) or 0
            status = "REVOKED" if lic.revoked else (
                "EXPIRED" if lic.expires_at < date.today() else "active"
            )
            print(f"{lic.license_key:25}  {lic.plan:9}  "
                  f"{lic.expires_at.isoformat():12}  "
                  f"{status:8}  {mc:5}  {lic.customer_email}")


def cmd_show(args):
    key = args.key.upper()
    with SessionLocal() as db:
        lic = db.scalar(select(License).where(License.license_key == key))
        if not lic:
            sys.exit("Not found")

        print(f"\n  Key:        {lic.license_key}")
        print(f"  Plan:       {lic.plan}")
        print(f"  Email:      {lic.customer_email or '-'}")
        print(f"  Company:    {lic.company_name or '-'}")
        print(f"  Expires:    {lic.expires_at.isoformat()}")
        print(f"  Txn limit:  {lic.txn_limit:,}")
        print(f"  User limit: {lic.user_limit}")
        print(f"  Revoked:    {lic.revoked}")
        print(f"  Created:    {lic.created_at.isoformat(' ', 'seconds')}")
        print(f"  Notes:      {lic.notes or '-'}")

        machines = db.scalars(
            select(MachineBinding).where(MachineBinding.license_id == lic.id)
        ).all()
        print(f"\n  Bound machines ({len(machines)}):")
        for m in machines:
            print(f"    {m.machine_id}  first={m.first_seen_at:%Y-%m-%d}  "
                  f"last={m.last_seen_at:%Y-%m-%d}")

        recent = db.scalars(
            select(ValidationLog)
            .where(ValidationLog.license_id == lic.id)
            .order_by(ValidationLog.created_at.desc())
            .limit(10)
        ).all()
        print(f"\n  Recent validations ({len(recent)}):")
        for v in recent:
            ok = "OK " if v.success else "FAIL"
            print(f"    {v.created_at:%Y-%m-%d %H:%M}  {ok}  "
                  f"{v.machine_id[:12]}  {v.error or ''}")
        print()


def cmd_revoke(args):
    key = args.key.upper()
    with SessionLocal() as db:
        lic = db.scalar(select(License).where(License.license_key == key))
        if not lic:
            sys.exit("Not found")
        lic.revoked = True
        db.commit()
        print(f"Revoked {key}")


def cmd_extend(args):
    key = args.key.upper()
    new = _parse_date(args.to)
    if new < date.today():
        sys.exit("New expiry is in the past")
    with SessionLocal() as db:
        lic = db.scalar(select(License).where(License.license_key == key))
        if not lic:
            sys.exit("Not found")
        old = lic.expires_at
        lic.expires_at = new
        db.commit()
        print(f"Extended {key}: {old.isoformat()} -> {new.isoformat()}")


def cmd_unbind(args):
    key = args.key.upper()
    with SessionLocal() as db:
        lic = db.scalar(select(License).where(License.license_key == key))
        if not lic:
            sys.exit("Not found")
        stmt = delete(MachineBinding).where(MachineBinding.license_id == lic.id)
        if args.machine:
            stmt = stmt.where(MachineBinding.machine_id == args.machine)
        result = db.execute(stmt)
        db.commit()
        print(f"Unbound {result.rowcount} machine(s) from {key}")


def main(argv=None):
    init_db()

    parser = argparse.ArgumentParser(prog="license_server.admin")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_mint = sub.add_parser("mint", help="Mint a new license key")
    p_mint.add_argument("--product", default="accgenie",
                         choices=["accgenie", "rwagenie"],
                         help="Which product is the licence for "
                              "(default: accgenie).")
    p_mint.add_argument("--plan", required=True, choices=PLANS)
    p_mint.add_argument("--email", default="",
                         help="Customer email — required for mint.")
    p_mint.add_argument("--company", default="")
    p_mint.add_argument("--expires", required=True, help="YYYY-MM-DD")
    p_mint.add_argument("--notes", default="")
    p_mint.add_argument("--txn-limit", type=int, dest="txn_limit", default=None)
    p_mint.add_argument("--user-limit", type=int, dest="user_limit", default=None)
    p_mint.set_defaults(func=cmd_mint)

    p_list = sub.add_parser("list", help="List keys")
    p_list.add_argument("--plan", choices=PLANS, default=None)
    p_list.add_argument("--revoked", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show key details")
    p_show.add_argument("key")
    p_show.set_defaults(func=cmd_show)

    p_rev = sub.add_parser("revoke", help="Revoke a key")
    p_rev.add_argument("key")
    p_rev.set_defaults(func=cmd_revoke)

    p_ext = sub.add_parser("extend", help="Extend key expiry")
    p_ext.add_argument("key")
    p_ext.add_argument("--to", required=True, help="YYYY-MM-DD")
    p_ext.set_defaults(func=cmd_extend)

    p_unb = sub.add_parser("unbind", help="Remove machine bindings")
    p_unb.add_argument("key")
    p_unb.add_argument("--machine", default=None,
                       help="Specific machine_id (default: all)")
    p_unb.set_defaults(func=cmd_unbind)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
