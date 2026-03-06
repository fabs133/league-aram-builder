"""
Launch ARAM Oracle with the transparent overlay.

Starts the FastAPI server in a background thread, then opens
the overlay window using the best available backend:

  Priority: pywebview > PyQt6 > browser fallback

Usage:
    python -m backend.overlay
"""

import sys
import threading
import time
import webbrowser
import logging


def _set_dpi_awareness():
    """Enable per-monitor DPI awareness so screen captures get real pixels."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


_set_dpi_awareness()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("aram-oracle.overlay")

OVERLAY_URL = "http://localhost:8765/overlay?mode=overlay"


def _start_server():
    """Run the FastAPI server in a background thread."""
    import uvicorn
    from backend.api.server import app

    uvicorn.run(app, host="0.0.0.0", port=8765, log_level="warning")


def _launch_overlay():
    """Try overlay backends in priority order: pywebview > PyQt6 > browser."""
    from backend.overlay.webview_window import is_available as webview_ok

    if webview_ok():
        logger.info("Using pywebview overlay")
        from backend.overlay.webview_window import run_overlay
        run_overlay(OVERLAY_URL)
        return

    from backend.overlay.window import is_available as pyqt_ok

    if pyqt_ok():
        logger.info("Using PyQt6 overlay")
        from backend.overlay.window import run_overlay
        run_overlay(OVERLAY_URL)
        return

    logger.warning("No overlay backend available — opening in browser")
    webbrowser.open(OVERLAY_URL)


def _wait_for_server(timeout: float = 15.0) -> bool:
    """Poll the health endpoint until the server is ready."""
    import requests as req
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            r = req.get("http://localhost:8765/health", timeout=0.5)
            if r.status_code == 200:
                logger.info("Server is ready")
                return True
        except req.ConnectionError:
            pass
        time.sleep(0.2)
    logger.warning("Server did not become ready within %.0fs", timeout)
    return False


def main():
    logger.info("Starting ARAM Oracle with overlay...")

    # Start the web server in a daemon thread
    server_thread = threading.Thread(target=_start_server, daemon=True)
    server_thread.start()
    logger.info("Server starting on http://localhost:8765")

    # Wait for the server to be ready instead of a fixed sleep
    _wait_for_server()

    # Launch the overlay (blocks until window is closed)
    _launch_overlay()


if __name__ == "__main__":
    main()
