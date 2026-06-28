"""Public RELEASE version (clean SemVer) per product — the source of truth for
self-update. This is the *released* version shown to users and compared by the
updater, NOT the internal build number in build/build.bat (which bumps every
compile). Bump these only on a blessed release.

Product is identified by the APP_LICENSE_PRODUCT env var baked at build time
(same value the licence check uses).
"""
from __future__ import annotations

import os

# Current released versions. Update on each blessed release (e.g. 1.0 -> 1.0.1
# for a fix, 1.0 -> 1.1 for features).
RELEASE_VERSIONS = {
    "accgenie": "1.2",   # Accounts HQ
    "rwagenie": "1.2",   # RWA HQ
}

# Internal build number — bump in lockstep with build/build.bat's VERSION on
# every compile. Shown in the window title + sidebar so the running app can be
# told apart from any other build the user has installed.
BUILD_VERSION = "1.0.39"

DEFAULT_PRODUCT = "accgenie"


def current_product() -> str:
    return (os.environ.get("APP_LICENSE_PRODUCT", "") or DEFAULT_PRODUCT).strip().lower()


def current_release() -> str:
    """The installed app's released version string (e.g. '1.0')."""
    return RELEASE_VERSIONS.get(current_product(), "1.0")
