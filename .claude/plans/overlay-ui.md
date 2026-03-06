# ARAM Oracle — In-Game Companion UI Plan

## Task
Build an in-game companion UI for ARAM Oracle — a web-based overlay served by the existing FastAPI backend that displays real-time augment recommendations, item build paths, and enemy CC info while playing League of Legends ARAM. Since League runs in exclusive fullscreen (borderless is broken), the UI must work as a second-monitor/mobile companion web app served by FastAPI. The frontend connects to the existing WebSocket at `/ws/game`, uses vanilla HTML/CSS/JS with a dark compact design, and includes manual augment quick-select input.

## Architecture Decision
**Approach: Browser-based companion app served by FastAPI**
- League runs exclusive fullscreen — pywebview/electron overlays cannot render on top
- The FastAPI backend already exists on port 8765 — serve the frontend as static files
- Player opens `http://localhost:8765/overlay` on second monitor, phone, or tablet
- WebSocket provides real-time push updates (2s interval)
- Future: Overwolf integration can wrap the same HTML/CSS/JS as a true in-game overlay

## Data Flow
```
League Client (localhost:2999)
    │ poll every 2s
    ▼
FastAPI Backend (localhost:8765)
    │ parse → GameSnapshot
    │ run Pipeline → PipelineResult
    │ push via WebSocket
    ▼
Browser Frontend (ws://localhost:8765/ws/game)
    │ receive PipelineResult JSON
    │ update DOM
    ▼
Rendered UI (second monitor / phone / tablet)
```

## Edge Cases
1. **WebSocket disconnects mid-game** → auto-reconnect with exponential backoff (1s, 2s, 4s, max 10s), show "Reconnecting..." banner
2. **No game active** → show waiting state with connection status indicator
3. **Augment choices empty** → collapse augment section, show "No augment pick active"
4. **Pipeline returns no recommendations** → show "Waiting for data..." instead of empty table
5. **Item IDs not resolvable** → display raw ID as fallback, never crash
6. **Multiple browser tabs open** → each gets its own WebSocket, no shared state issues
7. **Backend restarts mid-game** → frontend reconnects automatically, re-fetches static data
8. **Phone/tablet viewport** → responsive CSS, stack sections vertically below 400px width

---

## Stage 1: Backend Enrichment
**Files to modify:**
- `backend/api/server.py` — enrich WebSocket responses with display names, add static data endpoint, serve frontend files, wire up poll_game_loop as background task

**Acceptance criteria:**
- [ ] `GET /api/static-names` returns `{items: {id: name}, augments: {id: {name, tier}}, champions: {id: name}}`
- [ ] WebSocket `_serialize_result` includes `augment_name`, item display names in `core_items_names` and `full_build_names`
- [ ] `GET /api/augments/search?tier=2&q=jewel` returns filtered augment list for quick-select
- [ ] `poll_game_loop` registered as background task in FastAPI lifespan
- [ ] Static files served from `frontend/` directory at `/overlay`
- **DRIFT CHECK:** Run `checker_run` after completion

## Stage 2: Frontend — Static Shell & WebSocket Connection
**Files to create:**
- `frontend/index.html` — single-page overlay layout with all sections
- `frontend/style.css` — dark theme, compact typography, section expand/collapse
- `frontend/app.js` — WebSocket connection, auto-reconnect, static data fetch

**Acceptance criteria:**
- [ ] `http://localhost:8765/overlay` loads the companion UI
- [ ] WebSocket connects and shows connection status (green dot = connected, red = disconnected)
- [ ] Auto-reconnect on disconnect with backoff
- [ ] Static data fetched on page load for name resolution
- [ ] Waiting state displayed when no game is active
- **DRIFT CHECK:** Run `checker_run` after completion

## Stage 3: Frontend — Recommendation Rendering
**Files to modify:**
- `frontend/app.js` — DOM update logic for all sections
- `frontend/style.css` — styling for recommendation cards, build path, enemies

**Acceptance criteria:**
- [ ] Header shows champion name, game time (mm:ss), gold, phase
- [ ] Augment recommendations rendered as ranked cards (green highlight on #1, scores, labels, core items)
- [ ] Reroll banner appears conditionally with red styling
- [ ] Build path shows 6 items with status (Owned/BUY NEXT/Planned)
- [ ] Gold shortfall displayed when applicable
- [ ] Enemy list shows champion names with CC duration
- [ ] Sections auto-expand/collapse based on game phase
- **DRIFT CHECK:** Run `checker_run` after completion

## Stage 4: Frontend — Augment Quick-Select Input
**Files to modify:**
- `frontend/app.js` — augment search, selection UI, send choices to backend
- `frontend/style.css` — dropdown styling, selection states
- `backend/api/server.py` — handle augment choice messages from frontend via WebSocket

**Acceptance criteria:**
- [ ] "Set Augments" button opens a tier-filtered search dropdown
- [ ] Typing filters augments by name (debounced 200ms)
- [ ] Clicking an augment adds it to the choice list (max 3)
- [ ] "Evaluate" button sends choices to backend via WebSocket, receives scored results
- [ ] "Choose" button on a recommendation marks it as chosen and persists to pipeline state
- [ ] Entire flow completable in 3-4 clicks
- **DRIFT CHECK:** Run `checker_run` after completion

## Stage 5: Polish & Responsive
**Files to modify:**
- `frontend/style.css` — responsive breakpoints, animations
- `frontend/app.js` — smooth transitions, phase-based auto-behavior

**Acceptance criteria:**
- [ ] Layout works on phone viewport (360px+) with stacked sections
- [ ] Transitions under 200ms, no distracting animations
- [ ] Phase transitions trigger auto-expand of relevant section
- [ ] Gold/item changes highlight briefly (flash effect)
- [ ] Keyboard shortcut `Escape` collapses all sections
- **DRIFT CHECK:** Run `checker_run` after completion
