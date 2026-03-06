import numpy as np
from backend.models import (
    ChampionMeta, AugmentData, ItemData,
    AugmentRecommendation,
)
from backend.engine.scoring import score_augment, score_item, stat_vec
from backend.engine.label import derive_label, derive_explanation

REROLL_THRESHOLD = 0.5


def rank_augments(
    champion: ChampionMeta,
    choices: list[AugmentData],
    existing: list[AugmentData],
    all_items: list[ItemData],
    personal_winrates: dict[str, tuple[int, int]] | None = None,
    enemies: list[ChampionMeta] | None = None,
) -> list[AugmentRecommendation]:
    """
    Rank augment choices. Returns list sorted best->worst.
    personal_winrates: {augment_id: (wins, games)} -- applied only if games >= 5
    """
    results = []
    for aug in choices:
        score = score_augment(champion, aug, existing, enemies=enemies)

        if personal_winrates and aug.id in personal_winrates:
            wins, games = personal_winrates[aug.id]
            if games >= 5:
                wr_delta = (wins / games) - 0.5
                score += wr_delta * 0.2

        label = derive_label(champion, aug)
        explanation = derive_explanation(champion, aug)
        core_items = _suggest_core_items(champion, aug, existing, all_items)

        results.append(AugmentRecommendation(
            augment_id=aug.id,
            augment_name=aug.name,
            score=score,
            label=label,
            core_items=core_items,
            explanation=explanation,
        ))

    return sorted(results, key=lambda r: r.score, reverse=True)


def should_reroll(
    recommendations: list[AugmentRecommendation],
    champion: ChampionMeta,
    existing: list[AugmentData],
) -> tuple[bool, str]:
    """Returns (suggest_reroll, reason_string)."""
    if not recommendations:
        return False, ""

    best_score = recommendations[0].score

    # Champion ceiling = score of a perfect-fit hypothetical augment
    # approximated as the sum of the champion's top 3 stat weights
    champ_arr = stat_vec(champion.stats)
    ceiling = float(np.sort(champ_arr)[-3:].sum())

    if ceiling == 0:
        return False, ""

    ratio = best_score / ceiling

    if ratio < REROLL_THRESHOLD:
        label = recommendations[0].label
        return (
            True,
            f"Best option ({label[0]} · {label[1]}) scores {ratio:.0%} of your "
            f"ceiling. Consider rerolling for a better fit.",
        )
    return False, ""


def _suggest_core_items(
    champion: ChampionMeta,
    augment: AugmentData,
    existing: list[AugmentData],
    all_items: list[ItemData],
    n: int = 3,
) -> list[str]:
    """Returns top-n item IDs that synergize with champion + this augment."""
    scored = sorted(
        all_items,
        key=lambda item: score_item(champion, item, existing + [augment]),
        reverse=True,
    )
    result = []
    boots_seen = False
    for item in scored:
        if item.boots:
            if boots_seen:
                continue
            boots_seen = True
        result.append(item.id)
        if len(result) == n:
            break
    return result
