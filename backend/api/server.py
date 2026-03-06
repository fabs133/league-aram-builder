import asyncio
import json
import sys
import time
from pathlib import Path
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from contextlib import asynccontextmanager
import logging

logger = logging.getLogger("aram-oracle")

from backend.static_data.loader import StaticData
from backend.static_data.updater import force_refresh
from backend.workflow.pipeline import Pipeline
from backend.collectors.lcda import get_raw_game_data, parse_game_snapshot
from backend.collectors.screen_ocr import (
    detect_augments, is_available as ocr_available, watcher as screen_watcher,
)
from backend.models import GamePhase, GameSnapshot, PipelineResult
from backend.engine.augment_detector import has_stats_changed, match_augment
from backend.diagnostics import collector as diagnostics

static_data = StaticData()
pipeline: Pipeline | None = None
ws_clients: list[WebSocket] = []


# -- Thread-safe game state --


class GameState:
    """Encapsulates all mutable augment/OCR state with an asyncio.Lock.

    Replaces the former 13 module-level globals. All mutations go through
    methods that acquire ``self._lock`` so the poll loop and WS handlers
    never see partial updates.
    """

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        # Augment choices injected by overlay / OCR
        self.augment_choices: list[str] = []
        self.chosen_augments: list[str] = []  # real augments only (max 4)
        self.chosen_stat_anvils: list[str] = []  # stat anvil / voucher picks
        # OCR state
        self.ocr_enabled: bool = True
        self.ocr_last_detected: list[str] = []
        # Augment pick window
        self.last_known_level: int = 0
        self.scan_window_open: bool = False
        self.scan_window_level: int = 0
        self.was_dead: bool = False  # track death transitions
        # Stat delta matching
        self.stat_snapshot_before: dict[str, float] = {}
        self.awaiting_stat_delta: bool = False
        self.delta_wait_ticks: int = 0
        # Post-game detection
        self.had_game_last_tick: bool = False
        self.post_game: bool = False
        self.post_game_time: float = 0.0

    @property
    def lock(self) -> asyncio.Lock:
        return self._lock

    def reset(self) -> None:
        """Reset all game-specific state (called when no game is detected)."""
        if self.ocr_last_detected or screen_watcher.has_detection:
            self.ocr_last_detected.clear()
            self.augment_choices.clear()
            self.chosen_augments.clear()
            self.chosen_stat_anvils.clear()
            screen_watcher.reset()
        self.last_known_level = 0
        self.scan_window_open = False
        self.scan_window_level = 0
        self.was_dead = False
        self.stat_snapshot_before.clear()
        self.awaiting_stat_delta = False
        self.delta_wait_ticks = 0

    def get_augment_state(self) -> dict:
        """Current augment tracking state for the frontend."""
        expected = expected_augments_for_level(self.last_known_level)
        return {
            "max": len(AUGMENT_PICK_LEVELS),  # always 4
            "eligible": expected,
            "chosen": len(self.chosen_augments),
            "chosen_augments": list(self.chosen_augments),
            "stat_anvils": len(self.chosen_stat_anvils),
        }


game_state = GameState()

AUGMENT_PICK_LEVELS = {3, 7, 11, 15}
AUGMENT_PICK_LEVELS_SORTED = sorted(AUGMENT_PICK_LEVELS)  # [3, 7, 11, 15]


def expected_augments_for_level(level: int) -> int:
    """How many augments a player should have picked by this level."""
    return sum(1 for lvl in AUGMENT_PICK_LEVELS_SORTED if level >= lvl)


@asynccontextmanager
async def lifespan(app: FastAPI):
    diagnostics.install_log_handler()
    static_data.load()
    global pipeline
    pipeline = Pipeline(static_data)

    poll_task = asyncio.create_task(_poll_game_loop())
    yield
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass


app = FastAPI(lifespan=lifespan)

# In PyInstaller bundles, sys._MEIPASS points to the extraction dir.
_APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
FRONTEND_DIR = _APP_ROOT / "frontend"


# -- Static file serving for overlay --


@app.get("/")
def root_redirect():
    return RedirectResponse(url="/overlay")


