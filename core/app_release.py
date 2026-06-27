"""Single source of the app's display name and version.

Bump ``APP_VERSION`` in lockstep with ``build/build.bat``'s ``VERSION`` on
every build, so the running app shows the exact build the user installed
(the window title and the sidebar version label both read from here).
"""

APP_NAME = "Accounts HQ"
APP_VERSION = "1.0.38"
