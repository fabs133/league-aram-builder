"""
ARAM Oracle — pywebview click-through transparent overlay window.

Uses pywebview with the system WebView2 runtime (pre-installed on Win10/11)
to render the companion web UI as a transparent, always-on-top, click-through
window. Adds only ~2MB to the bundle vs ~250MB for PyQt6-WebEngine.

Win32 flags:
  WS_EX_TRANSPARENT — mouse events pass through to the game
  WS_EX_LAYERED     — required for per-pixel transparency

Features:
  - Alt+O hotkey toggles click-through on/off
  - System tray icon with context menu
  - Window position saved/restored across sessions
  - Auto-hide when no game is detected

Usage:
  python -m backend.overlay
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import json
import sys
import logging
import threading
from pathlib import Path

logger = logging.getLogger("aram-oracle.overlay")

try:
    import webview

    WEBVIEW_AVAILABLE = True
except ImportError:
    WEBVIEW_AVAILABLE = False

# Win32 constants
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_LAYERED = 0x00080000
HWND_TOPMOST = -1
SWP_NOMOVE = 0x0002
SWP_NOSIZE = 0x0001
SWP_NOACTIVATE = 0x0010

# Overlay dimensions (defaults)
OVERLAY_WIDTH = 320
OVERLAY_MARGIN_RIGHT = 10
OVERLAY_MARGIN_TOP = 60

WINDOW_TITLE = "ARAM Oracle Overlay"
CONFIG_DIR = Path.home() / ".aram-oracle"
CONFIG_FILE = CONFIG_DIR / "overlay.json"

# Global state
_window: webview.Window | None = None
_click_through = True
_visible = True


# ---------------------------------------------------------------------------
# Config persistence
# ---------------------------------------------------------------------------

def _load_config() -> dict:
    """Load saved overlay config (position, opacity)."""
    try:
        if CONFIG_FILE.exists():
            return json.loads(CONFIG_FILE.read_text())
    except Exception as e:
        logger.warning("Failed to load overlay config: %s", e)
    return {}


def _save_config(cfg: dict) -> None:
    """Persist overlay config to disk."""
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(cfg, indent=2))
    except Exception as e:
        logger.warning("Failed to save overlay config: %s", e)


# ---------------------------------------------------------------------------
# Win32 helpers
# ---------------------------------------------------------------------------

def _get_screen_size() -> tuple[int, int]:
    """Return (width, height) of the primary monitor."""
    user32 = ctypes.windll.user32
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def _find_hwnd(title: str) -> int | None:
    """Find the HWND of a window by its title."""
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, title)
    return hwnd if hwnd else None


def _force_topmost(hwnd: int) -> None:
    """Force overlay above all other topmost windows (including League).

    Both our overlay and League's RiotWindowClass are TOPMOST, so plain
    SetWindowPos(HWND_TOPMOST) doesn't change relative order.  Instead
    we push League's window *below* ours — telling Windows to insert it
    after our HWND in z-order.
    """
    try:
        user32 = ctypes.windll.user32
        flags = SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE

        # Find League's game window
        league = user32.FindWindowW("RiotWindowClass", None)
        if league:
            # Place League AFTER (below) our overlay in z-order
            user32.SetWindowPos(league, hwnd, 0, 0, 0, 0, flags)
        else:
            # No League window — just ensure we're topmost
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags)
    except Exception as e:
        logger.error("Failed to force topmost: %s", e)


def _start_topmost_watchdog(hwnd: int) -> None:
    """Re-assert overlay above League every 500ms."""
    import time

    def _loop():
        user32 = ctypes.windll.user32
        GW_HWNDPREV = 3
        while _window is not None:
            # Check if something is above us in z-order
            above = user32.GetWindow(hwnd, GW_HWNDPREV)
            if above:
                _force_topmost(hwnd)
            time.sleep(0.5)

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    logger.info("Topmost watchdog started (HWND=%d)", hwnd)


def _set_click_through(hwnd: int) -> None:
    """Set Win32 extended styles so mouse events pass through."""
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style | WS_EX_TRANSPARENT | WS_EX_LAYERED
        )
        logger.info("Click-through enabled (HWND=%d)", hwnd)
    except Exception as e:
        logger.error("Failed to set click-through: %s", e)


def _clear_click_through(hwnd: int) -> None:
    """Remove WS_EX_TRANSPARENT so the overlay accepts mouse input."""
    try:
        user32 = ctypes.windll.user32
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        user32.SetWindowLongW(
            hwnd, GWL_EXSTYLE, style & ~WS_EX_TRANSPARENT
        )
        logger.info("Click-through disabled (HWND=%d)", hwnd)
    except Exception as e:
        logger.error("Failed to clear click-through: %s", e)


def _set_opacity(hwnd: int, alpha: int) -> None:
    """Set window opacity (0-255). Requires WS_EX_LAYERED."""
    LWA_ALPHA = 0x00000002
    try:
        user32 = ctypes.windll.user32
        # Ensure layered flag is set
        style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        if not (style & WS_EX_LAYERED):
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
        user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
        logger.info("Opacity set to %d/255", alpha)
    except Exception as e:
        logger.error("Failed to set opacity: %s", e)


# ---------------------------------------------------------------------------
# Click-through toggle
# ---------------------------------------------------------------------------

def toggle_click_through() -> bool:
    """Toggle click-through on/off. Returns new click-through state."""
    global _click_through
    if _window is None:
        return _click_through

    hwnd = _find_hwnd(WINDOW_TITLE)
    if not hwnd:
        logger.warning("Could not find overlay HWND for toggle")
        return _click_through

    _click_through = not _click_through
    if _click_through:
        _set_click_through(hwnd)
        _window.evaluate_js(
            "document.body.classList.remove('interactive-mode');"
        )
    else:
        _clear_click_through(hwnd)
        _window.evaluate_js(
            "document.body.classList.add('interactive-mode');"
        )

    logger.info("Click-through toggled: %s", "ON" if _click_through else "OFF")
    return _click_through


# ---------------------------------------------------------------------------
# Show / hide
# ---------------------------------------------------------------------------

def show_overlay() -> None:
    """Show the overlay window."""
    global _visible
    if _window is None:
        return
    _window.show()
    _visible = True
    logger.info("Overlay shown")


def hide_overlay() -> None:
    """Hide the overlay window."""
    global _visible
    if _window is None:
        return
    _window.hide()
    _visible = False
    logger.info("Overlay hidden")


def toggle_visibility() -> None:
    """Toggle overlay visibility."""
    if _visible:
        hide_overlay()
    else:
        show_overlay()


# ---------------------------------------------------------------------------
# Tray icon (pystray — optional, degrades gracefully)
# ---------------------------------------------------------------------------

def _start_tray_icon():
    """Create a system tray icon with a context menu. Requires pystray+Pillow."""
    try:
        import pystray
        from PIL import Image, ImageDraw
    except ImportError:
        logger.info("pystray/Pillow not installed — skipping tray icon")
        return

    # Draw a simple 16x16 green circle icon
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(0, 200, 83, 255))

    def on_toggle_ct(icon, item):
        toggle_click_through()

    def on_toggle_vis(icon, item):
        toggle_visibility()

    def on_quit(icon, item):
        icon.stop()
        if _window:
            _window.destroy()

    menu = pystray.Menu(
        pystray.MenuItem("Show/Hide Overlay", on_toggle_vis),
        pystray.MenuItem("Toggle Click-Through (Alt+O)", on_toggle_ct),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("aram-oracle", img, "ARAM Oracle", menu)

    def _run():
        icon.run()

    t = threading.Thread(target=_run, daemon=True)
    t.start()
    logger.info("Tray icon started")


# ---------------------------------------------------------------------------
# Hotkey listener
# ---------------------------------------------------------------------------

def _start_hotkey_listener():
    """Register Alt+O global hotkey to toggle click-through."""
    MOD_ALT = 0x0001
    VK_O = 0x4F
    HOTKEY_ID = 1

    def _listen():
        user32 = ctypes.windll.user32
        if not user32.RegisterHotKey(None, HOTKEY_ID, MOD_ALT, VK_O):
            logger.warning("Failed to register Alt+O hotkey")
            return
        logger.info("Hotkey Alt+O registered for click-through toggle")

        msg = ctypes.wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            if msg.message == 0x0312:  # WM_HOTKEY
                toggle_click_through()

        user32.UnregisterHotKey(None, HOTKEY_ID)

    t = threading.Thread(target=_listen, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Window lifecycle
# ---------------------------------------------------------------------------

def _on_shown():
    """Called once the webview window is visible — apply Win32 flags."""
    if sys.platform != "win32":
        logger.warning("Click-through only works on Windows")
        return

    import time
    time.sleep(0.3)

    hwnd = _find_hwnd(WINDOW_TITLE)
    if hwnd:
        _set_click_through(hwnd)
        _force_topmost(hwnd)
        _start_topmost_watchdog(hwnd)
        # Apply saved opacity
        cfg = _load_config()
        alpha = cfg.get("opacity", 255)
        if alpha < 255:
            _set_opacity(hwnd, alpha)
    else:
        logger.warning("Could not find overlay HWND — click-through not set")

    _start_hotkey_listener()
    _start_tray_icon()


def _on_closing():
    """Save window position before the window closes."""
    if _window is None:
        return
    cfg = _load_config()
    cfg["x"] = _window.x
    cfg["y"] = _window.y
    cfg["width"] = _window.width
    cfg["height"] = _window.height
    _save_config(cfg)
    logger.info("Window position saved")


def is_available() -> bool:
    """Check if pywebview is installed."""
    return WEBVIEW_AVAILABLE


def run_overlay(url: str = "http://localhost:8765/overlay?mode=overlay"):
    """Launch the pywebview overlay window (blocking — runs the GUI loop)."""
    global _window

    if not WEBVIEW_AVAILABLE:
        print("ERROR: pywebview is required for the overlay.")
        print("Install with: pip install pywebview")
        sys.exit(1)

    sw, sh = _get_screen_size()

    # Use saved position or defaults
    cfg = _load_config()
    x = cfg.get("x", sw - OVERLAY_WIDTH - OVERLAY_MARGIN_RIGHT)
    y = cfg.get("y", OVERLAY_MARGIN_TOP)
    w = cfg.get("width", OVERLAY_WIDTH)
    h = cfg.get("height", sh - OVERLAY_MARGIN_TOP * 2)

    _window = webview.create_window(
        WINDOW_TITLE,
        url=url,
        width=w,
        height=h,
        x=x,
        y=y,
        frameless=True,
        on_top=True,
        transparent=True,
        resizable=False,
    )

    _window.events.closing += _on_closing

    # _on_shown runs after the window is created and visible
    webview.start(func=_on_shown, debug=False)
