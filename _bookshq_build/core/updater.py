"""Desktop self-update check (notify + open download — no silent install).

Asks the licence server for the latest *released* version + download link for
this product, compares it to the installed release (SemVer), and reports whether
a newer version exists. The UI (Settings card + a startup check) decides what to
show. Network/parse errors return None so callers can stay quiet.
"""
from __future__ import annotations

import json
import urllib.request
from typing import Optional

from core.app_release import current_product, current_release
from core.license_manager import SERVER_URL   # already ends in /api/v1


def _ver_tuple(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in str(v or "").split("."):
        digits = "".join(c for c in part if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return _ver_tuple(latest) > _ver_tuple(current)


def check_for_update(timeout: float = 6.0) -> Optional[dict]:
    """Return a dict or None (on any error — caller stays silent).

    Dict keys:
      update  : bool   — a newer release is available
      current : str    — installed released version
      latest  : str    — latest released version on the server
      url     : str    — where to download it
      notes   : str    — optional release notes
    """
    product = current_product()
    current = current_release()
    base = SERVER_URL.rstrip("/")            # https://host/api/v1
    try:
        with urllib.request.urlopen(
            f"{base}/app-version?product={product}", timeout=timeout
        ) as resp:
            data = json.loads(resp.read())
    except Exception:
        return None
    latest = (data.get("latest") or "").strip()
    if not latest:
        return None
    return {
        "update":  is_newer(latest, current),
        "current": current,
        "latest":  latest,
        "url":     (data.get("url") or "").strip(),
        "notes":   (data.get("notes") or "").strip(),
    }
