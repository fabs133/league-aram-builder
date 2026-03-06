"""
Generate champions.json with stat vectors and CC profiles for all champions.
Pulls base data from DataDragon and applies role-based heuristics.
"""
import json
import requests
from pathlib import Path

DD_BASE = "https://ddragon.leagueoflegends.com"

# Role-based stat templates (0-1 weights)
ROLE_TEMPLATES = {
    "Mage": {"ap": 0.85, "ad": 0.0, "attack_speed": 0.0, "hp": 0.15, "lethality": 0.0, "pen": 0.55, "crit": 0.0, "cdr": 0.6, "heal_power": 0.0, "hard_cc": 0.2, "soft_cc": 0.2, "shield": 0.0},
    "Assassin": {"ap": 0.2, "ad": 0.8, "attack_speed": 0.2, "hp": 0.1, "lethality": 0.7, "pen": 0.3, "crit": 0.1, "cdr": 0.3, "heal_power": 0.0, "hard_cc": 0.1, "soft_cc": 0.1, "shield": 0.0},
    "Fighter": {"ap": 0.0, "ad": 0.7, "attack_speed": 0.3, "hp": 0.6, "lethality": 0.3, "pen": 0.2, "crit": 0.1, "cdr": 0.4, "heal_power": 0.0, "hard_cc": 0.2, "soft_cc": 0.1, "shield": 0.1},
    "Tank": {"ap": 0.0, "ad": 0.2, "attack_speed": 0.1, "hp": 0.9, "lethality": 0.0, "pen": 0.1, "crit": 0.0, "cdr": 0.5, "heal_power": 0.0, "hard_cc": 0.5, "soft_cc": 0.3, "shield": 0.3},
    "Marksman": {"ap": 0.0, "ad": 0.8, "attack_speed": 0.7, "hp": 0.1, "lethality": 0.2, "pen": 0.3, "crit": 0.8, "cdr": 0.2, "heal_power": 0.0, "hard_cc": 0.1, "soft_cc": 0.1, "shield": 0.0},
    "Support": {"ap": 0.4, "ad": 0.0, "attack_speed": 0.0, "hp": 0.3, "lethality": 0.0, "pen": 0.1, "crit": 0.0, "cdr": 0.7, "heal_power": 0.5, "hard_cc": 0.4, "soft_cc": 0.3, "shield": 0.5},
}

