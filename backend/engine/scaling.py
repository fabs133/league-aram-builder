import math
from backend.models import ScalingSpec, ScalingType, StatVector, ChampionMeta
import numpy as np


def evaluate_on_hit(spec: ScalingSpec, stat: float) -> float:
    return spec.base * stat


def evaluate_on_cast(spec: ScalingSpec, stat: float) -> float:
    return spec.base * (1 + stat)


def evaluate_stacking(spec: ScalingSpec, stat: float) -> float:
    return spec.base * stat * spec.duration_factor


def evaluate_threshold(spec: ScalingSpec, stat: float) -> float:
    return spec.base if stat >= spec.gate_value else 0.0


def evaluate_amplifier(spec: ScalingSpec, stat: float) -> float:
    # Clamp stat to 3.0 to prevent quadratic explosion on high values
    clamped = min(stat, 3.0)
    return spec.base * clamped * clamped


def evaluate_passive(spec: ScalingSpec, stat: float) -> float:
    return spec.base * math.sqrt(stat) if stat > 0 else 0.0


_EVALUATORS = {
    ScalingType.ON_HIT: evaluate_on_hit,
    ScalingType.ON_CAST: evaluate_on_cast,
    ScalingType.STACKING: evaluate_stacking,
    ScalingType.THRESHOLD: evaluate_threshold,
    ScalingType.AMPLIFIER: evaluate_amplifier,
    ScalingType.PASSIVE: evaluate_passive,
}


def evaluate_spec(spec: ScalingSpec, stat: float) -> float:
    evaluator = _EVALUATORS.get(spec.type)
    if evaluator is None:
        return 0.0
    return evaluator(spec, stat)


def _get_stat_value(rate_stat: str, role_weighted_vec: np.ndarray) -> float | None:
    fields = StatVector.fields()
    if rate_stat not in fields:
        return None
    idx = fields.index(rate_stat)
    return float(role_weighted_vec[idx])


def compute_scaling_bonus(
    specs: list[ScalingSpec],
    champion: ChampionMeta,
    role_weighted_vec: np.ndarray,
) -> float:
    total = 0.0
    for spec in specs:
        stat = _get_stat_value(spec.rate_stat, role_weighted_vec)
        if stat is None:
            continue
        total += evaluate_spec(spec, stat)
    return total


def compute_scaling_breakdown(
    specs: list[ScalingSpec],
    champion: ChampionMeta,
    role_weighted_vec: np.ndarray,
) -> dict[str, float]:
    result: dict[str, float] = {}
    for spec in specs:
        stat = _get_stat_value(spec.rate_stat, role_weighted_vec)
        if stat is None:
            continue
        value = evaluate_spec(spec, stat)
        result[spec.rate_stat] = result.get(spec.rate_stat, 0.0) + value
    return result
