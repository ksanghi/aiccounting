# tradeHQ — Getting started

Setting up tradeHQ takes a minute. On first launch a short setup wizard walks
you through it; you can also do it any time from the **Accounts** page.

1. **Add the person** who owns the account (a family member). Every account
   belongs to a person — that's how tradeHQ groups the family view.
2. **Add a broker account.** Pick the broker, give it a name, and enter the
   login it needs to pull: your broker **Login/Client ID, password, and TOTP
   (authenticator) secret**. These are encrypted on your PC and never leave it.
3. **Pull.** Go to **Pull / Sync**, tick the account(s) and click *Pull
   selected* — tradeHQ logs in, fetches your holdings, trades and ledger, and
   the **Dashboard** fills in.

You can add several people and accounts, and pull many at once from Pull / Sync.

**Where do I find my TOTP secret?** It's the authenticator key your broker
shows when you set up two-factor login (the long code behind the QR, sometimes
called the "manual entry key"). tradeHQ uses it to generate the 6-digit code at
pull time, so logins are automatic.
