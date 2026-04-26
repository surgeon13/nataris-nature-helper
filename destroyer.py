# ==========================================
#           NATARIS DESTROYER
#           Demolishes buildings using the
#           Main Building demolish function.
#           Never wastes gold on demolitions.
#           Saves demolition state to JSON so
#           it can resume after restart.
# ==========================================

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from buildings import BUILDINGS
from helpers import BASE_URL, wait, idle, get_all_villages, switch_village, get_queue_status, red, yellow, green, cyan, bold, info, ok, warn, err, status
import time
import json
import os

STATE_FILE = os.path.join(os.path.dirname(__file__), "demolition_state.json")

# ==========================================
#           DEMOLITION STATE PERSISTENCE
# ==========================================

def save_state(state):
    """Saves demolition state to JSON. Called after every queued demolish."""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    print("State saved.")

def load_state():
    """Loads saved demolition state. Returns None if no state file exists."""
    if not os.path.exists(STATE_FILE):
        return None
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return None

def clear_state():
    """Deletes the state file when demolition is fully complete."""
    if os.path.exists(STATE_FILE):
        os.remove(STATE_FILE)
        ok("Demolition state cleared.")

# ==========================================
#           DEMOLITION HELPERS
# ==========================================

def get_demolish_list(driver):
    """
    Reads all demolishable buildings from the Main Building demolish page.
    Returns list of options with value and text.
    Returns empty list if Main Building is not built.
    """
    driver.get(BASE_URL + "build.php?id=26")  # Main Building - fixed slot
    wait()
    try:
        select_el = driver.find_element(By.ID, "demolition_type")
        select    = Select(select_el)
        options   = []
        for option in select.options:
            options.append({
                "value": option.get_attribute("value"),
                "text":  option.text.strip(),
            })
        return options
    except Exception:
        err("Could not find demolish list - is Main Building built?")
        return []

def get_demolish_timer(driver):
    """
    Reads the demolish timer from the queue after queuing.
    Returns finish timestamp so caller can save it to state.
    """
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "#building_contract tbody tr")
        for row in rows:
            try:
                timer = row.find_element(By.CSS_SELECTOR, "span[id^='timer']")
                parts = timer.text.strip().split(":")
                seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                return time.time() + seconds
            except Exception:
                continue
    except Exception:
        pass
    return None

def is_demolish_active(driver):
    """
    Checks if a demolish is currently in progress on the Main Building page.
    The #demolition_type select is hidden while a demolish is active.
    Returns (active, seconds_remaining) tuple.
    """
    try:
        select_el = driver.find_element(By.ID, "demolition_type")
        # If select is present and visible, no active demolish
        if select_el.is_displayed():
            return False, 0
    except Exception:
        pass
    # Select not found or hidden - check for active demolish timer
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "#building_contract tbody tr")
        for row in rows:
            text = row.text.lower()
            if "demolish" in text or "destruct" in text:
                try:
                    timer = row.find_element(By.CSS_SELECTOR, "span[id^='timer']")
                    parts = timer.text.strip().split(":")
                    seconds = int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
                    return True, seconds
                except Exception:
                    return True, 60  # demolish active but can't read timer
    except Exception:
        pass
    return True, 60  # select missing, assume active

def queue_demolish(driver, building_value, abort_flag):
    """
    Queues a single demolish action for a building.
    Never autocompletes - demolitions run on their natural timer.
    Waits for any active demolish to finish before queuing the next one.
    Returns finish timestamp so caller can save it to state.
    """
    while True:
        driver.get(BASE_URL + "build.php?id=26")  # Main Building - fixed slot
        wait()

        active, seconds_remaining = is_demolish_active(driver)
        if not active:
            break

        if seconds_remaining > 0:
            finish_str = time.strftime("%H:%M:%S", time.localtime(time.time() + seconds_remaining))
            warn(f"Demolish in progress - waiting {seconds_remaining}s (finishes ~{finish_str})...")
        else:
            warn("Demolish in progress - waiting...")

        # Wait out the demolish, checking abort every 5s
        waited = 0
        wait_for = max(seconds_remaining + 5, 65)  # +5s buffer for game to update
        while waited < wait_for:
            if abort_flag and abort_flag[0]:
                err("Aborted!")
                return None
            time.sleep(5)
            waited += 5

    try:
        select_el = driver.find_element(By.ID, "demolition_type")
        Select(select_el).select_by_value(building_value)
        time.sleep(1)

        driver.execute_script("window.verify_demolition = function() { return true; }")
        driver.find_element(By.ID, "btn_demolish").click()
        wait()

        finish_at = get_demolish_timer(driver)
        ok("Demolish queued!")
        if finish_at:
            finish_str = time.strftime("%H:%M:%S", time.localtime(finish_at))
            ok(f"Demolish will complete at: {finish_str}")
        return finish_at

    except Exception as e:
        err(f"Could not queue demolish: {e}")
        return None

