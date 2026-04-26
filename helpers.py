# ==========================================
#           NATARIS HELPERS
#           Single source of truth for all
#           shared utility functions.
#           Imported by every script that
#           needs navigation, waiting,
#           queue checking, or resources.
#           Never import these from anywhere
#           else - always use this file.
# ==========================================

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime
import time
import random
import re

BASE_URL = "https://project-nataris.com/"

# Merchant speed in fields per hour - adjust if server speed differs
MERCHANT_SPEED = 20

# ==========================================
#           TERMINAL COLORS
#           Single source of truth for all
#           color output across all scripts.
#           Import these functions everywhere
#           instead of using raw print().
#           Color scheme:
#             red    - errors, aborts, crashes, deficits
#             yellow - warnings, waiting, insufficient resources
#             green  - success, queued, sent, completed
#             cyan   - section headers, navigation info
#             bold   - emphasis, village names, summaries
#             white  - neutral status lines (plain print)
# ==========================================

class _Color:
    RED    = "\033[91m"
    YELLOW = "\033[93m"
    GREEN  = "\033[92m"
    CYAN   = "\033[96m"
    BLUE   = "\033[94m"
    BOLD   = "\033[1m"
    RESET  = "\033[0m"

def red(text):    return f"{_Color.RED}{text}{_Color.RESET}"
def yellow(text): return f"{_Color.YELLOW}{text}{_Color.RESET}"
def green(text):  return f"{_Color.GREEN}{text}{_Color.RESET}"
def cyan(text):   return f"{_Color.CYAN}{text}{_Color.RESET}"
def blue(text):   return f"{_Color.BLUE}{text}{_Color.RESET}"
def bold(text):   return f"{_Color.BOLD}{text}{_Color.RESET}"

def info(msg):    print(cyan(msg))
def ok(msg):      print(green(msg))
def warn(msg):    print(yellow(msg))
def err(msg):     print(red(msg))
def status(msg):  print(msg)

# ==========================================
#           RESOURCE DISPLAY
# ==========================================

def display_village_resources(village_name, resources):
    """
    Displays village resources in a compact, readable format.
    resources: dict with keys lumber, clay, iron, crop, each with current/max
    """
    if resources is None:
        warn(f"  {village_name} - could not read resources")
        return
    
    r = resources
    l_bar = f"L:{r['lumber']['current']:<6}/{r['lumber']['max']}"
    c_bar = f"C:{r['clay']['current']:<6}/{r['clay']['max']}"
    i_bar = f"I:{r['iron']['current']:<6}/{r['iron']['max']}"
    cr_bar = f"Cr:{r['crop']['current']:<6}/{r['crop']['max']}"
    
    status(f"  {bold(village_name):<20} {green(l_bar)}  {green(c_bar)}  {yellow(i_bar)}  {cyan(cr_bar)}")

def format_resources(resources):
    """
    Returns a formatted string of resources for inline display.
    Used when space is limited.
    """
    if resources is None:
        return "No resources"
    
    r = resources
    return f"L:{r['lumber']['current']} C:{r['clay']['current']} I:{r['iron']['current']} Cr:{r['crop']['current']}"

def format_building_time(seconds):
    """
    Converts seconds to readable format: "1h 45m" or "25m 30s" or "45s".
    Returns compact string suitable for queue display.
    """
    if seconds is None or seconds <= 0:
        return "0s"
    
    hours = seconds // 3600
    remaining = seconds % 3600
    minutes = remaining // 60
    secs = remaining % 60
    
    if hours > 0:
        return f"{hours}h {minutes}m"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

def format_queue_time(finish_times):
    """
    Takes list of finish times in seconds and returns when the first slot frees up.
    Uses the minimum (soonest) time - that's when the bot can queue the next build.
    """
    if not finish_times:
        return "Queue empty"

    return format_building_time(min(finish_times))

# ==========================================
#           TIMING
# ==========================================

