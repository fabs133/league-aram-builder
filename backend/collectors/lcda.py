import requests
import urllib3
from backend.models import GameSnapshot, GamePhase

# League's Live Client Data API uses a self-signed certificate
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

LCDA_BASE = "https://127.0.0.1:2999/liveclientdata"
SESSION = requests.Session()
SESSION.verify = False

# Champions whose LCDA display name normalizes differently from the data key
_CHAMPION_ALIASES = {
    "nunu&willump": "nunu",
    "dr.mundo": "drmundo",
    "wukong": "monkeyking",
    "renataglasc": "renata",
}


def _normalize_champion_name(raw: str) -> str:
    """Normalize an LCDA champion name to match champions.json keys."""
    key = raw.lower().replace(" ", "").replace("'", "")
    return _CHAMPION_ALIASES.get(key, key)


def get_raw_game_data() -> dict | None:
    """Returns raw API response or None if game is not running."""
    try:
        r = SESSION.get(f"{LCDA_BASE}/allgamedata", timeout=1)
        return r.json() if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def get_active_player_name() -> str | None:
    try:
        r = SESSION.get(f"{LCDA_BASE}/activeplayer", timeout=1)
        return r.json().get("summonerName") if r.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None


def parse_game_snapshot(raw: dict, phase: GamePhase) -> GameSnapshot:
    """
    Parse raw LCDv2 allgamedata response into a GameSnapshot.
    augment_choices and chosen_augments are not available from LCDv2 directly --
    they must be injected from the overlay event watcher.
    """
    active = raw.get("activePlayer", {})
    all_players = raw.get("allPlayers", [])
    game_data = raw.get("gameData", {})

    active_name = active.get("summonerName", "")
    active_player = next(
        (p for p in all_players if p.get("summonerName") == active_name), {}
    )

    items = [str(item["itemID"]) for item in active_player.get("items", [])]
    gold = int(active.get("currentGold", 0))
    game_time = float(game_data.get("gameTime", 0))
    game_id = str(game_data.get("gameId", "unknown"))
    level = int(active.get("level", 1))

    # Full champion stats dict for augment detection via stat deltas
    raw_stats = active.get("championStats", {})
    champion_stats = {
        k: float(v) for k, v in raw_stats.items()
        if isinstance(v, (int, float))
    }
    cur_hp = champion_stats.get("currentHealth", 0.0)
    max_hp = champion_stats.get("maxHealth", 1.0)
    health_pct = cur_hp / max_hp if max_hp > 0 else 1.0

    # Death status from allPlayers entry
    is_dead = bool(active_player.get("isDead", False))

    champion_id = _normalize_champion_name(
        active_player.get("championName", "")
    )

    enemies = [
        _normalize_champion_name(p.get("championName", ""))
        for p in all_players
        if p.get("team") != active_player.get("team")
    ]

    return GameSnapshot(
        game_id=game_id,
        phase=phase,
        champion_id=champion_id,
        augment_choices=[],
        chosen_augments=[],
        purchased_items=items,
        current_gold=gold,
        game_time=game_time,
        enemy_champion_ids=enemies,
        level=level,
        is_dead=is_dead,
        health_pct=health_pct,
        champion_stats=champion_stats,
    )