@app.get("/overlay")
def serve_overlay():
    index = FRONTEND_DIR / "index.html"
    if index.exists():
        return FileResponse(index)
    return {"error": "frontend/index.html not found"}


if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="frontend")


# -- REST --


@app.get("/health")
def health():
    return {
        "status": "ok",
        "data_loaded": static_data.loaded_ok,
        "champions_loaded": len(static_data._champions),
        "augments_loaded": len(static_data._augments),
        "items_loaded": len(static_data._items),
    }


@app.get("/champion/{champion_id}")
def get_champion(champion_id: str):
    champ = static_data.get_champion(champion_id)
    if champ is None:
        return {"error": "not found"}
    return {"id": champ.id, "name": champ.name, "stats": vars(champ.stats)}


@app.get("/api/static-names")
def get_static_names():
    items = {**static_data._all_item_names,
             **{iid: item.name for iid, item in static_data._items.items()}}
    augments = {
        aid: {"name": aug.name, "tier": aug.tier.value}
        for aid, aug in static_data._augments.items()
    }
    stat_anvils = {
        aid: {"name": aug.name, "tier": aug.tier.value}
        for aid, aug in static_data._stat_anvils.items()
    }
    champions = {cid: champ.name for cid, champ in static_data._champions.items()}
    return {"items": items, "augments": augments, "stat_anvils": stat_anvils, "champions": champions}


@app.get("/api/ocr/status")
def ocr_status():
    return {
        "available": ocr_available(),
        "enabled": game_state.ocr_enabled,
        "last_detected": game_state.ocr_last_detected,
    }


@app.post("/api/ocr/scan")
def ocr_scan():
    """Manually trigger an OCR scan for augment names."""
    if not ocr_available():
        return {"error": "OCR not available — is Tesseract installed?", "detected": []}

    augment_names = {aid: aug.name for aid, aug in static_data._augments.items()}
    augment_names.update({aid: aug.name for aid, aug in static_data._stat_anvils.items()})
    matches = detect_augments(augment_names, save=True)

    if matches:
        ids = [m[0] for m in matches]
        game_state.augment_choices.clear()
        game_state.augment_choices.extend(ids)
        game_state.ocr_last_detected.clear()
        game_state.ocr_last_detected.extend(ids)

    return {
        "detected": [
            {"id": aid, "name": name, "confidence": score}
            for aid, name, score in matches
        ],
        "augment_choices_set": list(game_state.augment_choices),
    }


@app.get("/api/ocr/screenshots")
def list_screenshots():
    """List saved screenshots for debugging OCR region calibration."""
    ss_dir = _APP_ROOT / "data" / "screenshots"
    if not ss_dir.exists():
        return []
    files = sorted(ss_dir.glob("*.png"), key=lambda p: p.stat().st_mtime, reverse=True)
    return [{"name": f.name, "url": f"/api/ocr/screenshots/{f.name}"} for f in files[:20]]


@app.get("/api/ocr/screenshots/{filename}")
def get_screenshot(filename: str):
    """Serve a saved screenshot."""
    ss_dir = _APP_ROOT / "data" / "screenshots"
    path = (ss_dir / filename).resolve()
    if not path.is_relative_to(ss_dir.resolve()):
        return {"error": "not found"}
    if not path.exists() or not path.suffix == ".png":
        return {"error": "not found"}
    return FileResponse(path, media_type="image/png")


@app.post("/api/refresh")
def refresh_data():
    """Force-refresh all cached augment and item data from APIs."""
    counts = force_refresh(static_data)
    global pipeline
    pipeline = Pipeline(static_data)
    return {"status": "refreshed", "loaded": counts}


@app.get("/api/augments/search")
def search_augments(
    q: str = Query(default="", min_length=0),
    tier: int | None = Query(default=None, ge=0, le=3),
):
    results = []
    query = q.lower()
    # Search augments and stat anvils based on tier filter
    pool = static_data.all_stat_anvils() if tier == 0 else static_data.all_augments()
    if tier is None:
        pool = static_data.all_augments() + static_data.all_stat_anvils()
    for aug in pool:
        if tier is not None and aug.tier.value != tier:
            continue
        if query and query not in aug.name.lower():
            continue
        results.append({
            "id": aug.id,
            "name": aug.name,
            "tier": aug.tier.value,
            "tier_name": aug.tier.name.replace("_", " ").title(),
            "description": aug.description,
        })
    results.sort(key=lambda a: a["name"])
    return results[:50]


