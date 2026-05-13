"""
User preferences — a tiny JSON store for app-wide toggles.

Location:
    Dev mode:     <repo>/config/user_prefs.json
    Packaged:     %APPDATA%/AccGenie/config/user_prefs.json  (Win)
                  ~/Library/Application Support/AccGenie/config/user_prefs.json  (mac)
                  ~/.local/share/AccGenie/config/user_prefs.json  (Linux)

Use the module-level singleton `prefs`:

    from core.user_prefs import prefs
    after_post = prefs.get("after_post_toast", True)
    prefs.set("backup_reminder_days", 14)

Reads are cached after first load; writes persist immediately. The store
is single-file JSON because nothing here needs transactional safety or
cross-process coordination — losing a setting on a crash is fine.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from core.paths import config_dir


PREFS_FILE_NAME = "user_prefs.json"


def _prefs_path() -> Path:
    return config_dir() / PREFS_FILE_NAME


class UserPrefs:
    def __init__(self) -> None:
        self._cache: dict[str, Any] = self._load()

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        p = _prefs_path()
        if not p.exists():
            return {}
        try:
            with open(p, encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save(self) -> None:
        p = _prefs_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(p, "w", encoding="utf-8") as f:
                json.dump(self._cache, f, indent=2, ensure_ascii=False)
        except Exception:
            # Settings are a UX nicety, not load-bearing — silently
            # tolerate disk-full / permission errors rather than crashing.
            pass

    # ── API ───────────────────────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        return self._cache.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._cache[key] = value
        self._save()

    def remove(self, key: str) -> None:
        if key in self._cache:
            del self._cache[key]
            self._save()

    def all(self) -> dict[str, Any]:
        return dict(self._cache)


# Module-level singleton. Cheap to construct; safe to import anywhere.
prefs = UserPrefs()
