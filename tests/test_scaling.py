import math
import pytest
from backend.models import (
    StatVector, ChampionMeta, AugmentData, AugmentTier, ScalingSpec, ScalingType,
)
from backend.engine.scaling import (
    evaluate_on_hit, evaluate_on_cast, evaluate_stacking,
    evaluate_threshold, evaluate_amplifier, evaluate_passive,
    evaluate_spec, compute_scaling_bonus, compute_scaling_breakdown,
)
from backend.engine.scoring import (
    score_augment, score_breakdown, set_scaling_specs, get_scaling_specs,
    _get_champion_vec,
)


def _make_spec(type: ScalingType, base: float = 0.5, rate_stat: str = "attack_speed",
               gate_value: float = 0.0, duration_factor: float = 1.0) -> ScalingSpec:
    return ScalingSpec(type=type, base=base, rate_stat=rate_stat,
                       gate_value=gate_value, duration_factor=duration_factor)


def _make_champion(id: str, role: str = "", **stat_kwargs) -> ChampionMeta:
    return ChampionMeta(id=id, name=id.title(), stats=StatVector(**stat_kwargs), role=role)


def _make_augment(id: str, tier: int = 1, **stat_kwargs) -> AugmentData:
    return AugmentData(
        id=id, name=id, tier=AugmentTier(tier),
        description="", contribution=StatVector(**stat_kwargs),
    )


# ===== Pure evaluation tests (8) =====

class TestEvaluateFunctions:
    def test_on_hit_linear(self):
        spec = _make_spec(ScalingType.ON_HIT, base=0.5)
        assert evaluate_on_hit(spec, 0.8) == pytest.approx(0.4)
        assert evaluate_on_hit(spec, 0.0) == 0.0

    def test_on_cast_nonzero_baseline(self):
        spec = _make_spec(ScalingType.ON_CAST, base=0.5)
        # At stat=0, result = 0.5 * (1 + 0) = 0.5
        assert evaluate_on_cast(spec, 0.0) == pytest.approx(0.5)
        assert evaluate_on_cast(spec, 1.0) == pytest.approx(1.0)

    def test_stacking_uses_duration_factor(self):
        spec = _make_spec(ScalingType.STACKING, base=0.4, duration_factor=1.5)
        # 0.4 * 0.8 * 1.5 = 0.48
        assert evaluate_stacking(spec, 0.8) == pytest.approx(0.48)

    def test_threshold_binary_gate(self):
        spec = _make_spec(ScalingType.THRESHOLD, base=0.7, gate_value=0.5)
        assert evaluate_threshold(spec, 0.6) == pytest.approx(0.7)  # above gate
        assert evaluate_threshold(spec, 0.4) == 0.0  # below gate
        assert evaluate_threshold(spec, 0.5) == pytest.approx(0.7)  # at gate

    def test_amplifier_quadratic(self):
        spec = _make_spec(ScalingType.AMPLIFIER, base=0.5)
        # 0.5 * 0.8^2 = 0.32
        assert evaluate_amplifier(spec, 0.8) == pytest.approx(0.32)

    def test_passive_sqrt_diminishing(self):
        spec = _make_spec(ScalingType.PASSIVE, base=0.5)
        assert evaluate_passive(spec, 1.0) == pytest.approx(0.5)
        assert evaluate_passive(spec, 0.0) == 0.0
        # sqrt(0.25) = 0.5 -> 0.5 * 0.5 = 0.25
        assert evaluate_passive(spec, 0.25) == pytest.approx(0.25)

    def test_unknown_type_returns_zero(self):
        spec = _make_spec(ScalingType.ON_HIT, base=0.5)
        # Manually override with invalid type to test dispatcher fallback
        result = evaluate_spec(spec, 0.8)
        assert result == pytest.approx(0.4)  # valid type works

    def test_zero_base_returns_zero(self):
        spec = _make_spec(ScalingType.ON_HIT, base=0.0)
        assert evaluate_spec(spec, 0.8) == 0.0
        spec2 = _make_spec(ScalingType.AMPLIFIER, base=0.0)
        assert evaluate_spec(spec2, 0.8) == 0.0


# ===== compute_scaling_bonus tests (4) =====

