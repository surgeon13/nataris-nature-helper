# ==========================================
#           NATARIS UNITS
#           Loads units.json and exposes
#           unit lookup and cost calculation
#           functions for all scripts.
#           All math is done here - never
#           hardcode unit stats elsewhere.
#           upgrade_stats reserved for future
#           smithy/armoury tracking.
# ==========================================

import json
import os

_UNITS_FILE = os.path.join(os.path.dirname(__file__), "units.json")

# Load once at import time
with open(_UNITS_FILE, encoding="utf-8") as f:
    _DATA = json.load(f)

# ==========================================
#           LOOKUP
# ==========================================

def get_unit(tribe, unit_id):
    """
    Returns a single unit dict by tribe and unit id.
    e.g. get_unit("roman", "roman_5") -> Equites Imperatoris dict
    Returns None if not found.
    """
    tribe_data = _DATA.get(tribe)
    if not tribe_data:
        return None
    for unit in tribe_data["units"]:
        if unit["id"] == unit_id:
            return unit
    return None

def get_units_for_tribe(tribe):
    """
    Returns full list of unit dicts for a tribe.
    e.g. get_units_for_tribe("teuton") -> list of 11 unit dicts
    Returns empty list if tribe not found.
    """
    tribe_data = _DATA.get(tribe)
    if not tribe_data:
        return []
    return tribe_data["units"]

def get_unit_by_name(tribe, name):
    """
    Returns a unit dict by tribe and unit name (case-insensitive).
    e.g. get_unit_by_name("gaul", "haeduan") -> Haeduan dict
    Returns None if not found.
    """
    for unit in get_units_for_tribe(tribe):
        if unit["name"].lower() == name.lower():
            return unit
    return None

def get_unit_by_dorf3_col(tribe, col):
    """
    Returns the unit that occupies a given dorf3 column index for a tribe.
    Used when parsing dorf3.php?s=5 troop table columns.
    Returns None if no unit matches that column.
    """
    for unit in get_units_for_tribe(tribe):
        if unit.get("dorf3_col") == col:
            return unit
    return None

def get_all_tribes():
    """
    Returns list of playable tribe keys (excludes _meta, nature, natar).
    """
    return [k for k in _DATA if k not in ("_meta", "nature", "natar")]

# ==========================================
#           COST CALCULATIONS
# ==========================================

def training_cost(tribe, unit_id, quantity=1):
    """
    Calculates total resource cost to train a given quantity of a unit.
    Returns dict with lumber, clay, iron, crop totals.
    Returns None if unit not found or has no cost (nature/natar).

    Example:
        training_cost("roman", "roman_5", 100)
        -> {"lumber": 55000, "clay": 44000, "iron": 32000, "crop": 10000}
    """
    unit = get_unit(tribe, unit_id)
    if not unit or not unit.get("cost"):
        return None
    lumber, clay, iron, crop = unit["cost"]
    return {
        "lumber": lumber * quantity,
        "clay":   clay   * quantity,
        "iron":   iron   * quantity,
        "crop":   crop   * quantity,
        "total":  (lumber + clay + iron + crop) * quantity,
    }

def training_cost_by_name(tribe, name, quantity=1):
    """
    Same as training_cost but looks up unit by name instead of id.
    Convenience wrapper for human-readable calls.

    Example:
        training_cost_by_name("teuton", "Clubswinger", 500)
    """
    unit = get_unit_by_name(tribe, name)
    if not unit:
        return None
    return training_cost(tribe, unit["id"], quantity)

def pre_queue_estimate(tribe, unit_id, quantity, current_resources):
    """
    Estimates whether current resources are sufficient to train a batch,
    and calculates the shortfall if not.

    current_resources: dict with lumber, clay, iron, crop keys
                       (same format as get_resources() in resource_sender.py)

    Returns dict:
        can_afford  - True/False
        cost        - total cost dict
        shortfall   - dict of missing amounts (0 if can afford)
        missing_res - list of resource names that are short

    Example:
        pre_queue_estimate("roman", "roman_3", 50, {"lumber": 5000, "clay": 8000, "iron": 10000, "crop": 3000})
    """
    cost = training_cost(tribe, unit_id, quantity)
    if not cost:
        return None

    shortfall   = {}
    missing_res = []

    for res in ("lumber", "clay", "iron", "crop"):
        have = current_resources.get(res, 0)
        # current_resources may be raw int or dict with 'current' key
        if isinstance(have, dict):
            have = have.get("current", 0)
        diff = cost[res] - have
        shortfall[res] = max(0, diff)
        if diff > 0:
            missing_res.append(res)

    return {
        "can_afford":  len(missing_res) == 0,
        "cost":        cost,
        "shortfall":   shortfall,
        "missing_res": missing_res,
    }

def training_time_total(tribe, unit_id, quantity, building_level=1):
    """
    Estimates total training time in seconds for a batch of units.
    Uses base training time from units.json (level 1 building).
    building_level param reserved for future speed reduction formula.
    Returns None if unit has no training time (hero, nature, natar).

    Note: Travian training time reduces by ~2.5% per building level above 1.
    Full formula can be added here when training automation is implemented.
    """
    unit = get_unit(tribe, unit_id)
    if not unit or not unit.get("training_time_s"):
        return None
    base_time = unit["training_time_s"]
    # Future: apply building_level reduction here
    return base_time * quantity

# ==========================================
#           DISPLAY HELPERS
# ==========================================

def format_cost(cost):
    """
    Returns a human-readable cost string.
    e.g. "L:55,000  C:44,000  I:32,000  Cr:10,000  Total:141,000"
    """
    if not cost:
        return "N/A"
    return (
        f"L:{cost['lumber']:,}  "
        f"C:{cost['clay']:,}  "
        f"I:{cost['iron']:,}  "
        f"Cr:{cost['crop']:,}  "
        f"Total:{cost['total']:,}"
    )

def print_unit_summary(tribe, unit_id):
    """
    Prints a compact summary of a unit's stats and base training cost.
    Useful for pre-queue display and debugging.
    """
    unit = get_unit(tribe, unit_id)
    if not unit:
        print(f"Unit not found: {tribe}/{unit_id}")
        return
    cost_str = format_cost(training_cost(tribe, unit_id, 1))
    print(
        f"{unit['name']:<22} "
        f"ATK:{unit['attack'] or '?':>4}  "
        f"DEF-I:{unit['def_infantry'] or '?':>4}  "
        f"DEF-C:{unit['def_cavalry'] or '?':>4}  "
        f"SPD:{unit['speed']:>3}  "
        f"CARRY:{unit['carry'] or '?':>5}  "
        f"UPKEEP:{unit['upkeep']:>2}  "
        f"COST/1: {cost_str}"
    )
