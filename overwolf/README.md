# ARAM Oracle — Overwolf Electron Overlay

## Overview

Overwolf Electron (`@overwolf/ow-electron`) app that renders the ARAM Oracle
overlay inside League of Legends via DirectX injection. This is the only
reliable way to overlay fullscreen/borderless games — standard Win32 windows
are hidden by DWM fullscreen optimizations.

## Architecture

```
overwolf/
├── package.json        # ow-electron config (overlay package declared here)
├── src/
│   └── main.js         # Main process: backend spawn + overlay API
└── public/             # Icons for store listing
```

**Two runtime modes:**

| Mode | Command | Overlay | Use case |
|------|---------|---------|----------|
| Dev (standard Electron) | `npm start` | Transparent window (no DirectX) | UI development |
| Overwolf | `npm run start:ow` | DirectX-injected overlay | In-game overlay |

## Prerequisites

1. **Overwolf developer account** — submit app proposal at [overwolf.com](https://www.overwolf.com)
2. **Node.js 18+**
3. **Python backend** running or bundled (`python -m backend.main`)

## Development

```bash
cd overwolf
npm install

# Dev mode (standard Electron — overlay won't render above League)
npm start

# Overwolf mode (requires approved developer account)
npm run start:ow
```

## Building

```bash
# Standalone Electron installer
npm run build

# Overwolf store package
npm run build:ow
```

## How It Works

1. App starts, spawns Python backend on port 8765
2. Waits for `/health` endpoint to respond
3. If running under ow-electron:
   - Registers League of Legends (class ID 5426) with overlay API
   - On `game-launched` event: injects into DirectX render pipeline
   - On `game-injected`: creates overlay window inside the game frame
4. If running under standard Electron:
   - Creates a transparent BrowserWindow (dev mode only)

## Overwolf Store Submission

- [ ] Approved developer account
- [ ] App icons: 256x256 (color + gray) in `public/`
- [ ] Store screenshots (1280x720 minimum)
- [ ] Privacy policy URL
- [ ] Windows code signing certificate
- [ ] No in-game advertisements (Riot policy)

## Notes

- **Game ID 5426** = League of Legends
- The `overwolf.packages` field in package.json declares which Overwolf
  services the app uses (`overlay` for DirectX injection)
- GEP (Game Events Provider) can be added later for real-time game data
  as a supplement to LCDA API polling
