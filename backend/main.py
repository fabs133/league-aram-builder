import argparse
import sys
import threading
import webbrowser
import uvicorn
from backend.storage.db import init_db
from backend.static_data.updater import check_and_update
from backend.static_data.loader import StaticData
from backend.config import config
from backend.api.server import app


def _set_dpi_awareness():
    """Enable per-monitor DPI awareness so screen captures get real pixels."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
    except (AttributeError, OSError):
        try:
            import ctypes
            ctypes.windll.user32.SetProcessDPIAware()
        except (AttributeError, OSError):
            pass


def _open_browser(port: int, delay: float = 1.5):
    """Open the overlay in the default browser after a short delay."""
    import time
    time.sleep(delay)
    url = f"http://localhost:{port}/overlay?mode=overlay"
    print(f"Opening {url} in browser...")
    webbrowser.open(url)


def main():
    _set_dpi_awareness()

    parser = argparse.ArgumentParser(description="ARAM Oracle")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--update", action="store_true", help="Force static data refresh")
    parser.add_argument("--community-sync", action="store_true", help="Enable community data submission")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser")
    parser.add_argument("--overlay", action="store_true", help="Start with transparent overlay window")
    args = parser.parse_args()

    config.load()
    init_db()

    if args.update:
        sd = StaticData()
        check_and_update(sd)
        print("Static data refreshed.")
        return

    if args.overlay:
        # Server + overlay in one process (same as python -m backend.overlay)
        from backend.overlay.__main__ import main as overlay_main
        overlay_main()
        return

    if not args.no_browser:
        threading.Thread(target=_open_browser, args=(args.port,), daemon=True).start()

    # Pass the app object directly instead of a dotted string.
    # uvicorn can't resolve import strings in PyInstaller frozen bundles.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=args.port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
