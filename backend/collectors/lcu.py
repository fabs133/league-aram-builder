from pathlib import Path
import requests


def _find_lockfile() -> Path | None:
    """Locate the League Client lockfile on Windows or macOS."""
    candidates = [
        Path("C:/Riot Games/League of Legends/lockfile"),
        Path.home() / "Library/Application Support/Riot Games/League of Legends/lockfile",
    ]
    for path in candidates:
        if path.exists():
            return path
    return None


def _parse_lockfile(path: Path) -> dict:
    parts = path.read_text().strip().split(":")
    return {
        "process": parts[0],
        "pid": parts[1],
        "port": parts[2],
        "password": parts[3],
        "protocol": parts[4],
    }


def get_lcu_session() -> requests.Session | None:
    """Returns an authenticated requests.Session for the LCU or None if client not running."""
    lockfile = _find_lockfile()
    if not lockfile:
        return None
    info = _parse_lockfile(lockfile)
    session = requests.Session()
    session.verify = False
    session.auth = ("riot", info["password"])
    session.base_url = f"https://127.0.0.1:{info['port']}"
    return session


def get_champ_select_session(lcu: requests.Session) -> dict | None:
    """Returns current champ select session data or None if not in champ select."""
    try:
        r = lcu.get(f"{lcu.base_url}/lol-champ-select/v1/session", timeout=1)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


def parse_bench_champions(session_data: dict) -> list[str]:
    """Extract bench champion IDs available for swapping."""
    return [
        str(c.get("championId"))
        for c in session_data.get("benchChampions", [])
    ]


def parse_team_champions(session_data: dict) -> list[str]:
    """Extract the 5 champion IDs on the local team."""
    return [
        str(a.get("championId"))
        for a in session_data.get("myTeam", [])
        if a.get("championId", 0) != 0
    ]
