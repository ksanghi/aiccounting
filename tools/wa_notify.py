"""
Send a WhatsApp message via CallMeBot.

Usage:
    python tools/wa_notify.py "your message"
    python tools/wa_notify.py "line 1" "line 2" "line 3"        # joined with newlines

Reads two env vars:
    CALLMEBOT_API_KEY   — assigned to you after you activate the bot
    CALLMEBOT_PHONE     — your WhatsApp number in international format,
                          digits only, no + or spaces (e.g. 9198XXXXXXXX)

Silent no-op (exit code 0) when env vars aren't set, so callers can fire
it unconditionally without breaking when it's not configured. Exit code
2 = HTTP/network error. Exit code 3 = CallMeBot rejected the request
(typically: wrong phone or stale API key — re-activate).

CallMeBot's free WhatsApp API is rate-limited (~1 message/sec, ~200/day)
and is meant for *personal* notifications to your own number. Don't use
it for transactional emails to customers.
"""
from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request

API_URL = "https://api.callmebot.com/whatsapp.php"


def notify(message: str,
           phone: str | None = None,
           api_key: str | None = None) -> int:
    phone   = (phone   or os.environ.get("CALLMEBOT_PHONE")   or "").strip()
    api_key = (api_key or os.environ.get("CALLMEBOT_API_KEY") or "").strip()
    if not phone or not api_key:
        # Silent — caller may be firing this best-effort from a script
        # that doesn't know whether the user has set up CallMeBot yet.
        print("wa_notify: CALLMEBOT_PHONE / CALLMEBOT_API_KEY not set; skipping.",
              file=sys.stderr)
        return 0

    if not message.strip():
        print("wa_notify: empty message; nothing to send.", file=sys.stderr)
        return 0

    # Sanitise phone: strip + and whitespace, keep only digits.
    phone = "".join(c for c in phone if c.isdigit())

    url = (
        f"{API_URL}?phone={urllib.parse.quote(phone)}"
        f"&text={urllib.parse.quote(message)}"
        f"&apikey={urllib.parse.quote(api_key)}"
    )

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except Exception as e:
        print(f"wa_notify: HTTP error: {e}", file=sys.stderr)
        return 2

    # CallMeBot returns 200 OK with an HTML page; check for success markers.
    body_lower = body.lower()
    if status == 200 and ("message queued" in body_lower
                          or "sent" in body_lower
                          or "successfully" in body_lower):
        return 0
    # Rejected — surface the response so the user can see why.
    snippet = body.strip().replace("\n", " ")[:200]
    print(f"wa_notify: CallMeBot rejected the request "
          f"(HTTP {status}): {snippet}", file=sys.stderr)
    return 3


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: python tools/wa_notify.py 'message' ['line2' ...]",
              file=sys.stderr)
        return 1
    message = "\n".join(sys.argv[1:])
    return notify(message)


if __name__ == "__main__":
    sys.exit(main())
