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
(`RoutingConfig.resolve`). This module only owns the lookup surface.

Source of truth: `config/ai_features.xlsx` — operator edits the .xlsx,
runs `build/bake_config.py`, which writes `core/_baked_config.py`.
Nothing here reads from disk at runtime; the values are compiled into
the binary.
"""
from __future__ import annotations

from core._baked_config import AI_FEATURES

_DEFAULT_CLASS = "ag_key"
_VALID_CLASSES = ("byok", "ag_key")


def feature_class(feature_id: str) -> str:
    """Return 'byok' or 'ag_key' for a feature. Unknown features default
    to 'ag_key' so nothing gets silently locked."""
    cls = AI_FEATURES.get(feature_id, _DEFAULT_CLASS)
    return cls if cls in _VALID_CLASSES else _DEFAULT_CLASS


def all_features() -> dict[str, str]:
    """The full {feature_id: class} map — for Settings display etc."""
    return dict(AI_FEATURES)