def recover_browser(driver):
    """
    Closes any extra tabs that a click may have opened and returns focus to
    the main window.  If the active page is a blank/data: URL, navigates
    back to dorf2 so the bot is never stuck on an empty page.
    Called automatically by wait(driver) after every action.
    """
    try:
        handles = driver.window_handles
        if len(handles) > 1:
            # Close every extra tab and return to the original window
            for handle in handles[1:]:
                try:
                    driver.switch_to.window(handle)
                    driver.close()
                except Exception:
                    pass
            driver.switch_to.window(handles[0])
            warn("Browser: closed stray tab(s) and returned to main window.")
        url = driver.current_url
        if not url or url.startswith("data:") or url in ("about:blank", ""):
            warn("Browser stuck on blank page - navigating back to game...")
            driver.get(BASE_URL + "dorf2.php")
            time.sleep(2)
    except Exception:
        pass


def wait(driver=None):
    """Random short delay between actions to simulate human behavior.
    If driver is passed, also recovers from blank/data: pages and stray tabs."""
    time.sleep(random.uniform(2, 5))
    if driver is not None:
        recover_browser(driver)

def idle(abort_flag, reason="Waiting..."):
    """
    Idles for a random time between 30 and 120 seconds.
    Checks abort flag every half second.
    Returns False if aborted, True if wait completed normally.
    Used by all scripts when queue is full or resources are low.
    """
    wait_time = random.uniform(30, 120)
    warn(f"{reason} Retrying in {round(wait_time)} seconds...")
    start = time.time()
    while time.time() - start < wait_time:
        if abort_flag and abort_flag[0]:
            return False
        time.sleep(0.5)
    return True

# ==========================================
#           VILLAGE NAVIGATION
# ==========================================