# ==========================================
#           RESUME LOGIC
# ==========================================

def resume_demolition(driver, abort_flag):
    """
    Checks saved state and resumes demolition if timer has expired.
    Called automatically by scheduler when demolition_ready flag is set.
    Returns True if resumed successfully, False if nothing to resume.
    """
    state = load_state()
    if not state:
        return False

    village          = state["village"]
    building_value   = state["building_value"]
    building_text    = state["building_text"]
    levels_remaining = state["levels_remaining"]
    finish_at        = state.get("finish_at")

    info(f"\n========== RESUMING DEMOLITION ==========")
    print(f"Village:          {village['name']}")
    print(f"Building:         {building_text}")
    print(f"Levels remaining: {levels_remaining}")

    if finish_at and time.time() < finish_at:
        remaining  = int(finish_at - time.time())
        finish_str = time.strftime("%H:%M:%S", time.localtime(finish_at))
        warn(f"Current demolish still in progress - finishes at {finish_str} ({remaining}s remaining)")
        return True

    if levels_remaining <= 0:
        ok("Demolition already complete!")
        clear_state()
        return False

    ok(f"Demolish complete - continuing with {levels_remaining} level(s) remaining...")
    switch_village(driver, village)

    for i in range(levels_remaining):
        if abort_flag and abort_flag[0]:
            err("Aborted! Progress saved.")
            return True

        print(f"\nDemolish {i + 1} of {levels_remaining}...")

        while True:
            if abort_flag and abort_flag[0]:
                return True
            queue = get_queue_status(driver)
            if queue["slots_free"] > 0:
                break
            if not idle(abort_flag, "Queue full."):
                return True

        finish_at = queue_demolish(driver, building_value, abort_flag)

        state["levels_remaining"] = levels_remaining - (i + 1)
        state["finish_at"]        = finish_at
        save_state(state)

        if state["levels_remaining"] <= 0:
            ok("All demolitions complete!")
            clear_state()
            return True

        if i < levels_remaining - 1:
            # Wait the actual demolish time instead of random idle
            if finish_at:
                wait_secs = max(int(finish_at - time.time()) + 5, 10)
                finish_str = time.strftime("%H:%M:%S", time.localtime(finish_at))
                warn(f"Level {i + 1} queued. Waiting {wait_secs}s for demolish to finish (~{finish_str})...")
                waited = 0
                while waited < wait_secs:
                    if abort_flag and abort_flag[0]:
                        return True
                    time.sleep(5)
                    waited += 5
            else:
                if not idle(abort_flag, f"Level {i + 1} queued. Waiting before next..."):
                    return True

    return True

# ==========================================
#           ENTRY POINT
# ==========================================

