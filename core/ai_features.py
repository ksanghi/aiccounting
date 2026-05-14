"""
AI feature → license-class table.

Each AI feature is `byok` or `ag_key`. This is operator config, defined
once per AccGenie version, the SAME for every customer, NOT end-user
editable. It can change between releases.

  byok   — the feature REQUIRES the customer's own Anthropic key. Without
           one the feature is locked.
  ag_key — the feature runs on AccGenie's key billed to the customer's
           credit wallet — UNLESS the customer has supplied their own key,
           in which case that key is used (a customer key covers everything).

The routing brain that consumes this lives in `core/ai_routing.py`
(`RoutingConfig.resolve`). This module only owns the table.

File location:
    Dev mode:  <repo>/config/ai_features.json
    Packaged:  <user_data_dir>/config/ai_features.json
The file is shipped with the app; `ensure_ai_features_file()` re-seeds it
if it's somehow missing (e.g. a packaged install where config/ wasn't
created). On dev the committed file is the source of truth.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.paths import config_dir


# The canonical table. Bump "version" when the mapping changes in a release.
_SEED: dict = {
    "_comment": (
        "AI feature -> license class. Defined per AccGenie version, same "
        "for all customers, NOT end-user editable. byok = requires the "
        "customer's own Anthropic key (locked without one). ag_key = "
        "AccGenie key billed to the customer wallet, unless the customer "
        "has supplied their own key."
    ),
    "version": "1.0",
    "features": {
        "document_recognition": "byok",
        "bank_statement_ai":     "ag_key",
        "ledger_statement_ai":   "ag_key",
        "sales_ai_fill":         "ag_key",
        "purchase_ai_fill":      "ag_key",
        "ledger_suggest":        "ag_key",
        "verbal_entry":          "ag_key",
    },
}

# Used when the file is missing AND a feature isn't in the seed either —
# the safe default is ag_key (wallet) so a new/unknown feature never gets
# silently locked.
_DEFAULT_CLASS = "ag_key"
_VALID_CLASSES = ("byok", "ag_key")


def ai_features_file_path() -> Path:
    return config_dir() / "ai_features.json"


def ensure_ai_features_file() -> Path:
    """Seed config/ai_features.json if missing. Never overwrites an
    existing file (the operator may have edited it for this version)."""
    p = ai_features_file_path()
    if not p.exists():
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(_SEED, f, indent=2, ensure_ascii=False)
    return p


def _load() -> dict:
    p = ai_features_file_path()
    if not p.exists():
        ensure_ai_features_file()
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("features"), dict):
            return data
    except Exception:
        pass
    return _SEED


def feature_class(feature_id: str) -> str:
    """Return 'byok' or 'ag_key' for a feature. Unknown features default
    to 'ag_key' so nothing gets silently locked."""
    cls = _load().get("features", {}).get(feature_id, _DEFAULT_CLASS)
    return cls if cls in _VALID_CLASSES else _DEFAULT_CLASS


def all_features() -> dict[str, str]:
    """The full {feature_id: class} map — for Settings display etc."""
    return dict(_load().get("features", {}))
