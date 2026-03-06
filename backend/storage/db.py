import json
import logging
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

logger = logging.getLogger("aram-oracle.db")

DB_PATH = Path.home() / ".aram-oracle" / "oracle.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS games (
    id              TEXT PRIMARY KEY,
    champion_id     TEXT NOT NULL,
    augments        TEXT NOT NULL,
    items           TEXT NOT NULL,
    win             INTEGER,
    game_time_secs  INTEGER,
    kills           INTEGER DEFAULT 0,
    deaths          INTEGER DEFAULT 0,
    assists         INTEGER DEFAULT 0,
    played_at       TEXT NOT NULL,
    submitted       INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS augment_stats (
    augment_id  TEXT NOT NULL,
    champion_id TEXT NOT NULL,
    games       INTEGER DEFAULT 0,
    wins        INTEGER DEFAULT 0,
    PRIMARY KEY (augment_id, champion_id)
);
"""


def init_db(db_path: Path | None = None) -> None:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with _connect(path) as con:
            con.executescript(SCHEMA)
    except sqlite3.Error as e:
        logger.error("Failed to initialize database at %s: %s", path, e, exc_info=True)


def record_game(
    game_id: str,
    champion_id: str,
    augments: list[str],
    items: list[str],
    win: bool | None,
    game_time_secs: int,
    kda: dict,
    db_path: Path | None = None,
) -> None:
    path = db_path or DB_PATH
    try:
        with _connect(path) as con:
            con.execute(
                """INSERT OR REPLACE INTO games
                   VALUES (?,?,?,?,?,?,?,?,?,?,0)""",
                (
                    game_id, champion_id,
                    json.dumps(augments), json.dumps(items),
                    int(win) if win is not None else None,
                    game_time_secs,
                    kda.get("kills", 0),
                    kda.get("deaths", 0),
                    kda.get("assists", 0),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            if win is not None:
                for aug_id in augments:
                    con.execute("""
                        INSERT INTO augment_stats (augment_id, champion_id, games, wins)
                        VALUES (?, ?, 1, ?)
                        ON CONFLICT(augment_id, champion_id) DO UPDATE SET
                            games = games + 1,
                            wins  = wins  + excluded.wins
                    """, (aug_id, champion_id, int(win)))
    except sqlite3.Error as e:
        logger.error("Failed to record game %s: %s", game_id, e, exc_info=True)


def get_personal_winrate(
    champion_id: str, augment_id: str, db_path: Path | None = None,
) -> tuple[int, int] | None:
    """Returns (wins, games) or None if no data."""
    path = db_path or DB_PATH
    try:
        with _connect(path) as con:
            row = con.execute(
                """SELECT wins, games FROM augment_stats
                   WHERE augment_id=? AND champion_id=?""",
                (augment_id, champion_id),
            ).fetchone()
        return (row[0], row[1]) if row else None
    except sqlite3.Error as e:
        logger.error("Failed to get winrate for %s/%s: %s", champion_id, augment_id, e)
        return None


def get_all_personal_winrates(
    champion_id: str, db_path: Path | None = None,
) -> dict[str, tuple[int, int]]:
    """Returns {augment_id: (wins, games)} for all augments on a champion."""
    path = db_path or DB_PATH
    try:
        with _connect(path) as con:
            rows = con.execute(
                "SELECT augment_id, wins, games FROM augment_stats WHERE champion_id=?",
                (champion_id,),
            ).fetchall()
        return {row[0]: (row[1], row[2]) for row in rows}
    except sqlite3.Error as e:
        logger.error("Failed to get winrates for %s: %s", champion_id, e)
        return {}


def get_unsubmitted_games(db_path: Path | None = None) -> list[dict]:
    path = db_path or DB_PATH
    try:
        with _connect(path) as con:
            rows = con.execute(
                "SELECT * FROM games WHERE submitted=0 AND win IS NOT NULL"
            ).fetchall()
        columns = [
            "id", "champion_id", "augments", "items", "win", "game_time_secs",
            "kills", "deaths", "assists", "played_at", "submitted",
        ]
        return [dict(zip(columns, row)) for row in rows]
    except sqlite3.Error as e:
        logger.error("Failed to get unsubmitted games: %s", e)
        return []


def mark_submitted(game_ids: list[str], db_path: Path | None = None) -> None:
    path = db_path or DB_PATH
    try:
        with _connect(path) as con:
            con.executemany(
                "UPDATE games SET submitted=1 WHERE id=?",
                [(gid,) for gid in game_ids],
            )
    except sqlite3.Error as e:
        logger.error("Failed to mark games submitted: %s", e)


def _connect(db_path: Path | None = None) -> sqlite3.Connection:
    path = db_path or DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    return sqlite3.connect(path)
