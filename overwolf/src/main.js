/**
 * ARAM Oracle — Overwolf Electron Main Process
 *
 * Architecture:
 *   1. Spawns the Python backend (FastAPI) as a child process
 *   2. Detects if running under ow-electron (Overwolf) or standard Electron
 *   3. Overwolf mode: uses DirectX overlay injection via overlayApi
 *   4. Electron mode: falls back to transparent BrowserWindow (dev only)
 *
 * Overwolf overlay injects into the game's render pipeline, so it renders
 * above fullscreen games without Win32 z-order hacks.
 */

// VS Code terminals set ELECTRON_RUN_AS_NODE which breaks require('electron').
delete process.env.ELECTRON_RUN_AS_NODE;

const { app, BrowserWindow, screen } = require("electron");
const { spawn } = require("child_process");
const path = require("path");
const http = require("http");

const BACKEND_PORT = 8765;
const BACKEND_URL = `http://127.0.0.1:${BACKEND_PORT}`;
const LOL_CLASS_ID = 5426;

let mainWindow = null;
let overlayWindow = null; // OverlayBrowserWindow (Overwolf mode)
let backendProcess = null;
let overlayApi = null;
let healthCheckInterval = null;
let healthFailCount = 0;
const MAX_HEALTH_FAILURES = 3;
const HEALTH_CHECK_INTERVAL_MS = 10000;

// ---------------------------------------------------------------------------
// Overwolf detection
// ---------------------------------------------------------------------------

function isOverwolf() {
  try {
    return typeof app.overwolf !== "undefined" && app.overwolf !== null;
  } catch {
    return false;
  }
}

// ---------------------------------------------------------------------------
// Backend lifecycle
// ---------------------------------------------------------------------------

function findPythonBackend() {
  const bundledExe = path.join(
    process.resourcesPath,
    "backend",
    "aram-oracle.exe"
  );
  const fs = require("fs");
  if (fs.existsSync(bundledExe)) {
    return { cmd: bundledExe, args: [] };
  }

  // Dev mode: run Python directly
  return {
    cmd: "python",
    args: [
      "-m",
      "backend.main",
      "--port",
      String(BACKEND_PORT),
      "--no-browser",
    ],
    cwd: path.resolve(__dirname, "..", ".."),
  };
}

function startBackend() {
  const { cmd, args, cwd } = findPythonBackend();
  console.log(`Starting backend: ${cmd} ${args.join(" ")}`);

  backendProcess = spawn(cmd, args, {
    cwd: cwd || process.resourcesPath,
    stdio: ["ignore", "pipe", "pipe"],
    windowsHide: true,
  });

  backendProcess.stdout.on("data", (data) => {
    try {
      console.log(`[backend] ${data.toString().trim()}`);
    } catch {}
  });

  backendProcess.stderr.on("data", (data) => {
    try {
      console.error(`[backend] ${data.toString().trim()}`);
    } catch {}
  });

  backendProcess.on("exit", (code) => {
    console.log(`Backend exited with code ${code}`);
    backendProcess = null;
    if (code !== 0 && code !== null) {
      console.warn("Backend crashed — scheduling restart in 3s...");
      stopHealthMonitor();
      setTimeout(() => restartBackend(), 3000);
    }
  });
}

function stopBackend() {
  if (backendProcess) {
    console.log("Stopping backend...");
    backendProcess.kill("SIGTERM");
    backendProcess = null;
  }
}

function waitForBackend(timeoutMs = 15000) {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    function check() {
      if (Date.now() - start > timeoutMs) {
        reject(new Error("Backend did not start in time"));
        return;
      }

      const req = http.get(`${BACKEND_URL}/health`, (res) => {
        if (res.statusCode === 200) {
          resolve();
        } else {
          setTimeout(check, 500);
        }
      });

      req.on("error", () => {
        setTimeout(check, 500);
      });

      req.end();
    }

    check();
  });
}