from pydantic import BaseModel


class BugReportRequest(BaseModel):
    description: str = ""


_last_bug_report_time: float = 0.0
_BUG_REPORT_COOLDOWN = 30.0  # seconds between reports


@app.post("/api/bug-report")
async def create_bug_report(req: BugReportRequest | None = None):
    """Generate a bug report with recent errors, logs, WS messages, and game state.

    Saves locally as JSON backup and optionally posts as a GitHub issue
    (if github_token and github_repo are configured in config.toml).
    Rate-limited to one report per 30 seconds.
    """
    global _last_bug_report_time
    now = time.monotonic()
    if now - _last_bug_report_time < _BUG_REPORT_COOLDOWN:
        remaining = int(_BUG_REPORT_COOLDOWN - (now - _last_bug_report_time))
        return {"error": f"Please wait {remaining}s before submitting another report"}
    _last_bug_report_time = now

    user_description = req.description if req else ""

    async with game_state.lock:
        state_dict = {
            "augment_choices": list(game_state.augment_choices),
            "chosen_augments": list(game_state.chosen_augments),
            "chosen_stat_anvils": list(game_state.chosen_stat_anvils),
            "last_known_level": game_state.last_known_level,
            "scan_window_open": game_state.scan_window_open,
            "awaiting_stat_delta": game_state.awaiting_stat_delta,
            "ocr_enabled": game_state.ocr_enabled,
        }

    # Always save local JSON backup
    report_path = diagnostics.generate_report(game_state_dict=state_dict)

    # Attempt GitHub issue creation
    github_url = None
    title, body = diagnostics.format_github_issue(
        game_state_dict=state_dict,
        user_description=user_description,
    )
    from backend.github_reporter import post_issue
    gh_result = post_issue(title, body)
    if gh_result:
        github_url = gh_result.get("html_url")

    return {
        "status": "created",
        "path": str(report_path),
        "filename": report_path.name,
        "github_url": github_url,
    }


# -- WebSocket --


