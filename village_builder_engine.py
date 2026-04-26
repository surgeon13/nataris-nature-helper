# ==========================================
#           NATARIS VILLAGE BUILDER ENGINE
#           Builds a new village from scratch.
#           Constructs Warehouse and Granary first,
#           then builds Main Building to target.
#           Storage upgraded on demand only.
#           Autocompletes only when 2 in queue.
#           Waits in place if resources run out.
#           Auto-sends resources from other villages.
#           Logs arrival time and resumes building.
#           Never exits unless aborted or done.
# ==========================================

from selenium.webdriver.common.by import By
from buildings import BUILDINGS
from helpers import (
    BASE_URL, wait, idle,
    get_all_villages, switch_village,
    get_storage_capacity, storage_is_sufficient, get_upgrade_cost,
    get_building_level, get_queue_status,
    autocomplete_if_two_in_queue, has_enough_resources,
    building_exists_in_village, find_building_slot, get_village_buildings, get_queue_finish_seconds, format_queue_time,
    is_workers_busy_banner_visible,
    red, yellow, green, cyan, bold, info, ok, warn, err, status
)
from resource_sender import auto_send_resources
import json
import os
import time

# ==========================================
#           BUILDER TASK TRACKING
# ==========================================

def get_builder_task():
    """
    Loads builder task status from file.
    Returns task dict or None if not found.
    """
    _BT = os.path.join(os.path.dirname(__file__), "builder_task.json")
    if not os.path.exists(_BT):
        return None
    try:
        with open(_BT, "r") as f:
            return json.load(f)
    except Exception:
        return None

def clear_builder_task():
    """
    Clears the builder task file when building resumes.
    """
    try:
        _BT = os.path.join(os.path.dirname(__file__), "builder_task.json")
        if os.path.exists(_BT):
            os.remove(_BT)
    except Exception:
        pass

def check_resources_arrived(driver, current_village):
    """
    Checks if resources for current village have arrived.
    Returns True if resources are ready, False if still waiting.
    """
    task = get_builder_task()
    if not task:
        return True  # No pending task, resources "ready"
    
    if task.get("status") != "waiting_for_resources":
        return True
    
    target = task.get("target_village", {})
    if target.get("id") != current_village.get("id"):
        return True  # Different village, not relevant
    
    arrival_time = task.get("expected_arrival", 0)
    current_time = time.time()
    
    if current_time >= arrival_time:
        ok(f"🎉 Resources have arrived at {current_village['name']}!")
        clear_builder_task()
        return True
    else:
        wait_secs = int(arrival_time - current_time)
        warn(f"⏳ Resources arriving in ~{wait_secs} seconds...")
        return False

# ==========================================
#           STORAGE UPGRADE (ON DEMAND)
# ==========================================

def idle_with_auto_send(driver, current_village, abort_flag, reason="Waiting..."):
    """
    Smart idle function that attempts to auto-send resources when low.
    Also monitors for arriving resources from previous sends.
    First tries auto_send_resources, then falls back to regular idle.
    If resources are sent or arrive, returns True and caller should retry the build.
    If abort_flag is set or auto-send fails, calls regular idle().
    """
    try:
        info(f"\n{reason} [ResSend] Attempting donor send...")
        required_cost = get_upgrade_cost(driver)
        if auto_send_resources(driver, current_village, abort_flag, threshold=0.5, required_cost=required_cost):
            ok("[ResSend] Sent. Waiting for arrival (~5 minutes)...")
            # Return to the original village after sending
            switch_village(driver, current_village)
            return True
    except Exception as e:
        warn(f"[ResSend] Send attempt failed: {e}")
    
    # Check if resources from a previous send have arrived
    if check_resources_arrived(driver, current_village):
        ok("Resuming build with arrived resources...")
        return True
    
    # Fall back to regular idle
    return idle(abort_flag, reason)

