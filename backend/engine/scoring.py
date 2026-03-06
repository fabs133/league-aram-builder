import logging

import numpy as np
from backend.models import StatVector, ChampionMeta, AugmentData, ItemData, ScalingSpec
from backend.engine.role_weights import get_role_weights
from backend.engine.scaling import compute_scaling_bonus, compute_scaling_breakdown

logger = logging.getLogger("aram-oracle.engine.scoring")


_scaling_specs: dict[str, list[ScalingSpec]] = {}


def set_scaling_specs(specs: dict[str, list[ScalingSpec]]) -> None:
    global _scaling_specs
    _scaling_specs = specs


def get_scaling_specs(augment_id: str) -> list[ScalingSpec]:
    return _scaling_specs.get(augment_id, [])


def stat_vec(s: StatVector) -> np.ndarray:
    return np.array(s.to_array(), dtype=float)


def _get_champion_vec(champion: ChampionMeta) -> np.ndarray:
    """Champion stat vector with role weights and synergy multipliers applied."""
    vec = stat_vec(champion.stats) * get_role_weights(champion.role)
    if champion.synergy:
        fields = StatVector.fields()
        syn = np.array([champion.synergy.get(f, 1.0) for f in fields], dtype=np.float64)
        vec = vec * syn
    return vec


def score_augment(
    champion: ChampionMeta,
    augment: AugmentData,
    existing_augments: list[AugmentData],
    enemies: list[ChampionMeta] | None = None,
) -> float:
    """
    Score = dot(champion.stats, augment.contribution)
          x tier_multiplier
          + cc_cdr_synergy
          + enemy_comp_cc_modifier
          - overlap_penalty
    """
    champ_vec = _get_champion_vec(champion)
    aug_vec = stat_vec(augment.contribution)

    base = float(np.dot(champ_vec, aug_vec))
    tier_multiplier = {0: 0.8, 1: 1.0, 2: 1.15, 3: 1.35}.get(augment.tier.value, 1.0)

    # Overlap penalty: cosine similarity with each existing augment
    penalty = 0.0
    for existing in existing_augments:
        ev = stat_vec(existing.contribution)
        norm = np.linalg.norm(aug_vec) * np.linalg.norm(ev)
        if norm > 0:
            similarity = float(np.dot(aug_vec, ev)) / norm
            penalty += similarity * 0.1

    score = base * tier_multiplier - penalty

    # Scaling spec bonus for indirect/proc-based augments
    specs = get_scaling_specs(augment.id)
    if specs:
        scaling_bonus = compute_scaling_bonus(specs, champion, champ_vec) * tier_multiplier
        score += scaling_bonus
        logger.debug("%s scaling bonus +%.3f for %s", champion.id, scaling_bonus, augment.name)

    # CC-CDR synergy bonus
    cdr_bonus = _cc_cdr_synergy(champion, augment)
    if cdr_bonus > 0:
        logger.debug("%s CC-CDR synergy +%.3f for %s", champion.id, cdr_bonus, augment.name)
    score += cdr_bonus

    # Enemy comp CC modifier
    if enemies:
        cc_mod = _enemy_comp_cc_modifier(champion, augment, enemies)
        if cc_mod != 0:
            logger.debug("%s enemy CC modifier %+.3f for %s", champion.id, cc_mod, augment.name)
        score += cc_mod

    return score


def _cc_cdr_synergy(champion: ChampionMeta, augment: AugmentData) -> float:
    """
    Extra bonus when an augment provides CDR to a CC-heavy champion.
    More CC abilities with shorter cooldowns = CDR is multiplicatively valuable.
    """
    if champion.cc_profile is None:
        return 0.0
    aug_cdr = augment.contribution.cdr
    cc_uptime = champion.cc_profile.cc_uptime_rating
    return aug_cdr * cc_uptime * 0.15


def _enemy_comp_cc_modifier(
    champion: ChampionMeta,
    augment: AugmentData,
    enemies: list[ChampionMeta],
) -> float:
    """
    CC is more valuable against melee-heavy comps (they must walk into you).
    """
    if not enemies:
        return 0.0

    # Approximate melee-heaviness by average HP weight (tanky = melee)
    avg_enemy_hp = sum(e.stats.hp for e in enemies) / len(enemies)

    # If enemies are tanky/melee, our hard CC is worth more
    cc_bonus = augment.contribution.hard_cc * avg_enemy_hp * 0.1

    return cc_bonus


def score_item(
    champion: ChampionMeta,
    item: ItemData,
    active_augments: list[AugmentData],
) -> float:
    """
    Score = dot(champ_vec + augment_boost, item.stats)
    augment_boost shifts item priority toward augment-synergistic stats.
    """
    champ_vec = _get_champion_vec(champion)

    if active_augments:
        aug_vecs = np.array([stat_vec(a.contribution) for a in active_augments])
        aug_boost = np.mean(aug_vecs, axis=0) * 0.3
    else:
        aug_boost = np.zeros(len(StatVector.fields()))

    effective_vec = champ_vec + aug_boost
    item_vec = stat_vec(item.stats)
    return float(np.dot(effective_vec, item_vec))


def score_breakdown(
    champion: ChampionMeta,
    augment: AugmentData,
) -> dict[str, float]:
    """
    Returns per-stat contribution to score. Used to derive labels and
    explanation strings without any LLM.
    """
    champ_arr = _get_champion_vec(champion)
    aug_arr = stat_vec(augment.contribution)
    fields = StatVector.fields()
    result = {
        field: float(champ_arr[i] * aug_arr[i])
        for i, field in enumerate(fields)
    }

    specs = get_scaling_specs(augment.id)
    if specs:
        scaling_bd = compute_scaling_breakdown(specs, champion, champ_arr)
        for stat, value in scaling_bd.items():
            result[stat] = result.get(stat, 0.0) + value

    return result