def run_destroyer(driver, abort_flag):
    """
    Main entry point for the destroyer (menu option 6).
    Checks for saved state first and offers to resume.
    Lists all villages and buildings, asks what to demolish
    and how many levels, then queues demolitions without gold.
    """
    info("\n========== BUILDING DESTROYER ==========")

    state = load_state()
    if state:
        ok(f"\nFound unfinished demolition:")
        print(f"  Village:          {state['village']['name']}")
        print(f"  Building:         {state['building_text']}")
        print(f"  Levels remaining: {state['levels_remaining']}")

        if state.get("finish_at"):
            remaining = int(state["finish_at"] - time.time())
            if remaining > 0:
                finish_str = time.strftime("%H:%M:%S", time.localtime(state["finish_at"]))
                print(f"  Finishes at: {finish_str} ({remaining}s remaining)")

        choice = input("\nResume this demolition? (y/n): ").strip().lower()
        if choice == "y":
            resume_demolition(driver, abort_flag)
            return

    villages = get_all_villages(driver)

    print("\nAvailable villages:")
    for i, village in enumerate(villages):
        print(f"  {i + 1}. {village['name']}")

    while True:
        choice = input("\nWhich village to demolish in? (enter number): ").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(villages):
                selected_village = villages[index]
                break
            else:
                print(f"Please enter a number between 1 and {len(villages)}.")
        except Exception:
            err("Invalid input.")

    switch_village(driver, selected_village)

    options = get_demolish_list(driver)
    if not options:
        warn("No buildings available to demolish!")
        return

    print("\nAvailable buildings to demolish:")
    for i, option in enumerate(options):
        # Strip leading slot number from game text e.g. "20. Warehouse (lvl 20)" -> "Warehouse (lvl 20)"
        display = option["text"].split(". ", 1)[-1] if ". " in option["text"] else option["text"]
        print(f"  {i + 1}. {display}")

    while True:
        choice = input("\nWhich building to demolish? (enter number): ").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(options):
                selected_building = options[index]
                break
            else:
                print(f"Please enter a number between 1 and {len(options)}.")
        except Exception:
            err("Invalid input.")

    # Strip slot prefix for display e.g. "20. Warehouse (lvl 20)" -> "Warehouse (lvl 20)"
    display_name = selected_building["text"].split(". ", 1)[-1] if ". " in selected_building["text"] else selected_building["text"]
    try:
        current_level = int(selected_building["text"].split("lvl ")[-1].replace(")", ""))
    except Exception:
        current_level = 1

    print(f"\n{display_name} - current level: {current_level}")

    while True:
        levels_input = input(f"How many levels to demolish? (1-{current_level}): ").strip()
        try:
            levels_to_demolish = int(levels_input)
            if 1 <= levels_to_demolish <= current_level:
                break
            else:
                print(f"Please enter a number between 1 and {current_level}.")
        except Exception:
            err("Invalid input.")

    print(f"\nDemolishing {display_name} by {levels_to_demolish} level(s)...")
    print("Note: Demolitions run naturally - no gold will be used!")

    state = {
        "village":          selected_village,
        "building_value":   selected_building["value"],
        "building_text":    selected_building["text"],
        "levels_total":     levels_to_demolish,
        "levels_remaining": levels_to_demolish,
        "finish_at":        None,
        "started_at":       time.time(),
    }
    save_state(state)

    for i in range(levels_to_demolish):
        if abort_flag and abort_flag[0]:
            err("Aborted! Progress saved - resume later from menu.")
            return

        print(f"\nDemolish {i + 1} of {levels_to_demolish}...")

        while True:
            if abort_flag and abort_flag[0]:
                return
            queue = get_queue_status(driver)
            if queue["slots_free"] > 0:
                break
            if not idle(abort_flag, "Queue full."):
                return

        finish_at = queue_demolish(driver, selected_building["value"], abort_flag)

        state["levels_remaining"] = levels_to_demolish - (i + 1)
        state["finish_at"]        = finish_at
        save_state(state)

        if state["levels_remaining"] <= 0:
            ok("\nAll demolitions queued!")
            clear_state()
            return

        if i < levels_to_demolish - 1:
            # Wait the actual demolish time instead of random idle
            if finish_at:
                wait_secs = max(int(finish_at - time.time()) + 5, 10)
                finish_str = time.strftime("%H:%M:%S", time.localtime(finish_at))
                warn(f"Level {i + 1} queued. Waiting {wait_secs}s for demolish to finish (~{finish_str})...")
                waited = 0
                while waited < wait_secs:
                    if abort_flag and abort_flag[0]:
                        err("Aborted! Progress saved.")
                        return
                    time.sleep(5)
                    waited += 5
            else:
                if not idle(abort_flag, f"Level {i + 1} queued. Waiting before next..."):
                    err("Aborted! Progress saved.")
                    return

    ok(f"\n========== DEMOLISH COMPLETE ==========")
    print(f"All {levels_to_demolish} demolition(s) queued for {display_name}.")
    clear_state()
