# ARAM Oracle — In-Game Overlay Assessment & Implementation Plan

## 1. Current State Assessment

### What Exists

The project has **three overlay approaches**, none of which currently work end-to-end in the standalone EXE:

| Approach | File | Status | Problem |
|----------|------|--------|---------|
| PyQt6 overlay | `backend/overlay/window.py` | Works from source only | PyQt6-WebEngine adds ~250MB to bundle, import fails in frozen exe |
| Overwolf Electron | `overwolf/src/main.js` | Scaffold only | Requires Node.js ecosystem, separate build chain |
| Browser fallback | `backend/main.py` | Works in EXE | Opens a normal browser tab — **not** an overlay, no transparency, no click-through |

### Why the Browser Tab Doesn't Work as an Overlay

A normal browser window **cannot** be an overlay because:

1. **No click-through** — Browsers capture all mouse input. Clicking on the overlay would alt-tab you out of League.
2. **No transparency** — Browser windows have a solid background. Even with `?mode=overlay`, the CSS transparency only works when the *window itself* is set to `WA_TranslucentBackground` (Win32 flag), which browsers don't support.
3. **No always-on-top** — Browser tabs have no z-order control. League in borderless windowed covers them.
4. **Focus stealing** — Any interaction with the browser steals focus from the game.

### What the PyQt6 Overlay Does Right

The existing `window.py` is architecturally sound:

- `WS_EX_TRANSPARENT | WS_EX_LAYERED` — true click-through at the Win32 level
- `WindowStaysOnTopHint | Tool` — stays above League, hidden from taskbar
- `WA_TranslucentBackground` — per-pixel transparency
- `QWebEngineView` — renders the existing HTML/CSS/JS frontend
- Loads `http://localhost:8765/overlay?mode=overlay` — reuses the same frontend

**The only problem is distribution size.** PyQt6-WebEngine bundles the Chromium engine (~200MB).

### League Display Mode Constraints

| Mode | Overlay works? | Notes |
|------|---------------|-------|
| Borderless Windowed | Yes | Standard Win32 windows render on top. This is what Blitz/Porofessor use. |
| Fullscreen (Exclusive) | No | DirectX exclusive mode covers all windows. No overlay tool works here without injection (blocked by Vanguard). |
| Windowed | Yes | But players rarely use this. |

**Conclusion:** All legitimate League overlays (Blitz, Porofessor, U.GG, Mobalytics) require **Borderless Windowed** mode. This is the standard expectation.

---

## 2. Overlay Technology Options

### Option A: Lightweight Win32 Overlay (No WebEngine)

**Approach:** Replace QWebEngineView with a native Win32 transparent window that draws directly using GDI+ or Direct2D. The Python backend sends pre-formatted text over WebSocket, and the overlay renders it as simple colored text blocks.

**Pros:**
- Tiny footprint (~5MB addition to EXE)
- No Chromium dependency
- Minimal resource usage
- Simple to bundle with PyInstaller

**Cons:**
- Loses the rich HTML/CSS layout — would need a custom rendering layer
- Significant rewrite of the display logic
- No web technologies, harder to iterate on UI

**Bundle size:** ~50MB total (current server-only EXE + ctypes overlay)

### Option B: PyWebView (Lightweight Web Overlay)

**Approach:** Use `pywebview` which wraps the system WebView2 (Edge/Chromium already installed on Windows 10/11). It provides a transparent, frameless window with web rendering but uses the **OS-provided** browser engine instead of bundling its own.

**Pros:**
- Reuses the existing HTML/CSS/JS frontend completely
- WebView2 is pre-installed on all Windows 10 21H2+ and Windows 11 machines
- Adds only ~2MB to the bundle (the `pywebview` library itself)
- Supports transparent windows and click-through via Win32 flags
- `pywebview` supports `on_top=True` and frameless mode natively

**Cons:**
- Requires WebView2 runtime (present on 99%+ of Win10/11 machines)
- Click-through needs manual Win32 flag setting (same ctypes code we already have)
- Less battle-tested than PyQt6 for overlay use cases

**Bundle size:** ~52MB total (server-only EXE + pywebview)

### Option C: PyQt6 Overlay with Separate Download

**Approach:** Keep the current PyQt6 overlay code. Ship two EXEs:
1. `aram-oracle.exe` — server-only, ~50MB (what we have now)
2. `aram-oracle-overlay.exe` — includes PyQt6-WebEngine, ~250MB

Users choose: lightweight browser version or full overlay version.

**Pros:**
- Already implemented and working from source
- Rich rendering with full Chromium engine
- No external dependencies

**Cons:**
- 250MB download for the overlay version
- Complex build pipeline (two spec files)
- PyInstaller + PyQt6-WebEngine is historically buggy

**Bundle size:** ~250MB for overlay, ~50MB for server-only

### Option D: Electron Overlay (Current Overwolf Scaffold)

**Approach:** Use the existing `overwolf/` scaffold. Ship as an Electron app that spawns the Python EXE as a child process.

**Pros:**
- Electron's `BrowserWindow` has native transparent, click-through, always-on-top support
- Rich web rendering
- Same codebase works for standalone and Overwolf distribution
- Well-documented overlay patterns (Discord, Overwolf apps all use this)

