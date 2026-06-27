# -*- coding: utf-8 -*-
"""Books HQ — on-premise desktop wrapper.

Starts the FastAPI app (webapp.py, reusing core) on a local port, then opens
it in a native desktop window via pywebview. Same UI as the web build, but
runs like a desktop app for side-by-side comparison with the Qt desktop (AHQ).

    python desktop_wrapper.py
"""
import os
import sys
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import uvicorn          # noqa: E402
import webview          # noqa: E402
from webapp import app  # noqa: E402

PORT = 8801


def _serve():
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")


def main():
    threading.Thread(target=_serve, daemon=True).start()
    time.sleep(1.3)  # let uvicorn bind the port before the window loads
    webview.create_window(
        "Books HQ",
        f"http://127.0.0.1:{PORT}/",
        width=1420,
        height=920,
        min_size=(1100, 700),
    )
    webview.start()


if __name__ == "__main__":
    main()