@app.websocket("/ws/game")
async def game_ws(websocket: WebSocket):
    """
    Bidirectional WebSocket for game state.
    Client can send:
      - {"type": "snapshot", "data": {...}} — manual snapshot
      - {"type": "set_augment_choices", "augment_ids": [...]} — set offered augments
      - {"type": "choose_augment", "augment_id": "..."} — mark augment as chosen
      - {"type": "clear_augments"} — reset augment tracking
    Server pushes PipelineResult on every poll cycle.
    """
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            diagnostics.record_ws_message("inbound", raw)

            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError) as e:
                logger.warning("Invalid JSON from WS client: %s", e)
                await websocket.send_text(json.dumps({"error": "invalid json"}))
                continue

            if not isinstance(msg, dict):
                await websocket.send_text(json.dumps({"error": "expected JSON object"}))
                continue

            msg_type = msg.get("type", "")

            if msg_type == "snapshot":
                data = msg.get("data")
                if not isinstance(data, dict):
                    await websocket.send_text(json.dumps({"error": "snapshot requires 'data' object"}))
                    continue
                snapshot = _parse_snapshot(data)
                result = pipeline.run(snapshot)
                if result:
                    await websocket.send_text(json.dumps(
                        _serialize_result(result, static_data)
                    ))

            elif msg_type == "set_augment_choices":
                augment_ids = msg.get("augment_ids", [])
                if not isinstance(augment_ids, list):
                    await websocket.send_text(json.dumps({"error": "'augment_ids' must be a list"}))
                    continue
                async with game_state.lock:
                    game_state.augment_choices.clear()
                    game_state.augment_choices.extend(augment_ids)
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "action": "set_augment_choices",
                    "augment_ids": list(game_state.augment_choices),
                }))

            elif msg_type == "choose_augment":
                aug_id = msg.get("augment_id", "")
                async with game_state.lock:
                    # Classify by data: stat anvil IDs go to stat_anvils list
                    is_stat_anvil = static_data.get_stat_anvil(aug_id) is not None
                    if aug_id:
                        if is_stat_anvil and aug_id not in game_state.chosen_stat_anvils:
                            game_state.chosen_stat_anvils.append(aug_id)
                        elif not is_stat_anvil and aug_id not in game_state.chosen_augments:
                            game_state.chosen_augments.append(aug_id)
                    game_state.augment_choices.clear()
                    game_state.ocr_last_detected.clear()
                    game_state.scan_window_open = False
                    screen_watcher.reset()
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "action": "choose_augment",
                    "chosen_augments": list(game_state.chosen_augments),
                }))

            elif msg_type == "clear_augments":
                async with game_state.lock:
                    game_state.augment_choices.clear()
                    game_state.chosen_augments.clear()
                    game_state.chosen_stat_anvils.clear()
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "action": "clear_augments",
                }))

            elif msg_type == "scan_augments":
                # Manual scan — full OCR, resets watcher hash
                ids, detected = await asyncio.to_thread(_run_ocr_scan_manual)
                async with game_state.lock:
                    if ids:
                        game_state.augment_choices.clear()
                        game_state.augment_choices.extend(ids)
                        game_state.ocr_last_detected.clear()
                        game_state.ocr_last_detected.extend(ids)
                        screen_watcher._frozen_hash = None
                    choices_snapshot = list(game_state.augment_choices)
                await websocket.send_text(json.dumps({
                    "type": "ocr_result",
                    "detected": detected,
                    "augment_choices": choices_snapshot,
                }))

            elif msg_type == "toggle_ocr":
                async with game_state.lock:
                    game_state.ocr_enabled = msg.get("enabled", not game_state.ocr_enabled)
                await websocket.send_text(json.dumps({
                    "type": "ack",
                    "action": "toggle_ocr",
                    "enabled": game_state.ocr_enabled,
                }))

            else:
                await websocket.send_text(json.dumps({"error": "unknown message type"}))

    except WebSocketDisconnect:
        pass
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)


# -- Polling loop --


def _run_ocr_scan_manual() -> tuple[list[str], list[dict]]:
    """Run a full OCR scan (manual trigger, bypasses hash check).

    Pure function — returns (ids, detected_dicts) without mutating game_state.
    Caller must apply results under the lock.
    """
    augment_names = {aid: aug.name for aid, aug in static_data._augments.items()}
    augment_names.update({aid: aug.name for aid, aug in static_data._stat_anvils.items()})
    matches = detect_augments(augment_names, save=True)

    ids = [m[0] for m in matches] if matches else []
    detected = [
        {"id": aid, "name": name, "confidence": score}
        for aid, name, score in matches
    ]
    return ids, detected


def _run_watcher_check() -> tuple[str, list[str], list[dict] | None]:
    """Run the ScreenWatcher.check() — hash comparison + OCR if changed.

    Pure function — returns (action, ids, detected_dicts) without mutating
    game_state. Caller must apply results under the lock.
    """
    augment_names = {aid: aug.name for aid, aug in static_data._augments.items()}
    augment_names.update({aid: aug.name for aid, aug in static_data._stat_anvils.items()})
    action, matches = screen_watcher.check(augment_names, save=True)

    if action == "detected" and matches:
        ids = [m[0] for m in matches]
        detected = [
            {"id": aid, "name": name, "confidence": score}
            for aid, name, score in matches
        ]
        return (action, ids, detected)

    return (action, [], None)