def get_all_villages(driver):
    """
    Reads all villages from the #vlist sidebar table.
    Returns list of dicts with name, id, and coords for each village.
    Coords are read from span.coords-text in the same row - format (-44|-22).
    Active village has td.dot.hl - flagged as is_active.
    Deduplicates by village ID.
    No extra navigation needed - sidebar is present on every game page.
    """
    import re
    villages = []
    seen = set()
    try:
        rows = driver.find_elements(By.CSS_SELECTOR, "#vlist tbody tr")
        for row in rows:
            try:
                link = row.find_element(By.CSS_SELECTOR, "td.link a")
                name = link.text.strip()
                href = link.get_attribute("href")
                if "newdid=" not in href:
                    continue
                village_id = href.split("newdid=")[1].split("&")[0]
                if not name or not village_id or village_id in seen:
                    continue

                # Read coords from span.coords-text e.g. (-44|-22)
                coords = None
                try:
                    coords_el = row.find_element(By.CSS_SELECTOR, "td.aligned_coords span.coords-text")
                    coords_text = coords_el.text.strip()  # e.g. "(-44|-22)"
                    match = re.match(r'\((-?\d+)\|(-?\d+)\)', coords_text)
                    if match:
                        coords = (int(match.group(1)), int(match.group(2)))
                except Exception:
                    pass

                # Check if marketplace quick-button is present in the sidebar row
                has_market = bool(row.find_elements(By.CSS_SELECTOR, "a.market-button"))

                # Check if this is the currently active village
                is_active = False
                try:
                    row.find_element(By.CSS_SELECTOR, "td.dot.hl")
                    is_active = True
                except Exception:
                    pass

                villages.append({
                    "name":       name,
                    "id":         village_id,
                    "coords":     coords,
                    "has_market": has_market,
                    "is_active":  is_active,
                })
                seen.add(village_id)
            except Exception:
                continue
    except Exception:
        pass

    if not villages:
        # Some game layouts hide the village list sidebar when only one village exists.
        # Fallback to the current village context from the page URL, heading, overview table,
        # or any visible village link with newdid=.
        try:
            current_url = (driver.current_url or "").strip()
            village_id = None
            village_name = None

            if "newdid=" in current_url:
                village_id = current_url.split("newdid=")[1].split("&")[0]
                warn(f"[village parser] found village id from current_url: {village_id}")

            if not village_id:
                links = driver.find_elements(By.CSS_SELECTOR, "a[href*='newdid=']")
                for link in links:
                    href = (link.get_attribute("href") or "").strip()
                    if "newdid=" in href:
                        candidate_id = href.split("newdid=")[1].split("&")[0]
                        if candidate_id:
                            village_id = candidate_id
                            village_name = link.text.strip() or None
                            warn(f"[village parser] found village id from page link: {village_id}")
                            break

            if not village_id:
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[name='newdid'][value]")
                for inp in inputs:
                    candidate_id = (inp.get_attribute("value") or "").strip()
                    if candidate_id:
                        village_id = candidate_id
                        warn(f"[village parser] found village id from hidden input: {village_id}")
                        break

            if not village_id:
                rows = driver.find_elements(By.CSS_SELECTOR, "#overview tbody tr, table#overview tbody tr")
                for row in rows:
                    try:
                        link = row.find_element(By.CSS_SELECTOR, "a[href*='newdid=']")
                        href = (link.get_attribute("href") or "").strip()
                        if "newdid=" in href:
                            village_id = href.split("newdid=")[1].split("&")[0]
                            village_name = link.text.strip() or None
                            warn(f"[village parser] found village id from overview table: {village_id}")
                            break
                    except Exception:
                        continue

            if not village_id:
                # Last resort: scan the raw page source for any newdid= value.
                try:
                    page_text = driver.page_source
                    match = re.search(r'newdid=(\d+)', page_text)
                    if match:
                        village_id = match.group(1)
                        warn(f"[village parser] found village id from page source: {village_id}")
                except Exception:
                    pass

            if village_id:
                if not village_name:
                    try:
                        title_el = driver.find_element(By.CSS_SELECTOR, "#content h1")
                        village_name = title_el.text.strip()
                    except Exception:
                        village_name = None
                if not village_name:
                    village_name = "Village"

                coords = None
                try:
                    coords_el = driver.find_element(By.CSS_SELECTOR, "span.coords-text")
                    coords_text = coords_el.text.strip()
                    match = re.match(r'\((-?\d+)\|(-?\d+)\)', coords_text)
                    if match:
                        coords = (int(match.group(1)), int(match.group(2)))
                except Exception:
                    pass

                villages.append({
                    "name":       village_name,
                    "id":         village_id,
                    "coords":     coords,
                    "has_market": False,
                    "is_active":  True,
                })
            else:
                # Single-village fallback without explicit newdid= in the page.
                try:
                    if not village_name:
                        title_el = driver.find_element(By.CSS_SELECTOR, "#content h1")
                        village_name = title_el.text.strip()
                except Exception:
                    village_name = None

                if village_name:
                    villages.append({
                        "name":       village_name,
                        "id":         None,
                        "coords":     None,
                        "has_market": False,
                        "is_active":  True,
                    })
        except Exception as e:
            warn(f"[village parser] fallback failed: {e}")

    return villages

def switch_village(driver, village):
    """
    Navigates to the building map (dorf2) of a specific village.
    Always navigates to dorf2 so building checks work correctly.
    """
    if not village or not village.get("id"):
        warn("No explicit village id available; staying on the current village page.")
        return
    driver.get(BASE_URL + f"dorf2.php?newdid={village['id']}")
    wait()
    ok(f"Switched to village: {village['name']}")

def switch_village_resources(driver, village):
    """
    Navigates to the resource fields page (dorf1) of a specific village.
    Used by resource upgrader which needs the field map, not the building map.
    """
    if not village or not village.get("id"):
        warn("No explicit village id available; staying on the current village page.")
        return
    driver.get(BASE_URL + f"dorf1.php?newdid={village['id']}")
    wait()
    ok(f"Switched to village (resources): {village['name']}")

