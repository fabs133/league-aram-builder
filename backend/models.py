from dataclasses import dataclass, field
from enum import Enum


class AugmentTier(int, Enum):
    STAT_ANVIL = 0
    SILVER = 1
    GOLD = 2
    PRISMATIC = 3


class GamePhase(str, Enum):
    CHAMP_SELECT = "champ_select"
    AUG_PICK_1 = "aug_pick_1"
    AUG_PICK_2 = "aug_pick_2"
    AUG_PICK_3 = "aug_pick_3"
    IN_GAME = "in_game"
    POST_GAME = "post_game"


@dataclass
class StatVector:
    ap: float = 0.0
    ad: float = 0.0
    attack_speed: float = 0.0
    hp: float = 0.0
    lethality: float = 0.0
    pen: float = 0.0
    crit: float = 0.0
    cdr: float = 0.0
    heal_power: float = 0.0
    hard_cc: float = 0.0  # stuns, roots, knockups, suppressions, charms
    soft_cc: float = 0.0  # slows, silences, blinds, grievous wounds, ground
    shield: float = 0.0   # shields, damage reduction, invulnerability

    def to_array(self) -> list[float]:
        return [
            self.ap, self.ad, self.attack_speed, self.hp,
            self.lethality, self.pen, self.crit,
            self.cdr, self.heal_power,
            self.hard_cc, self.soft_cc, self.shield,
        ]

    @staticmethod
    def fields() -> list[str]:
        return [
            "ap", "ad", "attack_speed", "hp", "lethality",
            "pen", "crit", "cdr", "heal_power",
            "hard_cc", "soft_cc", "shield",
        ]


@dataclass
class CCAbility:
    name: str               # e.g. "Dark Binding"
    cc_type: str            # "root", "stun", "knockup", "slow", "silence", etc.
    hard: bool              # True = hard CC, False = soft CC
    base_duration: float    # seconds at max rank
    cooldown: float         # seconds at max rank (before CDR)
    aoe: bool = False       # True if hits multiple targets


@dataclass
class CCProfile:
    abilities: list[CCAbility] = field(default_factory=list)
    total_hard_cc_sec: float = 0.0   # sum of all hard CC durations (single rotation)
    total_soft_cc_sec: float = 0.0   # sum of all soft CC durations
    cc_uptime_rating: float = 0.0    # 0-1, how much of a fight they can keep CC active


@dataclass
class ChampionMeta:
    id: str
    name: str
    stats: StatVector
    cc_profile: CCProfile = field(default_factory=CCProfile)
    role: str = ""  # marksman, mage, tank, fighter, assassin, support
    synergy: dict[str, float] = field(default_factory=dict)  # stat -> multiplier
    notes: str = ""


class ScalingType(str, Enum):
    ON_HIT = "on_hit"
    ON_CAST = "on_cast"
    STACKING = "stacking"
    THRESHOLD = "threshold"
    AMPLIFIER = "amplifier"
    PASSIVE = "passive"


@dataclass
class ScalingSpec:
    type: ScalingType
    base: float                   # effect magnitude (0.0-2.0 range)
    rate_stat: str                # StatVector field name driving activation
    gate_value: float = 0.0       # THRESHOLD: minimum stat required
    duration_factor: float = 1.0  # STACKING: ramp multiplier
    note: str = ""                # authoring note, ignored by engine


@dataclass
class AugmentData:
    id: str
    name: str
    tier: AugmentTier
    description: str
    contribution: StatVector


@dataclass
class ItemData:
    id: str
    name: str
    cost: int
    stats: StatVector
    mythic: bool = False
    boots: bool = False
    tags: list[str] = field(default_factory=list)


@dataclass
class AugmentRecommendation:
    augment_id: str
    augment_name: str
    score: float
    label: tuple[str, str]       # ("Magic", "Burst")
    core_items: list[str]        # item IDs, ordered
    explanation: str


@dataclass
class BuildState:
    champion_id: str
    chosen_augments: list[str] = field(default_factory=list)
    purchased_items: list[str] = field(default_factory=list)
    next_item_id: str | None = None
    gold_to_next: int = 0
    full_build: list[str] = field(default_factory=list)


@dataclass
class GameSnapshot:
    game_id: str
    phase: GamePhase
    champion_id: str
    augment_choices: list[str]       # currently offered, 3 IDs
    chosen_augments: list[str]
    purchased_items: list[str]
    current_gold: int
    game_time: float
    enemy_champion_ids: list[str]
    rerolls_remaining: int = 0
    level: int = 1
    is_dead: bool = False
    health_pct: float = 1.0  # currentHealth / maxHealth, 0-1
    champion_stats: dict[str, float] = field(default_factory=dict)


@dataclass
class PipelineResult:
    phase: GamePhase
    recommendations: list[AugmentRecommendation]
    build_state: BuildState
    suggest_reroll: bool
    reroll_reason: str = ""