async def _poll_game_loop(interval: float | None = None):
    """Background task: poll Live Client Data API and push updates to all connected WS clients.

    Augment detection state machine:
    1. Scan window opens when player levels up to 3/7/11/15.
       Snapshot champion stats at this point.
    2. ScreenWatcher detects augments on screen (OCR + hash).
    3. ScreenWatcher reports "disappeared" when augment UI goes away.
    4. Wait 2 ticks for stats to apply, then compare stat delta to
       identify which augment was chosen (cosine similarity matching).
    5. High confidence -> auto-confirm. Low confidence -> ask user.
    """
    if interval is None:
        try:
            from backend.config import config
            interval = config.get("poll_interval", 2.0)
        except Exception:
            interval = 2.0
    logger.info("Poll loop started (interval=%.1fs)", interval)
    while True:
        try:
            clients_count = len(ws_clients)
            if clients_count > 0:
                raw = get_raw_game_data()
                if raw:
                    snapshot = parse_game_snapshot(raw, GamePhase.IN_GAME)
                    current_level = snapshot.level

                    async with game_state.lock:
                        game_state.had_game_last_tick = True
                        game_state.post_game = False
                        # -- Scan window management --
                        #
                        # In ARAM Mayhem, augment selection appears on RESPAWN
                        # (after dying), not at level-up. The trigger is:
                        #   was_dead=True → is_dead=False (respawn)
                        #   AND player has fewer augments than expected for level
                        #
                        # Track death transitions
                        just_respawned = (
                            game_state.was_dead and not snapshot.is_dead
                        )
                        game_state.was_dead = snapshot.is_dead
                        game_state.last_known_level = current_level

                        # Open scan window on respawn when augments are due
                        expected = expected_augments_for_level(current_level)
                        have = len(game_state.chosen_augments)

                        if (
                            just_respawned
                            and have < expected
                            and not game_state.scan_window_open
                            and not game_state.awaiting_stat_delta
                        ):
                            game_state.scan_window_open = True
                            game_state.scan_window_level = current_level
                            game_state.awaiting_stat_delta = False
                            game_state.delta_wait_ticks = 0
                            game_state.stat_snapshot_before = dict(
                                snapshot.champion_stats
                            )
                            screen_watcher.reset()
                            logger.info(
                                "Augment pick window OPENED on respawn "
                                "(level %d, have %d/%d augments)",
                                current_level, have, expected,
                            )

                        # -- Stat delta detection --
                        # Two paths trigger matching:
                        # 1. OCR "disappeared" signal (awaiting_stat_delta)
                        # 2. Passive stat change detection (no OCR needed)
                        if game_state.awaiting_stat_delta:
                            game_state.delta_wait_ticks += 1
                            if game_state.delta_wait_ticks >= 2:
                                await _try_stat_delta_match(snapshot)
                                game_state.awaiting_stat_delta = False
                                game_state.delta_wait_ticks = 0

                        elif game_state.scan_window_open and not game_state.awaiting_stat_delta:
                            # Passive detection: stats changed → augment was chosen
                            if (
                                game_state.stat_snapshot_before
                                and has_stats_changed(
                                    game_state.stat_snapshot_before,
                                    dict(snapshot.champion_stats),
                                )
                            ):
                                logger.info(
                                    "Stat change detected — augment chosen "
                                    "(passive detection, no OCR needed)"
                                )
                                game_state.awaiting_stat_delta = True
                                game_state.delta_wait_ticks = 0

                        # Close window when player takes damage (left base)
                        if (
                            game_state.scan_window_open
                            and not game_state.awaiting_stat_delta
                        ):
                            if snapshot.health_pct < 0.98:
                                logger.info(
                                    "Augment pick window CLOSED (took damage, hp=%.0f%%)",
                                    snapshot.health_pct * 100,
                                )
                                # Player took damage without us detecting the choice
                                if game_state.augment_choices:
                                    await _send_augment_confirm(None)
                                game_state.scan_window_open = False

                    # -- Auto OCR (only while scan window is open) --
                    # Run outside the lock since OCR is blocking I/O
                    if (
                        game_state.scan_window_open
                        and not game_state.awaiting_stat_delta
                        and game_state.ocr_enabled
                        and ocr_available()
                    ):
                        try:
                            action, ids, detected = await asyncio.to_thread(
                                _run_watcher_check
                            )
                            async with game_state.lock:
                                if action == "detected" and detected:
                                    game_state.augment_choices.clear()
                                    game_state.augment_choices.extend(ids)
                                    game_state.ocr_last_detected.clear()
                                    game_state.ocr_last_detected.extend(ids)
                                    logger.info("OCR detected augments: %s", detected)
                                    ocr_msg = json.dumps({
                                        "type": "ocr_result",
                                        "detected": detected,
                                        "augment_choices": list(game_state.augment_choices),
                                    })
                                    await _broadcast(ocr_msg)

                                elif action == "disappeared":
                                    # Augment UI went away — player made a selection
                                    logger.info("Augment UI disappeared — awaiting stat delta")
                                    game_state.awaiting_stat_delta = True
                                    game_state.delta_wait_ticks = 0

                        except Exception as e:
                            logger.warning("OCR watcher error: %s", e, exc_info=True)

                    # Inject overlay augment state
                    snapshot.augment_choices = list(game_state.augment_choices)
                    snapshot.chosen_augments = list(game_state.chosen_augments)

                    result = pipeline.run(snapshot)
                    if result:
                        payload = json.dumps(
                            _serialize_result(result, static_data, snapshot)
                        )
                        await _broadcast(payload)
                else:
                    async with game_state.lock:
                        if game_state.had_game_last_tick:
                            # Game just ended — transition to post-game
                            game_state.had_game_last_tick = False
                            game_state.post_game = True
                            game_state.post_game_time = asyncio.get_event_loop().time()
                            logger.info("Game ended — entering post-game state")
                            await _broadcast(json.dumps({"type": "game_ended"}))
                        elif game_state.post_game:
                            # In post-game window — auto-reset after 5 minutes
                            elapsed = asyncio.get_event_loop().time() - game_state.post_game_time
                            if elapsed > 300:
                                logger.info("Post-game timeout — resetting state")
                                game_state.post_game = False
                                game_state.reset()
                                await _broadcast(json.dumps({"type": "no_game"}))
                        else:
                            game_state.reset()
                            await _broadcast(json.dumps({"type": "no_game"}))
        except Exception as e:
            logger.error("Poll loop error: %s", e, exc_info=True)
        await asyncio.sleep(interval)


