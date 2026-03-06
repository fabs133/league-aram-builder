"""Inspect all overlay-like windows to learn how Porofessor stays on top.

Usage:
    1. Start League + Porofessor
    2. Tab into League so Porofessor is overlaying the game
    3. Run:  python scripts/inspect_overlays.py
    (waits 10 seconds for you to tab back into League)
"""

import ctypes
import ctypes.wintypes
import time
import sys

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi

GWL_STYLE = -16
GWL_EXSTYLE = -20

# Extended style flags we care about
EX_FLAGS = {
    0x00000008: "WS_EX_TOPMOST",
    0x00000020: "WS_EX_TRANSPARENT",
    0x00000080: "WS_EX_TOOLWINDOW",
    0x00000100: "WS_EX_WINDOWEDGE",
    0x00000200: "WS_EX_CLIENTEDGE",
    0x00020000: "WS_EX_APPWINDOW",
    0x00080000: "WS_EX_LAYERED",
    0x00100000: "WS_EX_NOINHERITLAYOUT",
    0x00200000: "WS_EX_NOREDIRECTIONBITMAP",
    0x08000000: "WS_EX_NOACTIVATE",
    0x02000000: "WS_EX_COMPOSITED",
}

STYLE_FLAGS = {
    0x80000000: "WS_POPUP",
    0x10000000: "WS_VISIBLE",
    0x01000000: "WS_MAXIMIZE",
    0x00800000: "WS_BORDER",
    0x00C00000: "WS_CAPTION",
    0x00400000: "WS_DLGFRAME",
    0x04000000: "WS_CLIPSIBLINGS",
    0x02000000: "WS_CLIPCHILDREN",
    0x00040000: "WS_THICKFRAME",
}


def decode_flags(value, flag_map):
    result = []
    for bit, name in sorted(flag_map.items()):
        if value & bit:
            result.append(name)
    return result


def get_window_band(hwnd):
    """Try to get the window band via undocumented GetWindowBand."""
    try:
        band = ctypes.c_uint(0)
        result = user32.GetWindowBand(hwnd, ctypes.byref(band))
        if result:
            return band.value
    except Exception:
        pass
    return None


print(f"You have 10 seconds to tab into League...")
time.sleep(10)
print(f"Capturing...\n")

# Enumerate ALL visible windows
WNDENUMPROC = ctypes.WINFUNCTYPE(
    ctypes.c_bool, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM
)

windows = []


def enum_cb(hwnd, _):
    if not user32.IsWindowVisible(hwnd):
        return True
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    title = buf.value
    if not title:
        return True

    cls = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, cls, 256)

    rect = ctypes.wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    w = rect.right - rect.left
    h = rect.bottom - rect.top

    style = user32.GetWindowLongW(hwnd, GWL_STYLE)
    exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    band = get_window_band(hwnd)

    # DWM cloaked?
    cloaked = ctypes.c_int(0)
    dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)

    # Get thread/process
    pid = ctypes.wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    windows.append({
        "hwnd": hwnd,
        "title": title,
        "class": cls.value,
        "size": (w, h),
        "pos": (rect.left, rect.top),
        "style": style,
        "exstyle": exstyle,
        "band": band,
        "cloaked": cloaked.value,
        "pid": pid.value,
        "tid": tid,
    })
    return True


user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

# Now walk z-order
print("=" * 80)
print("TOP 20 VISIBLE WINDOWS (z-order, top to bottom)")
print("=" * 80)

GW_HWNDNEXT = 2
hwnd = user32.GetTopWindow(None)
z_index = 0

while hwnd and z_index < 20:
    if user32.IsWindowVisible(hwnd):
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value
        if title:
            cls = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, cls, 256)
            exstyle = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            style = user32.GetWindowLongW(hwnd, GWL_STYLE)
            band = get_window_band(hwnd)

            z_index += 1
            print(f"\n--- Z-order #{z_index} ---")
            print(f"  HWND:     {hwnd}")
            print(f"  Title:    {title!r}")
            print(f"  Class:    {cls.value!r}")
            print(f"  Style:    {hex(style)} = {decode_flags(style, STYLE_FLAGS)}")
            print(f"  ExStyle:  {hex(exstyle)} = {decode_flags(exstyle, EX_FLAGS)}")
            print(f"  Band:     {band}")

    hwnd = user32.GetWindow(hwnd, GW_HWNDNEXT)

# Highlight interesting windows (Porofessor, League, overlays)
print("\n" + "=" * 80)
print("INTERESTING WINDOWS (Porofessor, League, overlay-like)")
print("=" * 80)

keywords = ["porofessor", "league", "riot", "blitz", "overlay", "u.gg", "mobalytics", "overwolf", "aram"]
for win in windows:
    title_low = win["title"].lower()
    cls_low = win["class"].lower()
    combined = title_low + " " + cls_low

    if any(k in combined for k in keywords):
        print(f"\n  HWND:     {win['hwnd']}")
        print(f"  Title:    {win['title']!r}")
        print(f"  Class:    {win['class']!r}")
        print(f"  PID:      {win['pid']}")
        print(f"  Size:     {win['size'][0]}x{win['size'][1]}")
        print(f"  Pos:      ({win['pos'][0]}, {win['pos'][1]})")
        print(f"  Style:    {hex(win['style'])} = {decode_flags(win['style'], STYLE_FLAGS)}")
        print(f"  ExStyle:  {hex(win['exstyle'])} = {decode_flags(win['exstyle'], EX_FLAGS)}")
        print(f"  Band:     {win['band']}")
        print(f"  Cloaked:  {win['cloaked']}")

# Foreground
fg = user32.GetForegroundWindow()
buf = ctypes.create_unicode_buffer(256)
user32.GetWindowTextW(fg, buf, 256)
print(f"\nForeground: HWND={fg} title={buf.value!r}")
