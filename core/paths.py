"""
Single source of truth for runtime data locations.

  • Dev mode (running from source):    data lives in <repo>/data/
  • Packaged (PyInstaller):
        Windows:  %APPDATA%/AccGenie/
        macOS:    ~/Library/Application Support/AccGenie/
        Linux:    ~/.local/share/AccGenie/

Detect packaged via `sys.frozen` (PyInstaller, cx_Freeze, Nuitka all set it).
Bundled read-only assets resolve via sys._MEIPASS (one-file PyInstaller) or
the executable's directory (one-folder).

Every module that needs a writable path should call helpers here instead of
constructing paths from __file__ — that's the only way the same code works
in dev and packaged builds.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "AccGenie"


def is_packaged() -> bool:
    """True when running inside a PyInstaller / Nuitka / cx_Freeze bundle."""
    return getattr(sys, "frozen", False)


def app_root_dir() -> Path:
    """
    Read-only app root for bundled assets (icons, themes, default templates).
    Don't write here — packaged installs in Program Files are read-only.
    """
    if is_packaged():
        if hasattr(sys, "_MEIPASS"):
            return Path(sys._MEIPASS)         # one-file extraction temp
        return Path(sys.executable).parent    # one-folder install root
    return Path(__file__).resolve().parent.parent


def user_data_dir() -> Path:
    """
    Per-user writable root. All app-specific data lives under here.
    Auto-creates if missing.
    """
    if is_packaged():
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA")
                        or os.environ.get("USERPROFILE", ""))
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support"
        else:
            base = Path(
                os.environ.get("XDG_DATA_HOME")
                or (Path.home() / ".local" / "share")
            )
        root = base / APP_NAME
    else:
        # Dev mode: keep current ./data behaviour so existing repos work.
        root = Path(__file__).resolve().parent.parent / "data"
    root.mkdir(parents=True, exist_ok=True)
    return root


def companies_dir() -> Path:
    p = user_data_dir() / "companies"
    p.mkdir(parents=True, exist_ok=True)
    return p


def license_file() -> Path:
    return user_data_dir() / "license.json"


def credits_file() -> Path:
    return user_data_dir() / "credits.json"


def install_id_file() -> Path:
    return user_data_dir() / "install_id.txt"


def config_dir() -> Path:
    """Per-user config (API keys, theme prefs, etc.)."""
    if is_packaged():
        p = user_data_dir() / "config"
    else:
        # Dev: stay in <repo>/config to match existing files.
        p = Path(__file__).resolve().parent.parent / "config"
    p.mkdir(parents=True, exist_ok=True)
    return p