async def _broadcast(message: str) -> None:
    """Send a message to all connected WebSocket clients."""
    diagnostics.record_ws_message("outbound", message)
    for client in list(ws_clients):
        try:
            await client.send_text(message)
        except Exception:
            if client in ws_clients:
                ws_clients.remove(client)


async def _try_stat_delta_match(snapshot: GameSnapshot) -> None:
    """Compare champion stats before/after to identify chosen augment.

    Must be called while holding game_state.lock.
    """
    if not game_state.stat_snapshot_before:
        await _send_augment_confirm(None)
        game_state.scan_window_open = False
        return

    # Build candidate list: prefer OCR-detected choices, fall back to all augments
    if game_state.augment_choices:
        candidates = [
            static_data.get_augment(aid)
            for aid in game_state.augment_choices
        ]
        candidates = [c for c in candidates if c is not None]
    else:
        # No OCR data — match against all augments (wider search)
        candidates = static_data.all_augments()
        logger.info(
            "No OCR augment choices — matching against all %d augments",
            len(candidates),
        )

    if not candidates:
        await _send_augment_confirm(None)
        game_state.scan_window_open = False
        return

    after_stats = dict(snapshot.champion_stats)
    matched, confidence = match_augment(game_state.stat_snapshot_before, after_stats, candidates)

    if matched and confidence >= 0.3:
        # High confidence — auto-confirm
        # Classify by data: if matched ID is in stat_anvils dict, it's a stat pick
        is_stat_anvil = static_data.get_stat_anvil(matched.id) is not None
        if is_stat_anvil:
            logger.info(
                "Auto-detected stat anvil: %s (confidence=%.2f)", matched.name, confidence
            )
            game_state.chosen_stat_anvils.append(matched.id)
        else:
            logger.info(
                "Auto-detected augment: %s (confidence=%.2f)", matched.name, confidence
            )
            game_state.chosen_augments.append(matched.id)
        game_state.augment_choices.clear()
        game_state.ocr_last_detected.clear()
        game_state.scan_window_open = False
        screen_watcher.reset()

        await _broadcast(json.dumps({
            "type": "augment_auto_chosen",
            "augment_id": matched.id,
            "augment_name": matched.name,
            "confidence": round(confidence, 2),
            "augment_state": game_state.get_augment_state(),
        }))
    else:
        # Low confidence — ask user to confirm
        logger.info(
            "Augment match ambiguous (best=%.2f) — requesting user confirmation",
            confidence,
        )
        best_guess_id = matched.id if matched else None
        await _send_augment_confirm(best_guess_id)
        # Keep scan_window_open = True so OCR can detect new choices
        # if the user hasn't confirmed yet. The choose_augment handler
        # will close it when the user manually picks.
        game_state.awaiting_stat_delta = False


