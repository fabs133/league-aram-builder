import json
import sys
import requests
from pathlib import Path
import logging
from backend.models import (
    ChampionMeta, StatVector, AugmentData, AugmentTier, ItemData,
    CCAbility, CCProfile, ScalingSpec, ScalingType,
)

# Resolve data paths relative to the app root.
# In PyInstaller bundles sys._MEIPASS points to the temp extraction dir;
# in normal Python runs we fall back to the project root (3 levels up from this file).
_APP_ROOT = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))

CACHE_DIR = _APP_ROOT / "data" / "cache"
CHAMP_FILE = _APP_ROOT / "data" / "champions" / "champions.json"
SYNERGY_FILE = _APP_ROOT / "data" / "champions" / "synergies.json"
AUG_OVERRIDE_FILE = _APP_ROOT / "data" / "augments" / "overrides.json"
SCALING_FILE = _APP_ROOT / "data" / "augments" / "scaling.json"

CD_AUGMENTS_URL = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default/v1/cherry-augments.json"
CD_ARENA_DESC_URL = "https://raw.communitydragon.org/latest/cdragon/arena/en_us.json"
DD_BASE_URL = "https://ddragon.leagueoflegends.com"

DESCRIPTION_KEYWORDS: dict[str, str] = {
    "ability power": "ap",
    "AP": "ap",
    "magic damage": "ap",
    "attack damage": "ad",
    "AD": "ad",
    "physical damage": "ad",
    "attack speed": "attack_speed",
    "ability haste": "cdr",
    "haste": "cdr",
    "cooldown": "cdr",
    "health": "hp",
    "bonus hp": "hp",
    "max health": "hp",
    "lethality": "lethality",
    "armor penetration": "lethality",
    "magic penetration": "pen",
    "magic pen": "pen",
    "magic resist": "pen",
    "critical": "crit",
    "crit": "crit",
    "heal": "heal_power",
    "omnivamp": "heal_power",
    "lifesteal": "heal_power",
    "life steal": "heal_power",
    "vamp": "heal_power",
    "stun": "hard_cc",
    "root": "hard_cc",
    "knockup": "hard_cc",
    "knock up": "hard_cc",
    "knocking": "hard_cc",
    "snare": "hard_cc",
    "charm": "hard_cc",
    "suppress": "hard_cc",
    "immobilize": "hard_cc",
    "immobilizing": "hard_cc",
    "polymorph": "hard_cc",
    "slow": "soft_cc",
    "silence": "soft_cc",
    "blind": "soft_cc",
    "ground": "soft_cc",
    "grievous": "soft_cc",
    "exhaust": "soft_cc",
    "shield": "shield",
    "damage reduction": "shield",
    "invulnerab": "shield",
    "armor": "shield",
    "resist": "shield",
    "adaptive force": "ap",
    "on-hit": "attack_speed",
    "movement speed": "hp",
    "true damage": "lethality",
    "burn": "ap",
}