# ==========================================
#           SERVER TIME
# ==========================================

def get_server_time(driver):
    """
    Reads the current server time from #tp1 (hidden span, always server clock).
    Falls back to #tp1_user if #tp1 is unavailable.
    Returns a datetime object with today's date and server time,
    so all timers and travel calculations use server clock, not local clock.
    Returns None if server time cannot be read.
    """
    try:
        el = driver.find_element(By.ID, "tp1")
        text = el.get_attribute("textContent").strip()  # read hidden element
        t = datetime.strptime(text, "%H:%M:%S").time()
        return datetime.combine(datetime.today(), t)
    except Exception:
        try:
            el = driver.find_element(By.ID, "tp1_user")
            text = el.text.strip()
            t = datetime.strptime(text, "%H:%M:%S").time()
            return datetime.combine(datetime.today(), t)
        except Exception:
            return None

def get_server_lag_ms(driver):
    """
    Reads the server calculation lag from #ltimeWrap.
    Travian shows "Calculated in X ms" in that div.
    Returns lag in milliseconds as int, or None if unreadable.
    Useful for knowing how stale our page data is when making time-sensitive decisions.
    """
    try:
        wrap = driver.find_element(By.ID, "ltimeWrap")
        b_el = wrap.find_element(By.TAG_NAME, "b")
        return int(b_el.text.strip())
    except Exception:
        return None

# ==========================================
#           COORDINATES & TRAVEL TIME
# ==========================================

def get_village_coords(driver, village):
    """
    Returns coordinates for a village as (x, y) tuple.
    Coords are read from the sidebar by get_all_villages and cached in village['coords'].
    Falls back to scraping the sidebar again if coords missing (e.g. village dict was
    built manually without going through get_all_villages).
    Returns None if coords cannot be determined.
    """
    if village.get("coords"):
        return village["coords"]
    # Coords missing - re-read sidebar to populate them
    try:
        import re
        rows = driver.find_elements(By.CSS_SELECTOR, "#vlist tbody tr")
        for row in rows:
            try:
                link = row.find_element(By.CSS_SELECTOR, "td.link a")
                href = link.get_attribute("href")
                if f"newdid={village['id']}" not in href:
                    continue
                coords_el = row.find_element(By.CSS_SELECTOR, "span.coords-text")
                match = re.match(r'\((-?\d+)\|(-?\d+)\)', coords_el.text.strip())
                if match:
                    coords = (int(match.group(1)), int(match.group(2)))
                    village["coords"] = coords
                    return coords
            except Exception:
                continue
    except Exception:
        pass
    err(f"  Warning: could not read coords for {village.get('name', village.get('id'))}")
    return None

def chebyshev_distance(a, b):
    """
    Calculates Chebyshev distance between two (x, y) coordinate tuples.
    This is Travian's map distance - diagonal movement counts as 1 field.
    Formula: max(|ax - bx|, |ay - by|)
    """
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))

def merchant_travel_seconds(distance):
    """
    Calculates one-way merchant travel time in seconds.
    Based on MERCHANT_SPEED fields per hour (default 20 for standard T3.6).
    Minimum 60 seconds to account for game processing time.
    """
    if distance == 0:
        return 60
    seconds = int((distance / MERCHANT_SPEED) * 3600)
    return max(seconds, 60)

def get_travel_time_between(driver, from_village, to_village):
    """
    Calculates one-way merchant travel time between two villages.
    Fetches coordinates if not already cached.
    Returns travel time in seconds, or 120 as a safe fallback if coords unavailable.
    """
    from_coords = get_village_coords(driver, from_village)
    to_coords   = get_village_coords(driver, to_village)
    if not from_coords or not to_coords:
        err("Could not read coordinates - using 120s fallback travel time.")
        return 120
    dist    = chebyshev_distance(from_coords, to_coords)
    seconds = merchant_travel_seconds(dist)
    print(f"  Distance {from_village['name']} -> {to_village['name']}: {dist} fields, travel: {seconds}s")
    return seconds