def upgrade_storage_if_needed(driver, cost, use_gold, abort_flag, current_village=None):
    """
    Upgrades Warehouse and/or Granary on demand only
    when the next build cost exceeds current capacity.
    Constructs them first if they don't exist yet.
    Keeps upgrading until storage is sufficient.
    Called before any expensive build in the engine and template loader.
    current_village: dict with village data, needed for auto-send when out of resources
    """
    while True:
        if abort_flag[0]:
            return False

        storage = get_storage_capacity(driver)
        needs_warehouse = (
            cost["lumber"] > storage["warehouse"] or
            cost["clay"]   > storage["warehouse"] or
            cost["iron"]   > storage["warehouse"]
        )
        needs_granary = cost["crop"] > storage["granary"]

        if not needs_warehouse and not needs_granary:
            return True

        # One dorf2 load covers both Warehouse and Granary slot lookups.
        _bldgs = get_village_buildings(driver)

        if needs_warehouse:
            print(f"Warehouse too small ({storage['warehouse']}) - upgrading...")
            w = _bldgs.get("warehouse")
            if not w:
                print("Warehouse does not exist - constructing first...")
                if not construct_building(driver, "Warehouse", use_gold, abort_flag):
                    return False
                continue

            driver.get(BASE_URL + f"build.php?id={w['slot']}")
            wait()

            queue = get_queue_status(driver)
            if queue["slots_free"] == 0:
                autocomplete_if_two_in_queue(driver, use_gold)
                from helpers import get_queue_finish_times
                finish_times = get_queue_finish_times(driver)
                if finish_times:
                    warn(f"Queue full! {format_queue_time(finish_times)}")
                ok("Returning to main menu - queue full.")
                return False

            if not has_enough_resources(driver):
                if current_village:
                    if not idle_with_auto_send(driver, current_village, abort_flag, "Not enough resources for Warehouse."):
                        return False
                else:
                    if not idle(abort_flag, "Not enough resources for Warehouse."):
                        return False
                continue

            try:
                driver.find_element(By.CSS_SELECTOR, "a.build").click()
                ok("Warehouse upgrade queued!")
                wait()
                autocomplete_if_two_in_queue(driver, use_gold)
            except Exception:
                if not idle(abort_flag, "Could not upgrade Warehouse."):
                    return False

        if needs_granary:
            print(f"Granary too small ({storage['granary']}) - upgrading...")
            g = _bldgs.get("granary")
            if not g:
                print("Granary does not exist - constructing first...")
                if not construct_building(driver, "Granary", use_gold, abort_flag):
                    return False
                continue

            driver.get(BASE_URL + f"build.php?id={g['slot']}")
            wait()

            queue = get_queue_status(driver)
            if queue["slots_free"] == 0:
                autocomplete_if_two_in_queue(driver, use_gold)
                from helpers import get_queue_finish_times
                finish_times = get_queue_finish_times(driver)
                if finish_times:
                    warn(f"Queue full! {format_queue_time(finish_times)}")
                ok("Returning to main menu - queue full.")
                return False

            if not has_enough_resources(driver):
                if current_village:
                    if not idle_with_auto_send(driver, current_village, abort_flag, "Not enough resources for Granary."):
                        return False
                else:
                    if not idle(abort_flag, "Not enough resources for Granary."):
                        return False
                continue

            try:
                driver.find_element(By.CSS_SELECTOR, "a.build").click()
                ok("Granary upgrade queued!")
                wait()
                autocomplete_if_two_in_queue(driver, use_gold)
            except Exception:
                if not idle(abort_flag, "Could not upgrade Granary."):
                    return False

# ==========================================
#           UNSLOTTED CONSTRUCTION
#           Used only for on-demand Warehouse
#           and Granary by the greedy storage
#           algorithm. All other buildings use
#           construct_building_in_slot() in
#           template_loader.py instead.
# ==========================================

