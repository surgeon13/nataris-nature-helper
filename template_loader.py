# ==========================================
#           NATARIS TEMPLATE LOADER
#           Loads village templates from
#           /templates folder as JSON files.
#           Resolves tribe-specific overrides
#           and injects them into stage order.
#           Executes stage steps with slot-aware
#           building placement.
#           Asks user to continue to next
#           template when current one finishes.
# ==========================================

import os
import json
import time
import re
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from buildings import BUILDINGS
from helpers import (
    BASE_URL, wait, idle,
    get_all_villages, switch_village,
    get_storage_capacity, storage_is_sufficient, get_upgrade_cost,
    get_building_level, get_queue_status,
    autocomplete_if_two_in_queue, has_enough_resources, has_enough_resources_for_cost,
    building_exists_in_village, find_building_slot, get_village_buildings,
    get_village_resource_fields, get_all_queue_seconds, is_workers_busy_banner_visible,
    red, yellow, green, cyan, bold, info, ok, warn, err, status
)
from village_builder_engine import upgrade_storage_if_needed, run_village_build_cycle

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

# ==========================================
#           TEMPLATE LOADING
# ==========================================

def load_all_templates():
    """
    Loads all JSON template files from /templates folder.
    Returns dict keyed by template 'key' field.
    Skips any file that fails to parse.
    """
    templates = {}
    if not os.path.exists(TEMPLATES_DIR):
        err(f"Templates folder not found at {TEMPLATES_DIR}")
        return templates

    for filename in sorted(os.listdir(TEMPLATES_DIR)):
        if not filename.endswith(".json"):
            continue
        path = os.path.join(TEMPLATES_DIR, filename)
        try:
            with open(path, "r") as f:
                data = json.load(f)
            key = data.get("key", filename.replace(".json", ""))
            templates[key] = data
        except Exception as e:
            err(f"Could not load template {filename}: {e}")

    return templates


def filter_templates_for_tribe(templates, tribe):
    """
    Returns only templates that support the given tribe.
    Tribe is stored in accounts.py per account.
    """
    return {
        key: t for key, t in templates.items()
        if tribe in t.get("tribes", [])
    }


def resolve_stages(template, tribe):
    """
    Merges tribe_overrides stage_additions into the base stage list.
    Supports legacy keys (phases/phase_additions/after_phase) for backward compatibility.
    Insertions happen directly after the named stage they follow.
    Returns final ordered list of stages ready for execution.
    """
    base_stages = list(template.get("stages", template.get("phases", [])))
    overrides   = template.get("tribe_overrides", {}).get(tribe, {})
    additions   = overrides.get("stage_additions", overrides.get("phase_additions", []))

    for addition in additions:
        after = addition.get("after_stage", addition.get("after_phase"))
        # Find insertion point
        insert_at = len(base_stages)  # default: append at end
        for i, stage in enumerate(base_stages):
            if stage.get("name") == after:
                insert_at = i + 1
                break
        # Build the stage dict without placement meta keys
        new_stage = {
            k: v for k, v in addition.items()
            if k not in ("after_stage", "after_phase")
        }
        base_stages.insert(insert_at, new_stage)

    return base_stages

# ==========================================
#           SLOT-AWARE BUILDING PLACEMENT
# ==========================================

def is_crop_cap_reached(driver):
    """
    Returns True if the page is blocking construction due to insufficient crop
    production (population cap). Detects the 'Not enough food. Expand cropland.'
    span that the game shows instead of a build button.
    """
    try:
        spans = driver.find_elements(By.CSS_SELECTOR, "span.none")
        for span in spans:
            t = span.text.strip().lower()
            if "food" in t or "cropland" in t or "expand" in t or "getreide" in t:
                return True
    except Exception:
        pass
    return False


def upgrade_cheapest_crop_field(driver, current_village, use_gold, abort_flag):
    """
    When crop cap is reached, finds the lowest-level crop field in the current
    village and queues its upgrade so population capacity can grow.
    Returns True if an upgrade was queued, False otherwise.
    """
    warn("Crop cap reached — upgrading cheapest crop field to free population space...")
    fields = get_village_resource_fields(driver, current_village)
    crop_fields = [
        f for f in fields
        if any(k in f["type"].lower() for k in ("wheat", "crop", "grain", "getreide"))
    ]
    if not crop_fields:
        err("Could not find any crop fields on dorf1.")
        return False
    crop_fields.sort(key=lambda f: f["level"])
    field = crop_fields[0]
    driver.get(field["url"])
    wait()
    try:
        btn = driver.find_element(By.CSS_SELECTOR, "a.build")
        href = btn.get_attribute("href") or ""
        if "master=" in href:
            warn(f"Not enough resources to upgrade crop field L{field['level']} — requesting resources from nearby villages...")
            from resource_upgrader import try_send_resources_from_nearby
            try_send_resources_from_nearby(driver, current_village, field, abort_flag, 0)
            return False
        btn.click()
        ok(f"Crop field L{field['level']} → L{field['level'] + 1} queued.")
        wait(driver)
        autocomplete_if_two_in_queue(driver, use_gold)
        return True
    except Exception as e:
        err(f"Could not queue crop field upgrade: {e}")
        return False


def _matching_resource_fields(fields, keywords):
    return [f for f in fields if any(k in f["type"].lower() for k in keywords)]


