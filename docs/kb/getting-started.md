# Getting started — install, create or open a company

## Install
Accounts HQ is a Windows desktop app. Download the installer (`Accounts HQ-Setup-x.x.x.exe`)
and run it. It installs locally — no internet is needed to use the app day to day.

## First launch — the company selector
When you open Accounts HQ, a **company selector** appears first.

**Open an existing company:** pick it from the dropdown (it lists every company you've
created) and click **Open**.

**Create a new company:**
1. Click to create a new company.
2. Fill in:
   - **Company Name** (required)
   - **GSTIN** (optional — if you enter it, the state code is filled in for you)
   - **State Code** (2-digit; defaults to 07/Delhi — set this correctly, it drives GST)
3. Click **Create & Open**. The app seeds a standard chart of accounts (Tally-style
   groups + ledgers, GST ledgers) and the current financial year.

**Create and bring over old books:** use **Create & Migrate from another system…** to
launch the migration wizard right after creating the company (see *Migrate from Tally /
Busy / Excel*).

## Where your data lives
Each company is a single file on your own PC:
`C:\Users\<you>\AppData\Local\Aiccounting\data\companies\<company>.db`

Your books never leave your machine unless you back them up or export. Because it's one
file per company, a backup is just a copy of that file (see *Backup & restore*).

## Financial year
A financial year (default **1 April – 31 March**) is created automatically. You can change
the FY start in **Settings → Financial year**.

## The main window
A sidebar on the left lists every screen (Post Voucher, Day Book, reports, reconciliation,
etc.). The screens you see depend on your plan — locked ones show an upgrade card. Click
the logo any time to return to the **Home** dashboard.