def construct_building(driver, building_name, use_gold, abort_flag):
    """
    Constructs a building in the first available empty slot on dorf2.
    Used ONLY for on-demand Warehouse and Granary construction.
    All template buildings use construct_building_in_slot() in
    template_loader.py which targets confirmed slot IDs precisely.
    """
    gid_num = BUILDINGS[building_name]["gid_num"]
    print(f"Constructing {building_name} in first available slot...")

    # Check using slot page directly - more reliable than map area title scan.
    # find_building_slot scans area hrefs for the gid, then reads the page h1.
    _bldgs = get_village_buildings(driver)
    _name  = building_name.lower()
    _bdata = _bldgs.get(_name) or next((v for k, v in _bldgs.items() if _name in k), None)
    if _bdata:
        ok(f"{building_name} already exists in slot {_bdata['slot']} - skipping construction.")
        return True

    while True:
        if abort_flag[0]:
            return False

        driver.get(BASE_URL + "dorf2.php")
        wait()

        empty_slot = None
        slots = driver.find_elements(By.CSS_SELECTOR, "area[href*='id=']")
        for slot in slots:
            title = slot.get_attribute("title")
            if title and "Building site" in title:
                empty_slot = slot
                break

        if not empty_slot:
            ok("No empty building slots found!")
            if not idle(abort_flag, "No empty slots."):
                return False
            continue

        slot_url = empty_slot.get_attribute("href")
        driver.get(slot_url)
        wait()

        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            autocomplete_if_two_in_queue(driver, use_gold)
            from helpers import get_queue_finish_times
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                warn(f"Queue full! {format_queue_time(finish_times)}")
            ok("Returning to main menu - come back when queue has space.")
            return False

        try:
            construct_btn = driver.find_element(
                By.CSS_SELECTOR, f"a.build[href*='a={gid_num}&']"
            )
            href = construct_btn.get_attribute("href")
            if is_workers_busy_banner_visible(driver):
                from helpers import get_queue_finish_times
                finish_times = get_queue_finish_times(driver)
                if finish_times:
                    warn(f"Workers already busy. Waiting {format_queue_time(finish_times)} for a free slot...")
                else:
                    warn("Workers already busy. Waiting for a free slot...")
                if not idle(abort_flag, "Workers busy."):
                    return False
                continue
            if href and "master=" in href:
                if not idle(abort_flag, f"Not enough resources to construct {building_name}."):
                    return False
                continue
            construct_btn.click()
            ok(f"{building_name} construction started!")
            wait()
            autocomplete_if_two_in_queue(driver, use_gold)
            return True
        except Exception:
            err(f"Could not find {building_name} in construction list.")
            if not idle(abort_flag, "Retrying..."):
                return False

# ==========================================
#           MAIN BUILDING CYCLE
# ==========================================