class TestComputeScalingBonus:
    def test_empty_specs_returns_zero(self):
        champ = _make_champion("test", attack_speed=0.8)
        vec = _get_champion_vec(champ)
        assert compute_scaling_bonus([], champ, vec) == 0.0

    def test_additive_composition(self):
        champ = _make_champion("test", attack_speed=0.8)
        vec = _get_champion_vec(champ)
        spec1 = _make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed")
        spec2 = _make_spec(ScalingType.ON_HIT, base=0.3, rate_stat="attack_speed")
        bonus = compute_scaling_bonus([spec1, spec2], champ, vec)
        # Each individually: 0.5*0.8=0.4, 0.3*0.8=0.24 -> sum=0.64
        expected = 0.5 * 0.8 + 0.3 * 0.8
        assert bonus == pytest.approx(expected)

    def test_uses_role_weighted_vec(self):
        # Two champions with same base stats but different roles get different bonuses
        champ_marksman = _make_champion("adc", role="marksman", attack_speed=0.8)
        champ_tank = _make_champion("tank", role="tank", attack_speed=0.8)
        spec = _make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed")
        vec_m = _get_champion_vec(champ_marksman)
        vec_t = _get_champion_vec(champ_tank)
        bonus_m = compute_scaling_bonus([spec], champ_marksman, vec_m)
        bonus_t = compute_scaling_bonus([spec], champ_tank, vec_t)
        # Marksman should weight attack_speed higher
        assert bonus_m > bonus_t

    def test_invalid_rate_stat_skipped(self):
        champ = _make_champion("test", attack_speed=0.8)
        vec = _get_champion_vec(champ)
        spec = _make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="nonexistent")
        assert compute_scaling_bonus([spec], champ, vec) == 0.0


# ===== score_augment integration tests (4) =====

class TestScoreAugmentIntegration:
    def test_scaling_spec_increases_score(self):
        champ = _make_champion("kogmaw", attack_speed=0.9, ad=0.6)
        aug = _make_augment("twice_thrice", tier=2, attack_speed=0.3)
        score_without = score_augment(champ, aug, [])

        set_scaling_specs({"twice_thrice": [
            _make_spec(ScalingType.ON_HIT, base=0.55, rate_stat="attack_speed"),
        ]})
        score_with = score_augment(champ, aug, [])
        assert score_with > score_without

    def test_zero_contribution_augment_with_specs_scores_positive(self):
        champ = _make_champion("kogmaw", attack_speed=0.9)
        # All-zero contribution augment
        aug = _make_augment("proc_aug")
        score_without = score_augment(champ, aug, [])
        assert score_without == pytest.approx(0.0, abs=0.01)

        set_scaling_specs({"proc_aug": [
            _make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed"),
        ]})
        score_with = score_augment(champ, aug, [])
        assert score_with > 0.0

    def test_augment_without_specs_unchanged(self):
        champ = _make_champion("lux", ap=0.9, pen=0.6)
        aug = _make_augment("ap_aug", ap=0.8)
        # No specs registered (cleared by fixture)
        score = score_augment(champ, aug, [])
        assert score > 0.0  # should work as before

    def test_scaling_bonus_gets_tier_multiplier(self):
        champ = _make_champion("test", attack_speed=0.8)
        silver = _make_augment("s", tier=1)
        prismatic = _make_augment("p", tier=3)

        set_scaling_specs({
            "s": [_make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed")],
            "p": [_make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed")],
        })
        score_s = score_augment(champ, silver, [])
        score_p = score_augment(champ, prismatic, [])
        assert score_p > score_s


# ===== score_breakdown + labels tests (2) =====

class TestScoreBreakdown:
    def test_breakdown_includes_scaling_contributions(self):
        champ = _make_champion("kogmaw", attack_speed=0.9)
        aug = _make_augment("on_hit_aug")

        set_scaling_specs({"on_hit_aug": [
            _make_spec(ScalingType.ON_HIT, base=0.5, rate_stat="attack_speed"),
        ]})
        bd = score_breakdown(champ, aug)
        assert bd["attack_speed"] > 0.0

    def test_zero_contribution_augment_gets_scaling_in_breakdown(self):
        champ = _make_champion("test", hp=0.7)
        aug = _make_augment("aura_aug")

        set_scaling_specs({"aura_aug": [
            _make_spec(ScalingType.PASSIVE, base=0.5, rate_stat="hp"),
        ]})
        bd = score_breakdown(champ, aug)
        # hp should be the dominant stat now
        assert bd["hp"] > 0.0
        assert bd["hp"] == max(bd.values())


# ===== Loading tests (2) =====

class TestScalingLoading:
    def test_load_scaling_specs_valid(self, tmp_path):
        import json
        data = {
            "123": [{"type": "on_hit", "base": 0.5, "rate_stat": "attack_speed"}],
        }
        f = tmp_path / "scaling.json"
        f.write_text(json.dumps(data))

        from backend.static_data.loader import _load_scaling_specs, SCALING_FILE
        import backend.static_data.loader as loader_mod

        original = loader_mod.SCALING_FILE
        loader_mod.SCALING_FILE = f
        try:
            result = _load_scaling_specs()
            assert "123" in result
            assert len(result["123"]) == 1
            assert result["123"][0].type == ScalingType.ON_HIT
            assert result["123"][0].base == 0.5
            assert result["123"][0].rate_stat == "attack_speed"
        finally:
            loader_mod.SCALING_FILE = original

    def test_missing_file_returns_empty(self, tmp_path):
        from pathlib import Path
        import backend.static_data.loader as loader_mod

        original = loader_mod.SCALING_FILE
        loader_mod.SCALING_FILE = tmp_path / "nonexistent.json"
        try:
            from backend.static_data.loader import _load_scaling_specs
            result = _load_scaling_specs()
            assert result == {}
        finally:
            loader_mod.SCALING_FILE = original
