# Scaling Spec System — Projected Scoring for Indirect Augments

## Context

39% of augments (204/517) have all-zero contribution vectors and always score 0. Many Gold/Prismatic augments have proc-based effects ("on hit", "stacking infinitely", "when you deal damage") whose value depends on champion trigger rates, not flat stat gains. The keyword parser can't capture these because:

- `{{ Item_Keyword_OnHit }}` template placeholders are never resolved (18 augments miss matching)
- "stacking", "when you", "each time" aren't in `DESCRIPTION_KEYWORDS`
- No proc-rate or activation-rate projection exists in the engine

Examples of severely mispriced augments:
- **Twice Thrice** (Gold): doubles on-hit procs every 3rd attack → scores **0** on all champions
- **Hybrid** (Gold): alternating attack/ability damage amp → scores **0**
- **Trueshot Prodigy** (Prismatic): auto-fires skillshots on ranged hits → scores **0**
- **Dual Wield** (Prismatic): fires bonus bolt + doubles on-hit → only gets attack_speed: 0.7

We adopt the **Specification Pattern** (pure evaluation functions, composable, structured results) to project these indirect values based on champion stats.

---

## Design

Every indirect augment reduces to: `projected_value = base_effect × f(champion_stat)`.

Six scaling types cover ~90% of indirect augments:

| Type | Formula | When to use |
|------|---------|-------------|
| `on_hit` | `base × stat` | Procs on auto attacks (AS-driven) |
| `on_cast` | `base × (1 + stat)` | Procs on ability use (CDR-driven, +1 baseline) |
| `stacking` | `base × stat × duration_factor` | Infinitely stacking effects |
| `threshold` | `base if stat ≥ gate else 0` | Effects requiring minimum stat |
| `amplifier` | `base × stat²` | Multiplicative stat amplifiers (quadratic synergy) |
| `passive` | `base × √stat` | Survivability-gated auras/passives (diminishing) |

Each augment gets 0+ specs. Specs compose additively. Augments with no specs work exactly as before.

---

## Implementation

### Step 1: Add data models to `backend/models.py`

Add after `AugmentData`:

```python
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
    base: float                  # effect magnitude (0.0-2.0 range)
    rate_stat: str               # StatVector field name driving activation
    gate_value: float = 0.0      # THRESHOLD: minimum stat required
    duration_factor: float = 1.0  # STACKING: ramp multiplier
    note: str = ""               # authoring note, ignored by engine
```

### Step 2: Create `backend/engine/scaling.py`

New file — pure evaluation functions, no side effects.

**Functions:**
- `evaluate_on_hit(spec, stat) → base × stat`
- `evaluate_on_cast(spec, stat) → base × (1 + stat)`
- `evaluate_stacking(spec, stat) → base × stat × duration_factor`
- `evaluate_threshold(spec, stat) → base if stat ≥ gate else 0`
- `evaluate_amplifier(spec, stat) → base × stat²`
- `evaluate_passive(spec, stat) → base × √stat`
- `evaluate_spec(spec, stat)` — dispatcher by type
- `compute_scaling_bonus(specs, champion, role_weighted_vec) → float` — sum of all spec evaluations
- `compute_scaling_breakdown(specs, champion, role_weighted_vec) → dict[str, float]` — per-rate_stat contributions (for labels)

### Step 3: Create `data/augments/scaling.json`

Starter batch with 15 augments covering all 6 types. Both ID variants included (1000+ and base).