// ---------------------------------------------------------------------------
// Health monitoring & auto-restart
// ---------------------------------------------------------------------------

function startHealthMonitor() {
  healthFailCount = 0;
  healthCheckInterval = setInterval(() => {
    const req = http.get(`${BACKEND_URL}/health`, (res) => {
      if (res.statusCode === 200) {
        healthFailCount = 0;
      } else {
        healthFailCount++;
        handleHealthFailure();
      }
      res.resume(); // drain response
    });
    req.on("error", () => {
      healthFailCount++;
      handleHealthFailure();
    });
    req.setTimeout(3000, () => {
      req.destroy();
      healthFailCount++;
      handleHealthFailure();
    });
  }, HEALTH_CHECK_INTERVAL_MS);
}

function stopHealthMonitor() {
  if (healthCheckInterval) {
    clearInterval(healthCheckInterval);
    healthCheckInterval = null;
  }
}

function handleHealthFailure() {
  if (healthFailCount >= MAX_HEALTH_FAILURES) {
    console.error(
      `Backend health check failed ${healthFailCount} times — restarting`
    );
    stopHealthMonitor();
    restartBackend();
  }
}

async function restartBackend() {
  stopBackend();
  // Wait for port to be released
  await new Promise((r) => setTimeout(r, 2000));
  startBackend();
  try {
    await waitForBackend();
    console.log("Backend restarted successfully");
    startHealthMonitor();
    // Reload overlay window to reconnect WebSocket
    if (overlayWindow && overlayWindow.window) {
      overlayWindow.window.reload();
    } else if (mainWindow) {
      mainWindow.reload();
    }
  } catch (err) {
    console.error("Backend failed to restart:", err.message);
  }
}

// ---------------------------------------------------------------------------
// Overwolf overlay mode (DirectX injection)
//
// API pattern from ow-electron-packages-sample:
//   1. Wait for app.overwolf.packages 'ready' event (overlay package loaded)
//   2. Access overlay API via app.overwolf.packages.overlay
//   3. Register games, listen for game-launched, call event.inject()
//   4. On game-injected, create overlay windows via overlayApi.createWindow()
// ---------------------------------------------------------------------------

function initOverwolfOverlay() {
  // Wait for the overlay package to be loaded by ow-electron runtime
  app.overwolf.packages.on("ready", (e, packageName, version) => {
    if (packageName !== "overlay") return;

    console.log(`Overlay package ready (v${version})`);
    overlayApi = app.overwolf.packages.overlay;

    registerOverlayEvents();
    registerGame();
  });

  console.log("Waiting for overlay package to be ready...");
}

async function registerGame() {
  // Small delay to ensure overlay internals are fully initialized
  await new Promise((r) => setTimeout(r, 1000));

  console.log(`Registering League of Legends (game ID ${LOL_CLASS_ID})...`);
  await overlayApi.registerGames({ gamesIds: [LOL_CLASS_ID] });
  console.log("Game registered for overlay injection");
}

function registerOverlayEvents() {
  overlayApi.removeAllListeners();

  // Game launched — inject into render pipeline
  overlayApi.on("game-launched", (event, gameInfo) => {
    console.log("Game launched:", gameInfo);

    if (gameInfo.processInfo && gameInfo.processInfo.isElevated) {
      console.warn(
        "Game is running elevated — cannot inject unless app is also elevated"
      );
      return;
    }

    console.log("Injecting overlay into game...");
    event.inject();
  });

  // Injection successful — create the overlay window
  overlayApi.on("game-injected", async (gameInfo) => {
    console.log("Overlay injected into game:", gameInfo);
    await createOverwolfOverlayWindow();
  });

  // Injection failed
  overlayApi.on("game-injection-error", (gameInfo, error) => {
    console.error("Overlay injection failed:", error, gameInfo);
  });

  // Game closed — keep overlay alive for post-game feedback
  overlayApi.on("game-exit", () => {
    console.log("Game exited — keeping overlay for post-game feedback");
    // Backend poll loop will detect LCDA failure and send game_ended.
    // Auto-close after 5 minutes if user doesn't interact.
    setTimeout(() => {
      if (overlayWindow) {
        console.log("Post-game timeout — closing overlay");
        overlayWindow.window.close();
        overlayWindow = null;
      }
    }, 5 * 60 * 1000);
  });

  overlayApi.on("game-focus-changed", (window, game, focus) => {
    console.log(`Game focus changed: ${game.name} focus=${focus}`);
  });

  overlayApi.on("game-window-changed", (window, game, reason) => {
    console.log(`Game window changed: ${reason}`);
  });
}