# Champion-specific overrides for accuracy (key = lowercase no spaces/quotes)
# Format: {stat_overrides}, {cc_override}
OVERRIDES = {
    # --- Mages with notable CC ---
    "lux": ({"ap": 0.9, "pen": 0.6, "cdr": 0.7, "hard_cc": 0.5, "soft_cc": 0.3, "shield": 0.3},
            {"abilities": [{"name": "Light Binding", "cc_type": "root", "hard": True, "base_duration": 2.0, "cooldown": 10.0}, {"name": "Lucent Singularity", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 10.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.3}),
    "ahri": ({"ap": 0.9, "pen": 0.6, "cdr": 0.5, "hard_cc": 0.4},
             {"abilities": [{"name": "Charm", "cc_type": "charm", "hard": True, "base_duration": 1.4, "cooldown": 12.0}], "total_hard_cc_sec": 1.4, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "annie": ({"ap": 0.95, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.7},
              {"abilities": [{"name": "Pyromania", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 0.0, "aoe": True}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.35}),
    "brand": ({"ap": 0.9, "pen": 0.6, "cdr": 0.4, "hard_cc": 0.3, "soft_cc": 0.2},
              {"abilities": [{"name": "Sear", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 8.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "cassiopeia": ({"ap": 0.9, "attack_speed": 0.1, "pen": 0.5, "cdr": 0.3, "hard_cc": 0.4, "soft_cc": 0.4},
                   {"abilities": [{"name": "Petrifying Gaze", "cc_type": "stun", "hard": True, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "Miasma", "cc_type": "ground", "hard": False, "base_duration": 5.0, "cooldown": 18.0, "aoe": True}, {"name": "Noxious Blast", "cc_type": "slow", "hard": False, "base_duration": 0.0, "cooldown": 3.5}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 5.0, "cc_uptime_rating": 0.3}),
    "lissandra": ({"ap": 0.85, "pen": 0.5, "cdr": 0.6, "hard_cc": 0.7, "soft_cc": 0.4},
                  {"abilities": [{"name": "Ring of Frost", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 12.0, "aoe": True}, {"name": "Frozen Tomb", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}, {"name": "Ice Shard", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 8.0}], "total_hard_cc_sec": 3.0, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.4}),
    "malzahar": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.3},
                 {"abilities": [{"name": "Nether Grasp", "cc_type": "suppress", "hard": True, "base_duration": 2.5, "cooldown": 100.0}, {"name": "Call of the Void", "cc_type": "silence", "hard": False, "base_duration": 1.0, "cooldown": 11.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.2}),
    "morgana": ({"ap": 0.7, "pen": 0.4, "cdr": 0.7, "hard_cc": 0.8, "soft_cc": 0.1, "shield": 0.5},
                {"abilities": [{"name": "Dark Binding", "cc_type": "root", "hard": True, "base_duration": 3.0, "cooldown": 10.0}, {"name": "Soul Shackles", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 4.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.4}),
    "neeko": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.2},
              {"abilities": [{"name": "Tangle-Barbs", "cc_type": "root", "hard": True, "base_duration": 2.0, "cooldown": 12.0}, {"name": "Pop Blossom", "cc_type": "knockup", "hard": True, "base_duration": 1.25, "cooldown": 90.0, "aoe": True}], "total_hard_cc_sec": 3.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "orianna": ({"ap": 0.9, "pen": 0.5, "cdr": 0.6, "hard_cc": 0.5, "soft_cc": 0.3, "shield": 0.3},
                {"abilities": [{"name": "Shockwave", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 80.0, "aoe": True}, {"name": "Command: Dissonance", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 7.0, "aoe": True}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.3}),
    "syndra": ({"ap": 0.95, "pen": 0.6, "cdr": 0.4, "hard_cc": 0.5, "soft_cc": 0.2},
               {"abilities": [{"name": "Scatter the Weak", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 16.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "twistedfate": ({"ap": 0.8, "ad": 0.2, "attack_speed": 0.3, "pen": 0.4, "cdr": 0.4, "hard_cc": 0.4, "soft_cc": 0.2},
                    {"abilities": [{"name": "Gold Card", "cc_type": "stun", "hard": True, "base_duration": 2.0, "cooldown": 6.0}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.3}),
    "veigar": ({"ap": 0.95, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.6, "soft_cc": 0.1},
               {"abilities": [{"name": "Event Horizon", "cc_type": "stun", "hard": True, "base_duration": 2.5, "cooldown": 18.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "velkoz": ({"ap": 0.9, "pen": 0.6, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.2},
               {"abilities": [{"name": "Tectonic Disruption", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 16.0, "aoe": True}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "viktor": ({"ap": 0.9, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.3},
               {"abilities": [{"name": "Gravity Field", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 17.0, "aoe": True}, {"name": "Gravity Field", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 17.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.2}),
    "xerath": ({"ap": 0.9, "pen": 0.6, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.3},
               {"abilities": [{"name": "Shocking Orb", "cc_type": "stun", "hard": True, "base_duration": 2.0, "cooldown": 13.0}, {"name": "Eye of Destruction", "cc_type": "slow", "hard": False, "base_duration": 2.5, "cooldown": 14.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 2.5, "cc_uptime_rating": 0.2}),
    "ziggs": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.2, "soft_cc": 0.3},
              {"abilities": [{"name": "Satchel Charge", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 20.0}, {"name": "Hexplosive Minefield", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 16.0, "aoe": True}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.15}),
    "zyra": ({"ap": 0.85, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.6, "soft_cc": 0.3},
             {"abilities": [{"name": "Grasping Roots", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 12.0, "aoe": True}, {"name": "Stranglethorns", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "anivia": ({"ap": 0.9, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.5, "soft_cc": 0.5},
               {"abilities": [{"name": "Flash Frost", "cc_type": "stun", "hard": True, "base_duration": 1.1, "cooldown": 10.0, "aoe": True}, {"name": "Glacial Storm", "cc_type": "slow", "hard": False, "base_duration": 99.0, "cooldown": 4.0, "aoe": True}], "total_hard_cc_sec": 1.1, "total_soft_cc_sec": 99.0, "cc_uptime_rating": 0.5}),
    "aurelionsol": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.4, "soft_cc": 0.3},
                    {"abilities": [{"name": "Singularity", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 12.0, "aoe": True}, {"name": "Falling Star", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "azir": ({"ap": 0.9, "attack_speed": 0.4, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.3},
             {"abilities": [{"name": "Emperor's Divide", "cc_type": "knockback", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "hwei": ({"ap": 0.9, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.4, "shield": 0.2},
             {"abilities": [{"name": "Spiraling Despair", "cc_type": "root", "hard": True, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "Grim Visage", "cc_type": "fear", "hard": True, "base_duration": 1.5, "cooldown": 18.0}], "total_hard_cc_sec": 3.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "karma": ({"ap": 0.7, "pen": 0.3, "cdr": 0.7, "hard_cc": 0.3, "soft_cc": 0.4, "shield": 0.6},
              {"abilities": [{"name": "Focused Resolve", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 12.0}, {"name": "Inner Flame", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 7.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.25}),
    "leblanc": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.3, "soft_cc": 0.1, "lethality": 0.1},
                {"abilities": [{"name": "Ethereal Chains", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 14.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "ryze": ({"ap": 0.85, "pen": 0.5, "cdr": 0.5, "hp": 0.3, "hard_cc": 0.3},
             {"abilities": [{"name": "Rune Prison", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 13.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "swain": ({"ap": 0.8, "pen": 0.4, "cdr": 0.5, "hp": 0.5, "hard_cc": 0.4, "soft_cc": 0.3, "heal_power": 0.3},
              {"abilities": [{"name": "Nevermove", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 13.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "taliyah": ({"ap": 0.85, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.4, "soft_cc": 0.3},
                {"abilities": [{"name": "Seismic Shove", "cc_type": "knockup", "hard": True, "base_duration": 0.8, "cooldown": 14.0}, {"name": "Unraveled Earth", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 16.0, "aoe": True}], "total_hard_cc_sec": 0.8, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.2}),
    "zoe": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.5, "soft_cc": 0.2},
            {"abilities": [{"name": "Sleepy Trouble Bubble", "cc_type": "stun", "hard": True, "base_duration": 2.2, "cooldown": 16.0}], "total_hard_cc_sec": 2.2, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    # --- AP Assassins ---
    "katarina": ({"ap": 0.8, "ad": 0.4, "attack_speed": 0.2, "pen": 0.5, "lethality": 0.2, "cdr": 0.2}, None),
    "akali": ({"ap": 0.85, "ad": 0.3, "pen": 0.5, "lethality": 0.2, "cdr": 0.3}, None),
    "ekko": ({"ap": 0.85, "pen": 0.5, "cdr": 0.4, "attack_speed": 0.2, "hard_cc": 0.4, "soft_cc": 0.3},
             {"abilities": [{"name": "Parallel Convergence", "cc_type": "stun", "hard": True, "base_duration": 2.25, "cooldown": 22.0, "aoe": True}, {"name": "Timewinder", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 9.0}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.2}),
    "evelynn": ({"ap": 0.9, "pen": 0.5, "lethality": 0.2, "cdr": 0.3, "hard_cc": 0.3},
                {"abilities": [{"name": "Allure", "cc_type": "charm", "hard": True, "base_duration": 1.5, "cooldown": 14.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "fizz": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.3},
             {"abilities": [{"name": "Chum the Waters", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "diana": ({"ap": 0.85, "attack_speed": 0.3, "pen": 0.5, "cdr": 0.3, "hp": 0.3, "hard_cc": 0.3},
              {"abilities": [{"name": "Moonfall", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "kassadin": ({"ap": 0.9, "pen": 0.5, "cdr": 0.4, "hp": 0.2, "soft_cc": 0.2},
                 {"abilities": [{"name": "Null Sphere", "cc_type": "silence", "hard": False, "base_duration": 1.0, "cooldown": 11.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.1}),
    "sylas": ({"ap": 0.85, "pen": 0.4, "cdr": 0.5, "hp": 0.4, "hard_cc": 0.3, "heal_power": 0.3},
              {"abilities": [{"name": "Abscond/Abduct", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 13.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    # --- AD Assassins ---
    "zed": ({"ad": 0.9, "lethality": 0.8, "pen": 0.3, "cdr": 0.3, "attack_speed": 0.2}, None),
    "talon": ({"ad": 0.9, "lethality": 0.8, "pen": 0.2, "cdr": 0.3, "soft_cc": 0.2},
              {"abilities": [{"name": "Rake", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 9.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.1}),
    "khazix": ({"ad": 0.9, "lethality": 0.8, "cdr": 0.3, "soft_cc": 0.2},
               {"abilities": [{"name": "Void Spike", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 9.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "pyke": ({"ad": 0.8, "lethality": 0.7, "cdr": 0.5, "hp": 0.2, "hard_cc": 0.5, "soft_cc": 0.2},
             {"abilities": [{"name": "Bone Skewer", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 10.0}, {"name": "Phantom Undertow", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 15.0, "aoe": True}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "qiyana": ({"ad": 0.9, "lethality": 0.7, "cdr": 0.3, "hard_cc": 0.4, "soft_cc": 0.3},
               {"abilities": [{"name": "Supreme Display of Talent", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}, {"name": "Audacity", "cc_type": "root", "hard": True, "base_duration": 0.5, "cooldown": 7.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "rengar": ({"ad": 0.9, "lethality": 0.7, "crit": 0.3, "attack_speed": 0.3, "cdr": 0.3, "hard_cc": 0.2},
               {"abilities": [{"name": "Bola Strike", "cc_type": "root", "hard": True, "base_duration": 1.75, "cooldown": 0.0}], "total_hard_cc_sec": 1.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "shaco": ({"ap": 0.4, "ad": 0.6, "attack_speed": 0.3, "lethality": 0.5, "cdr": 0.3, "hard_cc": 0.2, "soft_cc": 0.2},
              {"abilities": [{"name": "Jack In The Box", "cc_type": "fear", "hard": True, "base_duration": 1.0, "cooldown": 15.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "naafiri": ({"ad": 0.9, "lethality": 0.7, "cdr": 0.3}, None),
    # --- Fighters / Bruisers ---
    "aatrox": ({"ad": 0.8, "hp": 0.6, "cdr": 0.5, "heal_power": 0.4, "hard_cc": 0.3, "soft_cc": 0.2},
               {"abilities": [{"name": "The Darkin Blade", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 12.0, "aoe": True}, {"name": "Infernal Chains", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 20.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.15}),
    "camille": ({"ad": 0.8, "attack_speed": 0.4, "hp": 0.4, "cdr": 0.3, "hard_cc": 0.4, "shield": 0.2},
                {"abilities": [{"name": "Hookshot", "cc_type": "stun", "hard": True, "base_duration": 0.75, "cooldown": 16.0}, {"name": "Hextech Ultimatum", "cc_type": "knockback", "hard": True, "base_duration": 2.5, "cooldown": 100.0}], "total_hard_cc_sec": 3.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "darius": ({"ad": 0.8, "hp": 0.7, "attack_speed": 0.2, "pen": 0.3, "cdr": 0.3, "soft_cc": 0.3},
               {"abilities": [{"name": "Apprehend", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 24.0, "aoe": True}, {"name": "Crippling Strike", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 5.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "fiora": ({"ad": 0.9, "attack_speed": 0.3, "hp": 0.3, "cdr": 0.3, "hard_cc": 0.2, "heal_power": 0.2},
              {"abilities": [{"name": "Riposte", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 24.0}, {"name": "Riposte", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 24.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.1}),
    "garen": ({"ad": 0.5, "hp": 0.9, "attack_speed": 0.2, "lethality": 0.3, "pen": 0.2, "crit": 0.3, "cdr": 0.3, "soft_cc": 0.2, "shield": 0.2},
              {"abilities": [{"name": "Decisive Strike", "cc_type": "silence", "hard": False, "base_duration": 1.5, "cooldown": 8.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.1}),
    "gwen": ({"ap": 0.9, "attack_speed": 0.5, "hp": 0.3, "pen": 0.4, "cdr": 0.3, "soft_cc": 0.2},
             {"abilities": [{"name": "Needlework", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 80.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.05}),
    "illaoi": ({"ad": 0.7, "hp": 0.8, "cdr": 0.4, "heal_power": 0.3}, None),
    "irelia": ({"ad": 0.8, "attack_speed": 0.6, "hp": 0.3, "cdr": 0.3, "hard_cc": 0.3, "soft_cc": 0.2},
               {"abilities": [{"name": "Vanguard's Edge", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "Flawless Duet", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 16.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "jax": ({"ad": 0.7, "attack_speed": 0.6, "hp": 0.5, "cdr": 0.3, "hard_cc": 0.3, "shield": 0.1},
            {"abilities": [{"name": "Counter Strike", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 14.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "mordekaiser": ({"ap": 0.8, "hp": 0.6, "pen": 0.5, "cdr": 0.4, "shield": 0.2},
                    {"abilities": [{"name": "Death's Grasp", "cc_type": "slow", "hard": False, "base_duration": 0.5, "cooldown": 18.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 0.5, "cc_uptime_rating": 0.05}),
    "nasus": ({"ad": 0.5, "hp": 0.8, "cdr": 0.7, "soft_cc": 0.5},
              {"abilities": [{"name": "Wither", "cc_type": "slow", "hard": False, "base_duration": 5.0, "cooldown": 15.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 5.0, "cc_uptime_rating": 0.35}),
    "olaf": ({"ad": 0.7, "attack_speed": 0.5, "hp": 0.6, "cdr": 0.3, "heal_power": 0.3, "soft_cc": 0.2},
             {"abilities": [{"name": "Undertow", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 7.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.2}),
    "pantheon": ({"ad": 0.8, "lethality": 0.4, "hp": 0.4, "cdr": 0.4, "hard_cc": 0.3},
                 {"abilities": [{"name": "Shield Vault", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 13.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "renekton": ({"ad": 0.7, "hp": 0.7, "cdr": 0.3, "hard_cc": 0.3},
                 {"abilities": [{"name": "Ruthless Predator", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 13.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "riven": ({"ad": 0.9, "cdr": 0.6, "hp": 0.2, "shield": 0.2, "hard_cc": 0.3, "soft_cc": 0.1},
              {"abilities": [{"name": "Ki Burst", "cc_type": "stun", "hard": True, "base_duration": 0.75, "cooldown": 11.0, "aoe": True}, {"name": "Broken Wings", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 13.0}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "sett": ({"ad": 0.7, "hp": 0.7, "attack_speed": 0.3, "cdr": 0.3, "hard_cc": 0.5, "shield": 0.3},
             {"abilities": [{"name": "Facebreaker", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 16.0, "aoe": True}, {"name": "The Show Stopper", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "trundle": ({"ad": 0.7, "attack_speed": 0.5, "hp": 0.6, "cdr": 0.3, "soft_cc": 0.4},
                {"abilities": [{"name": "Pillar of Ice", "cc_type": "slow", "hard": False, "base_duration": 6.0, "cooldown": 22.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 6.0, "cc_uptime_rating": 0.25}),
    "tryndamere": ({"ad": 0.8, "attack_speed": 0.6, "crit": 0.7, "hp": 0.2, "cdr": 0.2, "soft_cc": 0.2},
                   {"abilities": [{"name": "Mocking Shout", "cc_type": "slow", "hard": False, "base_duration": 4.0, "cooldown": 14.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 4.0, "cc_uptime_rating": 0.2}),
    "urgot": ({"ad": 0.7, "attack_speed": 0.4, "hp": 0.7, "cdr": 0.3, "hard_cc": 0.4, "soft_cc": 0.2},
              {"abilities": [{"name": "Disdain", "cc_type": "knockback", "hard": True, "base_duration": 0.75, "cooldown": 16.0}, {"name": "Fear Beyond Death", "cc_type": "suppress", "hard": True, "base_duration": 1.5, "cooldown": 80.0}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "vi": ({"ad": 0.8, "attack_speed": 0.3, "hp": 0.6, "lethality": 0.5, "pen": 0.3, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.1},
           {"abilities": [{"name": "Vault Breaker", "cc_type": "knockback", "hard": True, "base_duration": 0.7, "cooldown": 8.0}, {"name": "Assault and Battery", "cc_type": "knockup", "hard": True, "base_duration": 1.3, "cooldown": 80.0}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "warwick": ({"ad": 0.6, "attack_speed": 0.5, "hp": 0.6, "cdr": 0.3, "heal_power": 0.4, "hard_cc": 0.4},
                {"abilities": [{"name": "Infinite Duress", "cc_type": "suppress", "hard": True, "base_duration": 1.5, "cooldown": 80.0}, {"name": "Primal Howl", "cc_type": "fear", "hard": True, "base_duration": 1.0, "cooldown": 15.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "wukong": ({"ad": 0.8, "hp": 0.5, "cdr": 0.3, "hard_cc": 0.5},
               {"abilities": [{"name": "Cyclone", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "xinzhao": ({"ad": 0.7, "attack_speed": 0.6, "hp": 0.5, "cdr": 0.3, "hard_cc": 0.4},
                {"abilities": [{"name": "Three Talon Strike", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 7.0}, {"name": "Crescent Guard", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "yasuo": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.9, "cdr": 0.2, "hard_cc": 0.3},
              {"abilities": [{"name": "Last Breath", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 30.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "yone": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.8, "cdr": 0.2, "hard_cc": 0.4},
             {"abilities": [{"name": "Mortal Steel", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 4.0}, {"name": "Fate Sealed", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 1.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "yorick": ({"ad": 0.6, "hp": 0.7, "cdr": 0.4, "soft_cc": 0.3},
               {"abilities": [{"name": "Dark Procession", "cc_type": "slow", "hard": False, "base_duration": 4.0, "cooldown": 20.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 4.0, "cc_uptime_rating": 0.15}),
    "belveth": ({"ad": 0.7, "attack_speed": 0.8, "hp": 0.4, "cdr": 0.2, "hard_cc": 0.2},
                {"abilities": [{"name": "Royal Maelstrom", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 20.0}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "briar": ({"ad": 0.8, "attack_speed": 0.5, "hp": 0.5, "cdr": 0.2, "heal_power": 0.3, "hard_cc": 0.3},
              {"abilities": [{"name": "Certain Death", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0}, {"name": "Chilling Scream", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 14.0}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "viego": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.3, "hp": 0.3, "cdr": 0.3, "hard_cc": 0.2},
              {"abilities": [{"name": "Spectral Maw", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 11.0}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "hecarim": ({"ad": 0.7, "hp": 0.6, "cdr": 0.4, "attack_speed": 0.2, "hard_cc": 0.4, "soft_cc": 0.2},
                {"abilities": [{"name": "Onslaught of Shadows", "cc_type": "fear", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}, {"name": "Devastating Charge", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 20.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "jarvaniv": ({"ad": 0.7, "hp": 0.6, "cdr": 0.4, "hard_cc": 0.5, "soft_cc": 0.2},
                 {"abilities": [{"name": "Demacian Standard + Dragon Strike", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 12.0, "aoe": True}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "leesin": ({"ad": 0.8, "hp": 0.4, "cdr": 0.4, "lethality": 0.3, "hard_cc": 0.4, "shield": 0.2},
               {"abilities": [{"name": "Dragon's Rage", "cc_type": "knockback", "hard": True, "base_duration": 1.0, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "nocturne": ({"ad": 0.8, "attack_speed": 0.5, "lethality": 0.5, "cdr": 0.3, "hard_cc": 0.2, "soft_cc": 0.2},
                 {"abilities": [{"name": "Unspeakable Horror", "cc_type": "fear", "hard": True, "base_duration": 1.75, "cooldown": 15.0}], "total_hard_cc_sec": 1.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "masteryi": ({"ad": 0.7, "attack_speed": 0.9, "crit": 0.4, "hp": 0.1, "cdr": 0.2}, None),
    "udyr": ({"ad": 0.5, "attack_speed": 0.4, "hp": 0.7, "cdr": 0.4, "hard_cc": 0.3, "soft_cc": 0.2, "shield": 0.2},
             {"abilities": [{"name": "Blazing Stampede", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 16.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "volibear": ({"ap": 0.3, "ad": 0.5, "attack_speed": 0.4, "hp": 0.8, "cdr": 0.3, "hard_cc": 0.4, "soft_cc": 0.2},
                 {"abilities": [{"name": "Thundering Smash", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 14.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    # --- Tanks ---
    "alistar": ({"hp": 0.8, "cdr": 0.6, "hard_cc": 0.9, "soft_cc": 0.1, "shield": 0.2, "heal_power": 0.2},
                {"abilities": [{"name": "Pulverize", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 15.0, "aoe": True}, {"name": "Headbutt", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 14.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "amumu": ({"ap": 0.4, "hp": 0.8, "cdr": 0.5, "pen": 0.3, "hard_cc": 0.7, "soft_cc": 0.1},
              {"abilities": [{"name": "Bandage Toss", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 10.0}, {"name": "Curse of the Sad Mummy", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "braum": ({"hp": 0.8, "cdr": 0.5, "hard_cc": 0.7, "soft_cc": 0.3, "shield": 0.5},
              {"abilities": [{"name": "Concussive Blows", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 0.0}, {"name": "Glacial Fissure", "cc_type": "knockup", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.3}),
    "chogath": ({"ap": 0.4, "hp": 0.9, "pen": 0.2, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.3},
                {"abilities": [{"name": "Rupture", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 7.0, "aoe": True}, {"name": "Feral Scream", "cc_type": "silence", "hard": False, "base_duration": 1.6, "cooldown": 13.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 1.6, "cc_uptime_rating": 0.3}),
    "drmundo": ({"hp": 0.9, "ad": 0.4, "heal_power": 0.5, "cdr": 0.3, "soft_cc": 0.2},
                {"abilities": [{"name": "Infected Bonesaw", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 4.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.3}),
    "galio": ({"ap": 0.5, "hp": 0.7, "pen": 0.3, "cdr": 0.5, "hard_cc": 0.7, "soft_cc": 0.1, "shield": 0.3},
              {"abilities": [{"name": "Justice Punch", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 12.0}, {"name": "Shield of Durand", "cc_type": "taunt", "hard": True, "base_duration": 1.5, "cooldown": 18.0, "aoe": True}, {"name": "Hero's Entrance", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 180.0, "aoe": True}], "total_hard_cc_sec": 3.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.3}),
    "gragas": ({"ap": 0.6, "hp": 0.6, "pen": 0.3, "cdr": 0.5, "hard_cc": 0.5, "soft_cc": 0.3},
               {"abilities": [{"name": "Body Slam", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 14.0}, {"name": "Explosive Cask", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 80.0, "aoe": True}, {"name": "Barrel Roll", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 10.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.25}),
    "ksante": ({"ad": 0.5, "hp": 0.8, "cdr": 0.4, "hard_cc": 0.5, "shield": 0.2},
               {"abilities": [{"name": "Footwork", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 9.0}, {"name": "All Out", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 100.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "leona": ({"hp": 0.8, "cdr": 0.6, "hard_cc": 0.9, "soft_cc": 0.1, "shield": 0.2},
              {"abilities": [{"name": "Shield of Daybreak", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 5.0}, {"name": "Zenith Blade", "cc_type": "root", "hard": True, "base_duration": 0.5, "cooldown": 12.0}, {"name": "Solar Flare", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 3.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.45}),
    "malphite": ({"ap": 0.5, "hp": 0.8, "pen": 0.3, "cdr": 0.4, "hard_cc": 0.7, "soft_cc": 0.3},
                 {"abilities": [{"name": "Unstoppable Force", "cc_type": "knockup", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}, {"name": "Ground Slam", "cc_type": "slow", "hard": False, "base_duration": 3.0, "cooldown": 7.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.25}),
    "maokai": ({"ap": 0.3, "hp": 0.8, "cdr": 0.5, "hard_cc": 0.7, "soft_cc": 0.3, "heal_power": 0.2},
               {"abilities": [{"name": "Twisted Advance", "cc_type": "root", "hard": True, "base_duration": 1.0, "cooldown": 13.0}, {"name": "Nature's Grasp", "cc_type": "root", "hard": True, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "Bramble Smash", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 8.0}], "total_hard_cc_sec": 3.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.3}),
    "nautilus": ({"hp": 0.8, "cdr": 0.5, "hard_cc": 0.9, "soft_cc": 0.2, "shield": 0.3},
                 {"abilities": [{"name": "Staggering Blow", "cc_type": "root", "hard": True, "base_duration": 1.0, "cooldown": 0.0}, {"name": "Dredge Line", "cc_type": "stun", "hard": True, "base_duration": 0.5, "cooldown": 14.0}, {"name": "Depth Charge", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.4}),
    "ornn": ({"hp": 0.8, "cdr": 0.4, "hard_cc": 0.7, "soft_cc": 0.2, "shield": 0.1},
             {"abilities": [{"name": "Bellows Breath", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 12.0}, {"name": "Call of the Forge God", "cc_type": "knockup", "hard": True, "base_duration": 1.5, "cooldown": 120.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "poppy": ({"ad": 0.4, "hp": 0.7, "cdr": 0.4, "hard_cc": 0.6, "shield": 0.3},
              {"abilities": [{"name": "Heroic Charge", "cc_type": "stun", "hard": True, "base_duration": 1.6, "cooldown": 14.0}, {"name": "Keeper's Verdict", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}, {"name": "Steadfast Presence", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 20.0, "aoe": True}], "total_hard_cc_sec": 2.6, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.25}),
    "rammus": ({"hp": 0.8, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.4},
               {"abilities": [{"name": "Frenzying Taunt", "cc_type": "taunt", "hard": True, "base_duration": 2.0, "cooldown": 12.0}, {"name": "Soaring Slam", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.2}),
    "sejuani": ({"hp": 0.8, "cdr": 0.5, "hard_cc": 0.8, "soft_cc": 0.3},
                {"abilities": [{"name": "Permafrost", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 1.5, "aoe": True}, {"name": "Glacial Prison", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}, {"name": "Arctic Assault", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 18.0}], "total_hard_cc_sec": 3.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.4}),
    "shen": ({"hp": 0.7, "cdr": 0.5, "hard_cc": 0.4, "shield": 0.6},
             {"abilities": [{"name": "Shadow Dash", "cc_type": "taunt", "hard": True, "base_duration": 1.5, "cooldown": 18.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "singed": ({"ap": 0.5, "hp": 0.7, "cdr": 0.3, "pen": 0.3, "hard_cc": 0.3, "soft_cc": 0.5},
               {"abilities": [{"name": "Fling", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 10.0}, {"name": "Mega Adhesive", "cc_type": "ground", "hard": False, "base_duration": 3.0, "cooldown": 17.0, "aoe": True}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.2}),
    "sion": ({"ad": 0.4, "hp": 0.9, "cdr": 0.4, "hard_cc": 0.6, "soft_cc": 0.3},
             {"abilities": [{"name": "Decimating Smash", "cc_type": "knockup", "hard": True, "base_duration": 1.25, "cooldown": 10.0, "aoe": True}, {"name": "Roar of the Slayer", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 11.0}, {"name": "Unstoppable Onslaught", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 100.0}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.25}),
    "tahmkench": ({"hp": 0.9, "cdr": 0.4, "hard_cc": 0.5, "soft_cc": 0.3, "shield": 0.3},
                  {"abilities": [{"name": "Tongue Lash", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 7.0}, {"name": "Devour", "cc_type": "suppress", "hard": True, "base_duration": 1.0, "cooldown": 20.0}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "thresh": ({"ap": 0.3, "hp": 0.4, "cdr": 0.7, "hard_cc": 0.8, "soft_cc": 0.3, "shield": 0.4},
               {"abilities": [{"name": "Death Sentence", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 16.0}, {"name": "Flay", "cc_type": "knockback", "hard": True, "base_duration": 0.75, "cooldown": 9.0, "aoe": True}, {"name": "The Box", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.45}),
    "zac": ({"ap": 0.3, "hp": 0.8, "cdr": 0.4, "hard_cc": 0.7, "soft_cc": 0.2},
            {"abilities": [{"name": "Elastic Slingshot", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 18.0, "aoe": True}, {"name": "Let's Bounce!", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    # --- Marksmen ---
    "ashe": ({"ad": 0.8, "attack_speed": 0.6, "crit": 0.7, "cdr": 0.2, "hard_cc": 0.5, "soft_cc": 0.6},
             {"abilities": [{"name": "Enchanted Crystal Arrow", "cc_type": "stun", "hard": True, "base_duration": 3.5, "cooldown": 80.0, "aoe": True}, {"name": "Frost Shot", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 0.0}], "total_hard_cc_sec": 3.5, "total_soft_cc_sec": 99.0, "cc_uptime_rating": 0.5}),
    "caitlyn": ({"ad": 0.9, "attack_speed": 0.5, "crit": 0.8, "lethality": 0.3, "cdr": 0.2, "soft_cc": 0.2},
                {"abilities": [{"name": "Yordle Snap Trap", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 30.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "draven": ({"ad": 0.9, "attack_speed": 0.5, "crit": 0.6, "lethality": 0.3, "cdr": 0.1, "hard_cc": 0.2, "soft_cc": 0.2},
               {"abilities": [{"name": "Stand Aside", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 18.0}, {"name": "Stand Aside", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 18.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.1}),
    "ezreal": ({"ap": 0.4, "ad": 0.7, "attack_speed": 0.3, "pen": 0.3, "cdr": 0.4, "lethality": 0.2}, None),
    "jhin": ({"ad": 0.9, "crit": 0.6, "lethality": 0.4, "cdr": 0.3, "attack_speed": 0.1, "hard_cc": 0.2, "soft_cc": 0.4},
             {"abilities": [{"name": "Deadly Flourish", "cc_type": "root", "hard": True, "base_duration": 1.25, "cooldown": 14.0}, {"name": "Captive Audience", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 2.0, "aoe": True}, {"name": "Curtain Call", "cc_type": "slow", "hard": False, "base_duration": 0.5, "cooldown": 100.0}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 2.5, "cc_uptime_rating": 0.2}),
    "jinx": ({"ad": 0.8, "attack_speed": 0.7, "crit": 0.9, "hp": 0.1, "lethality": 0.2, "pen": 0.3, "cdr": 0.2, "hard_cc": 0.3, "soft_cc": 0.2},
             {"abilities": [{"name": "Flame Chompers!", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 18.0}, {"name": "Zap!", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 6.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "kaisa": ({"ap": 0.4, "ad": 0.7, "attack_speed": 0.7, "pen": 0.3, "cdr": 0.2}, None),
    "kalista": ({"ad": 0.8, "attack_speed": 0.8, "hp": 0.1, "cdr": 0.1, "hard_cc": 0.3},
                {"abilities": [{"name": "Fate's Call", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "kogmaw": ({"ap": 0.5, "ad": 0.5, "attack_speed": 0.8, "pen": 0.4, "cdr": 0.2, "soft_cc": 0.2},
               {"abilities": [{"name": "Void Ooze", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 12.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.1}),
    "lucian": ({"ad": 0.9, "attack_speed": 0.4, "crit": 0.5, "cdr": 0.3, "lethality": 0.2}, None),
    "missfortune": ({"ad": 0.8, "lethality": 0.5, "crit": 0.5, "attack_speed": 0.3, "cdr": 0.3, "soft_cc": 0.3},
                    {"abilities": [{"name": "Make it Rain", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 14.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "samira": ({"ad": 0.9, "attack_speed": 0.4, "crit": 0.6, "cdr": 0.2, "hard_cc": 0.2},
               {"abilities": [{"name": "Wild Rush", "cc_type": "knockup", "hard": True, "base_duration": 0.5, "cooldown": 20.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "sivir": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.7, "cdr": 0.2, "shield": 0.2}, None),
    "smolder": ({"ad": 0.8, "attack_speed": 0.3, "crit": 0.4, "cdr": 0.3, "soft_cc": 0.2},
                {"abilities": [{"name": "MMOOOMMMM!", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.1}),
    "tristana": ({"ad": 0.8, "attack_speed": 0.7, "crit": 0.7, "cdr": 0.2, "hard_cc": 0.2},
                 {"abilities": [{"name": "Buster Shot", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 80.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "twitch": ({"ad": 0.8, "attack_speed": 0.7, "crit": 0.6, "ap": 0.2, "pen": 0.3, "cdr": 0.1, "soft_cc": 0.2},
               {"abilities": [{"name": "Venom Cask", "cc_type": "slow", "hard": False, "base_duration": 3.0, "cooldown": 13.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.15}),
    "varus": ({"ad": 0.7, "attack_speed": 0.5, "ap": 0.3, "pen": 0.4, "cdr": 0.3, "lethality": 0.4, "hard_cc": 0.4, "soft_cc": 0.2},
              {"abilities": [{"name": "Chain of Corruption", "cc_type": "root", "hard": True, "base_duration": 2.0, "cooldown": 80.0, "aoe": True}, {"name": "Hail of Arrows", "cc_type": "slow", "hard": False, "base_duration": 4.0, "cooldown": 18.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 4.0, "cc_uptime_rating": 0.2}),
    "vayne": ({"ad": 0.8, "attack_speed": 0.7, "crit": 0.5, "hp": 0.1, "cdr": 0.1, "hard_cc": 0.2},
              {"abilities": [{"name": "Condemn", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 20.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "xayah": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.7, "cdr": 0.2, "hard_cc": 0.3},
              {"abilities": [{"name": "Bladecaller", "cc_type": "root", "hard": True, "base_duration": 1.25, "cooldown": 11.0}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "zeri": ({"ad": 0.7, "attack_speed": 0.6, "crit": 0.5, "ap": 0.2, "cdr": 0.2, "soft_cc": 0.3},
             {"abilities": [{"name": "Ultrashock Laser", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 10.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.15}),
    "aphelios": ({"ad": 0.9, "attack_speed": 0.6, "crit": 0.7, "cdr": 0.1, "hard_cc": 0.2, "soft_cc": 0.3},
                 {"abilities": [{"name": "Gravitum", "cc_type": "root", "hard": True, "base_duration": 1.0, "cooldown": 9.0, "aoe": True}, {"name": "Gravitum", "cc_type": "slow", "hard": False, "base_duration": 3.5, "cooldown": 0.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 3.5, "cc_uptime_rating": 0.15}),
    "nilah": ({"ad": 0.8, "attack_speed": 0.5, "crit": 0.6, "cdr": 0.2, "heal_power": 0.2, "shield": 0.2},
              {"abilities": [{"name": "Jubilant Veil", "cc_type": "slow", "hard": False, "base_duration": 0.0, "cooldown": 0.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.0}),
    # --- Supports ---
    "bard": ({"ap": 0.4, "cdr": 0.6, "hp": 0.3, "hard_cc": 0.6, "soft_cc": 0.3, "shield": 0.2, "heal_power": 0.3},
             {"abilities": [{"name": "Cosmic Binding", "cc_type": "stun", "hard": True, "base_duration": 1.8, "cooldown": 11.0}, {"name": "Tempered Fate", "cc_type": "stun", "hard": True, "base_duration": 2.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 4.3, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.25}),
    "janna": ({"ap": 0.4, "cdr": 0.7, "heal_power": 0.5, "shield": 0.8, "hard_cc": 0.5, "soft_cc": 0.4},
              {"abilities": [{"name": "Howling Gale", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 12.0, "aoe": True}, {"name": "Monsoon", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 130.0, "aoe": True}, {"name": "Zephyr", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 8.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.25}),
    "lulu": ({"ap": 0.5, "cdr": 0.7, "shield": 0.7, "hard_cc": 0.4, "soft_cc": 0.4, "attack_speed": 0.2},
             {"abilities": [{"name": "Wild Growth", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 100.0, "aoe": True}, {"name": "Whimsy", "cc_type": "polymorph", "hard": True, "base_duration": 1.5, "cooldown": 17.0}, {"name": "Glitterlance", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 7.0}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.3}),
    "nami": ({"ap": 0.5, "cdr": 0.7, "heal_power": 0.7, "hard_cc": 0.6, "soft_cc": 0.3, "shield": 0.1},
             {"abilities": [{"name": "Aqua Prison", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 10.0}, {"name": "Tidal Wave", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "rakan": ({"ap": 0.4, "cdr": 0.6, "hp": 0.3, "hard_cc": 0.7, "shield": 0.4, "heal_power": 0.2},
              {"abilities": [{"name": "Grand Entrance", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 12.0, "aoe": True}, {"name": "The Quickness", "cc_type": "charm", "hard": True, "base_duration": 1.0, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "senna": ({"ad": 0.6, "crit": 0.3, "cdr": 0.4, "heal_power": 0.5, "shield": 0.3, "hard_cc": 0.2, "soft_cc": 0.2},
              {"abilities": [{"name": "Last Embrace", "cc_type": "root", "hard": True, "base_duration": 1.25, "cooldown": 11.0}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "seraphine": ({"ap": 0.7, "cdr": 0.6, "heal_power": 0.4, "shield": 0.4, "hard_cc": 0.5, "soft_cc": 0.3},
                  {"abilities": [{"name": "Encore", "cc_type": "charm", "hard": True, "base_duration": 1.5, "cooldown": 120.0, "aoe": True}, {"name": "Beat Drop", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 10.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.2}),
    "sona": ({"ap": 0.7, "hp": 0.2, "pen": 0.3, "cdr": 0.8, "heal_power": 0.6, "hard_cc": 0.4, "soft_cc": 0.3, "shield": 0.3},
             {"abilities": [{"name": "Crescendo", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}, {"name": "Song of Celerity", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 12.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.2}),
    "soraka": ({"ap": 0.5, "hp": 0.3, "pen": 0.1, "cdr": 0.8, "heal_power": 1.0, "hard_cc": 0.2, "soft_cc": 0.4, "shield": 0.1},
               {"abilities": [{"name": "Starcall", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 6.0, "aoe": True}, {"name": "Equinox", "cc_type": "silence", "hard": False, "base_duration": 1.5, "cooldown": 20.0, "aoe": True}, {"name": "Equinox Root", "cc_type": "root", "hard": True, "base_duration": 1.5, "cooldown": 20.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.3}),
    "taric": ({"hp": 0.6, "cdr": 0.6, "heal_power": 0.5, "shield": 0.5, "hard_cc": 0.5},
              {"abilities": [{"name": "Dazzle", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 15.0, "aoe": True}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "yuumi": ({"ap": 0.6, "cdr": 0.7, "heal_power": 0.8, "shield": 0.3, "hard_cc": 0.3, "soft_cc": 0.3},
              {"abilities": [{"name": "Final Chapter", "cc_type": "root", "hard": True, "base_duration": 1.75, "cooldown": 100.0, "aoe": True}, {"name": "Prowling Projectile", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 7.0}], "total_hard_cc_sec": 1.75, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.15}),
    "zilean": ({"ap": 0.7, "cdr": 0.8, "hard_cc": 0.4, "soft_cc": 0.5},
               {"abilities": [{"name": "Time Bomb", "cc_type": "stun", "hard": True, "base_duration": 1.5, "cooldown": 10.0, "aoe": True}, {"name": "Time Warp", "cc_type": "slow", "hard": False, "base_duration": 2.5, "cooldown": 15.0}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 2.5, "cc_uptime_rating": 0.25}),
    "milio": ({"ap": 0.5, "cdr": 0.7, "heal_power": 0.6, "shield": 0.6, "hard_cc": 0.2, "soft_cc": 0.3},
              {"abilities": [{"name": "Ultra Mega Fire Kick", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 12.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "renata": ({"ap": 0.4, "cdr": 0.6, "shield": 0.5, "hard_cc": 0.5, "soft_cc": 0.3},
               {"abilities": [{"name": "Handshake", "cc_type": "root", "hard": True, "base_duration": 1.0, "cooldown": 16.0}, {"name": "Hostile Takeover", "cc_type": "berserk", "hard": True, "base_duration": 1.25, "cooldown": 120.0, "aoe": True}], "total_hard_cc_sec": 2.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    # --- Others / Unique ---
    "teemo": ({"ap": 0.8, "ad": 0.3, "attack_speed": 0.6, "pen": 0.5, "cdr": 0.3, "soft_cc": 0.5},
              {"abilities": [{"name": "Blinding Dart", "cc_type": "blind", "hard": False, "base_duration": 2.0, "cooldown": 7.0}, {"name": "Noxious Trap", "cc_type": "slow", "hard": False, "base_duration": 4.0, "cooldown": 0.25, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 6.0, "cc_uptime_rating": 0.4}),
    "kayle": ({"ap": 0.7, "ad": 0.5, "attack_speed": 0.8, "hp": 0.2, "pen": 0.5, "crit": 0.3, "cdr": 0.3, "heal_power": 0.4, "soft_cc": 0.1, "shield": 0.2},
              {"abilities": [{"name": "Radiant Blast", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 12.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.05}),
    "heimerdinger": ({"ap": 0.9, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.2},
                     {"abilities": [{"name": "CH-2 Electron Storm Grenade", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 11.0, "aoe": True}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "ivern": ({"ap": 0.4, "cdr": 0.7, "shield": 0.7, "hard_cc": 0.5, "soft_cc": 0.3, "heal_power": 0.3},
              {"abilities": [{"name": "Rootcaller", "cc_type": "root", "hard": True, "base_duration": 1.2, "cooldown": 12.0}, {"name": "Daisy!", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 120.0, "aoe": True}], "total_hard_cc_sec": 2.2, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "kennen": ({"ap": 0.85, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.6, "attack_speed": 0.2},
               {"abilities": [{"name": "Mark of the Storm", "cc_type": "stun", "hard": True, "base_duration": 1.25, "cooldown": 0.0, "aoe": True}], "total_hard_cc_sec": 1.25, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.3}),
    "lillia": ({"ap": 0.85, "hp": 0.3, "pen": 0.4, "cdr": 0.4, "hard_cc": 0.4, "soft_cc": 0.3},
               {"abilities": [{"name": "Lilting Lullaby", "cc_type": "stun", "hard": True, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "Swirlseed", "cc_type": "slow", "hard": False, "base_duration": 3.0, "cooldown": 18.0}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.2}),
    "nidalee": ({"ap": 0.85, "attack_speed": 0.3, "pen": 0.4, "cdr": 0.4, "heal_power": 0.3}, None),
    "rumble": ({"ap": 0.85, "pen": 0.5, "cdr": 0.3, "hp": 0.3, "soft_cc": 0.3},
               {"abilities": [{"name": "Electro Harpoon", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 10.0}, {"name": "The Equalizer", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 3.5, "cc_uptime_rating": 0.2}),
    "vladimir": ({"ap": 0.9, "hp": 0.4, "pen": 0.5, "cdr": 0.5, "heal_power": 0.3}, None),
    "fiddlesticks": ({"ap": 0.9, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.5, "soft_cc": 0.3},
                     {"abilities": [{"name": "Terrify", "cc_type": "fear", "hard": True, "base_duration": 1.5, "cooldown": 15.0}, {"name": "Reap", "cc_type": "silence", "hard": False, "base_duration": 1.0, "cooldown": 10.0, "aoe": True}], "total_hard_cc_sec": 1.5, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.2}),
    "elise": ({"ap": 0.8, "pen": 0.5, "cdr": 0.4, "hard_cc": 0.3},
              {"abilities": [{"name": "Cocoon", "cc_type": "stun", "hard": True, "base_duration": 1.6, "cooldown": 12.0}], "total_hard_cc_sec": 1.6, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.1}),
    "graves": ({"ad": 0.8, "lethality": 0.5, "crit": 0.4, "attack_speed": 0.3, "hp": 0.3, "cdr": 0.2, "soft_cc": 0.2},
               {"abilities": [{"name": "Smoke Screen", "cc_type": "slow", "hard": False, "base_duration": 4.0, "cooldown": 24.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 4.0, "cc_uptime_rating": 0.15}),
    "kindred": ({"ad": 0.7, "attack_speed": 0.6, "crit": 0.5, "cdr": 0.2, "soft_cc": 0.2},
                {"abilities": [{"name": "Mounting Dread", "cc_type": "slow", "hard": False, "base_duration": 1.0, "cooldown": 14.0}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.0, "cc_uptime_rating": 0.05}),
    "kled": ({"ad": 0.8, "hp": 0.5, "attack_speed": 0.3, "cdr": 0.3, "hard_cc": 0.3},
             {"abilities": [{"name": "Bear Trap on a Rope", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 11.0}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "nunu": ({"ap": 0.6, "hp": 0.7, "cdr": 0.4, "hard_cc": 0.5, "soft_cc": 0.4, "heal_power": 0.3},
             {"abilities": [{"name": "Biggest Snowball Ever!", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 14.0, "aoe": True}, {"name": "Absolute Zero", "cc_type": "slow", "hard": False, "base_duration": 3.0, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 3.0, "cc_uptime_rating": 0.2}),
    "reksai": ({"ad": 0.7, "attack_speed": 0.4, "hp": 0.6, "cdr": 0.3, "hard_cc": 0.4},
               {"abilities": [{"name": "Unburrow", "cc_type": "knockup", "hard": True, "base_duration": 1.0, "cooldown": 1.0, "aoe": True}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.15}),
    "shyvana": ({"ap": 0.5, "ad": 0.4, "attack_speed": 0.5, "hp": 0.6, "pen": 0.3, "cdr": 0.2, "hard_cc": 0.2},
                {"abilities": [{"name": "Dragon's Descent", "cc_type": "knockback", "hard": True, "base_duration": 0.5, "cooldown": 100.0, "aoe": True}], "total_hard_cc_sec": 0.5, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
    "skarner": ({"hp": 0.7, "ad": 0.5, "attack_speed": 0.3, "cdr": 0.4, "hard_cc": 0.7, "soft_cc": 0.3},
                {"abilities": [{"name": "Impale", "cc_type": "suppress", "hard": True, "base_duration": 1.75, "cooldown": 100.0, "aoe": True}, {"name": "Ixtal's Impact", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 12.0}], "total_hard_cc_sec": 2.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.2}),
    "twistedfate": ({"ap": 0.8, "ad": 0.2, "attack_speed": 0.3, "pen": 0.4, "cdr": 0.4, "hard_cc": 0.4, "soft_cc": 0.2},
                    {"abilities": [{"name": "Gold Card", "cc_type": "stun", "hard": True, "base_duration": 2.0, "cooldown": 6.0}], "total_hard_cc_sec": 2.0, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.3}),
    "aurora": ({"ap": 0.85, "pen": 0.5, "cdr": 0.5, "hard_cc": 0.3, "soft_cc": 0.4},
               {"abilities": [{"name": "Between Worlds", "cc_type": "slow", "hard": False, "base_duration": 2.0, "cooldown": 100.0, "aoe": True}, {"name": "The Weirding", "cc_type": "stun", "hard": True, "base_duration": 1.0, "cooldown": 14.0}], "total_hard_cc_sec": 1.0, "total_soft_cc_sec": 2.0, "cc_uptime_rating": 0.2}),
    "mel": ({"ap": 0.85, "pen": 0.5, "cdr": 0.5, "shield": 0.3, "hard_cc": 0.2, "soft_cc": 0.2},
            {"abilities": [{"name": "Purge", "cc_type": "slow", "hard": False, "base_duration": 1.5, "cooldown": 14.0, "aoe": True}], "total_hard_cc_sec": 0.0, "total_soft_cc_sec": 1.5, "cc_uptime_rating": 0.1}),
    "ambessa": ({"ad": 0.8, "hp": 0.4, "attack_speed": 0.3, "cdr": 0.3, "lethality": 0.3, "hard_cc": 0.3, "soft_cc": 0.1},
                {"abilities": [{"name": "Public Execution", "cc_type": "knockup", "hard": True, "base_duration": 0.75, "cooldown": 80.0, "aoe": True}], "total_hard_cc_sec": 0.75, "total_soft_cc_sec": 0.0, "cc_uptime_rating": 0.05}),
}


def get_dd_version():
    r = requests.get(f"{DD_BASE}/api/versions.json", timeout=5)
    return r.json()[0]


def get_all_champions(version: str):
    r = requests.get(f"{DD_BASE}/cdn/{version}/data/en_US/champion.json", timeout=10)
    return r.json()["data"]


def normalize_id(name: str) -> str:
    """Convert champion name to our lowercase key format."""
    return name.lower().replace(" ", "").replace("'", "").replace(".", "")


def blend_tags(tags: list[str]) -> dict[str, float]:
    """Blend stat templates based on DD tags."""
    if not tags:
        return dict(ROLE_TEMPLATES["Fighter"])

    result = {k: 0.0 for k in ROLE_TEMPLATES["Mage"]}
    weights = [0.7, 0.3] if len(tags) > 1 else [1.0]

    for i, tag in enumerate(tags[:2]):
        template = ROLE_TEMPLATES.get(tag, ROLE_TEMPLATES["Fighter"])
        w = weights[i]
        for k, v in template.items():
            result[k] += v * w

    # Clamp all values to [0, 1]
    return {k: min(round(v, 2), 1.0) for k, v in result.items()}


def main():
    version = get_dd_version()
    print(f"Fetching champions for patch {version}...")
    dd_champs = get_all_champions(version)

    result = {}

    for key, data in dd_champs.items():
        champ_id = normalize_id(data["id"])
        name = data["name"]
        tags = data.get("tags", [])

        # Start with role-blended template
        stats = blend_tags(tags)

        # Check for override
        cc_profile_data = None
        notes = f"Tags: {', '.join(tags)}"

        if champ_id in OVERRIDES:
            stat_override, cc_override = OVERRIDES[champ_id]
            stats.update(stat_override)
            if cc_override:
                cc_profile_data = cc_override
            notes = ""  # Overridden champions don't need tag notes

        entry = {
            "name": name,
            "stats": stats,
        }

        if cc_profile_data:
            entry["cc_profile"] = cc_profile_data
        else:
            # Generate a minimal CC profile from stats
            entry["cc_profile"] = {
                "abilities": [],
                "total_hard_cc_sec": round(stats.get("hard_cc", 0) * 3.0, 1),
                "total_soft_cc_sec": round(stats.get("soft_cc", 0) * 3.0, 1),
                "cc_uptime_rating": round(stats.get("hard_cc", 0) * 0.3 + stats.get("soft_cc", 0) * 0.15, 2),
            }

        if notes:
            entry["notes"] = notes

        result[champ_id] = entry

    out_path = Path("data/champions/champions.json")
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(result)} champions to {out_path}")


if __name__ == "__main__":
    main()