```json
{
  "1107": [{ "type": "on_hit", "base": 0.55, "rate_stat": "attack_speed", "note": "Twice Thrice" }],
  "107":  [{ "type": "on_hit", "base": 0.55, "rate_stat": "attack_speed", "note": "Twice Thrice" }],

  "1036": [
    { "type": "on_hit", "base": 0.45, "rate_stat": "attack_speed", "note": "Firebrand: on-hit burn" },
    { "type": "stacking", "base": 0.3, "rate_stat": "attack_speed", "duration_factor": 1.3, "note": "Firebrand: infinite stacking" }
  ],
  "36": [
    { "type": "on_hit", "base": 0.45, "rate_stat": "attack_speed", "note": "Firebrand" },
    { "type": "stacking", "base": 0.3, "rate_stat": "attack_speed", "duration_factor": 1.3, "note": "Firebrand" }
  ],

  "1029": [{ "type": "on_cast", "base": 0.5, "rate_stat": "cdr", "note": "Ethereal Weapon" }],
  "29":   [{ "type": "on_cast", "base": 0.5, "rate_stat": "cdr", "note": "Ethereal Weapon" }],

  "1045": [
    { "type": "on_cast", "base": 0.5, "rate_stat": "cdr", "note": "Infernal Conduit: on-cast burn" },
    { "type": "stacking", "base": 0.35, "rate_stat": "ap", "duration_factor": 1.4, "note": "Infernal Conduit: infinite stacking" }
  ],
  "45": [
    { "type": "on_cast", "base": 0.5, "rate_stat": "cdr", "note": "Infernal Conduit" },
    { "type": "stacking", "base": 0.35, "rate_stat": "ap", "duration_factor": 1.4, "note": "Infernal Conduit" }
  ],

  "1081": [{ "type": "stacking", "base": 0.4, "rate_stat": "attack_speed", "duration_factor": 1.5, "note": "Tap Dancer" }],
  "81":   [{ "type": "stacking", "base": 0.4, "rate_stat": "attack_speed", "duration_factor": 1.5, "note": "Tap Dancer" }],

  "1136": [{ "type": "stacking", "base": 0.35, "rate_stat": "hard_cc", "duration_factor": 1.2, "note": "Slap Around: stacks on CC" }],
  "136":  [{ "type": "stacking", "base": 0.35, "rate_stat": "hard_cc", "duration_factor": 1.2, "note": "Slap Around" }],

  "1":    [{ "type": "stacking", "base": 0.45, "rate_stat": "cdr", "duration_factor": 1.3, "note": "Accelerating Sorcery" }],

  "1052": [{ "type": "threshold", "base": 0.7, "rate_stat": "attack_speed", "gate_value": 0.5, "note": "Lightning Strikes" }],
  "52":   [{ "type": "threshold", "base": 0.7, "rate_stat": "attack_speed", "gate_value": 0.5, "note": "Lightning Strikes" }],

  "1225": [{ "type": "amplifier", "base": 0.5, "rate_stat": "attack_speed", "note": "Dual Wield" }],
  "225":  [{ "type": "amplifier", "base": 0.5, "rate_stat": "attack_speed", "note": "Dual Wield" }],

  "1220": [{ "type": "amplifier", "base": 0.45, "rate_stat": "crit", "note": "Fan The Hammer" }],

  "1054": [
    { "type": "on_hit", "base": 0.4, "rate_stat": "attack_speed", "note": "Master of Duality: on-hit AP stacking" },
    { "type": "on_cast", "base": 0.3, "rate_stat": "cdr", "note": "Master of Duality: on-cast AD stacking" }
  ],
  "54": [
    { "type": "on_hit", "base": 0.4, "rate_stat": "attack_speed", "note": "Master of Duality" },
    { "type": "on_cast", "base": 0.3, "rate_stat": "cdr", "note": "Master of Duality" }
  ],

  "1046": [{ "type": "passive", "base": 0.5, "rate_stat": "hp", "note": "Infernal Soul: damage aura" }],
  "46":   [{ "type": "passive", "base": 0.5, "rate_stat": "hp", "note": "Infernal Soul" }],

  "1075": [
    { "type": "passive", "base": 0.45, "rate_stat": "hp", "note": "Slow Cooker: proximity burn" },
    { "type": "stacking", "base": 0.3, "rate_stat": "hp", "duration_factor": 1.3, "note": "Slow Cooker: infinite stacking" }
  ],
  "75": [
    { "type": "passive", "base": 0.45, "rate_stat": "hp", "note": "Slow Cooker" },
    { "type": "stacking", "base": 0.3, "rate_stat": "hp", "duration_factor": 1.3, "note": "Slow Cooker" }
  ],

  "357":  [{ "type": "amplifier", "base": 0.4, "rate_stat": "attack_speed", "note": "Hybrid: alternating attack/ability amp" }],

  "1086": [{ "type": "on_hit", "base": 0.6, "rate_stat": "ad", "note": "Trueshot Prodigy: auto-fires on ranged hit" }],
  "86":   [{ "type": "on_hit", "base": 0.6, "rate_stat": "ad", "note": "Trueshot Prodigy" }]
}
```

### Step 4: Add loading to `backend/static_data/loader.py`

Add `SCALING_FILE` constant alongside other paths.

Add `_load_scaling_specs()` function:
- Reads `data/augments/scaling.json`
- Parses each entry into `list[ScalingSpec]`
- Logs warning and skips malformed entries
- Returns `dict[str, list[ScalingSpec]]`