async function createOverwolfOverlayWindow() {
  // Use game window info if available, fall back to screen size
  const activeGame = overlayApi.getActiveGameInfo();
  const gameWindow = activeGame?.gameWindowInfo;

  const screenW = gameWindow?.size?.width || screen.getPrimaryDisplay().workAreaSize.width;
  const screenH = gameWindow?.size?.height || screen.getPrimaryDisplay().workAreaSize.height;
  const overlayWidth = 340;

  try {
    overlayWindow = await overlayApi.createWindow({
      name: "aram-oracle-overlay",
      width: overlayWidth,
      height: screenH - 120,
      x: screenW - overlayWidth - 10,
      y: 60,
      show: true,
      transparent: true,
      resizable: false,
      webPreferences: {
        nodeIntegration: false,
        contextIsolation: true,
      },
    });

    const win = overlayWindow.window;

    // Load the overlay frontend from the Python backend
    await win.loadURL(`${BACKEND_URL}/overlay?mode=overlay`);
    win.show();

    console.log("Overwolf overlay window created and loaded");
  } catch (err) {
    console.error("Failed to create overlay window:", err);
  }
}

// ---------------------------------------------------------------------------
// Fallback: standard Electron BrowserWindow (dev mode only)
//
// This does NOT work above League's fullscreen due to DWM FSO.
// Only useful for development without a running game.
// ---------------------------------------------------------------------------

function createFallbackWindow() {
  const primaryDisplay = screen.getPrimaryDisplay();
  const { width: screenW, height: screenH } = primaryDisplay.workAreaSize;
  const overlayWidth = 340;

  mainWindow = new BrowserWindow({
    x: screenW - overlayWidth - 10,
    y: 60,
    width: overlayWidth,
    height: screenH - 120,
    frame: false,
    transparent: true,
    alwaysOnTop: true,
    skipTaskbar: true,
    resizable: false,
    focusable: false,
    webPreferences: {
      nodeIntegration: false,
      contextIsolation: true,
    },
  });

  mainWindow.setAlwaysOnTop(true, "screen-saver");
  mainWindow.setIgnoreMouseEvents(true, { forward: true });
  mainWindow.loadURL(`${BACKEND_URL}/overlay?mode=overlay`);

  mainWindow.on("closed", () => {
    mainWindow = null;
  });

  console.log(
    "Fallback Electron window created (no DirectX — won't render above fullscreen games)"
  );
}

// ---------------------------------------------------------------------------
// App lifecycle
// ---------------------------------------------------------------------------

app.whenReady().then(async () => {
  startBackend();

  try {
    console.log("Waiting for backend to be ready...");
    await waitForBackend();
    console.log("Backend is ready.");
    startHealthMonitor();
  } catch (err) {
    console.error("Backend failed to start:", err.message);
    console.log("Overlay will load once backend becomes available.");
  }

  if (isOverwolf()) {
    console.log("Running under ow-electron — DirectX overlay enabled");
    initOverwolfOverlay();
  } else {
    console.log("Running under standard Electron — fallback window (dev mode)");
    createFallbackWindow();
  }
});

app.on("window-all-closed", () => {
  stopBackend();
  app.quit();
});

app.on("before-quit", () => {
  stopHealthMonitor();
  stopBackend();
});
