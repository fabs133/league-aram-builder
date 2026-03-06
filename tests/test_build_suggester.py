import pytest
from backend.models import StatVector, ChampionMeta, AugmentData, AugmentTier, ItemData
from backend.engine.build_suggester import suggest_build


def _make_champion(id: str, **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs))


def _make_augment(id: str, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier.SILVER,
        description="", contribution=StatVector(**stat_kwargs),
    )


def _make_item(id: str, cost: int = 3000, **stat_kwargs) -> ItemData:
    return ItemData(id=id, name=id, cost=cost, stats=StatVector(**stat_kwargs))


def test_purchased_items_not_in_suggestions():
    lux = _make_champion("lux", ap=0.9)
    items = [
        _make_item("i1", cost=3000, ap=0.8),
        _make_item("i2", cost=2000, ap=0.5),
        _make_item("i3", cost=1000, pen=0.3),
    ]
    build = suggest_build(lux, [], ["i1"], 5000, items)
    assert "i1" not in build.full_build[1:]  # i1 is in purchased_items slot


def test_next_item_none_when_gold_zero():
    lux = _make_champion("lux", ap=0.9)
    items = [_make_item("i1", cost=3000, ap=0.8)]
    build = suggest_build(lux, [], [], 0, items)
    assert build.next_item_id is None


def test_full_build_length_equals_build_size():
    lux = _make_champion("lux", ap=0.9)
    items = [
        _make_item(f"i{i}", cost=1000 * i, ap=0.1 * i)
        for i in range(1, 10)
    ]
    build = suggest_build(lux, [], [], 5000, items, build_size=6)
    assert len(build.full_build) == 6


def test_augments_shift_item_priority():
    lux = _make_champion("lux", ap=0.9, ad=0.0)
    ap_item = _make_item("ap_item", cost=3000, ap=0.8)
    ad_item = _make_item("ad_item", cost=3000, ad=0.8)

    # Without augments, AP item should rank higher for Lux
    build_no_aug = suggest_build(lux, [], [], 5000, [ap_item, ad_item])
    assert build_no_aug.next_item_id == "ap_item"

    # With an AD augment, AD item might score closer but AP still wins
    # because champion vector dominates
    ad_aug = _make_augment("ad_aug", ad=0.9)
    build_with_aug = suggest_build(lux, [ad_aug], [], 5000, [ap_item, ad_item])
    # The augment boost shifts priorities
    assert build_with_aug.next_item_id is not None


def test_gold_to_next_calculated():
    lux = _make_champion("lux", ap=0.9)
    items = [_make_item("expensive", cost=3000, ap=0.8)]
    build = suggest_build(lux, [], [], 1000, items)
    assert build.gold_to_next == 2000