**Cons:**
- Adds Electron runtime (~80MB)
- Two runtimes in the bundle (Python + Node.js)
- More complex build/release pipeline
- Total size ~130-150MB

**Bundle size:** ~140MB (Electron + bundled Python EXE)

---

## 3. Recommendation

### Primary: Option B (pywebview) — Best Balance

pywebview is the clear winner for the standalone EXE distribution:

- **Minimal size increase** (~2MB on top of the current 50MB bundle)
- **Reuses the existing frontend** — zero UI rewrite needed
- **WebView2 is universally available** on modern Windows
- **Click-through and transparency** work with the same Win32 ctypes code already written
- **Single EXE** — no two-runtime complexity

### Secondary: Option D (Electron) — For Overwolf Path

Keep the Electron scaffold for the Overwolf distribution channel. When the app reaches 500+ DAU and an Overwolf port makes sense, the Electron path is ready.

---

## 4. Implementation Plan — pywebview Overlay

### Phase 1: Core Overlay Window (est. ~60 lines of code)

**File: `backend/overlay/webview_window.py`** (new)

```
1. pip install pywebview
2. Create a transparent, frameless, always-on-top pywebview window
3. Load http://localhost:8765/overlay?mode=overlay
4. Apply WS_EX_TRANSPARENT | WS_EX_LAYERED via ctypes (reuse from window.py)
5. Position at right edge of screen (same geometry as PyQt6 version)
```

Key API calls:
- `webview.create_window(url=..., frameless=True, on_top=True, transparent=True)`
- `webview.start()` — blocks on the GUI event loop
- After window creation, use the existing `_set_click_through()` ctypes code

### Phase 2: Entry Point Integration

**File: `backend/overlay/__main__.py`** (modify)

```
1. Try pywebview first (lightweight, no heavy deps)
2. Fall back to PyQt6 if pywebview unavailable
3. Fall back to browser if neither available
```

Priority chain: pywebview > PyQt6 > browser

**File: `backend/main.py`** (modify)

```
1. Add --overlay flag: starts server + overlay in one process
2. Default behavior (no flag): server + browser (current)
3. --no-browser: server only (headless)
```

### Phase 3: PyInstaller Integration

**File: `aram-oracle.spec`** (modify)

```
1. Add pywebview to hiddenimports
2. Add WebView2Loader.dll to binaries (pywebview bundles this)
3. Test frozen bundle launches overlay correctly
```

pywebview with WebView2 backend adds minimal files:
- `webview/` Python package (~500KB)
- `WebView2Loader.dll` (~150KB)
- No Chromium engine — uses the system-installed Edge WebView2

### Phase 4: Toggle Interactivity

The overlay must be click-through during gameplay but needs to accept input during augment picks (to click "Choose this" buttons).

```
1. Add a global hotkey (e.g., Alt+O) to toggle click-through on/off
2. When toggled ON: WS_EX_TRANSPARENT set, mouse passes through
3. When toggled OFF: WS_EX_TRANSPARENT cleared, overlay accepts clicks
4. Visual indicator: border glow changes color (green=passthrough, cyan=interactive)
5. Auto-toggle: when augment_confirm message arrives, briefly enable interaction
```

Implementation: `ctypes.windll.user32.SetWindowLongW()` to flip WS_EX_TRANSPARENT.

### Phase 5: Polish

```
1. Tray icon with right-click menu (Show/Hide overlay, Toggle click-through, Quit)
2. Remember window position across sessions (save to ~/.aram-oracle/overlay.json)
3. Auto-hide when no game is detected (listen for "no_game" WS message)
4. Opacity slider (adjustable via tray menu or hotkey)
```

---

## 5. Dependency Changes

### pyproject.toml additions

```toml
[project.optional-dependencies]
overlay = [
    "PyQt6>=6.5",
    "PyQt6-WebEngine>=6.5",
]
webview-overlay = [
    "pywebview>=5.0",
]
```

### For the standalone EXE build

Only `pywebview` is needed (not PyQt6). This keeps the bundle small.

---

## 6. Risk Analysis

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| WebView2 not installed on user's PC | Very low (pre-installed on Win10 21H2+, Win11) | Detect at startup, show download link if missing |
| pywebview transparent window doesn't work with League | Low (same Win32 mechanism as PyQt6) | Test with borderless windowed League; fall back to PyQt6 |
| Click-through toggle confuses users | Medium | Clear visual indicator + auto-toggle during augment picks |
| Vanguard blocks the overlay process | Very low (we use no injection, only standard Win32 windows) | Same approach as Blitz/Porofessor which work fine |

---

## 7. File Summary

| File | Action | Description |
|------|--------|-------------|
| `backend/overlay/webview_window.py` | CREATE | pywebview transparent overlay window |
| `backend/overlay/__main__.py` | MODIFY | Priority chain: pywebview > PyQt6 > browser |
| `backend/main.py` | MODIFY | Add `--overlay` flag |
| `pyproject.toml` | MODIFY | Add `pywebview` optional dep |
| `aram-oracle.spec` | MODIFY | Add pywebview to hiddenimports |
| `frontend/style.css` | MODIFY | Add interactive-mode visual indicator |
| `frontend/app.js` | MODIFY | Add click-through toggle indicator |