def ensure_resource_field_level(driver, current_village, field_label, keywords, required_level, use_gold, abort_flag, non_blocking=False):
    """
    Ensures at least one resource field of the given type reaches required_level.
    If not met, queues upgrades for the cheapest matching field until the
    prerequisite is satisfied.
    """
    while True:
        fields = get_village_resource_fields(driver, current_village)
        matching = _matching_resource_fields(fields, keywords)
        if not matching:
            err(f"Could not find any {field_label} fields in this village.")
            return False

        max_level = max((f["level"] for f in matching), default=0)
        if max_level >= required_level:
            ok(f"Prerequisite confirmed: highest {field_label} field is L{max_level} (need L{required_level}).")
            return True

        field = min(matching, key=lambda f: f["level"])
        warn(
            f"Need {field_label} field L{required_level} for this building. "
            f"Upgrading {field['type']} L{field['level']} first..."
        )

        driver.get(field["url"])
        wait()

        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            autocomplete_if_two_in_queue(driver, use_gold)
            from helpers import get_queue_finish_times, format_queue_time
            finish_times = get_queue_finish_times(driver)
            if non_blocking:
                if finish_times:
                    warn(f"Queue full ({format_queue_time(finish_times)}). Deferring field prerequisite.")
                else:
                    warn("Queue full. Deferring field prerequisite.")
                return "deferred"
            if finish_times:
                if not idle(abort_flag, f"Queue full ({format_queue_time(finish_times)}). Waiting for field prerequisite..."):
                    return False
            else:
                if not idle(abort_flag, "Queue full. Waiting for field prerequisite..."):
                    return False
            continue

        _field_cost = get_upgrade_cost(driver)
        if not has_enough_resources_for_cost(driver, _field_cost):
            if current_village is not None:
                from resource_upgrader import try_send_resources_from_nearby
                warn(f"Not enough resources for {field_label} prerequisite upgrade. Requesting donor send...")
                try_send_resources_from_nearby(driver, current_village, field, abort_flag, 0)
                switch_village(driver, current_village)
                if abort_flag and abort_flag[0]:
                    return False
                if non_blocking:
                    return "deferred"
            else:
                if non_blocking:
                    return "deferred"
                if not idle(abort_flag, f"Not enough resources for {field_label} prerequisite upgrade."):
                    return False
            continue

        try:
            btn = driver.find_element(By.CSS_SELECTOR, "a.build")
            href = btn.get_attribute("href") or ""
            if "master=" in href:
                if current_village is not None:
                    from resource_upgrader import try_send_resources_from_nearby
                    warn(f"Insufficient resources for {field_label} prerequisite. Requesting donor send...")
                    try_send_resources_from_nearby(driver, current_village, field, abort_flag, 0)
                    switch_village(driver, current_village)
                    if abort_flag and abort_flag[0]:
                        return False
                    if non_blocking:
                        return "deferred"
                else:
                    if non_blocking:
                        return "deferred"
                    if not idle(abort_flag, f"Not enough resources for {field_label} prerequisite upgrade."):
                        return False
                continue

            btn.click()
            ok(f"Queued {field['type']} L{field['level'] + 1} for prerequisite progress.")
            wait(driver)
            autocomplete_if_two_in_queue(driver, use_gold)
            if non_blocking:
                return "deferred"
        except Exception as e:
            err(f"Could not queue {field_label} prerequisite upgrade: {e}")
            if non_blocking:
                return "deferred"
            if not idle(abort_flag, "Retrying field prerequisite upgrade..."):
                return False
            continue


def ensure_bonus_building_unlock(driver, current_village, use_gold, abort_flag):
    """
    Ensures universal unlock prerequisite for resource bonus buildings:
    at least one wood, clay, iron, and crop field at level 10.
    """
    requirements = [
        ("wood", ("wood", "lumber", "forest", "holz")),
        ("clay", ("clay", "pit", "lehm")),
        ("iron", ("iron", "mine", "eisen")),
        ("crop", ("wheat", "crop", "grain", "getreide")),
    ]
    for label, kinds in requirements:
        if not ensure_resource_field_level(
            driver, current_village, label, kinds, 10, use_gold, abort_flag
        ):
            return False
    return True


def find_empty_slot(driver, start=19, end=40, village=None):
    """
    Finds an empty dorf2 building slot quickly from the map itself.
    Returns the first empty slot in [start, end], or None if all are occupied.
    This avoids slow build.php probing of every slot when villages are full.
    """
    url = BASE_URL + "dorf2.php"
    if village:
        url += f"?newdid={village['id']}"
    driver.get(url)
    wait()
    areas = driver.find_elements(By.CSS_SELECTOR, "area[title][href*='build.php?id=']")
    for area in areas:
        href = area.get_attribute("href") or ""
        m = re.search(r"id=(\d+)", href)
        if not m:
            continue
        slot = int(m.group(1))
        if slot < start or slot > end:
            continue
        title = (area.get_attribute("title") or "").strip().lower()
        is_empty = (
            "building site" in title
            or "construct a new building" in title
            or "construct new building" in title
            or "baustelle" in title
            or "neues gebäude" in title
            or "empty" in title
            or not re.search(r"(?:level|lvl)\.?\s*\d+", title, re.IGNORECASE)
        )
        if is_empty:
            return slot
    return None


