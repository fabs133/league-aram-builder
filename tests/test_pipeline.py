import pytest
from unittest.mock import patch
from backend.models import (
    StatVector, ChampionMeta, AugmentData, AugmentTier, ItemData,
    GameSnapshot, GamePhase, CCProfile,
)
from backend.static_data.loader import StaticData
from backend.workflow.pipeline import Pipeline


def _make_champion(id: str, **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs))


def _make_augment(id: str, tier: int = 1, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier(tier),
        description="", contribution=StatVector(**stat_kwargs),
    )


def _make_item(id: str, cost: int = 3000, **stat_kwargs) -> ItemData:
    return ItemData(id=id, name=id, cost=cost, stats=StatVector(**stat_kwargs))


@pytest.fixture
def static_data():
    sd = StaticData()
    sd._champions = {
        "lux": _make_champion("lux", ap=0.9, pen=0.6, cdr=0.7),
    }
    sd._augments = {
        "a1": _make_augment("a1", ap=0.8),
        "a2": _make_augment("a2", pen=0.5),
        "a3": _make_augment("a3", cdr=0.6),
    }
    sd._items = {
        "i1": _make_item("i1", cost=3000, ap=0.8),
        "i2": _make_item("i2", cost=2000, pen=0.5),
    }
    return sd


@pytest.fixture
def pipeline(static_data):
    return Pipeline(static_data)


def _make_snapshot(champion_id="lux", augment_choices=None, purchased_items=None):
    return GameSnapshot(
        game_id="test-1",
        phase=GamePhase.AUG_PICK_1,
        champion_id=champion_id,
        augment_choices=augment_choices or ["a1", "a2", "a3"],
        chosen_augments=[],
        purchased_items=purchased_items or [],
        current_gold=5000,
        game_time=300.0,
        enemy_champion_ids=[],
    )


@patch("backend.workflow.pipeline.get_all_personal_winrates", return_value={})
def test_pipeline_returns_result_with_3_recs(mock_wr, pipeline):
    snap = _make_snapshot()
    result = pipeline.run(snap)
    assert result is not None
    assert len(result.recommendations) == 3


@patch("backend.workflow.pipeline.get_all_personal_winrates", return_value={})
def test_pipeline_recs_sorted_descending(mock_wr, pipeline):
    snap = _make_snapshot()
    result = pipeline.run(snap)
    scores = [r.score for r in result.recommendations]
    assert scores == sorted(scores, reverse=True)


@patch("backend.workflow.pipeline.get_all_personal_winrates", return_value={})
def test_pipeline_unknown_champion_returns_none(mock_wr, pipeline):
    snap = _make_snapshot(champion_id="unknown_champ")
    result = pipeline.run(snap)
    assert result is None


@patch("backend.workflow.pipeline.get_all_personal_winrates", return_value={})
def test_pipeline_build_state_matches_snapshot(mock_wr, pipeline):
    snap = _make_snapshot(purchased_items=["i1"])
    result = pipeline.run(snap)
    assert result.build_state.purchased_items == ["i1"]