# Name-based stat hints for augments whose names imply a stat category.
# Matched case-insensitively against the augment name.
NAME_STAT_HINTS: dict[str, dict[str, float]] = {
    "adapt": {"ap": 0.4, "ad": 0.4},
    "escapade": {"ad": 0.4, "ap": 0.4},
    "blunt force": {"ad": 0.5},
    "deft": {"attack_speed": 0.6},
    "goredrink": {"heal_power": 0.5},
    "goliath": {"hp": 0.6},
    "glass cannon": {"lethality": 0.4, "ad": 0.3},
    "executioner": {"ad": 0.3, "lethality": 0.3},
    "jeweled gauntlet": {"crit": 0.5, "ap": 0.3},
    "it's critical": {"crit": 0.6},
    "critical rhythm": {"crit": 0.4, "attack_speed": 0.3},
    "critical healing": {"crit": 0.3, "heal_power": 0.4},
    "critical missile": {"crit": 0.4, "ad": 0.3},
    "double tap": {"crit": 0.3, "attack_speed": 0.3},
    "dual wield": {"attack_speed": 0.4, "ad": 0.3},
    "fan the hammer": {"attack_speed": 0.4, "crit": 0.3},
    "heavy hitter": {"ad": 0.4, "hp": 0.3},
    "first-aid kit": {"heal_power": 0.5},
    "all for you": {"heal_power": 0.5, "shield": 0.3},
    "celestial body": {"hp": 0.6},
    "apex inventor": {"cdr": 0.6},
    "bread and butter": {"cdr": 0.5},
    "bread and cheese": {"cdr": 0.5},
    "bread and jam": {"cdr": 0.5},
    "infinite recursion": {"cdr": 0.6},
    "eureka": {"cdr": 0.4, "ap": 0.3},
    "crit 'n cast": {"crit": 0.3, "cdr": 0.3},
    "erosion": {"pen": 0.4, "lethality": 0.3},
    "back to basics": {"ap": 0.4, "ad": 0.4},
    "can't touch this": {"shield": 0.6},
    "courage of the colossus": {"shield": 0.5, "hard_cc": 0.3},
    "holy snowball": {"shield": 0.4},
    "final form": {"shield": 0.3, "heal_power": 0.3},
    "cruelty": {"hard_cc": 0.4, "ap": 0.3},
    "frost wraith": {"hard_cc": 0.4},
    "guilty pleasure": {"hard_cc": 0.3, "heal_power": 0.3},
    "adamant": {"shield": 0.4, "hard_cc": 0.3},
    "ice cold": {"soft_cc": 0.5},
    "flashy": {"cdr": 0.3},
    "donation": {"hp": 0.3},
    "get excited": {"attack_speed": 0.4, "ad": 0.3},
    "firebrand": {"ap": 0.3, "attack_speed": 0.3},
    "infernal conduit": {"ap": 0.4, "cdr": 0.3},
    "devil on your shoulder": {"lethality": 0.4},
    "gash": {"lethality": 0.4, "ad": 0.3},
    "draw your sword": {"ad": 0.4, "attack_speed": 0.3},
    "feel the burn": {"soft_cc": 0.4},
    "dashing": {"cdr": 0.5},
    "homeguard": {"hp": 0.3},
    "escape plan": {"shield": 0.4},
    "giant slayer": {"ad": 0.3, "lethality": 0.3},
    "hand of baron": {"ap": 0.4, "ad": 0.4},
}

ITEM_STAT_MAP: dict[str, str] = {
    "FlatMagicDamageMod": "ap",
    "FlatPhysicalDamageMod": "ad",
    "PercentAttackSpeedMod": "attack_speed",
    "FlatHPPoolMod": "hp",
    "FlatArmorPenetrationMod": "lethality",
    "FlatMagicPenetrationMod": "pen",
    "FlatCritChanceMod": "crit",
    "AbilityHasteMod": "cdr",
    "FlatSpellBlockMod": "shield",
}


class StaticData:
    def __init__(self):
        self._champions: dict[str, ChampionMeta] = {}
        self._augments: dict[str, AugmentData] = {}
        self._stat_anvils: dict[str, AugmentData] = {}
        self._items: dict[str, ItemData] = {}
        self._all_item_names: dict[str, str] = {}  # ALL item names for display

    def load(self) -> None:
        self._champions = _load_champions()
        all_augments = _load_augments()
        # Separate stat anvils (kBronze / tier 0) from real augments
        self._augments = {
            k: v for k, v in all_augments.items()
            if v.tier != AugmentTier.STAT_ANVIL
        }
        self._stat_anvils = {
            k: v for k, v in all_augments.items()
            if v.tier == AugmentTier.STAT_ANVIL
        }
        self._items = _load_items()
        self._all_item_names = _load_all_item_names()

        # Load and register scaling specs for indirect augments
        from backend.engine.scoring import set_scaling_specs
        scaling = _load_scaling_specs()
        set_scaling_specs(scaling)

    def get_champion(self, champion_id: str) -> ChampionMeta | None:
        return self._champions.get(champion_id.lower())

    def get_augment(self, augment_id: str) -> AugmentData | None:
        return self._augments.get(str(augment_id)) or self._stat_anvils.get(str(augment_id))

    def get_item(self, item_id: str) -> ItemData | None:
        return self._items.get(str(item_id))

    def get_item_name(self, item_id: str) -> str:
        """Resolve any item ID to a name, even if not in our scored item set."""
        item = self._items.get(str(item_id))
        if item:
            return item.name
        return self._all_item_names.get(str(item_id), str(item_id))

    def all_items(self) -> list[ItemData]:
        return list(self._items.values())

    def all_augments(self) -> list[AugmentData]:
        return list(self._augments.values())

    def get_stat_anvil(self, anvil_id: str) -> AugmentData | None:
        return self._stat_anvils.get(str(anvil_id))

    def all_stat_anvils(self) -> list[AugmentData]:
        return list(self._stat_anvils.values())


_TAG_TO_ROLE = {
    "marksman": "marksman", "mage": "mage", "tank": "tank",
    "fighter": "fighter", "assassin": "assassin", "support": "support",
}

