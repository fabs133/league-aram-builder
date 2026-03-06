from backend.models import ChampionMeta, AugmentData, ItemData, BuildState
from backend.engine.scoring import score_item


def suggest_build(
    champion: ChampionMeta,
    active_augments: list[AugmentData],
    purchased_items: list[str],
    current_gold: int,
    all_items: list[ItemData],
    build_size: int = 6,
) -> BuildState:
    """
    Project a full build from current state.
    - purchased_items are sunk costs, excluded from suggestions
    - next_item is the highest-scoring item the user can currently afford
    - full_build fills remaining slots in score order
    """
    available = [
        item for item in all_items
        if item.id not in purchased_items
    ]

    scored = sorted(
        available,
        key=lambda item: score_item(champion, item, active_augments),
        reverse=True,
    )

    slots_remaining = build_size - len(purchased_items)
    full_build_suggestions = [item.id for item in scored[:slots_remaining]]

    affordable = [item for item in scored if item.cost <= current_gold]
    next_item = affordable[0] if affordable else None

    gold_to_next = 0
    if next_item is None and scored:
        gold_to_next = scored[0].cost - current_gold

    return BuildState(
        champion_id=champion.id,
        chosen_augments=[a.id for a in active_augments],
        purchased_items=purchased_items,
        next_item_id=next_item.id if next_item else None,
        gold_to_next=gold_to_next,
        full_build=purchased_items + full_build_suggestions,
    )