# ==========================================
#           STORAGE
# ==========================================

def get_storage_capacity(driver):
    """
    Reads max warehouse and granary capacity from the resource bar.
    Returns dict with 'warehouse' and 'granary' max values.
    Used before queuing builds to check if storage is sufficient.
    """
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "l4")))
    warehouse_max = int(driver.find_element(By.ID, "l4").text.split("/")[1].replace(",", ""))
    granary_max   = int(driver.find_element(By.ID, "l1").text.split("/")[1].replace(",", ""))
    return {"warehouse": warehouse_max, "granary": granary_max}

def storage_is_sufficient(driver, cost):
    """
    Checks if current warehouse and granary capacity can hold the given build cost.
    Returns False if any resource cost exceeds storage max.
    Used to trigger on-demand storage upgrades before queuing builds.
    """
    storage = get_storage_capacity(driver)
    if (cost["lumber"] > storage["warehouse"] or
        cost["clay"]   > storage["warehouse"] or
        cost["iron"]   > storage["warehouse"]):
        print(f"Warehouse too small! Capacity: {storage['warehouse']}, "
              f"Need: max({cost['lumber']}, {cost['clay']}, {cost['iron']})")
        return False
    if cost["crop"] > storage["granary"]:
        print(f"Granary too small! Capacity: {storage['granary']}, Need: {cost['crop']}")
        return False
    return True

# ==========================================
#           BUILD QUEUE
# ==========================================

def get_queue_status(driver):
    """
    Reads the build queue and returns slots used and free.
    Always called before adding anything to the queue.
    Returns dict with 'slots_used' and 'slots_free'.
    Max queue size is 2 slots.
    """
    try:
        # Some build pages show a worker-busy banner instead of reflecting
        # queue state clearly in #building_contract.
        if is_workers_busy_banner_visible(driver):
            return {"slots_used": 2, "slots_free": 0}

        rows = driver.find_elements(By.CSS_SELECTOR, "#building_contract tbody tr")
        queue_size = len(rows)
        if queue_size == 0:
            return {"slots_used": 0, "slots_free": 2}
        elif queue_size == 1:
            return {"slots_used": 1, "slots_free": 1}
        else:
            return {"slots_used": 2, "slots_free": 0}
    except Exception:
        return {"slots_used": 0, "slots_free": 2}

def get_first_queue_building_level(driver):
    """
    Reads the building level of the first item in the build queue.
    Returns the level number (0, 1, 2, etc.) or None if queue is empty.
    Extracts from queue row text e.g. "Main Building Level 5" -> 5
    """
    try:
        first_row = driver.find_element(By.CSS_SELECTOR, "#building_contract tbody tr:first-child")
        row_text = first_row.text.strip()
        
        # Extract level number from text like "Main Building Level 5"
        import re
        match = re.search(r'Level\s+(\d+)', row_text)
        if match:
            return int(match.group(1))
        
        # Fallback: look for just a number at the end
        parts = row_text.split()
        if parts:
            try:
                return int(parts[-1])
            except Exception:
                pass
        
        return None
    except Exception:
        return None

def get_queue_finish_seconds(driver):
    """
    Reads the finish time of the first item in the build queue.
    Confirmed from live HTML: timers use id="timer1", id="timer2" etc.
    Format is h:mm:ss e.g. "0:21:40".
    Returns the total seconds remaining for the first queued item,
    or None if queue is empty or timer cannot be parsed.
    """
    try:
        # timer1 is always the first item in queue - confirmed from live HTML
        timer_el   = driver.find_element(By.ID, "timer1")
        timer_text = timer_el.text.strip()  # e.g. "0:21:40"
        parts = timer_text.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        return None
    except Exception:
        return None