def run_village_build_cycle(driver, use_gold, abort_flag, target_level=20, current_village=None, ensure_storage_buildings=True):
    """
    Builds a village foundation:
    1. Optionally constructs Warehouse if missing (legacy unslotted mode)
    2. Optionally constructs Granary if missing (legacy unslotted mode)
    3. Upgrades Main Building to target level (slot 26)
    4. Upgrades storage on demand as costs increase
    5. Autocompletes only when 2 builds in queue
    6. Waits in place if resources insufficient
    7. Auto-sends resources from other villages if low
    8. Never exits unless aborted or target reached
    current_village: dict with village data, needed for auto-send when out of resources
    """
    ok("\n--- Village build cycle started ---")
    print(f"Target: Main Building level {target_level}")
    err("Abort from main menu to stop.")

    if ensure_storage_buildings:
        info("\nChecking Warehouse and Granary...")
        _bldgs = get_village_buildings(driver)

        info("\nChecking Warehouse...")
        if not _bldgs.get("warehouse"):
            print("Warehouse does not exist - constructing...")
            if not construct_building(driver, "Warehouse", use_gold, abort_flag):
                return False
        else:
            warn("Warehouse already exists - skipping.")

        info("\nChecking Granary...")
        if not _bldgs.get("granary"):
            print("Granary does not exist - constructing...")
            if not construct_building(driver, "Granary", use_gold, abort_flag):
                return False
        else:
            warn("Granary already exists - skipping.")
    else:
        info("\nTemplate mode: skipping unslotted Warehouse/Granary auto-construction.")

    failed_resource_attempts = 0
    from resource_sender import auto_send_resources

    def _read_live_resources():
        try:
            return {
                "lumber": int(driver.find_element(By.ID, "l4").text.split("/")[0].replace(",", "").strip()),
                "clay":   int(driver.find_element(By.ID, "l3").text.split("/")[0].replace(",", "").strip()),
                "iron":   int(driver.find_element(By.ID, "l2").text.split("/")[0].replace(",", "").strip()),
                "crop":   int(driver.find_element(By.ID, "l1").text.split("/")[0].replace(",", "").strip()),
            }
        except Exception:
            return None

    while True:
        if abort_flag[0]:
            err("Aborted!")
            return False

        driver.get(BASE_URL + "build.php?id=26")  # Main Building - fixed slot
        wait()

        current_level = get_building_level(driver)
        print(f"\nMain Building - Level {current_level} / Target {target_level}")

        if current_level >= target_level:
            print(f"Main Building reached level {target_level}!")
            return True

        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            autocomplete_if_two_in_queue(driver, use_gold)
            from helpers import get_queue_finish_times
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                total_time = format_queue_time(finish_times)
                warn(f"Queue full! {total_time}")
            else:
                warn("Queue full!")
            ok("Returning to main menu - come back when queue has space.")
            return True

        cost = get_upgrade_cost(driver)
        if cost is None:
            # Quick in-place retry before entering long idle.
            driver.get(BASE_URL + "build.php?id=26")
            wait()
            cost = get_upgrade_cost(driver)
        if cost is None:
            if not idle(abort_flag, "Could not read upgrade cost."):
                return False
            continue

        print(f"Cost - Lumber: {cost['lumber']}, Clay: {cost['clay']}, "
              f"Iron: {cost['iron']}, Crop: {cost['crop']}")

        if not storage_is_sufficient(driver, cost):
            if not upgrade_storage_if_needed(driver, cost, use_gold, abort_flag, current_village):
                return False
            driver.get(BASE_URL + "build.php?id=26")  # Main Building - fixed slot
            wait()
            continue

        # Escalation logic for repeated resource shortages
        live_resources = _read_live_resources()
        if live_resources:
            enough_resources = (
                live_resources["lumber"] >= cost["lumber"] and
                live_resources["clay"]   >= cost["clay"] and
                live_resources["iron"]   >= cost["iron"] and
                live_resources["crop"]   >= cost["crop"]
            )
        else:
            enough_resources = has_enough_resources(driver)
        if not enough_resources:
            missing = {
                "lumber": max(0, cost["lumber"] - (live_resources["lumber"] if live_resources else 0)),
                "clay":   max(0, cost["clay"]   - (live_resources["clay"] if live_resources else 0)),
                "iron":   max(0, cost["iron"]   - (live_resources["iron"] if live_resources else 0)),
                "crop":   max(0, cost["crop"]   - (live_resources["crop"] if live_resources else 0)),
            }
            status(
                f"COST - L:{cost['lumber']} C:{cost['clay']} I:{cost['iron']} Cr:{cost['crop']}"
            )
            if live_resources:
                status(
                    f"RESOURCES IN VILLAGE - L:{live_resources['lumber']} C:{live_resources['clay']} "
                    f"I:{live_resources['iron']} Cr:{live_resources['crop']}"
                )
            if sum(missing.values()) > 0:
                status(
                    f"RESOURCES MISSING - L:{missing['lumber']} C:{missing['clay']} "
                    f"I:{missing['iron']} Cr:{missing['crop']}"
                )

            failed_resource_attempts += 1
            warn(f"Not enough resources for Main Building. Attempt {failed_resource_attempts}/2.")
            if failed_resource_attempts >= 2:
                # Try to auto-send resources from other villages
                if current_village:
                    ok("[ResSend] Attempting donor send from other villages...")
                    sent = auto_send_resources(driver, current_village, abort_flag, required_cost=cost)
                    if not sent:
                        if has_enough_resources(driver):
                            ok("Resources are now sufficient. Retrying build.")
                            continue
                        warn("[ResSend] No resources could be sent. Idling in main menu.")
                        idle(abort_flag, "No resources available to send. Returning to main menu.")
                        return False
                    else:
                        ok("[ResSend] Sent. Waiting for arrival before retrying.")
                        switch_village(driver, current_village)
                        failed_resource_attempts = 0
                        idle(abort_flag, "Waiting for resources to arrive...")
                        continue
                else:
                    warn("No current village context for auto-send. Idling.")
                    idle(abort_flag, "Not enough resources for Main Building.")
                    return False
            else:
                if not idle(abort_flag, "Not enough resources for Main Building."):
                    return False
                continue
        else:
            failed_resource_attempts = 0  # Reset on success

        if is_workers_busy_banner_visible(driver):
            from helpers import get_queue_finish_times
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
            ok(f"Main Building level {current_level + 1} queued!")
            wait()
            autocomplete_if_two_in_queue(driver, use_gold)
            # Queue action succeeded; restart the loop to re-read live level/queue/resources.
            # This avoids running a second stale resource check in the same pass.
            continue
        except Exception:
            if not idle(abort_flag, "Could not click upgrade button."):
                return False
            continue

# ==========================================
#           ENTRY POINT
# ==========================================

def run_build_logic(driver, use_gold, abort_flag):
    """
    Main entry point for the village builder (menu option 2).
    Asks user which village and target level,
    then runs the build cycle.
    """
    from template_loader import run_template_loader
    info("\n========== STARTING TEMPLATE BUILD LOGIC ==========")
    # Tribe should be determined from account or user input; for now, ask user
    tribe = input("Enter your tribe (roman/teuton/gaul): ").strip().lower()
    run_template_loader(driver, use_gold, abort_flag, tribe)
