"""Detect which augment the player chose by comparing champion stat deltas."""

from __future__ import annotations

import logging

import numpy as np

from backend.models import AugmentData, StatVector

logger = logging.getLogger("aram-oracle.augment_detector")

# Map StatVector dimensions -> LCDA championStats field names.
# Each dimension may map to multiple LCDA fields (summed).
STAT_MAPPING: dict[str, list[str]] = {
    "ap": ["abilityPower"],
    "ad": ["attackDamage"],
    "attack_speed": ["attackSpeed"],
    "hp": ["maxHealth"],
    "lethality": ["physicalLethality"],
    "pen": ["magicPenetrationFlat", "magicPenetrationPercent"],
    "crit": ["critChance"],
    "cdr": ["cooldownReduction"],
    "heal_power": ["lifeSteal", "spellVamp"],
    "shield": ["armor", "magicResist"],
    # hard_cc, soft_cc have no direct champion stat — excluded
}

# Fields that fluctuate constantly and should be ignored in delta comparison.
VOLATILE_FIELDS = {"currentHealth", "resourceValue"}

# Minimum cosine similarity to consider a match confident.
CONFIDENCE_THRESHOLD = 0.3

# Minimum gap between best and second-best to auto-confirm.
CONFIDENCE_GAP = 0.05

# If the absolute delta magnitude is below this, consider it a zero-stat pick.
ZERO_DELTA_THRESHOLD = 2.0


def compute_stat_delta(
    before: dict[str, float], after: dict[str, float],
) -> dict[str, float]:
    """Compute per-field stat changes, ignoring volatile fields."""
    delta = {}
    for key in after:
        if key in VOLATILE_FIELDS:
            continue
        val_before = before.get(key, 0.0)
        val_after = after.get(key, 0.0)
        diff = val_after - val_before
        if abs(diff) > 0.001:
            delta[key] = diff
    return delta


def _delta_to_vector(delta: dict[str, float]) -> np.ndarray:
    """Convert a raw stat delta dict to a 12D vector aligned with StatVector.fields()."""
    fields = StatVector.fields()
    vec = np.zeros(len(fields), dtype=np.float64)
    for i, field_name in enumerate(fields):
        lcda_keys = STAT_MAPPING.get(field_name)
        if not lcda_keys:
            continue
        for lcda_key in lcda_keys:
            vec[i] += delta.get(lcda_key, 0.0)
    return vec


def _normalize(v: np.ndarray) -> np.ndarray:
    """L2-normalize a vector. Returns zero vector if magnitude is near-zero."""
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-8 else np.zeros_like(v)


def _cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Cosine similarity between two vectors."""
    a_n = _normalize(a)
    b_n = _normalize(b)
    return float(np.dot(a_n, b_n))


def is_zero_stat_augment(augment: AugmentData) -> bool:
    """True if the augment has no stat contribution at all."""
    return all(v == 0.0 for v in augment.contribution.to_array())


def has_stats_changed(before: dict[str, float], after: dict[str, float]) -> bool:
    """Check if champion stats changed enough to indicate an augment was chosen."""
    delta = compute_stat_delta(before, after)
    delta_vec = _delta_to_vector(delta)
    return float(np.linalg.norm(delta_vec)) >= ZERO_DELTA_THRESHOLD


def match_augment(
    before: dict[str, float],
    after: dict[str, float],
    candidates: list[AugmentData],
) -> tuple[AugmentData | None, float]:
    """Determine which candidate augment was chosen based on stat changes.

    Returns (matched_augment, confidence) or (None, 0.0) if ambiguous.
    """
    if not candidates:
        return None, 0.0

    delta = compute_stat_delta(before, after)
    delta_vec = _delta_to_vector(delta)
    delta_magnitude = np.linalg.norm(delta_vec)

    # Zero-stat augment detection (e.g., Donation, Flashy)
    if delta_magnitude < ZERO_DELTA_THRESHOLD:
        zero_stat = [c for c in candidates if is_zero_stat_augment(c)]
        non_zero = [c for c in candidates if not is_zero_stat_augment(c)]
        if len(zero_stat) == 1:
            # Exactly one zero-stat candidate — must be the one chosen
            return zero_stat[0], 0.7
        if len(zero_stat) > 1:
            # Multiple zero-stat candidates — stat delta can't distinguish.
            # Return the first as a low-confidence guess so the confirm panel
            # can highlight it, rather than showing no guess at all.
            logger.info(
                "Multiple zero-stat candidates (%s) — returning low-confidence guess",
                [c.name for c in zero_stat],
            )
            return zero_stat[0], 0.15
        # All candidates have stats in our data but LCDA stats didn't change.
        # The chosen augment likely has a non-stat effect (e.g., "Dashing").
        # Pick the candidate with the smallest expected stat magnitude as a
        # low-confidence guess so the confirm panel can show it.
        smallest = min(
            candidates,
            key=lambda c: float(np.linalg.norm(c.contribution.to_array())),
        )
        logger.info(
            "Zero delta but no zero-stat candidates — lowest-magnitude guess: %s (norm=%.3f)",
            smallest.name,
            float(np.linalg.norm(smallest.contribution.to_array())),
        )
        return smallest, 0.15

    # Cosine similarity matching
    scores: list[tuple[AugmentData, float]] = []
    for candidate in candidates:
        contrib_vec = np.array(candidate.contribution.to_array(), dtype=np.float64)
        sim = _cosine_similarity(delta_vec, contrib_vec)
        scores.append((candidate, sim))

    scores.sort(key=lambda x: x[1], reverse=True)
    best, best_score = scores[0]
    second_score = scores[1][1] if len(scores) > 1 else 0.0

    # Log borderline cases for data collection
    if 0.25 <= best_score < 0.4:
        logger.info(
            "BORDERLINE confidence: best=%s (%.3f), second=%.3f, "
            "delta_magnitude=%.2f, delta_fields=%s",
            best.name, best_score, second_score,
            float(delta_magnitude),
            {k: round(v, 2) for k, v in delta.items()},
        )

    # Read thresholds from config (with fallback to module constants)
    try:
        from backend.config import config
        conf_threshold = config.get("confidence_threshold", CONFIDENCE_THRESHOLD)
        conf_gap = config.get("confidence_gap", CONFIDENCE_GAP)
    except Exception:
        conf_threshold = CONFIDENCE_THRESHOLD
        conf_gap = CONFIDENCE_GAP

    # Confident match
    if best_score >= conf_threshold and (best_score - second_score) >= conf_gap:
        return best, best_score

    # Ambiguous
    return None, best_score