async def _send_augment_confirm(best_guess_id: str | None) -> None:
    """Send augment_confirm message to all clients for manual selection."""
    candidates = []
    for aid in game_state.augment_choices:
        aug = static_data.get_augment(aid)
        if aug:
            candidates.append({
                "id": aug.id,
                "name": aug.name,
                "tier": aug.tier.value,
            })

    await _broadcast(json.dumps({
        "type": "augment_confirm",
        "candidates": candidates,
        "best_guess_id": best_guess_id,
    }))


# -- Helpers --


def _parse_snapshot(data: dict) -> GameSnapshot:
    return GameSnapshot(
        game_id=data.get("game_id", ""),
        phase=GamePhase(data.get("phase", "in_game")),
        champion_id=data.get("champion_id", ""),
        augment_choices=data.get("augment_choices", []),
        chosen_augments=data.get("chosen_augments", []),
        purchased_items=data.get("purchased_items", []),
        current_gold=data.get("current_gold", 0),
        game_time=data.get("game_time", 0),
        enemy_champion_ids=data.get("enemy_champion_ids", []),
        rerolls_remaining=data.get("rerolls_remaining", 0),
    )


def _resolve_item_name(item_id: str, sd: StaticData) -> str:
    return sd.get_item_name(item_id)


def _resolve_champion_name(champ_id: str, sd: StaticData) -> str:
    champ = sd.get_champion(champ_id)
    return champ.name if champ else champ_id


def _serialize_result(
    result: PipelineResult, sd: StaticData, snapshot: GameSnapshot | None = None,
) -> dict:
    out: dict = {
        "type": "update",
        "phase": result.phase.value,
        "suggest_reroll": result.suggest_reroll,
        "reroll_reason": result.reroll_reason,
        "recommendations": [
            {
                "augment_id": r.augment_id,
                "augment_name": r.augment_name,
                "score": round(r.score, 4),
                "label": list(r.label),
                "core_items": r.core_items,
                "core_items_names": [_resolve_item_name(i, sd) for i in r.core_items],
                "explanation": r.explanation,
            }
            for r in result.recommendations
        ],
        "build_state": {
            "champion_id": result.build_state.champion_id,
            "champion_name": _resolve_champion_name(result.build_state.champion_id, sd),
            "chosen_augments": result.build_state.chosen_augments,
            "purchased_items": result.build_state.purchased_items,
            "purchased_items_names": [
                _resolve_item_name(i, sd) for i in result.build_state.purchased_items
            ],
            "next_item_id": result.build_state.next_item_id,
            "next_item_name": (
                _resolve_item_name(result.build_state.next_item_id, sd)
                if result.build_state.next_item_id else None
            ),
            "gold_to_next": result.build_state.gold_to_next,
            "full_build": result.build_state.full_build,
            "full_build_names": [
                _resolve_item_name(i, sd) for i in result.build_state.full_build
            ],
        },
    }

    if snapshot:
        out["game_time"] = snapshot.game_time
        out["current_gold"] = snapshot.current_gold
        out["level"] = snapshot.level
        out["scan_window_open"] = game_state.scan_window_open
        out["augment_state"] = game_state.get_augment_state()
        out["enemies"] = [
            {
                "id": eid,
                "name": _resolve_champion_name(eid, sd),
                "cc_sec": _get_enemy_cc(eid, sd),
            }
            for eid in snapshot.enemy_champion_ids
        ]

    return out


def _get_enemy_cc(champ_id: str, sd: StaticData) -> float:
    champ = sd.get_champion(champ_id)
    if champ and champ.cc_profile:
        return champ.cc_profile.total_hard_cc_sec
    return 0.0
