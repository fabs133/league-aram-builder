import pytest
import tempfile
from pathlib import Path
from backend.storage.db import (
    init_db, record_game, get_personal_winrate,
    get_all_personal_winrates, get_unsubmitted_games, mark_submitted,
)


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "test_oracle.db"
    init_db(path)
    return path


def test_init_creates_db(db_path):
    assert db_path.exists()


def test_record_game_win_creates_augment_stats(db_path):
    record_game(
        game_id="g1", champion_id="lux",
        augments=["aug1", "aug2"], items=["item1"],
        win=True, game_time_secs=600,
        kda={"kills": 5, "deaths": 2, "assists": 10},
        db_path=db_path,
    )
    wr = get_personal_winrate("lux", "aug1", db_path=db_path)
    assert wr is not None
    assert wr == (1, 1)  # 1 win, 1 game


def test_record_game_none_win_no_augment_stats(db_path):
    record_game(
        game_id="g2", champion_id="lux",
        augments=["aug3"], items=["item1"],
        win=None, game_time_secs=600,
        kda={},
        db_path=db_path,
    )
    wr = get_personal_winrate("lux", "aug3", db_path=db_path)
    assert wr is None


def test_get_personal_winrate_none_for_unknown(db_path):
    wr = get_personal_winrate("lux", "nonexistent", db_path=db_path)
    assert wr is None


def test_personal_winrate_accumulates(db_path):
    record_game("g1", "lux", ["aug1"], [], True, 600, {}, db_path=db_path)
    record_game("g2", "lux", ["aug1"], [], False, 700, {}, db_path=db_path)
    record_game("g3", "lux", ["aug1"], [], True, 800, {}, db_path=db_path)

    wr = get_personal_winrate("lux", "aug1", db_path=db_path)
    assert wr == (2, 3)  # 2 wins, 3 games


def test_duplicate_game_id_no_duplicate_row(db_path):
    record_game("g1", "lux", ["aug1"], [], True, 600, {}, db_path=db_path)
    record_game("g1", "lux", ["aug1"], [], False, 600, {}, db_path=db_path)

    games = get_unsubmitted_games(db_path=db_path)
    game_ids = [g["id"] for g in games]
    assert game_ids.count("g1") == 1


def test_get_all_personal_winrates(db_path):
    record_game("g1", "lux", ["aug1", "aug2"], [], True, 600, {}, db_path=db_path)
    wrs = get_all_personal_winrates("lux", db_path=db_path)
    assert "aug1" in wrs
    assert "aug2" in wrs
    assert wrs["aug1"] == (1, 1)


# -- Error handling tests (corrupt/bad database) --


def test_get_personal_winrate_corrupt_db(tmp_path):
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_text("not a database")
    result = get_personal_winrate("lux", "aug1", db_path=bad_path)
    assert result is None


def test_get_all_personal_winrates_corrupt_db(tmp_path):
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_text("not a database")
    result = get_all_personal_winrates("lux", db_path=bad_path)
    assert result == {}


def test_record_game_corrupt_db_no_crash(tmp_path):
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_text("not a database")
    # Should not raise — just logs the error
    record_game("g1", "lux", ["aug1"], [], True, 600, {}, db_path=bad_path)


def test_get_unsubmitted_games_corrupt_db(tmp_path):
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_text("not a database")
    result = get_unsubmitted_games(db_path=bad_path)
    assert result == []


def test_mark_submitted_corrupt_db_no_crash(tmp_path):
    bad_path = tmp_path / "corrupt.db"
    bad_path.write_text("not a database")
    # Should not raise
    mark_submitted(["g1"], db_path=bad_path)
