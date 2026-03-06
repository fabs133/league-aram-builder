<p align="center">
  <h1 align="center">ARAM Oracle</h1>
  <p align="center">Real-time build recommendation engine for League of Legends ARAM Mayhem</p>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11+-blue?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
  <img src="https://img.shields.io/badge/tests-104%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/status-alpha-orange" alt="Alpha">
</p>

---

ARAM Oracle connects to League's Live Client Data API during an ARAM Mayhem match and provides real-time augment recommendations, item build paths, and reroll advice through a lightweight overlay.

## Features

- **Augment Scoring** -- 12-dimensional stat vector model with role weights, synergy multipliers, CC-CDR bonuses, and enemy comp awareness
- **OCR Augment Detection** -- Tesseract-based screen reading with perceptual hashing for fast change detection (~1ms per tick)
- **Stat-Delta Matching** -- Cosine similarity on champion stat changes to auto-detect which augment was chosen
- **Build Path Suggestions** -- Dynamic item recommendations that adapt to your augments and gold
- **Reroll Advisor** -- Compares best option against champion ceiling to suggest when to reroll
- **Enemy Comp Analysis** -- CC profiling of enemies to weight defensive/offensive augments
- **Personal Winrate Tracking** -- SQLite-backed per-champion augment win rates that influence future recommendations
- **Overlay UI** -- 320px dark-themed companion panel with WebSocket live updates

## Quick Start

### Prerequisites

- Python 3.11+
- League of Legends (running an ARAM Mayhem match for live data)
- Tesseract OCR *(optional, for screen-based augment detection)*

### Install

```bash
git clone https://github.com/fabs133/league-aram-builder.git
cd league-aram-builder
pip install -e .
```

For OCR support, install Tesseract:

```bash
winget install UB-Mannheim.TesseractOCR
```

### Run

```bash
# Start the server (polls game API, serves overlay)
python -m backend.main

# Open the overlay in your browser
# http://localhost:8765/overlay
```

The overlay connects via WebSocket and updates automatically when a game is detected.

### Optional: Desktop Overlay

```bash
# PyQt6 overlay (click-through window on top of game)
pip install -e ".[overlay]"
python -m backend.overlay

# Or lightweight pywebview overlay
pip install -e ".[webview-overlay]"
python -m backend.overlay
```

## Architecture

```
League Client (port 2999)
       |
       v
  +-----------+     +-------------+     +----------+
  | Collectors |---->|   Engine    |---->| Pipeline |
  | lcda.py   |     | scoring.py  |     |          |
  | screen_ocr|     | ranker.py   |     +----+-----+
  +-----------+     | augment_det.|          |
                    | build_sugg. |          v
                    +-------------+     +----------+     +-----------+
                                        | FastAPI  |---->| Frontend  |
                                        | server.py|     | (overlay) |
                                        | /ws/game |     +-----------+
                                        +----------+
                                             |
                                             v
                                        +----------+
                                        | SQLite   |
                                        | winrates |
                                        +----------+
```

| Layer | Description |
|-------|-------------|
| **Collectors** | Poll Live Client Data API, OCR screen capture, LCU client |
| **Engine** | Pure scoring functions -- dot products on stat vectors, overlap penalties, scaling specs |
| **Pipeline** | Orchestrates engine calls, resolves augment/item/champion data |
| **API** | FastAPI + WebSocket server, augment detection state machine, poll loop |
| **Frontend** | Vanilla HTML/CSS/JS overlay, 320px dark layout, WS-driven updates |
| **Storage** | SQLite personal winrate tracking, game history |

## Configuration

Create `~/.aram-oracle/config.toml` (all values are optional):

```toml
[server]
port = 8765
poll_interval = 2.0

[ocr]
match_threshold = 65          # Fuzzy match score (0-100)
hash_change_threshold = 30    # Perceptual hash sensitivity
# ocr_region = [0.15, 0.22, 0.85, 0.50]  # Custom screen region

[augment_detector]
confidence_threshold = 0.3    # Minimum cosine similarity for auto-confirm
confidence_gap = 0.05         # Min gap between best and second-best

[overlay]
overlay_width = 320

[github]
# github_token = "ghp_..."   # For automatic bug report filing
# github_repo = "owner/repo"
```

## Tech Stack

- **Backend:** Python 3.11, FastAPI, WebSocket, NumPy, aiosqlite
- **OCR:** Tesseract, Pillow, rapidfuzz
- **Overlay:** PyQt6 / pywebview (optional)
- **Data Sources:** Riot DataDragon, CommunityDragon
- **Packaging:** PyInstaller

## Anti-Cheat Compliance

ARAM Oracle only reads data from Riot's officially sanctioned **Live Client Data API** (`https://127.0.0.1:2999`). It does not inject code, modify game memory, or interact with the game process. This is the same API used by approved third-party tools like Overwolf apps.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, coding conventions, and how to submit changes.

## License

[MIT](LICENSE) -- see the LICENSE file for details.
