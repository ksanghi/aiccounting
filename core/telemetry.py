"""
Anonymous install heartbeat.

Posts {install_id, machine_id, app_version, plan, license_key, os_name} to
the license server on app startup. Fire-and-forget on a background thread —
never blocks UI, never raises.

install_id is a stable UUID generated on first launch and persisted to
user_data_dir/install_id.txt. machine_id is the same hash already used by
LicenseManager (hostname + arch).

No PII transmitted: install_id is opaque, machine_id is a one-way hash,
license_key is only sent if the user has activated a paid plan.
"""
from __future__ import annotations

import json
import platform
import sys
import threading
import urllib.request
import urllib.error
import uuid
from pathlib import Path

from core.paths import install_id_file
from core.license_manager import SERVER_URL, LicenseManager


HEARTBEAT_URL = f"{SERVER_URL}/install/heartbeat"
TIMEOUT_SECS  = 3


def _get_or_create_install_id() -> str:
    path: Path = install_id_file()
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8").strip()
            if existing:
                return existing
    except Exception:
        pass

    new_id = uuid.uuid4().hex
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(new_id, encoding="utf-8")
    except Exception:
        # If we can't persist, still return the value so this session reports.
        pass
    return new_id


def _os_name() -> str:
    if sys.platform.startswith("win"):
        return "windows"
    if sys.platform == "darwin":
        return "macos"
    return "linux"


def _post_heartbeat(payload: dict) -> None:
    try:
        data = json.dumps(payload).encode()
        req = urllib.request.Request(
            HEARTBEAT_URL,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=TIMEOUT_SECS).read()
    except (urllib.error.URLError, TimeoutError, OSError):
        # Server down, no internet, etc — silently skip. Telemetry is
        # best-effort and must never affect user experience.
        pass
    except Exception:
        pass


def send_install_heartbeat(license_mgr: LicenseManager | None = None,
                           app_version: str = "1.0.0") -> None:
    """Fire-and-forget. Returns immediately; the actual POST runs on a thread."""
    mgr = license_mgr or LicenseManager()
    payload = {
        "install_id":  _get_or_create_install_id(),
        "machine_id":  LicenseManager.get_machine_id(),
        "app_version": app_version,
        "plan":        mgr.plan,
        "license_key": mgr.license_key if mgr.license_key not in ("FREE-DEMO", "") else "",
        "os_name":     _os_name(),
    }
    t = threading.Thread(target=_post_heartbeat, args=(payload,), daemon=True)
    t.start()
