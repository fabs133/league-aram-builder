import pytest
from backend.models import StatVector, ChampionMeta, AugmentData, AugmentTier, CCProfile
from backend.engine.label import derive_label, derive_explanation


def _make_champion(id: str, **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs))


def _make_augment(id: str, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier.SILVER,
        description="", contribution=StatVector(**stat_kwargs),
    )


def test_magic_label_for_ap_augment_on_lux():
    lux = _make_champion("lux", ap=0.9, pen=0.6, cdr=0.7)
    ap_aug = _make_augment("ap", ap=0.8, pen=0.3)
    label = derive_label(lux, ap_aug)
    assert label[0] == "Magic"


def test_heals_label_for_heal_augment_on_soraka():
    soraka = _make_champion("soraka", heal_power=1.0, cdr=0.8, ap=0.5)
    heal_aug = _make_augment("heal", heal_power=0.9, cdr=0.3)
    label = derive_label(soraka, heal_aug)
    assert label[0] == "Heals"


def test_zero_contribution_returns_utility_mixed():
    garen = _make_champion("garen", hp=0.9, ad=0.5)
    zero_aug = _make_augment("zero")  # all stats 0
    label = derive_label(garen, zero_aug)
    assert label == ("Utility", "Mixed")


def test_kayle_as_ap_augment_has_speed_or_magic():
    kayle = _make_champion("kayle", ap=0.7, attack_speed=0.8, ad=0.5)
    as_ap_aug = _make_augment("as_ap", attack_speed=0.6, ap=0.5)
    label = derive_label(kayle, as_ap_aug)
    assert label[0] in ("Speed", "Magic") or label[1] in ("Speed", "Magic")


def test_lockdown_label_for_cc_augment_on_thresh():
    thresh = _make_champion("thresh", hard_cc=0.8, cdr=0.7, shield=0.4)
    cc_aug = _make_augment("cc", hard_cc=0.9, cdr=0.2)
    label = derive_label(thresh, cc_aug)
    assert label[0] == "Lockdown"


def test_protect_label_for_shield_augment():
    thresh = _make_champion("thresh", shield=0.4, hard_cc=0.1)
    shield_aug = _make_augment("shield", shield=0.9)
    label = derive_label(thresh, shield_aug)
    assert "Protect" in label


def test_derive_explanation_returns_string():
    lux = _make_champion("lux", ap=0.9, pen=0.6)
    ap_aug = _make_augment("ap", ap=0.8, pen=0.3)
    explanation = derive_explanation(lux, ap_aug)
    assert isinstance(explanation, str)
    assert len(explanation) > 0


def test_derive_explanation_low_synergy():
    garen = _make_champion("garen", hp=0.9, ad=0.5)
    zero_aug = _make_augment("zero")
    explanation = derive_explanation(garen, zero_aug)
    assert "Low synergy" in explanation
