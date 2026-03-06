import pytest
from backend.models import (
    StatVector, ChampionMeta, AugmentData, AugmentTier, ItemData, CCProfile, CCAbility,
)
from backend.engine.scoring import (
    score_augment, score_item, score_breakdown, stat_vec,
    _cc_cdr_synergy,
)


def _make_champion(id: str, **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs))


def _make_champion_with_cc(id: str, cc_uptime: float, **stat_kwargs) -> ChampionMeta:
    cc_profile = CCProfile(
        abilities=[],
        total_hard_cc_sec=2.0,
        total_soft_cc_sec=1.0,
        cc_uptime_rating=cc_uptime,
    )
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs), cc_profile=cc_profile)


def _make_augment(id: str, tier: int = 1, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier(tier),
        description="", contribution=StatVector(**stat_kwargs),
    )


def _make_item(id: str, cost: int = 3000, **stat_kwargs) -> ItemData:
    return ItemData(id=id, name=id, cost=cost, stats=StatVector(**stat_kwargs))


# --- StatVector tests ---

def test_stat_vector_to_array_length():
    assert len(StatVector().to_array()) == 12


def test_stat_vector_fields_length():
    assert len(StatVector.fields()) == 12


def test_stat_vector_to_array_all_zero():
    assert all(v == 0.0 for v in StatVector().to_array())


def test_stat_vector_fields_match_to_array_order():
    sv = StatVector(ap=1, ad=2, attack_speed=3, hp=4, lethality=5,
                    pen=6, crit=7, cdr=8, heal_power=9,
                    hard_cc=10, soft_cc=11, shield=12)
    arr = sv.to_array()
    fields = StatVector.fields()
    for i, f in enumerate(fields):
        assert arr[i] == getattr(sv, f)


# --- score_augment tests ---

def test_ap_augment_scores_higher_on_lux_than_ad():
    lux = _make_champion("lux", ap=0.9, cdr=0.7, pen=0.6)
    ap_aug = _make_augment("ap_aug", ap=0.8, pen=0.3)
    ad_aug = _make_augment("ad_aug", ad=0.8, lethality=0.3)
    assert score_augment(lux, ap_aug, []) > score_augment(lux, ad_aug, [])


def test_prismatic_scores_higher_than_silver():
    lux = _make_champion("lux", ap=0.9)
    silver = _make_augment("s", tier=1, ap=0.5)
    prismatic = _make_augment("p", tier=3, ap=0.5)
    assert score_augment(lux, prismatic, []) > score_augment(lux, silver, [])


def test_overlap_penalty_reduces_score():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    aug = _make_augment("new", ap=0.8)
    existing1 = _make_augment("e1", ap=0.9)
    existing2 = _make_augment("e2", ap=0.7)

    score_no_existing = score_augment(lux, aug, [])
    score_with_existing = score_augment(lux, aug, [existing1, existing2])
    assert score_no_existing > score_with_existing


def test_score_breakdown_values_nonnegative():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    aug = _make_augment("a", ap=0.5, pen=0.3)
    breakdown = score_breakdown(lux, aug)
    assert all(v >= 0 for v in breakdown.values())


def test_score_breakdown_sum_within_tolerance():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    aug = _make_augment("a", ap=0.5, pen=0.3)
    breakdown = score_breakdown(lux, aug)
    # breakdown sum should equal base dot product (before tier/penalty)
    total = sum(breakdown.values())
    base = score_augment(lux, aug, [])  # tier=1 so multiplier=1.0, no penalty, no CC bonus
    assert abs(total - base) < 0.1  # within tolerance (CC synergy adds small amount)


# --- score_item tests ---

def test_ap_item_scores_higher_than_hp_item_on_lux():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    ap_item = _make_item("ap_item", ap=0.8)
    hp_item = _make_item("hp_item", hp=0.8)
    assert score_item(lux, ap_item, []) > score_item(lux, hp_item, [])


# --- CC-CDR synergy tests ---

def test_cc_cdr_synergy_higher_for_cc_heavy_champion():
    thresh = _make_champion_with_cc("thresh", cc_uptime=0.45, hard_cc=0.8, cdr=0.7)
    jinx = _make_champion_with_cc("jinx", cc_uptime=0.15, crit=0.9, ad=0.8)
    cdr_aug = _make_augment("cdr_aug", cdr=0.8)

    thresh_synergy = _cc_cdr_synergy(thresh, cdr_aug)
    jinx_synergy = _cc_cdr_synergy(jinx, cdr_aug)
    assert thresh_synergy > jinx_synergy


def test_cc_cdr_synergy_zero_without_cdr():
    thresh = _make_champion_with_cc("thresh", cc_uptime=0.45, hard_cc=0.8)
    no_cdr_aug = _make_augment("no_cdr", ap=0.5)
    assert _cc_cdr_synergy(thresh, no_cdr_aug) == 0.0


def test_cdr_augment_scores_higher_on_thresh_than_jinx():
    thresh = _make_champion_with_cc("thresh", cc_uptime=0.45, hard_cc=0.8, cdr=0.7)
    jinx = _make_champion_with_cc("jinx", cc_uptime=0.15, crit=0.9, ad=0.8, cdr=0.2)
    cdr_aug = _make_augment("cdr_aug", cdr=0.8)

    assert score_augment(thresh, cdr_aug, []) > score_augment(jinx, cdr_aug, [])