# Heuristic classifiers for champions without explicit role tags.
# Checked in order; first match wins.
_ROLE_CLASSIFIERS: list[tuple[str, callable]] = [
    ("marksman", lambda s: s.crit >= 0.4 and s.ad >= 0.5),
    ("assassin", lambda s: s.lethality >= 0.4 and s.hp < 0.3),
    ("mage",     lambda s: s.ap >= 0.6 and s.ad < 0.4),
    ("tank",     lambda s: s.hp >= 0.6 and s.ad < 0.5 and s.ap < 0.3),
    ("support",  lambda s: s.heal_power >= 0.3 or (s.shield >= 0.4 and s.hp >= 0.4)),
    ("fighter",  lambda s: True),  # default fallback
]


def _classify_role(stats: StatVector, notes: str) -> str:
    """Determine champion role from notes tags or stat vector heuristics."""
    # Try explicit tags first (e.g., "Tags: Marksman, Assassin")
    if "Tags:" in notes:
        tag_str = notes.split("Tags:")[1].strip()
        for tag in tag_str.split(","):
            role = _TAG_TO_ROLE.get(tag.strip().lower())
            if role:
                return role

    # Fall back to stat-based classification
    for role, check in _ROLE_CLASSIFIERS:
        if check(stats):
            return role
    return "fighter"


def _load_synergies() -> dict[str, dict[str, float]]:
    """Load champion-specific stat multipliers from synergies.json."""
    if not SYNERGY_FILE.exists():
        return {}
    return json.loads(SYNERGY_FILE.read_text(encoding="utf-8"))


def _load_champions() -> dict[str, ChampionMeta]:
    if not CHAMP_FILE.exists():
        return {}

    synergies = _load_synergies()
    raw = json.loads(CHAMP_FILE.read_text(encoding="utf-8"))
    result = {}
    for champ_id, data in raw.items():
        stats_raw = data.get("stats", {})
        stats = StatVector(**{k: stats_raw.get(k, 0.0) for k in StatVector.fields()})

        cc_profile = CCProfile()
        cc_raw = data.get("cc_profile", {})
        if cc_raw:
            abilities = []
            for ab in cc_raw.get("abilities", []):
                abilities.append(CCAbility(
                    name=ab["name"],
                    cc_type=ab["cc_type"],
                    hard=ab["hard"],
                    base_duration=ab["base_duration"],
                    cooldown=ab["cooldown"],
                    aoe=ab.get("aoe", False),
                ))
            cc_profile = CCProfile(
                abilities=abilities,
                total_hard_cc_sec=cc_raw.get("total_hard_cc_sec", 0.0),
                total_soft_cc_sec=cc_raw.get("total_soft_cc_sec", 0.0),
                cc_uptime_rating=cc_raw.get("cc_uptime_rating", 0.0),
            )

        notes = data.get("notes", "")
        role = _classify_role(stats, notes)
        synergy = synergies.get(champ_id.lower(), {})

        result[champ_id] = ChampionMeta(
            id=champ_id,
            name=data["name"],
            stats=stats,
            cc_profile=cc_profile,
            role=role,
            synergy=synergy,
            notes=notes,
        )
    return result


def _get_dd_version() -> str:
    r = requests.get(f"{DD_BASE_URL}/api/versions.json", timeout=5)
    r.raise_for_status()
    versions = r.json()
    return versions[0]


def _load_augments() -> dict[str, AugmentData]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    # Check cache
    try:
        version = _get_dd_version()
    except Exception:
        version = "unknown"

    cache_file = CACHE_DIR / f"augments_{version}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return _parse_augment_cache(cached)

    # Fetch ARAM Mayhem augments from cherry-augments.json (primary source)
    try:
        r = requests.get(CD_AUGMENTS_URL, timeout=15)
        r.raise_for_status()
        augments_raw = r.json()
    except Exception:
        augments_raw = []

    # Fetch Arena descriptions as supplementary source (match by name)
    desc_by_name: dict[str, str] = {}
    try:
        r2 = requests.get(CD_ARENA_DESC_URL, timeout=15)
        r2.raise_for_status()
        arena_data = r2.json()
        for arena_aug in arena_data.get("augments", []):
            aname = arena_aug.get("name", "")
            adesc = arena_aug.get("desc", "")
            if aname and adesc:
                desc_by_name[aname.lower()] = adesc
    except Exception:
        pass

    RARITY_MAP = {"ksilver": 1, "kgold": 2, "kprismatic": 3, "kbronze": 0}

    result = {}
    cache_data = {}

    for aug in augments_raw:
        aug_id = str(aug.get("id", ""))
        name = aug.get("nameTRA", "") or aug.get("name", "")
        if not aug_id or not name:
            continue

        # Map rarity string to tier
        rarity_str = aug.get("rarity", "kSilver").lower()
        tier_val = RARITY_MAP.get(rarity_str, 1)
        tier = AugmentTier(tier_val)

        # Try to get description from Arena data (match by name)
        desc = desc_by_name.get(name.lower(), "")

        # Compute contribution from description + name hints
        contribution = _parse_description_to_stats(desc, name)

        result[aug_id] = AugmentData(
            id=aug_id,
            name=name,
            tier=tier,
            description=desc,
            contribution=contribution,
        )
        cache_data[aug_id] = {
            "name": name,
            "tier": tier.value,
            "description": desc,
            "contribution": {k: getattr(contribution, k) for k in StatVector.fields()},
        }

    # Apply overrides
    result = _apply_overrides(result)

    # Cache
    cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")

    return result