def get_queue_finish_times(driver):
    """
    Alias for get_all_queue_seconds.
    Returns list of seconds remaining per queued slot e.g. [1300, 1561].
    """
    return get_all_queue_seconds(driver)

def get_all_queue_seconds(driver):
    """
    Reads finish times for all queued items.
    Returns list of seconds remaining per slot e.g. [1300, 1561].
    Useful for knowing when both slots free up.
    """
    results = []
    for timer_id in ("timer1", "timer2"):
        try:
            el    = driver.find_element(By.ID, timer_id)
            parts = el.text.strip().split(":")
            if len(parts) == 3:
                results.append(int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2]))
            elif len(parts) == 2:
                results.append(int(parts[0]) * 60 + int(parts[1]))
        except Exception:
            break  # timer2 missing means only 1 item in queue
    return results

def is_workers_busy_banner_visible(driver):
    """
    Detects the build-page banner that appears when no normal worker slot is
    available (e.g. "The workers are already at work").
    Returns True when the page is in this queue-busy state.
    """
    try:
        spans = driver.find_elements(By.CSS_SELECTOR, "span.none")
        for span in spans:
            text = (span.text or "").strip().lower()
            if not text:
                continue
            if (
                "workers are already at work" in text
                or "already at work" in text
                or "constructing with master builder" in text
                or "arbeiter sind bereits" in text
            ):
                return True
    except Exception:
        pass
    return False

def autocomplete_if_two_in_queue(driver, use_gold):
    """
    Autocompletes ONLY when 2 builds are in queue AND the first
    build has more than 3 minutes remaining AND is level 2 or higher.
    Never autocompletes level 0 or level 1 - too fast, waste of gold.
    Never wastes gold on a single build.
    Never wastes gold on a build finishing in under 3 minutes - just wait it out.
    Returns True if autocomplete was triggered, False otherwise.
    """
    if not use_gold:
        return False
    
    queue = get_queue_status(driver)
    if queue["slots_used"] < 2:
        return False  # Need 2 in queue
    
    # Skip autocomplete for level 0 and level 1 buildings
    building_level = get_first_queue_building_level(driver)
    if building_level is not None and building_level <= 1:
        warn(f"Level {building_level} build - too fast, skipping gold autocomplete.")
        return False
    
    finish_seconds = get_queue_finish_seconds(driver)
    if finish_seconds is not None and finish_seconds < 180:
        warn(f"Queue finishes in {finish_seconds}s - under 3 min, skipping gold autocomplete.")
        return False
    
    print("2 builds in queue (level 2+) - autocompleting!")
    try:
        finish_btn = driver.find_element(By.CSS_SELECTOR, "a[href*='buildingFinish=1']")
        finish_btn.click()
        ok("Autocomplete clicked!")
        wait()
        return True
    except Exception:
        ok("No autocomplete button found.")
    
    return False

def has_enough_resources(driver):
    """
    Returns True if resources are sufficient for the current upgrade/build.
    Primary check is numeric and on-page: compares live resource bar (l1-l4)
    against the exact cost from #contract.
    Falls back to build-button href heuristic when cost cannot be read.
    """
    # Prefer exact numeric check from current page.
    try:
        cost = get_upgrade_cost(driver)
        if cost:
            lumber = int(driver.find_element(By.ID, "l4").text.split("/")[0].replace(",", "").strip())
            clay   = int(driver.find_element(By.ID, "l3").text.split("/")[0].replace(",", "").strip())
            iron   = int(driver.find_element(By.ID, "l2").text.split("/")[0].replace(",", "").strip())
            crop   = int(driver.find_element(By.ID, "l1").text.split("/")[0].replace(",", "").strip())
            return (
                lumber >= cost["lumber"] and
                clay   >= cost["clay"] and
                iron   >= cost["iron"] and
                crop   >= cost["crop"]
            )
    except Exception:
        pass

    # Fallback heuristic for pages where #contract is unavailable.
    try:
        upgrade_btn = driver.find_element(By.CSS_SELECTOR, "a.build")
        href = upgrade_btn.get_attribute("href")
        if href and "master=" in href:
            return False
        return bool(href)
    except Exception:
        return False


