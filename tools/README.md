# tools/

Local-only dev helpers — not bundled into the AccGenie / RWAGenie
installer.

## wa_notify.py — WhatsApp notifications via CallMeBot

Sends a WhatsApp message to your own number using the free
[CallMeBot](https://www.callmebot.com/blog/free-api-whatsapp-messages/)
gateway. Used by `build/build.bat` to ping you when a long build
finishes; you can also call it from any script.

### One-time setup

1. **Activate the bot.** From your WhatsApp, send the exact text
   `I allow callmebot to send me messages` to **+34 644 51 95 23**.
   Within ~2 minutes you'll get a reply containing your personal API
   key (a string like `1234567`).

2. **Set the env vars** (Windows, one-shot in this shell):

   ```cmd
   setx CALLMEBOT_PHONE   9198XXXXXXXX
   setx CALLMEBOT_API_KEY 1234567
   ```

   Phone format: international, digits only, no `+` or spaces. Close
   and reopen your terminal so the new vars are picked up.

3. **Smoke test:**

   ```cmd
   python tools\wa_notify.py "hello from AccGenie"
   ```

   The message should arrive on WhatsApp within seconds. If it doesn't,
   re-run step 1 — CallMeBot occasionally rotates keys.

### Behaviour

- **Env vars unset:** the script silently exits 0 — safe to call from
  scripts that don't know whether CallMeBot is configured yet.
- **HTTP / network error:** exit 2, message logged to stderr.
- **CallMeBot rejected:** exit 3, response body logged. Usually means
  the phone or API key is wrong — re-activate.

### Limits

CallMeBot's free WhatsApp tier is meant for **personal notifications
to your own number**. Rate-limited around 1 message/sec and ~200/day.
Not suitable for transactional emails to customers — for that, use the
license server's SMTP path (`license_server/services/email_service.py`)
or upgrade to Twilio / WATI / Gupshup.
