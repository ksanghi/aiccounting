# tradeHQ — Troubleshooting

**A pull failed.** Common causes:
- **Login details wrong or changed.** Re-check the account's Login/Client ID,
  password and TOTP secret on the Accounts page. If you recently changed your
  broker password, update it here too.
- **No login saved.** An account with no saved login can't be pulled — it shows
  greyed-out on Pull / Sync. Add the login on the Accounts page first.
- **Broker changed their login page.** The auto-login replays the broker's own
  website, so a broker redesign can temporarily break it until tradeHQ is
  updated. Check for an app update under **About → Check for updates**.

**The dashboard figures look stale.** Do a fresh pull from Pull / Sync, then
open the Dashboard — it re-reads after every pull.

**The top wealth number doesn't change when I switch the period.** That's by
design: total wealth is an *as-of-now* figure (free cash + holdings value), so
it doesn't move with the period. The gain/return shown next to it *does* follow
the period.

**The "Profit by day/week/month" chart is empty.** That account hasn't pulled a
realized-P&L (Console) report yet — pull again, or it may have no closed trades
in the selected period.

Still stuck? Use the in-app **Feedback** page or write to info@ai-consultants.in.