Wire into `StaticData.load()`:
- Call `_load_scaling_specs()`
- Import and call `set_scaling_specs()` from scoring.py to register them

### Step 5: Integrate into `backend/engine/scoring.py`

**Module-level registry** (avoids changing AugmentData constructor everywhere):

```python
_scaling_specs: dict[str, list[ScalingSpec]] = {}

def set_scaling_specs(specs: dict[str, list[ScalingSpec]]) -> None:
    global _scaling_specs
    _scaling_specs = specs

def get_scaling_specs(augment_id: str) -> list[ScalingSpec]:
    return _scaling_specs.get(augment_id, [])
```

**In `score_augment`** — add after existing bonus terms:

```python
specs = get_scaling_specs(augment.id)
if specs:
    score += compute_scaling_bonus(specs, champion, champ_vec) * tier_multiplier
```

Scaling bonus also gets tier_multiplier so Prismatic procs benefit from their tier.

**In `score_breakdown`** — merge scaling contributions into the per-stat dict:

```python
specs = get_scaling_specs(augment.id)
if specs:
    scaling_bd = compute_scaling_breakdown(specs, champion, champ_arr)
    for stat, value in scaling_bd.items():
        result[stat] = result.get(stat, 0.0) + value
```

This means `label.py` (`derive_label`, `derive_explanation`) automatically picks up scaling contributions with zero changes.

### Step 6: Add test isolation fixture

Add to `tests/conftest.py`:

```python
@pytest.fixture(autouse=True)
def _clear_scaling_specs():
    from backend.engine.scoring import set_scaling_specs
    set_scaling_specs({})
    yield
    set_scaling_specs({})
```

Ensures no scaling specs leak between tests. All 74 existing tests pass unchanged.

### Step 7: Create `tests/test_scaling.py`

~20 tests covering:

**Pure evaluation (8 tests):**
- on_hit scales linearly with stat
- on_cast has nonzero baseline at stat=0
- stacking uses duration_factor
- threshold binary gate (pass/fail)
- amplifier quadratic relationship
- passive sqrt diminishing returns
- unknown type returns 0
- zero base returns 0

**compute_scaling_bonus (4 tests):**
- empty specs → 0
- additive composition of multiple specs
- uses role-weighted vec (not raw stats)
- invalid rate_stat silently skipped

**score_augment integration (4 tests):**
- augment with scaling spec scores higher than without
- zero-contribution augment with scaling specs scores > 0
- augment without specs scores identically to before
- scaling bonus gets tier_multiplier

**score_breakdown + labels (2 tests):**
- breakdown includes scaling contributions for rate_stat
- zero-contribution augment with scaling spec gets real label (not "Utility Mixed")

**Loading (2 tests):**
- valid scaling.json produces correct ScalingSpec objects
- missing file returns empty dict

---

## Files Summary

| Action | File | Changes |
|--------|------|---------|
| **MODIFY** | `backend/models.py` | Add `ScalingType` enum + `ScalingSpec` dataclass |
| **CREATE** | `backend/engine/scaling.py` | 6 pure eval functions + bonus/breakdown helpers |
| **CREATE** | `data/augments/scaling.json` | 15 augments × both ID variants (~30 entries) |
| **MODIFY** | `backend/static_data/loader.py` | Add `SCALING_FILE`, `_load_scaling_specs()`, wire into `load()` |
| **MODIFY** | `backend/engine/scoring.py` | Add registry + 3 lines in `score_augment` + 4 lines in `score_breakdown` |
| **MODIFY** | `tests/conftest.py` | Add autouse fixture to clear scaling specs |
| **CREATE** | `tests/test_scaling.py` | ~20 new tests |

No changes to: `label.py`, `ranker.py`, `pipeline.py`, `StatVector` dimensions, `overrides.json`.

---

## Verification

1. `pytest tests/` — all 74 existing + ~20 new tests pass
2. Quick scoring check:
   ```python
   # Twice Thrice (ID 1107) should now score > 0 on Kog'Maw (high AS)
   score_augment(kogmaw, twice_thrice, []) > 0.3
   # Twice Thrice should score near-zero on Lux (low AS)
   score_augment(lux, twice_thrice, []) < 0.1
   # Lightning Strikes should gate on AS threshold
   score_augment(jinx, lightning_strikes, []) > score_augment(lux, lightning_strikes, [])
   ```
3. Restart backend, verify previously-zero augments now show meaningful scores