def get_live_resource_amounts(driver):
    """
    Reads current resource amounts from top bar (#l1-#l4).
    Returns dict with lumber/clay/iron/crop, or None if unreadable.
    """
    try:
        return {
            "lumber": int(driver.find_element(By.ID, "l4").text.split("/")[0].replace(",", "").strip()),
            "clay":   int(driver.find_element(By.ID, "l3").text.split("/")[0].replace(",", "").strip()),
            "iron":   int(driver.find_element(By.ID, "l2").text.split("/")[0].replace(",", "").strip()),
            "crop":   int(driver.find_element(By.ID, "l1").text.split("/")[0].replace(",", "").strip()),
        }
    except Exception:
        return None


def has_enough_resources_for_cost(driver, cost):
    """
    Strict affordability check using known cost and live top-bar resources.
    Returns True/False when live resources can be read, else falls back to
    has_enough_resources(driver).
    """
    if not cost:
        return has_enough_resources(driver)

    live = get_live_resource_amounts(driver)
    if not live:
        return has_enough_resources(driver)

    return (
        live["lumber"] >= int(cost.get("lumber", 0)) and
        live["clay"]   >= int(cost.get("clay", 0)) and
        live["iron"]   >= int(cost.get("iron", 0)) and
        live["crop"]   >= int(cost.get("crop", 0))
    )

def get_upgrade_cost(driver):
    """
    Reads upgrade cost directly from the current building page.
    Returns dict with lumber, clay, iron, crop costs.
    Returns None if cost cannot be read (page error or wrong page).
    """
    try:
        contract = driver.find_element(By.ID, "contract")

        # Preferred: read exact values from NPC trade query params in contract HTML.
        # Example: ...r1=4840&r2=2420&r3=4840&r4=3025...
        html = contract.get_attribute("innerHTML") or ""
        m = re.search(r"r1=(\d+).*?r2=(\d+).*?r3=(\d+).*?r4=(\d+)", html, re.IGNORECASE | re.DOTALL)
        if m:
            return {
                "lumber": int(m.group(1)),
                "clay":   int(m.group(2)),
                "iron":   int(m.group(3)),
                "crop":   int(m.group(4)),
            }

        # Fallback 1: read numeric .value nodes from the contract block.
        # Some pages render costs in spans/divs instead of pipe-delimited text.
        try:
            vals = []
            for el in contract.find_elements(By.CSS_SELECTOR, ".value"):
                digits = re.sub(r"\D", "", (el.text or "").strip())
                if digits:
                    vals.append(int(digits))
            if len(vals) >= 4:
                return {
                    "lumber": vals[0],
                    "clay":   vals[1],
                    "iron":   vals[2],
                    "crop":   vals[3],
                }
        except Exception:
            pass

        # Fallback: parse the first four '|' sections and take the LAST numeric token
        # in each section (avoids capturing "level 9" in the first section).
        text = contract.text
        parts = text.split("|")
        if len(parts) >= 4:
            values = []
            for part in parts[:4]:
                nums = re.findall(r"\d[\d., ]*", part)
                if not nums:
                    values = []
                    break
                digits = re.sub(r"\D", "", nums[-1])
                if not digits:
                    values = []
                    break
                values.append(int(digits))
            if len(values) == 4:
                return {
                    "lumber": values[0],
                    "clay":   values[1],
                    "iron":   values[2],
                    "crop":   values[3],
                }
    except Exception:
        pass
    return None

def get_building_level(driver):
    """
    Reads the current level of a building from its page.
    Returns 0 if level cannot be determined.
    """
    try:
        level_text = driver.find_element(By.CSS_SELECTOR, "span.level").text
        m = re.search(r"(\d+)", level_text or "")
        if m:
            return int(m.group(1))
    except Exception:
        pass
    return 0

