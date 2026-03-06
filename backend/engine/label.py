from backend.models import ChampionMeta, AugmentData
from backend.engine.scoring import score_breakdown

STAT_WORDS: dict[str, str] = {
    "ap": "Magic",
    "ad": "Physical",
    "attack_speed": "Speed",
    "hp": "Tank",
    "lethality": "Assassin",
    "pen": "Shred",
    "crit": "Crit",
    "cdr": "Haste",
    "heal_power": "Heals",
    "hard_cc": "Lockdown",
    "soft_cc": "Control",
    "shield": "Protect",
}


def derive_label(champion: ChampionMeta, augment: AugmentData) -> tuple[str, str]:
    """
    Top 2 weighted stat contributions -> two-word label.
    If only 1 stat contributes, second word is "Focus".
    If 0 stats contribute, returns ("Utility", "Mixed").
    """
    breakdown = score_breakdown(champion, augment)
    ranked = sorted(
        [(stat, val) for stat, val in breakdown.items() if val > 0],
        key=lambda x: x[1],
        reverse=True,
    )
    if len(ranked) == 0:
        return ("Utility", "Mixed")
    if len(ranked) == 1:
        return (STAT_WORDS.get(ranked[0][0], ranked[0][0]), "Focus")
    return (
        STAT_WORDS.get(ranked[0][0], ranked[0][0]),
        STAT_WORDS.get(ranked[1][0], ranked[1][0]),
    )


def derive_explanation(champion: ChampionMeta, augment: AugmentData) -> str:
    """
    Human-readable one-sentence explanation derived entirely from score_breakdown.
    """
    breakdown = score_breakdown(champion, augment)
    top = sorted(
        [(stat, val) for stat, val in breakdown.items() if val > 0.05],
        key=lambda x: x[1],
        reverse=True,
    )[:3]

    if not top:
        return "Low synergy with this champion's stat profile."

    parts = [f"{STAT_WORDS.get(s, s)} ({v:.2f})" for s, v in top]
    return f"Powers your strongest stats: {', '.join(parts)}."