def _parse_description_to_stats(description: str, name: str = "") -> StatVector:
    stats = {f: 0.0 for f in StatVector.fields()}

    # 1. Name-based hints (highest priority, manually curated)
    name_lower = name.lower()
    for hint_name, hint_stats in NAME_STAT_HINTS.items():
        if hint_name == name_lower:
            for stat, val in hint_stats.items():
                stats[stat] = max(stats[stat], val)
            break

    # 2. Description keyword matching
    if description:
        desc_lower = description.lower()
        for keyword, stat in DESCRIPTION_KEYWORDS.items():
            if keyword.lower() in desc_lower:
                stats[stat] = min(stats[stat] + 0.3, 1.0)

    # 3. If still all zeros, try matching keywords against the name itself
    if all(v == 0.0 for v in stats.values()) and name:
        for keyword, stat in DESCRIPTION_KEYWORDS.items():
            if keyword.lower() in name_lower:
                stats[stat] = min(stats[stat] + 0.3, 1.0)

    return StatVector(**stats)


def _apply_overrides(augments: dict[str, AugmentData]) -> dict[str, AugmentData]:
    if not AUG_OVERRIDE_FILE.exists():
        return augments

    overrides = json.loads(AUG_OVERRIDE_FILE.read_text(encoding="utf-8"))
    for aug_id, override in overrides.items():
        if aug_id in augments:
            if "contribution" in override:
                for stat, val in override["contribution"].items():
                    if hasattr(augments[aug_id].contribution, stat):
                        setattr(augments[aug_id].contribution, stat, val)
            if "tier" in override:
                augments[aug_id].tier = AugmentTier(override["tier"])
        else:
            # Override can define a full new augment
            if "name" in override and "contribution" in override:
                contrib = StatVector(**{
                    k: override["contribution"].get(k, 0.0)
                    for k in StatVector.fields()
                })
                augments[aug_id] = AugmentData(
                    id=aug_id,
                    name=override["name"],
                    tier=AugmentTier(override.get("tier", 1)),
                    description=override.get("description", ""),
                    contribution=contrib,
                )
    return augments


def _parse_augment_cache(cached: dict) -> dict[str, AugmentData]:
    result = {}
    for aug_id, data in cached.items():
        contrib = StatVector(**{
            k: data["contribution"].get(k, 0.0)
            for k in StatVector.fields()
        })
        result[aug_id] = AugmentData(
            id=aug_id,
            name=data["name"],
            tier=AugmentTier(data["tier"]),
            description=data.get("description", ""),
            contribution=contrib,
        )
    return _apply_overrides(result)