def get_village_buildings(driver, village=None):
    """
    Reads all buildings present in the village from dorf2 in a single page load.
    Returns a dict keyed by lowercase building name mapped to {"level": int, "slot": int}.
    Building sites (empty slots) are excluded.
    Use this instead of calling building_exists_in_village + find_building_slot
    separately — one load answers both questions at once.
    """
    url = BASE_URL + "dorf2.php"
    if village:
        url += f"?newdid={village['id']}"
    driver.get(url)
    wait()
    areas     = driver.find_elements(By.CSS_SELECTOR, "area[title]")
    buildings = {}
    for area in areas:
        title = area.get_attribute("title")
        if not title:
            continue
        normalized = " ".join(title.split())
        if "building site" in normalized.lower():
            continue
        level_match = re.search(r"(?:level|lvl)\.?\s*(\d+)", normalized, re.IGNORECASE)
        level       = int(level_match.group(1)) if level_match else 1
        href        = area.get_attribute("href") or ""
        slot_match  = re.search(r"id=(\d+)", href)
        slot        = int(slot_match.group(1)) if slot_match else None
        # Strip "Level N" suffix to recover the clean building name
        name = re.sub(r"\s+(?:level|lvl)\.?\s*\d+.*$", "", normalized, flags=re.IGNORECASE).strip().lower()
        buildings[name] = {"level": level, "slot": slot}
    return buildings


def building_exists_in_village(driver, building_name, village=None):
    """
    Checks village map on dorf2 to see if a building exists.
    Returns current level if found, 0 if not found.
    For bulk lookups (multiple buildings at once), prefer get_village_buildings()
    directly to avoid repeated dorf2 navigations.
    """
    buildings  = get_village_buildings(driver, village)
    name_lower = building_name.lower()
    if name_lower in buildings:
        return buildings[name_lower]["level"]
    for bname, bdata in buildings.items():
        if name_lower in bname:
            return bdata["level"]
    return 0


def find_building_slot(driver, building_name, village=None):
    """
    Scans dorf2 map to find which slot a building is on.
    Returns slot number (int) if found, None if not found.
    For bulk lookups (multiple buildings at once), prefer get_village_buildings()
    directly to avoid repeated dorf2 navigations.
    """
    buildings  = get_village_buildings(driver, village)
    name_lower = building_name.lower()
    if name_lower in buildings:
        return buildings[name_lower]["slot"]
    for bname, bdata in buildings.items():
        if name_lower in bname:
            return bdata["slot"]
    return None


def get_village_resource_fields(driver, village=None):
    """
    Reads all resource fields from the village map on dorf1 in a single page load.
    Parses level and type directly from area[title] attributes — no individual
    build.php navigation needed.
    Returns a list of dicts: {"id", "type", "level", "url"} sorted lowest to
    highest level, ready for bottom-up greedy upgrading.
    Pass village to navigate with newdid and avoid context drift.
    """
    url = BASE_URL + "dorf1.php"
    if village:
        url += f"?newdid={village['id']}"
    driver.get(url)
    wait()
    fields = []
    for area in driver.find_elements(By.CSS_SELECTOR, "area[href*='build.php?id=']"):
        title = area.get_attribute("title")
        href  = area.get_attribute("href")
        if not title or not href:
            continue
        level_match = re.search(r"(?:level|lvl)\.?\s*(\d+)", title, re.IGNORECASE)
        if not level_match:
            continue
        level      = int(level_match.group(1))
        field_type = re.sub(r"\s+(?:level|lvl)\.?\s*\d+.*$", "", title, flags=re.IGNORECASE).strip()
        field_id   = re.search(r"id=(\d+)", href)
        fields.append({
            "id":    field_id.group(1) if field_id else None,
            "type":  field_type,
            "level": level,
            "url":   href,
        })
    return sorted(fields, key=lambda f: f["level"])
