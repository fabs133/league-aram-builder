"""Role-based stat weight multipliers for augment/item scoring.

Each role has a 12D multiplier vector aligned with StatVector.fields().
Applied as: effective_vec = champion.stats * role_weights[role]
This amplifies role-appropriate stats and suppresses inappropriate ones.
"""

import numpy as np
from backend.models import StatVector

ROLE_WEIGHTS: dict[str, dict[str, float]] = {
    "marksman": {
        "ap": 0.3, "ad": 1.4, "attack_speed": 1.3, "hp": 0.3,
        "lethality": 0.8, "pen": 0.5, "crit": 1.5, "cdr": 0.7,
        "heal_power": 0.3, "hard_cc": 0.5, "soft_cc": 0.5, "shield": 0.3,
    },
    "mage": {
        "ap": 1.4, "ad": 0.2, "attack_speed": 0.2, "hp": 0.4,
        "lethality": 0.2, "pen": 1.3, "crit": 0.1, "cdr": 1.2,
        "heal_power": 0.4, "hard_cc": 0.8, "soft_cc": 0.6, "shield": 0.4,
    },
    "tank": {
        "ap": 0.3, "ad": 0.4, "attack_speed": 0.3, "hp": 1.4,
        "lethality": 0.2, "pen": 0.3, "crit": 0.1, "cdr": 1.1,
        "heal_power": 0.6, "hard_cc": 1.2, "soft_cc": 1.0, "shield": 1.3,
    },
    "fighter": {
        "ap": 0.4, "ad": 1.2, "attack_speed": 0.9, "hp": 1.0,
        "lethality": 0.7, "pen": 0.6, "crit": 0.4, "cdr": 1.0,
        "heal_power": 0.7, "hard_cc": 0.8, "soft_cc": 0.6, "shield": 0.7,
    },
    "assassin": {
        "ap": 0.8, "ad": 1.3, "attack_speed": 0.6, "hp": 0.2,
        "lethality": 1.4, "pen": 1.2, "crit": 0.5, "cdr": 0.9,
        "heal_power": 0.2, "hard_cc": 0.3, "soft_cc": 0.3, "shield": 0.2,
    },
    "support": {
        "ap": 0.6, "ad": 0.2, "attack_speed": 0.2, "hp": 0.8,
        "lethality": 0.1, "pen": 0.4, "crit": 0.1, "cdr": 1.3,
        "heal_power": 1.4, "hard_cc": 1.0, "soft_cc": 0.8, "shield": 1.3,
    },
}

_NEUTRAL = np.ones(len(StatVector.fields()), dtype=np.float64)

# Pre-compute numpy arrays for each role
_ROLE_ARRAYS: dict[str, np.ndarray] = {}
for _role, _weights in ROLE_WEIGHTS.items():
    _ROLE_ARRAYS[_role] = np.array(
        [_weights[f] for f in StatVector.fields()], dtype=np.float64
    )


def get_role_weights(role: str) -> np.ndarray:
    """Return 12D role weight array. Falls back to neutral (all 1.0) for unknown roles.

    Checks config for user overrides before using built-in defaults.
    """
    role_lower = role.lower()

    # Check for config overrides (lazy import to avoid circular dependency)
    try:
        from backend.config import config
        overrides = config.get("role_weights")
        if overrides and role_lower in overrides:
            base = dict(ROLE_WEIGHTS.get(role_lower, {}))
            base.update(overrides[role_lower])
            return np.array(
                [base.get(f, 1.0) for f in StatVector.fields()], dtype=np.float64
            )
    except Exception:
        pass

    return _ROLE_ARRAYS.get(role_lower, _NEUTRAL)