def _load_items() -> dict[str, ItemData]:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        version = _get_dd_version()
    except Exception:
        version = "unknown"

    cache_file = CACHE_DIR / f"items_{version}.json"
    if cache_file.exists():
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        return _parse_item_cache(cached)

    # Fetch from DataDragon
    try:
        url = f"{DD_BASE_URL}/cdn/{version}/data/en_US/item.json"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        raw = r.json()
    except Exception:
        return {}

    items_raw = raw.get("data", {})
    excluded_tags = {"Jungle"}

    # Quest/reward items that DataDragon marks purchasable but can't be bought
    excluded_ids = {
        "994403",   # Golden Spatula (ARAM quest reward)
        "4403",     # The Golden Spatula (Summoner's Rift variant)
        "224403",   # The Golden Spatula (Arena variant)
    }

    # First pass: collect all raw stats for normalization
    raw_items = {}
    stat_ranges: dict[str, list[float]] = {f: [] for f in StatVector.fields()}

    for item_id, data in items_raw.items():
        if item_id in excluded_ids:
            continue

        gold = data.get("gold", {})
        if not gold.get("purchasable", False):
            continue
        if gold.get("total", 0) < 300:
            continue

        # Only include items available on SR (map 11) or ARAM (map 12)
        maps = data.get("maps", {})
        if maps and not maps.get("11", False) and not maps.get("12", False):
            continue

        tags = data.get("tags", [])
        if excluded_tags & set(tags):
            continue
        if "Consumable" in tags:
            continue

        # Skip items that require specific allies (e.g., Ornn items)
        required_champion = data.get("requiredChampion", "")
        if required_champion:
            continue

        item_stats = data.get("stats", {})
        mapped = {}
        for dd_key, our_key in ITEM_STAT_MAP.items():
            val = item_stats.get(dd_key, 0)
            if val:
                mapped[our_key] = float(val)
                stat_ranges[our_key].append(float(val))

        is_boots = "Boots" in tags
        desc = data.get("description", "").lower()
        is_mythic = "mythic" in desc

        raw_items[item_id] = {
            "name": data.get("name", ""),
            "cost": gold.get("total", 0),
            "raw_stats": mapped,
            "mythic": is_mythic,
            "boots": is_boots,
            "tags": tags,
        }

    # Compute min-max per stat for normalization
    stat_min: dict[str, float] = {}
    stat_max: dict[str, float] = {}
    for stat, values in stat_ranges.items():
        if values:
            stat_min[stat] = min(values)
            stat_max[stat] = max(values)
        else:
            stat_min[stat] = 0.0
            stat_max[stat] = 1.0

    # Second pass: normalize and create ItemData
    result = {}
    cache_data = {}

    for item_id, data in raw_items.items():
        normalized = {}
        for stat in StatVector.fields():
            raw_val = data["raw_stats"].get(stat, 0.0)
            if raw_val == 0.0:
                normalized[stat] = 0.0
            else:
                range_val = stat_max[stat] - stat_min[stat]
                if range_val > 0:
                    normalized[stat] = (raw_val - stat_min[stat]) / range_val
                else:
                    normalized[stat] = 1.0

        stats = StatVector(**normalized)
        result[item_id] = ItemData(
            id=item_id,
            name=data["name"],
            cost=data["cost"],
            stats=stats,
            mythic=data["mythic"],
            boots=data["boots"],
            tags=data["tags"],
        )
        cache_data[item_id] = {
            "name": data["name"],
            "cost": data["cost"],
            "stats": normalized,
            "mythic": data["mythic"],
            "boots": data["boots"],
            "tags": data["tags"],
        }

    cache_file.write_text(json.dumps(cache_data, indent=2), encoding="utf-8")
    return result


def _parse_item_cache(cached: dict) -> dict[str, ItemData]:
    result = {}
    for item_id, data in cached.items():
        stats = StatVector(**{
            k: data["stats"].get(k, 0.0)
            for k in StatVector.fields()
        })
        result[item_id] = ItemData(
            id=item_id,
            name=data["name"],
            cost=data["cost"],
            stats=stats,
            mythic=data.get("mythic", False),
            boots=data.get("boots", False),
            tags=data.get("tags", []),
        )
    return result


def _load_all_item_names() -> dict[str, str]:
    """Load ALL item names from DataDragon (unfiltered) for display purposes."""
    try:
        version = _get_dd_version()
    except Exception:
        return {}

    cache_file = CACHE_DIR / f"item_names_{version}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    try:
        url = f"{DD_BASE_URL}/cdn/{version}/data/en_US/item.json"
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        raw = r.json()
    except Exception:
        return {}

    names = {
        item_id: data.get("name", "")
        for item_id, data in raw.get("data", {}).items()
        if data.get("name")
    }

    cache_file.write_text(json.dumps(names, ensure_ascii=False), encoding="utf-8")
    return names


_logger = logging.getLogger(__name__)


def _load_scaling_specs() -> dict[str, list[ScalingSpec]]:
    if not SCALING_FILE.exists():
        return {}

    try:
        raw = json.loads(SCALING_FILE.read_text(encoding="utf-8"))
    except Exception:
        _logger.warning("Failed to read scaling.json", exc_info=True)
        return {}

    result: dict[str, list[ScalingSpec]] = {}
    for aug_id, spec_list in raw.items():
        specs = []
        for entry in spec_list:
            try:
                specs.append(ScalingSpec(
                    type=ScalingType(entry["type"]),
                    base=float(entry["base"]),
                    rate_stat=entry["rate_stat"],
                    gate_value=float(entry.get("gate_value", 0.0)),
                    duration_factor=float(entry.get("duration_factor", 1.0)),
                    note=entry.get("note", ""),
                ))
            except (KeyError, ValueError) as exc:
                _logger.warning("Skipping malformed scaling spec for augment %s: %s", aug_id, exc)
                continue
        if specs:
            result[str(aug_id)] = specs
    return result
