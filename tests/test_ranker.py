import pytest
from backend.models import (
    StatVector, ChampionMeta, AugmentData, AugmentTier, ItemData, CCProfile,
)
from backend.engine.ranker import rank_augments, should_reroll


def _make_champion(id: str, **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs))


def _make_augment(id: str, tier: int = 1, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier(tier),
        description="", contribution=StatVector(**stat_kwargs),
    )


def _make_item(id: str, cost: int = 3000, **stat_kwargs) -> ItemData:
    return ItemData(id=id, name=id, cost=cost, stats=StatVector(**stat_kwargs))


def test_rank_augments_sorted_descending():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    choices = [
        _make_augment("low", ap=0.1),
        _make_augment("high", ap=0.9),
        _make_augment("mid", ap=0.5),
    ]
    items = [_make_item("i1", ap=0.5)]

    recs = rank_augments(lux, choices, [], items)
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)


def test_should_reroll_true_when_scores_low():
    lux = _make_champion("lux", ap=0.9, pen=0.6, cdr=0.7)
    # All augments are bad fits (AD-only for an AP champion)
    choices = [
        _make_augment("bad1", ad=0.1),
        _make_augment("bad2", lethality=0.1),
        _make_augment("bad3", crit=0.05),
    ]
    items = [_make_item("i1")]

    recs = rank_augments(lux, choices, [], items)
    reroll, reason = should_reroll(recs, lux, [])
    assert reroll is True
    assert "rerolling" in reason.lower()


def test_should_reroll_false_when_scores_high():
    lux = _make_champion("lux", ap=0.9, pen=0.6, cdr=0.7)
    choices = [
        _make_augment("great", ap=0.9, pen=0.8, cdr=0.6),
    ]
    items = [_make_item("i1")]

    recs = rank_augments(lux, choices, [], items)
    reroll, reason = should_reroll(recs, lux, [])
    assert reroll is False


def test_personal_winrate_applied_when_enough_games():
    lux = _make_champion("lux", ap=0.9)
    aug_a = _make_augment("a", ap=0.5)
    aug_b = _make_augment("b", ap=0.5)
    items = [_make_item("i1")]

    # aug_b has 80% winrate over 10 games
    winrates = {"b": (8, 10)}
    recs = rank_augments(lux, [aug_a, aug_b], [], items, personal_winrates=winrates)

    # aug_b should be ranked higher due to winrate bonus
    assert recs[0].augment_id == "b"


def test_personal_winrate_not_applied_when_few_games():
    lux = _make_champion("lux", ap=0.9)
    aug_a = _make_augment("a", ap=0.5)
    aug_b = _make_augment("b", ap=0.5)
    items = [_make_item("i1")]

    # aug_b has data but only 3 games (below threshold of 5)
    winrates = {"b": (3, 3)}
    recs = rank_augments(lux, [aug_a, aug_b], [], items, personal_winrates=winrates)

    # Both should have equal scores (winrate not applied)
    assert abs(recs[0].score - recs[1].score) < 0.01