def construct_building_in_slot(driver, building_name, slot_id, use_gold, abort_flag, current_village=None, non_blocking=False):
    """
    Constructs a building in a specific dorf2 slot.
    Since we are always first to place buildings on this server,
    the slot is always empty - no fallback needed.
    Navigates directly to the slot URL and selects the correct building by gid_num.
    Waits in place if resources insufficient or queue full.
    When resources are insufficient and current_village is provided, attempts to
    send resources from nearby villages before retrying.
    """
    slot_url = BASE_URL + f"build.php?id={slot_id}"
    if current_village:
        slot_url += f"&newdid={current_village['id']}"

    # Check if building already exists anywhere in village — one dorf2 load.
    _bldgs = get_village_buildings(driver, current_village)
    _name  = building_name.lower()
    _bdata = _bldgs.get(_name) or next((v for k, v in _bldgs.items() if _name in k), None)
    if _bdata:
        ok(f"{building_name} already exists in slot {_bdata['slot']} (level {_bdata['level']}). Skipping construction.")
        return True

    # Resolve gid_num for this building so we click the right button
    gid_num = BUILDINGS.get(building_name, {}).get("gid_num")
    if not gid_num:
        err(f"No gid_num found for '{building_name}' in buildings.py. Cannot construct.")
        return False

    # Grain Mill prerequisite: at least one crop field at level 5
    if building_name == "Grain Mill":
        _req = ensure_resource_field_level(
            driver, current_village, "crop", ("wheat", "crop", "grain", "getreide"), 5, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False

    # Resource bonus building prerequisites:
    # - Sawmill requires at least one wood field at level 10
    # - Brickyard requires at least one clay field at level 10
    # - Iron Foundry requires at least one iron field at level 10
    if building_name in ("Sawmill", "Brickyard", "Iron Foundry"):
        if building_name == "Sawmill":
            kinds = ("wood", "lumber", "forest", "holz")
            label = "wood"
        elif building_name == "Brickyard":
            kinds = ("clay", "pit", "lehm")
            label = "clay"
        else:
            kinds = ("iron", "mine", "eisen")
            label = "iron"
        _req = ensure_resource_field_level(
            driver, current_village, label, kinds, 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False

    # Bakery prerequisite: Grain Mill level 5
    if building_name == "Bakery":
        _req = ensure_resource_field_level(
            driver, current_village, "crop", ("wheat", "crop", "grain", "getreide"), 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False

        _bldgs           = get_village_buildings(driver)
        _gm              = _bldgs.get("grain mill")
        grain_mill_level = _gm["level"] if _gm else 0
        if grain_mill_level < 5:
            warn("Bakery requires Grain Mill level 5. Upgrading Grain Mill first...")
            grain_mill_slot = (_gm["slot"] if _gm else None) or 23
            if not upgrade_building_to_level(driver, "Grain Mill", 5, grain_mill_slot, use_gold, abort_flag, current_village):
                return False

    # Town Hall prerequisites: Academy level 10
    if building_name == "Town Hall":
        _bldgs        = get_village_buildings(driver)
        _ac           = _bldgs.get("academy")
        academy_level = _ac["level"] if _ac else 0
        if academy_level < 10:
            warn(f"Town Hall requires Academy level 10. Current Academy level: {academy_level}. Upgrading Academy first...")
            academy_slot = (_ac["slot"] if _ac else None) or 32
            if not upgrade_building_to_level(driver, "Academy", 10, academy_slot, use_gold, abort_flag, current_village):
                return False
        ok("Academy level 10 confirmed - proceeding with Town Hall construction.")

    # Verify the slot is either empty or already holds the expected building.
    # If a DIFFERENT building is in this slot, stop immediately rather than
    # accidentally constructing or upgrading the wrong thing.
    driver.get(slot_url)
    wait()
    try:
        page_heading = driver.find_element(By.CSS_SELECTOR, "h1").text.strip().lower()
        building_name_lower = building_name.lower()
        is_build_site = (
            "building site" in page_heading
            or "baustelle" in page_heading
            or "construct a new building" in page_heading
            or "construct new building" in page_heading
            or "neues gebäude" in page_heading
        )
        is_correct_building = building_name_lower in page_heading
        if is_correct_building:
            ok(f"{building_name} already exists in slot {slot_id}. Skipping construction.")
            return True
        if not is_build_site:
            warn(f"Slot {slot_id} is occupied by '{page_heading}'. Looking for an empty slot...")
            alt_slot = find_empty_slot(driver, village=current_village)
            if alt_slot is None:
                err(f"No empty slots found in dorf2. Cannot construct {building_name}.")
                return False
            warn(f"Using empty slot {alt_slot} for {building_name} instead of slot {slot_id}.")
            slot_id  = alt_slot
            slot_url = BASE_URL + f"build.php?id={slot_id}"
            if current_village:
                slot_url += f"&newdid={current_village['id']}"
    except Exception:
        pass  # If we can't read the heading, proceed and let the XPath search fail naturally

    ok(f"Constructing {building_name} (slot {slot_id})...")
    failed_attempts = 0
    max_retries = 3

    while True:
        if abort_flag[0]:
            return False

        driver.get(slot_url)

        # Wait for page to settle, then check queue
        wait()
        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            autocomplete_if_two_in_queue(driver, use_gold)
            from helpers import get_queue_finish_times, format_queue_time
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                warn(f"Queue full. Waiting {format_queue_time(finish_times)} for slot to free up...")
            else:
                warn("Queue full. Waiting for slot to free up...")
            if not idle(abort_flag, "Queue full."):
                return False
            continue

        # Check resources BEFORE searching for the button — when resources are
        # insufficient the button renders in a locked/greyed state and won't match
        # the normal XPath, causing false "button not found" retries.
        if is_crop_cap_reached(driver):
            upgraded = upgrade_cheapest_crop_field(driver, current_village, use_gold, abort_flag)
            if not upgraded:
                if not idle(abort_flag, "Crop cap reached — waiting for crop field upgrade..."):
                    return False
            driver.get(slot_url)
            wait()
            continue

        if not has_enough_resources(driver):
            warn(f"Not enough resources to construct {building_name}.")
            if current_village is not None:
                from resource_upgrader import try_send_resources_from_nearby
                warn("Trying to send resources from nearby villages...")
                try_send_resources_from_nearby(
                    driver, current_village, {"url": slot_url, "gid_num": gid_num}, abort_flag
                )
                if abort_flag and abort_flag[0]:
                    return False
            else:
                if not idle(abort_flag, f"Not enough resources to construct {building_name}."):
                    return False
            continue

        # Use WebDriverWait to give the page plenty of time to render the button.
        # Match ONLY the link for the target building (href contains a={gid_num}).
        try:
            construct_btn = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (By.XPATH, f"//a[contains(@class,'build') and contains(@href,'a={gid_num}')]")
                )
            )
        except Exception:
            construct_btn = None

        if construct_btn is None:
            # Sometimes the page already shows the target building but no
            # construction action (because it is already built). Treat that
            # as success instead of retrying construct-button lookup.
            try:
                heading_now = driver.find_element(By.CSS_SELECTOR, "h1").text.strip().lower()
            except Exception:
                heading_now = ""
            if building_name.lower() in heading_now:
                ok(f"{building_name} already exists in slot {slot_id}. Continuing with upgrade flow.")
                return True

            # Some pages render a worker-busy banner instead of a normal build
            # action. Treat it like queue saturation, not a hard failure.
            if is_workers_busy_banner_visible(driver):
                from helpers import get_queue_finish_times, format_queue_time
                finish_times = get_queue_finish_times(driver)
                if finish_times:
                    warn(f"Workers already busy. Waiting {format_queue_time(finish_times)} for a free slot...")
                else:
                    warn("Workers already busy. Waiting for a free slot...")
                if not idle(abort_flag, "Workers busy."):
                    return False
                continue

            # Check if a master-builder link is present — this means the normal
            # build button was replaced because resources are insufficient.
            # Treat it as a resource wait, NOT a failed attempt.
            try:
                master_link = driver.find_element(
                    By.XPATH, f"//a[contains(@class,'build') and contains(@href,'master=')]"
                )
            except Exception:
                master_link = None

            if master_link is not None:
                warn(f"Not enough resources to construct {building_name} (master builder link visible).")
                if current_village is not None:
                    from resource_upgrader import try_send_resources_from_nearby
                    warn("Trying to send resources from nearby villages...")
                    try_send_resources_from_nearby(
                        driver, current_village, {"url": slot_url, "gid_num": gid_num}, abort_flag
                    )
                    switch_village(driver, current_village)
                    if abort_flag and abort_flag[0]:
                        return False
                else:
                    if not idle(abort_flag, f"Not enough resources to construct {building_name}."):
                        return False
                continue

            failed_attempts += 1
            err(f"Could not find build button for {building_name} (gid={gid_num}) - attempt {failed_attempts}/{max_retries}.")
            if failed_attempts >= max_retries:
                err(f"Could not construct {building_name} after {max_retries} attempts. Returning to main menu.")
                return False
            if not idle(abort_flag, "Retrying..."):
                return False
            continue

        href = construct_btn.get_attribute("href") or ""
        if "master=" in href:
            if is_workers_busy_banner_visible(driver):
                from helpers import get_queue_finish_times, format_queue_time
                finish_times = get_queue_finish_times(driver)
                if finish_times:
                    warn(f"Workers already busy. Waiting {format_queue_time(finish_times)} for a free slot...")
                else:
                    warn("Workers already busy. Waiting for a free slot...")
                if not idle(abort_flag, "Workers busy."):
                    return False
                continue

            # Not enough resources — try sending from nearby villages first
            if current_village is not None:
                from resource_upgrader import try_send_resources_from_nearby
                warn(f"Not enough resources to construct {building_name}. Trying to send from nearby...")
                try_send_resources_from_nearby(
                    driver, current_village, {"url": slot_url, "gid_num": gid_num}, abort_flag
                )
                switch_village(driver, current_village)
                if abort_flag and abort_flag[0]:
                    return False
            else:
                if not idle(abort_flag, f"Not enough resources to construct {building_name}."):
                    return False
            continue

        try:
            construct_btn.click()
            ok(f"{building_name} construction started in slot {slot_id}!")
            wait(driver)
            autocomplete_if_two_in_queue(driver, use_gold)
            return True
        except Exception as e:
            failed_attempts += 1
            err(f"Could not click {building_name} button - attempt {failed_attempts}/{max_retries}: {e}")
            if failed_attempts >= max_retries:
                return False
            if not idle(abort_flag, "Retrying..."):
                return False


def upgrade_building_to_level(driver, building_name, target_level, slot_id, use_gold, abort_flag, current_village=None, non_blocking=False):
    """
    Upgrades a specific building to target level.
    Reads level directly from build.php?id={slot_id} — no map scan.
    If the slot is empty, constructs it first.
    If the building already exists in a DIFFERENT slot, uses that slot instead.
    When a building was just constructed (L1 queued but not visible yet), returns
    "deferred" so outer schedulers can continue other work.
    """
    print(f"\n{building_name} -> L{target_level} (slot {slot_id})")

    # Hard prerequisite enforcement for bonus resource buildings in upgrade path.
    if building_name == "Grain Mill":
        _req = ensure_resource_field_level(
            driver, current_village, "crop", ("wheat", "crop", "grain", "getreide"), 5, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False
    elif building_name == "Sawmill":
        _req = ensure_resource_field_level(
            driver, current_village, "wood", ("wood", "lumber", "forest", "holz"), 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False
    elif building_name == "Brickyard":
        _req = ensure_resource_field_level(
            driver, current_village, "clay", ("clay", "pit", "lehm"), 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False
    elif building_name == "Iron Foundry":
        _req = ensure_resource_field_level(
            driver, current_village, "iron", ("iron", "mine", "eisen"), 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False
    elif building_name == "Bakery":
        _req = ensure_resource_field_level(
            driver, current_village, "crop", ("wheat", "crop", "grain", "getreide"), 10, use_gold, abort_flag, non_blocking=non_blocking
        )
        if _req == "deferred":
            return "deferred"
        if not _req:
            return False

    # ── Pre-check: read slot AND level from dorf2 in a single page load ────
    _bldgs      = get_village_buildings(driver, current_village)
    _name       = building_name.lower()
    _bdata      = _bldgs.get(_name) or next((v for k, v in _bldgs.items() if _name in k), None)
    actual_slot = _bdata["slot"] if _bdata else None
    lvl         = _bdata["level"] if _bdata else 0
    if actual_slot and actual_slot != slot_id:
        warn(f"{building_name} found in slot {actual_slot} (template says {slot_id}). Using actual slot.")
        slot_id = actual_slot
    if actual_slot:
        if lvl >= target_level:
            ok(f"{building_name} already at L{lvl} (target L{target_level}). Skipping.")
            return True
        if lvl > 0:
            ok(f"{building_name} exists at L{lvl}, needs L{target_level}. Continuing upgrade.")
        # lvl == 0: building is queued but not yet reflected in the dorf2 map title.
        if lvl == 0:
            ok(f"{building_name} found in slot {slot_id} (under construction). Waiting for it to complete...")
            if target_level <= 1:
                ok(f"{building_name} L1 is already queued in slot {slot_id}. Continuing without blocking wait.")
                return True
    # ───────────────────────────────────────────────────────────────────────

    building_url = BASE_URL + f"build.php?id={slot_id}"
    if current_village:
        building_url += f"&newdid={current_village['id']}"

    failed_click_attempts = 0
    max_click_retries = 3
    just_constructed = actual_slot is not None and lvl == 0
    failed_resource_attempts = 0

    while True:
        if abort_flag[0]:
            err("Aborted!")
            return False

        # Read level directly from the slot page — reliable on all servers.
        driver.get(building_url)
        wait()
        page_h1 = ""
        try:
            page_h1 = driver.find_element(By.CSS_SELECTOR, "h1").text.strip().lower()
        except Exception:
            pass

        building_name_lower = building_name.lower()
        is_empty_slot = (
            "building site" in page_h1
            or "construct a new building" in page_h1
            or "construct new building" in page_h1
            or "baustelle" in page_h1
            or "neues gebäude" in page_h1
            or page_h1 == ""
        )

        if not is_empty_slot and building_name_lower not in page_h1:
            warn(f"Slot {slot_id} contains '{page_h1}', expected '{building_name}'. Looking for an empty slot...")
            alt_slot = find_empty_slot(driver, village=current_village)
            if alt_slot is None:
                err(f"No empty slots found in dorf2. Cannot place {building_name}.")
                return False
            warn(f"Using empty slot {alt_slot} for {building_name} instead of slot {slot_id}.")
            slot_id      = alt_slot
            building_url = BASE_URL + f"build.php?id={slot_id}"
            if current_village:
                building_url += f"&newdid={current_village['id']}"
            is_empty_slot = True
            current_level = 0

        current_level = 0 if is_empty_slot else get_building_level(driver)

        if current_level == 0:
            if just_constructed:
                from helpers import get_queue_finish_times, format_queue_time
                finish_times = get_queue_finish_times(driver)
                if non_blocking:
                    if finish_times:
                        warn(f"{building_name} is queued and not visible yet. Deferring ({format_queue_time(finish_times)}).")
                    else:
                        warn(f"{building_name} is queued and not visible yet. Deferring to next pass.")
                    return "deferred"

                if finish_times:
                    if not idle(abort_flag, f"Waiting for {building_name} to appear ({format_queue_time(finish_times)})..."):
                        return False
                else:
                    if not idle(abort_flag, f"Waiting for {building_name} to appear..."):
                        return False
                continue

            result = construct_building_in_slot(driver, building_name, slot_id, use_gold, abort_flag, current_village, non_blocking=non_blocking)
            if result == "deferred":
                return "deferred"
            if not result:
                return False
            # construct_building_in_slot may have skipped because building exists elsewhere.
            # Re-resolve the actual slot so the upgrade loop navigates to the right page.
            actual_slot_now = find_building_slot(driver, building_name, current_village)
            if actual_slot_now and actual_slot_now != slot_id:
                warn(f"{building_name} found in slot {actual_slot_now} after construction check. Switching.")
                slot_id = actual_slot_now
                building_url = BASE_URL + f"build.php?id={slot_id}"
                if current_village:
                    building_url += f"&newdid={current_village['id']}"
                # Check level immediately — may already be at target
                driver.get(building_url)
                wait()
                lvl = get_building_level(driver)
                if lvl >= target_level:
                    ok(f"{building_name} already at L{lvl}. Done.")
                    return True
                if lvl > 0:
                    just_constructed = False  # exists, don't wait for queue
                    continue
            just_constructed = True

            if target_level <= 1:
                ok(f"{building_name} L1 queued.")
                return True
            continue

        just_constructed = False

        if current_level >= target_level:
            ok(f"{building_name} already L{target_level}.")
            return True

        status(f"{building_name} L{current_level}/{target_level}")

        # Already on building_url from top of loop — no need to re-navigate.
        cost = get_upgrade_cost(driver)
        if cost and not storage_is_sufficient(driver, cost):
            if not upgrade_storage_if_needed(driver, cost, use_gold, abort_flag):
                return False
            driver.get(building_url)
            wait()

        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            autocomplete_if_two_in_queue(driver, use_gold)
            from helpers import get_queue_finish_times, format_queue_time
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                warn(f"Queue full. Waiting {format_queue_time(finish_times)} for slot to free up...")
            else:
                warn("Queue full. Waiting for slot to free up...")
            if not idle(abort_flag, "Queue full."):
                return False
            continue

        if is_crop_cap_reached(driver):
            upgraded = upgrade_cheapest_crop_field(driver, current_village, use_gold, abort_flag)
            if not upgraded:
                if not idle(abort_flag, "Crop cap reached — waiting for crop field upgrade..."):
                    return False
            driver.get(building_url)
            wait()
            continue

        if not has_enough_resources_for_cost(driver, cost):
            failed_resource_attempts += 1
            warn(f"Not enough resources for {building_name}. Attempt {failed_resource_attempts}/2.")
            if failed_resource_attempts >= 2:
                from resource_sender import auto_send_resources
                if current_village:
                    ok(f"[ResSend] Attempting donor send to current village...")
                    required_cost = get_upgrade_cost(driver)
                    sent = auto_send_resources(driver, current_village, abort_flag, required_cost=required_cost)
                    if sent:
                        failed_resource_attempts = 0
                        ok("[ResSend] Sent. Waiting for arrival...")
                        switch_village(driver, current_village)
                        if not idle(abort_flag, "Waiting for resources to arrive..."):
                            return False
                    else:
                        if has_enough_resources_for_cost(driver, required_cost):
                            ok("Resources are now sufficient. Retrying build.")
                            failed_resource_attempts = 0
                            driver.get(building_url)
                            wait()
                            continue
                        warn("[ResSend] No resources available to send. Idling...")
                        if not idle(abort_flag, f"No resources for {building_name}. Waiting..."):
                            return False
                        failed_resource_attempts = 0
                else:
                    if not idle(abort_flag, f"Not enough resources for {building_name}."):
                        return False
                    failed_resource_attempts = 0
            else:
                if not idle(abort_flag, f"Not enough resources for {building_name}."):
                    return False
            driver.get(building_url)
            wait()
            continue

        failed_resource_attempts = 0  # reset on success

        if is_workers_busy_banner_visible(driver):
            from helpers import get_queue_finish_times, format_queue_time
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                warn(f"Workers already busy. Waiting {format_queue_time(finish_times)} for a free slot...")
            else:
                warn("Workers already busy. Waiting for a free slot...")
            if not idle(abort_flag, "Workers busy."):
                return False
            continue

        try:
            driver.find_element(By.CSS_SELECTOR, "a.build").click()
            ok(f"{building_name} L{current_level + 1} queued.")
            wait(driver)
            autocomplete_if_two_in_queue(driver, use_gold)
            failed_click_attempts = 0  # Reset on successful click
            # If this was the last needed upgrade, stop immediately
            # to prevent the loop from re-reading stale map level and over-queuing
            if current_level + 1 >= target_level:
                ok(f"{building_name} reached target L{target_level}.")
                return True
        except KeyboardInterrupt:
            raise
        except Exception:
            failed_click_attempts += 1
            if failed_click_attempts >= max_click_retries:
                err(f"Could not upgrade {building_name} after {max_click_retries} attempts. Returning to main menu.")
                return False
            err(f"Could not click upgrade button for {building_name} - attempt {failed_click_attempts}/{max_click_retries}.")
            if not idle(abort_flag, "Retrying..."):
                return False

# ==========================================
#           STAGE EXECUTOR
# ==========================================

def preflight_check_slots(driver, stages):
    """
    Before executing any stage, reads every building present on dorf2 in a single
    page load, then validates every slot referenced in the template against it.
    Reports conflicts (slot occupied by a DIFFERENT building) so the user can fix
    the template before the bot wastes time running stages.
    Returns True always — conflicts are auto-resolved at runtime.
    """
    conflicts = []
    info("\n[Pre-flight] Checking all template slots...")

    # One dorf2 load gives us slot → name and name → slot for every building.
    _bldgs     = get_village_buildings(driver)             # keyed by lowercase name
    _slot_map  = {v["slot"]: k for k, v in _bldgs.items() if v["slot"] is not None}

    checked_slots = set()
    for stage in stages:
        if stage.get("type") != "buildings":
            continue
        for step in stage.get("steps", []):
            building_name = step.get("building", "")
            slot_id       = step.get("slot")
            if not slot_id or building_name not in BUILDINGS:
                continue
            if slot_id in checked_slots:
                continue
            checked_slots.add(slot_id)

            occupant = _slot_map.get(slot_id)       # lowercase name in that slot, or None
            is_empty   = occupant is None
            is_correct = (not is_empty) and building_name.lower() in occupant

            if not is_empty and not is_correct:
                conflicts.append((building_name, slot_id, occupant))
                err(f"  [CONFLICT] Slot {slot_id}: expected '{building_name}' but found '{occupant}'")
            else:
                display = occupant if not is_empty else "empty"
                ok(f"  [OK] Slot {slot_id}: '{building_name}' — {display}")

    if conflicts:
        warn("\n[Pre-flight] Some template slots are occupied by different buildings:")
        for building_name, slot_id, found in conflicts:
            warn(f"  Slot {slot_id}: template says '{building_name}', server has '{found}'")
            warn(f"  → Bot will auto-find an empty slot at runtime.")
        warn("Continuing — conflicts will be resolved automatically.\n")
    else:
        ok("[Pre-flight] All slots OK.\n")
    return True


def execute_stage(
    driver,
    stage,
    use_gold,
    abort_flag,
    current_village=None,
    non_blocking=False,
    max_non_blocking_actions=2,
):
    """
        Executes a single template stage.
        Handles three stage types:
      - main_building: runs the village build cycle
      - buildings:     upgrades each building in steps list with slot awareness
      - resource_fields: upgrades resource fields to target level (future use)
    """
    stage_type = stage.get("type")
    stage_name = stage.get("name", "Unnamed stage")
    notes      = stage.get("notes", "")

    info(f"\n> {stage_name}")
    if notes:
        status(f"   {notes}")

    if stage_type == "main_building":
        target = stage.get("target_level", 20)
        slot   = stage.get("slot", 26)
        # Skip if already at target level
        driver.get(BASE_URL + f"build.php?id={slot}")
        wait()
        current = get_building_level(driver)
        if current >= target:
            ok(f"Main Building already L{current} (target L{target}). Skipping stage.")
            return True
        if not run_village_build_cycle(
            driver,
            use_gold,
            abort_flag,
            target,
            current_village,
            ensure_storage_buildings=False,
        ):
            return False

    elif stage_type == "buildings":
        # Check if ALL steps in this stage are already done before doing anything.
        # One dorf2 load gives us level + slot for every existing building.
        all_done = True
        _bldgs = get_village_buildings(driver)
        deferred_in_stage = False
        for step in stage.get("steps", []):
            s_target = step.get("target_level", 1)
            s_name   = step.get("building", "").lower()
            _bdata   = _bldgs.get(s_name) or next((v for k, v in _bldgs.items() if s_name in k), None)
            if not _bdata or _bdata["level"] < s_target:
                all_done = False
                break
        if all_done:
            ok(f"Stage already complete — all buildings at target level. Skipping.")
            return True

        for step in stage.get("steps", []):
            if abort_flag[0]:
                err("Aborted!")
                return False
            building_name = step["building"]
            target_level  = step["target_level"]
            slot_id       = step.get("slot")

            # Force Marketplace to always use slot 33 if not specified
            if building_name == "Marketplace" and slot_id is None:
                slot_id = 33
                warn("No slot specified for Marketplace. Forcing slot 33.")

            if building_name == "Barracks":
                # Re-use the dorf2 data we already fetched; refresh only if stale.
                _rp = _bldgs.get("rally point")
                if not _rp:
                    warn("Barracks requires Rally Point. Building Rally Point first...")
                    rp_result = upgrade_building_to_level(
                        driver, "Rally Point", 1, 39, use_gold, abort_flag, current_village, non_blocking=non_blocking
                    )
                    if rp_result == "deferred":
                        return "deferred"
                    if not rp_result:
                        return False
                    _bldgs = get_village_buildings(driver)  # refresh after potential build

            if building_name not in BUILDINGS:
                err(f"WARNING: '{building_name}' not found in buildings.py - skipping.")
                continue

            if slot_id is None:
                warn(f"WARNING: No slot defined for {building_name} - skipping.")
                continue

            # Always attempt upgrade/build, do not skip if already exists
            step_result = upgrade_building_to_level(
                driver, building_name, target_level, slot_id, use_gold, abort_flag, current_village, non_blocking=non_blocking
            )
            if step_result == "deferred":
                deferred_in_stage = True
                continue
            if not step_result:
                return False

        if deferred_in_stage:
            return "deferred"

    elif stage_type == "resource_fields":
        target_level = int(stage.get("resource_target", 1) or 1)
        queued_in_this_visit = 0
        try:
            non_blocking_queue_cap = int(max_non_blocking_actions)
        except Exception:
            non_blocking_queue_cap = 2
        if non_blocking_queue_cap < 1:
            non_blocking_queue_cap = 1
        if non_blocking_queue_cap > 2:
            non_blocking_queue_cap = 2

        while True:
            if abort_flag[0]:
                err("Aborted!")
                return False

            fields = get_village_resource_fields(driver, current_village)
            pending = sorted([f for f in fields if f["level"] < target_level], key=lambda x: x["level"])
            if not pending:
                ok(f"Resource fields already at level {target_level}+.")
                return True

            nxt = pending[0]
            status(f"Resource fields target L{target_level}: {nxt['type']} L{nxt['level']} -> L{nxt['level'] + 1}")
            driver.get(nxt["url"])
            wait()

            queue = get_queue_status(driver)
            if queue["slots_free"] == 0:
                autocomplete_if_two_in_queue(driver, use_gold)
                from helpers import get_queue_finish_times, format_queue_time
                finish_times = get_queue_finish_times(driver)
                if non_blocking:
                    if finish_times:
                        warn(f"Queue full. Deferring resource field stage ({format_queue_time(finish_times)}).")
                    else:
                        warn("Queue full. Deferring resource field stage.")
                    return "deferred"
                if finish_times:
                    if not idle(abort_flag, f"Queue full ({format_queue_time(finish_times)})."):
                        return False
                else:
                    if not idle(abort_flag, "Queue full."):
                        return False
                continue

            if not has_enough_resources_for_cost(driver, get_upgrade_cost(driver)):
                warn(f"Not enough resources for resource fields target L{target_level}.")
                if current_village is not None:
                    from resource_upgrader import try_send_resources_from_nearby
                    sent = try_send_resources_from_nearby(driver, current_village, nxt, abort_flag, 0)
                    switch_village(driver, current_village)
                    if abort_flag and abort_flag[0]:
                        return False
                    if non_blocking:
                        return "deferred"
                    if not sent:
                        if not idle(abort_flag, "Waiting for resources for field upgrade..."):
                            return False
                else:
                    if non_blocking:
                        return "deferred"
                    if not idle(abort_flag, "Not enough resources for field upgrade."):
                        return False
                continue

            try:
                driver.find_element(By.CSS_SELECTOR, "a.build").click()
                ok(f"Queued {nxt['type']} L{nxt['level'] + 1}.")
                wait(driver)
                autocomplete_if_two_in_queue(driver, use_gold)
                if non_blocking:
                    queued_in_this_visit += 1
                    queue_after = get_queue_status(driver)
                    if queue_after["slots_free"] == 0:
                        return "deferred"
                    if queued_in_this_visit >= non_blocking_queue_cap:
                        return "deferred"
                    # Keep this village active in the same pass and try to fill slot 2.
                    continue
                continue
            except Exception as e:
                warn(f"Could not queue resource field upgrade: {e}")
                if non_blocking:
                    return "deferred"
                if not idle(abort_flag, "Retrying resource field stage..."):
                    return False
                continue

    return True


def execute_template(driver, template, tribe, use_gold, abort_flag, current_village=None):
    """
    Executes all stages of a template for the given tribe.
    Resolves tribe overrides and inserts them into stage order first.
    Stops cleanly if abort flag is set.
    """
    stages = resolve_stages(template, tribe)
    name   = template.get("name", "Unknown")

    ok(f"\n> Template: {name} | Tribe: {tribe.capitalize()} | Stages: {len(stages)}")

    # Check "requires" field for resource field level prerequisites.
    # Format: "Resource fields level N" — abort early with clear message if not met.
    requires = template.get("requires", "")
    import re as _re
    _rf_match = _re.search(r"resource fields? level\s+(\d+)", requires, _re.IGNORECASE)
    if _rf_match:
        required_level = int(_rf_match.group(1))
        info(f"[Pre-flight] Checking resource fields — all must be level {required_level}+...")
        fields = get_village_resource_fields(driver, current_village)
        below = [f for f in fields if f["level"] < required_level]
        if below:
            err(f"[Pre-flight] FAILED — {len(below)} resource field(s) below level {required_level}:")
            for f in sorted(below, key=lambda x: x["level"]):
                err(f"  {f['type']} at level {f['level']}")
            err(f"Use option 3 (Resource Upgrader) to bring all fields to level {required_level} first.")
            return False
        ok(f"[Pre-flight] All resource fields at level {required_level}+.\n")

    if not preflight_check_slots(driver, stages):
        return False

    for i, stage in enumerate(stages):
        if abort_flag[0]:
            err("Template aborted.")
            return False
        status(f"[{i+1}/{len(stages)}] Executing stage...")
        if not execute_stage(driver, stage, use_gold, abort_flag, current_village):
            err("Stage failed or was aborted.")
            return False

    print(f"\n{'=' * 50}")
    ok(f"[OK] Template complete: {name}")
    print(f"{'=' * 50}")
    return True

# ==========================================
#           MAIN ENTRY POINT
# ==========================================

def run_template_loader(driver, use_gold, abort_flag, tribe):
    """
    Main entry point for the JSON template engine.
    Loads all templates, filters by tribe, lets user pick village
    and template, executes it, then asks whether to continue
    to the next template in the chain.
    """
    info("\n========== VILLAGE TEMPLATE ENGINE ==========")

    # Load templates
    all_templates = load_all_templates()
    if not all_templates:
        ok("No templates found in /templates folder.")
        return

    # Filter for tribe
    available = filter_templates_for_tribe(all_templates, tribe)
    if not available:
        err("No templates available for your tribe.")
        return

    # Pick village
    villages = get_all_villages(driver)
    print("\nAvailable villages:")
    for i, village in enumerate(villages):
        print(f"  {i + 1}. {village['name']}")

    while True:
        choice = input("\nWhich village to apply template to? (enter number): ").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(villages):
                selected_village = villages[index]
                break
            else:
                print(f"Please enter a number between 1 and {len(villages)}.")
        except ValueError:
            err("Invalid input.")

    # Pick template
    template_keys = list(available.keys())
    print(f"\nAvailable templates for {tribe.capitalize()}:")
    for i, key in enumerate(template_keys):
        t = available[key]
        req = f" (requires: {t['requires']})" if t.get("requires") else ""
        print(f"  {i}. {t['name']}{req}")

    while True:
        choice = input("\nWhich template to run? (enter number): ").strip()
        try:
            index = int(choice)
            if 0 <= index < len(template_keys):
                selected_key = template_keys[index]
                break
            else:
                print(f"Please enter a number between 0 and {len(template_keys) - 1}.")
        except ValueError:
            err("Invalid input.")

    # Switch to village and run template chain
    if selected_village.get("id"):
        switch_village(driver, selected_village)
    else:
        warn("Single village detected with no explicit newdid. Using current page context.")
    current_key = selected_key

    while current_key:
        if abort_flag[0]:
            err("Aborted.")
            return

        template = all_templates.get(current_key)
        if not template:
            err(f"Template '{current_key}' not found.")
            break

        success = execute_template(driver, template, tribe, use_gold, abort_flag, selected_village)
        if not success:
            print("Template stopped.")
            break

        # Ask whether to continue to next template
        next_key = template.get("next_template")
        if not next_key or next_key not in all_templates:
            print("\nNo further templates in this chain. Returning to main menu.")
            break

        next_name = all_templates[next_key].get("name", next_key)
        print(f"\nNext template in chain: {next_name}")
        choice = input("Continue to next template? (y/n): ").strip().lower()
        if choice == "y":
            current_key = next_key
        else:
            print("Stopping here. Returning to main menu.")
            break

    info("\n========== TEMPLATE ENGINE DONE ==========\n")
    # Navigate back to a known-good page so the menu loop starts clean.
    try:
        driver.get(BASE_URL + "dorf2.php")
    except Exception:
        pass
