from backend.models import GameSnapshot, GamePhase, PipelineResult
from backend.static_data.loader import StaticData
from backend.engine.ranker import rank_augments, should_reroll
from backend.engine.build_suggester import suggest_build
from backend.storage.db import get_all_personal_winrates


class Pipeline:
    def __init__(self, static_data: StaticData):
        self.data = static_data

    def run(self, snapshot: GameSnapshot) -> PipelineResult | None:
        champion = self.data.get_champion(snapshot.champion_id)
        if champion is None:
            return None

        choices = [
            self.data.get_augment(aid) for aid in snapshot.augment_choices
        ]
        choices = [a for a in choices if a is not None]

        existing = [
            self.data.get_augment(aid) for aid in snapshot.chosen_augments
        ]
        existing = [a for a in existing if a is not None]

        # Resolve enemy champions for CC-aware scoring
        enemies = [
            self.data.get_champion(eid) for eid in snapshot.enemy_champion_ids
        ]
        enemies = [e for e in enemies if e is not None]

        personal_wrs = get_all_personal_winrates(champion.id)
        all_items = self.data.all_items()

        recommendations = rank_augments(
            champion=champion,
            choices=choices,
            existing=existing,
            all_items=all_items,
            personal_winrates=personal_wrs if personal_wrs else None,
            enemies=enemies if enemies else None,
        )

        reroll, reroll_reason = should_reroll(recommendations, champion, existing)

        build_state = suggest_build(
            champion=champion,
            active_augments=existing,
            purchased_items=snapshot.purchased_items,
            current_gold=snapshot.current_gold,
            all_items=all_items,
        )

        return PipelineResult(
            phase=snapshot.phase,
            recommendations=recommendations,
            build_state=build_state,
            suggest_reroll=reroll,
            reroll_reason=reroll_reason,
        )
