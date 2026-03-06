import requests
from backend.storage.db import get_unsubmitted_games, mark_submitted

COMMUNITY_ENDPOINT = "https://your-endpoint-here/submit"  # placeholder


def submit_pending(enabled: bool = False) -> int:
    """
    Submits unsubmitted games to community endpoint.
    Returns number of games submitted.
    Only runs if enabled=True (user opt-in).
    """
    if not enabled:
        return 0

    games = get_unsubmitted_games()
    if not games:
        return 0

    payload = [
        {
            "champion_id": g["champion_id"],
            "augments": g["augments"],
            "items": g["items"],
            "win": g["win"],
            "game_time_secs": g["game_time_secs"],
        }
        for g in games
    ]

    try:
        r = requests.post(COMMUNITY_ENDPOINT, json=payload, timeout=5)
        r.raise_for_status()
        mark_submitted([g["id"] for g in games])
        return len(games)
    except (requests.RequestException, ValueError):
        return 0
