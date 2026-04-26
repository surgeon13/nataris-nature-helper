# ==========================================
#           NATARIS RESOURCE SENDER
#           Scans all villages for surplus
#           resources and sends them to a
#           target village via merchants.
#           Generic - no hardcoded roles.
#           User decides who sends and receives.
#           Respects crop deficit flag.
# ==========================================

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from buildings import BUILDINGS
from helpers import BASE_URL, wait, get_all_villages, switch_village_resources, find_building_slot, red, yellow, green, cyan, bold, info, ok, warn, err, status
import time
import math
import sys
import re
import os
import json

# ==========================================
#           TIMED INPUT
#           Waits for user input with a
#           countdown. Returns default_val
#           automatically after timeout.
# ==========================================

def timed_input(prompt, default_val, timeout=30):
    """
    Prompts the user for input with a countdown timer.
    If no input is received within timeout seconds, returns default_val.
    Works on Windows using msvcrt.
    """
    import msvcrt
    print(f"{prompt} (auto-selecting '{default_val}' in {timeout}s) ", end="", flush=True)
    start = time.time()
    chars = []
    while True:
        elapsed = time.time() - start
        remaining = timeout - elapsed
        if remaining <= 0:
            print(f"\n[Auto] No input - using: {default_val}")
            return str(default_val)
        if msvcrt.kbhit():
            ch = msvcrt.getwche()
            if ch in ("\r", "\n"):
                print()
                return "".join(chars).strip() or str(default_val)
            elif ch == "\b":  # backspace
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
            else:
                chars.append(ch)
        time.sleep(0.05)

# ==========================================
#           DISTANCE CALCULATION
# ==========================================

def calculate_distance(coords1, coords2):
    """
    Calculates distance between two villages using coordinates.
    coords format: (x, y)
    Returns distance in fields.
    """
    if not coords1 or not coords2:
        return float('inf')  # Prioritize villages with known coords
    
    x1, y1 = coords1
    x2, y2 = coords2
    return math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)

def get_resources(driver):
    """
    Reads current resources and max capacity from resource bar.
    Returns dict with current and max for each resource type.
    Returns None if resource bar is not found (wrong page or load failure).
    """
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.ID, "l4")))
    except Exception:
        return None

    def to_int(text):
        # Locale-safe parse: 12,345 / 12.345 / 12 345 -> 12345
        digits = re.sub(r"\D", "", text or "")
        return int(digits) if digits else 0

    def parse(el_id):
        try:
            parts = driver.find_element(By.ID, el_id).text.split("/")
            current = to_int(parts[0]) if len(parts) > 0 else 0
            maximum = to_int(parts[1]) if len(parts) > 1 else 0
            return {"current": current, "max": maximum}
        except Exception:
            return {"current": 0, "max": 0}
    return {
        "lumber": parse("l4"),
        "clay":   parse("l3"),
        "iron":   parse("l2"),
        "crop":   parse("l1"),
    }

def get_crop_balance(driver):
    """
    Reads crop production vs consumption from l5 element.
    Returns True if crop is in deficit (consumption > production).
    """
    try:
        text = driver.find_element(By.ID, "l5").text
        parts = text.split("/")
        consumption = int(parts[0].replace(",", ""))
        production  = int(parts[1].replace(",", ""))
        return production - consumption < 0
    except Exception:
        return False

def get_merchant_count(driver):
    """
    Reads available merchant count from marketplace page.
    Returns number of available merchants.
    """
    try:
        text = driver.find_element(By.CSS_SELECTOR, "td.mer").text
        available = int(text.strip().split("/")[0].split()[-1])
        return available
    except Exception:
        return 0

def calculate_surplus(resources, threshold=0.5):
    """
    Calculates how much of each resource is above the threshold.
    Default threshold is 50% of max capacity.
    Only returns positive surplus amounts.
    """
    surplus = {}
    for res, data in resources.items():
        spare = data["current"] - int(data["max"] * threshold)
        surplus[res] = max(0, spare)
    return surplus

def scan_villages_for_surplus(driver, villages, threshold):
    """
    Scans all villages and returns their surplus resources.
    Skips villages with crop deficit or no marketplace.
    """
    results = []
    for village in villages:
        switch_village_resources(driver, village)

        resources    = get_resources(driver)
        crop_deficit = get_crop_balance(driver)

        if crop_deficit:
            err(f"  {village['name']} - crop deficit, skipping")
            continue

        surplus = calculate_surplus(resources, threshold)
        if sum(surplus.values()) == 0:
            warn(f"  {village['name']} - no surplus")
            continue

        # Check if marketplace exists
        driver.get(BASE_URL + f"dorf2.php?newdid={village['id']}")
        wait()
        has_market = False
        areas = driver.find_elements(By.CSS_SELECTOR, "area[title]")
        for area in areas:
            title = area.get_attribute("title")
            if title and "Marketplace" in title:
                has_market = True
                break

        if not has_market:
            warn(f"  {village['name']} - no marketplace")
            continue

        market_slot = find_building_slot(driver, "Marketplace")
        if not market_slot:
            warn(f"  {village['name']} - marketplace not found on map")
            continue
        driver.get(BASE_URL + f"build.php?id={market_slot}")
        wait()
        merchants = get_merchant_count(driver)

        if merchants == 0:
            warn(f"  {village['name']} - no merchants available")
            continue

        print(f"  {village['name']} - Surplus: L:{surplus['lumber']} C:{surplus['clay']} "
              f"I:{surplus['iron']} Cr:{surplus['crop']} - Merchants: {merchants}")
        results.append({
            "village":   village,
            "surplus":   surplus,
            "merchants": merchants,
            "resources": resources,
        })

    return results

# Marketplace resource field max (maxlength="5" confirmed from live HTML)
MARKET_MAX_PER_FIELD = 99999

def get_merchant_capacity(driver):
    """
    Returns total carry capacity available for this village in one trip.
    Reads directly from the marketplace page td.mer which shows "available/total"
    and from td.car which shows carry capacity per merchant.
    Falls back to available_merchants * 500 if carry per merchant cannot be read.
    This automatically accounts for Trade Office upgrades.
    """
    try:
        # td.mer = "Merchants 9/9" or similar
        mer_text = driver.find_element(By.CSS_SELECTOR, "td.mer").text
        available = int(mer_text.strip().split("/")[0].split()[-1])
    except Exception:
        available = 0

    if available == 0:
        return 0

    try:
        # td.car shows carry capacity per merchant e.g. "500" or "750"
        carry_text = driver.find_element(By.CSS_SELECTOR, "td.car").text
        carry_per  = int(carry_text.strip().replace(",", ""))
    except Exception:
        # Fallback: use known base values by tribe
        try:
            from accounts import accounts
            tribe = accounts[0].get("tribe", "roman").lower()
            carry_per = {"roman": 500, "teuton": 1000, "gaul": 750}.get(tribe, 500)
        except Exception:
            carry_per = 500

    return available * carry_per

def cap_to_merchant_capacity(amounts, driver, merchant_count=None):
    """
    Caps amounts to exact merchant carry capacity.
    Keeps exact requested values (no 100-rounding), so small shortfalls
    like 12 resources are not rounded down to 0.
    """
    if merchant_count is not None:
        try:
            carry_text = driver.find_element(By.CSS_SELECTOR, "td.car").text
            carry_per  = int(carry_text.strip().replace(",", ""))
        except Exception:
            try:
                from accounts import accounts
                tribe = accounts[0].get("tribe", "roman").lower()
                carry_per = {"roman": 500, "teuton": 1000, "gaul": 750}.get(tribe, 500)
            except Exception:
                carry_per = 500
        total_capacity = merchant_count * carry_per
    else:
        total_capacity = get_merchant_capacity(driver)

    total_requested = sum(amounts.values())

    if total_requested <= total_capacity:
        # Already fits â€” keep exact requested values
        return {res: int(val) for res, val in amounts.items()}

    # Scale down proportionally using integer values
    ratio  = total_capacity / total_requested
    capped = {}
    for res, val in amounts.items():
        capped[res] = int(val * ratio)

    # Fill remaining capacity back up in 1-unit increments,
    # prioritising resources with most remaining headroom
    res_order = ["lumber", "clay", "iron", "crop"]
    while True:
        used      = sum(capped.values())
        remaining = total_capacity - used
        if remaining < 1:
            break
        # Pick resource with most headroom that can still receive 100 more
        candidates = [
            r for r in res_order
            if amounts[r] - capped[r] >= 1
        ]
        if not candidates:
            break
        candidates.sort(key=lambda r: amounts[r] - capped[r], reverse=True)
        capped[candidates[0]] += 1

    return capped

def plan_full_merchant_load(donor_available, required_shortfall, target_free, total_capacity):
    """
    Builds an efficient one-trip send plan.

    Rules:
    1) Always prioritize the required shortfall first.
    2) If capacity remains, top up additional resources toward target free space.
    3) Never exceed donor availability, target free capacity, or merchant capacity.
    """
    resources = ("lumber", "clay", "iron", "crop")

    cap = max(0, int(total_capacity or 0))
    if cap <= 0:
        return {r: 0 for r in resources}

    send = {r: 0 for r in resources}

    # Step 1: reserve mandatory shortfall where possible
    for r in resources:
        donor_have = max(0, int(donor_available.get(r, 0)))
        need = max(0, int(required_shortfall.get(r, 0)))
        free = max(0, int(target_free.get(r, 0)))
        send[r] = min(donor_have, need, free)

    used = sum(send.values())
    if used >= cap:
        return cap_to_total(send, cap)

    # Step 2: add extra top-up to use remaining merchants efficiently
    extra_headroom = {}
    for r in resources:
        donor_left = max(0, int(donor_available.get(r, 0)) - send[r])
        free_left = max(0, int(target_free.get(r, 0)) - send[r])
        extra_headroom[r] = min(donor_left, free_left)

    remaining_cap = cap - used
    total_headroom = sum(extra_headroom.values())
    if remaining_cap <= 0 or total_headroom <= 0:
        return send

    # Proportional initial allocation
    for r in resources:
        h = extra_headroom[r]
        if h <= 0:
            continue
        add = min(h, int((remaining_cap * h) / total_headroom))
        send[r] += add

    # Fill any leftover one unit at a time by highest remaining headroom
    while True:
        used_now = sum(send.values())
        if used_now >= cap:
            break
        candidates = []
        for r in resources:
            donor_left = max(0, int(donor_available.get(r, 0)) - send[r])
            free_left = max(0, int(target_free.get(r, 0)) - send[r])
            room = min(donor_left, free_left)
            if room > 0:
                candidates.append((room, r))
        if not candidates:
            break
        candidates.sort(reverse=True)
        send[candidates[0][1]] += 1

    return send


def parse_farmlist(driver):
    """Parse in-game farmlist UI and return list of targets.
    Tries a few heuristics and returns a list of dicts: {name, coords?(x,y), id?}
    """
    targets = []
    try:
        # Try known farmlist screen
        driver.get(BASE_URL + "dorf3.php?s=2")
        wait()

        # Look for rows in common containers
        candidates = []
        try:
            candidates = driver.find_elements(By.CSS_SELECTOR, "#farm_list tbody tr, .farm_list tr, .farmlist tr")
        except Exception:
            candidates = []

        if not candidates:
            # fallback: look at any list items or anchors that contain coords text
            candidates = driver.find_elements(By.CSS_SELECTOR, "a, li, tr, td")

        seen = set()
        coord_re = re.compile(r"(-?\d+)\s*\|\s*(-?\d+)")

        for el in candidates:
            try:
                text = el.text.strip()
                if not text:
                    continue
                # find coords
                m = coord_re.search(text)
                coords = None
                if m:
                    try:
                        x = int(m.group(1))
                        y = int(m.group(2))
                        coords = (x, y)
                    except Exception:
                        coords = None

                # find village id from href if present
                vid = None
                try:
                    a = el.find_element(By.CSS_SELECTOR, "a[href*='newdid=']")
                    href = a.get_attribute("href") or ""
                    m2 = re.search(r"newdid=(\d+)", href)
                    if m2:
                        vid = int(m2.group(1))
                except Exception:
                    # try any child anchor
                    try:
                        a2 = el.find_element(By.TAG_NAME, "a")
                        href = a2.get_attribute("href") or ""
                        m2 = re.search(r"newdid=(\d+)", href)
                        if m2:
                            vid = int(m2.group(1))
                    except Exception:
                        vid = None

                name = None
                # pick a reasonable name string from element text
                parts = [p for p in text.splitlines() if p.strip()]
                if parts:
                    name = parts[0]

                key = (name, coords, vid)
                if key in seen:
                    continue
                seen.add(key)

                if name or coords or vid:
                    entry = {}
                    if name:
                        entry["name"] = name
                    if coords:
                        entry["coords"] = coords
                    if vid:
                        entry["id"] = vid
                    targets.append(entry)
            except Exception:
                continue

    except Exception:
        return []

    return targets

def cap_to_total(amounts, cap):
    """Caps a resource dict to a total sum while keeping integer values."""
    cap = max(0, int(cap or 0))
    total = sum(max(0, int(v)) for v in amounts.values())
    if total <= cap:
        return {k: max(0, int(v)) for k, v in amounts.items()}

    if cap == 0:
        return {k: 0 for k in amounts}

    ratio = cap / total
    out = {k: int(max(0, int(v)) * ratio) for k, v in amounts.items()}

    keys = ["lumber", "clay", "iron", "crop"]
    while sum(out.values()) < cap:
        candidates = [
            k for k in keys
            if k in out and max(0, int(amounts.get(k, 0))) - out[k] > 0
        ]
        if not candidates:
            break
        candidates.sort(key=lambda k: max(0, int(amounts.get(k, 0))) - out[k], reverse=True)
        out[candidates[0]] += 1

    return out

def _click_ok(driver):
    """
    Clicks the OK/submit button on marketplace form and confirmation page.
    Tries multiple selectors in order of likelihood.
    If none found, logs a warning - caller should check if send succeeded.
    """
    selectors = [
        (By.ID,          "btn_ok"),
        (By.CSS_SELECTOR,"input[name='s1']"),
        (By.CSS_SELECTOR,"input[type='image']"),
        (By.CSS_SELECTOR,"input[type='submit']"),
        (By.CSS_SELECTOR,"button[type='submit']"),
    ]
    for by, sel in selectors:
        try:
            driver.find_element(by, sel).click()
            return True
        except Exception:
            continue
    warn("Could not find OK button on page - send may have failed.")
    return False


def detect_captcha_on_page(driver):
    """Detects common captcha elements on the current page.
    Returns True if a captcha-like input or image is found.
    """
    try:
        # common input names
        captcha_inputs = ["captcha", "captcha_code", "captcha_val", "captcha_input"]
        for name in captcha_inputs:
            els = driver.find_elements(By.NAME, name)
            if els:
                return True

        # image-based captchas
        imgs = driver.find_elements(By.TAG_NAME, "img")
        for img in imgs:
            src = img.get_attribute("src") or ""
            if "captcha" in src.lower():
                return True

        # generic containers
        if driver.find_elements(By.ID, "captcha"):
            return True
    except Exception:
        return False
    return False


def handle_captcha_manual(driver, abort_flag, prompt_timeout=120):
    """Save a screenshot, ask the user to solve captcha, fill it, and submit.
    Returns True if solved and submitted, False otherwise.
    """
    try:
        fname = os.path.abspath("captcha.png")
        try:
            driver.save_screenshot(fname)
        except Exception:
            pass

        # Prefer using a provided captcha solver module if available
        try:
            import captcha_solver
            if hasattr(captcha_solver, "solve"):
                ok("Attempting automated captcha solve via `captcha_solver.solve()`...")
                try:
                    solution = captcha_solver.solve(fname)
                except Exception as e:
                    warn(f"captcha_solver.solve() failed: {e}")
                    solution = None
                if solution:
                    val = str(solution).strip()
                else:
                    val = None
            else:
                val = None
        except Exception:
            val = None

        # If automated solver not used or failed, ask user
        if not val:
            ok(f"Captcha detected. Screenshot saved to {fname}. Please solve it.")
            val = timed_input("Enter captcha value (or empty to abort)", "", timeout=prompt_timeout)

        if not val:
            err("No captcha entered. Aborting send.")
            return False

        # Try filling known input names
        filled = False
        for name in ("captcha", "captcha_code", "captcha_val", "captcha_input"):
            try:
                els = driver.find_elements(By.NAME, name)
                if els:
                    els[0].clear()
                    els[0].send_keys(val)
                    filled = True
                    break
            except Exception:
                continue

        # Fallback: try input[type=text] with placeholder containing 'captcha'
        if not filled:
            try:
                inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text']")
                for inp in inputs:
                    ph = (inp.get_attribute("placeholder") or "").lower()
                    if "captcha" in ph:
                        inp.clear()
                        inp.send_keys(val)
                        filled = True
                        break
            except Exception:
                pass

        if not filled:
            warn("Could not find captcha input to fill â€” please enter it manually in the browser.")
            return False

        # Submit
        _click_ok(driver)
        wait()
        ok("Captcha submitted â€” continuing.")
        return True
    except Exception as e:
        err(f"Captcha handling failed: {e}")
        return False

def send_resources(driver, from_village, to_village, amounts, merchant_count=None, market_slot=None):
    """
    Sends resources from one village to another via marketplace.
    Handles the two-step send confirmation (ft=check -> confirm).
    Uses coordinates (x, y) as target if available, falls back to village name.
    Caps total send to merchant carry capacity (one trip).
    market_slot: pass the known slot id to avoid re-scanning dorf2.
    Confirmed selectors from live HTML: #r1-#r4, input[name=dname], #btn_ok.
    """
    total_sent = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}

    # Find marketplace slot if not provided - use slot-based URL for trading page
    if market_slot is None:
        driver.get(BASE_URL + f"dorf2.php?newdid={from_village['id']}")
        wait()
        market_slot = find_building_slot(driver, "Marketplace")
        if not market_slot:
            warn(f"No marketplace found in {from_village['name']} - skipping.")
            return False

    # Navigate to marketplace trading page via slot (not gid=17 which is construction)
    driver.get(BASE_URL + f"build.php?id={market_slot}&newdid={from_village['id']}")
    wait()

    # Read live merchant count from marketplace page
    live_merchants = get_merchant_count(driver)
    if live_merchants == 0:
        warn(f"No merchants available at {from_village['name']} - skipping.")
        return False

    # Cap to what merchants can actually carry in one trip (using live page data)
    amounts = cap_to_merchant_capacity(amounts, driver, live_merchants)

    # Also cap each field to maxlength=5 limit
    amounts = {r: min(v, MARKET_MAX_PER_FIELD) for r, v in amounts.items()}

    if sum(amounts.values()) == 0:
        warn(f"Nothing to send after merchant capacity cap ({live_merchants} merchants).")
        return False

    remaining = dict(amounts)

    ok(f"\nSending from {from_village['name']} to [target] {to_village['name']}...")
    status(f"  L:{amounts.get('lumber',0)}  C:{amounts.get('clay',0)}  "
           f"I:{amounts.get('iron',0)}  Cr:{amounts.get('crop',0)}")

    for trip in range(1):  # single trip only - capacity already capped above
        this_send = dict(remaining)

        if sum(this_send.values()) == 0:
            break

        # Already on marketplace page - only re-navigate on subsequent trips
        if trip > 0:
            driver.get(BASE_URL + f"build.php?id={market_slot}&newdid={from_village['id']}")
            wait()

        try:
            # Fill resource fields
            for field_id, res in [("r1","lumber"),("r2","clay"),("r3","iron"),("r4","crop")]:
                if this_send[res] > 0:
                    field = driver.find_element(By.ID, field_id)
                    field.clear()
                    field.send_keys(str(this_send[res]))
                    time.sleep(0.3)

            # Target: prefer coordinates (always reliable), fall back to village name
            coords = to_village.get("coords")
            if coords:
                x_field = driver.find_element(By.CSS_SELECTOR, "input[name='x']")
                y_field = driver.find_element(By.CSS_SELECTOR, "input[name='y']")
                x_field.clear()
                x_field.send_keys(str(coords[0]))
                y_field.clear()
                y_field.send_keys(str(coords[1]))
            else:
                target_field = driver.find_element(By.CSS_SELECTOR, "input[name='dname']")
                target_field.clear()
                target_field.send_keys(to_village["name"])
            time.sleep(0.5)

            # Submit form (step 1 - ft=check)
            _click_ok(driver)
            wait()

            # Detect and handle captcha if it appears on the confirmation page
            try:
                # Only handle captcha if the page shows common indicators
                if detect_captcha_on_page(driver):
                    ok("Captcha detected on confirmation page. Prompting for manual solve...")
                    solved = handle_captcha_manual(driver, abort_flag)
                    if not solved:
                        err("Captcha not solved â€” aborting send.")
                        return False
            except Exception:
                # Non-fatal â€” proceed to click confirm
                pass

            # Confirm send (step 2 - confirmation page)
            _click_ok(driver)
            wait()

            # Track what was sent
            for r in remaining:
                remaining[r]  -= this_send[r]
                total_sent[r] += this_send[r]

        except Exception as e:
            err(f"  Send failed: {e}")
            return False

    ok(f"  Done. Total sent - L:{total_sent['lumber']}  C:{total_sent['clay']}  "
          f"I:{total_sent['iron']}  Cr:{total_sent['crop']}")
    return True

def run_resource_sender(driver, abort_flag):
    """
    Main entry point for the resource sender (menu option 5).
    Mode A - Manual: user picks target village, then picks donor villages and amounts.
    Mode B - Auto:   user picks target village, bot finds donors and sends automatically.
    """
    info("\n========== RESOURCE SENDER ==========")

    print("\n  1. Manual  - I pick target and donors")
    print("  2. Auto    - I pick target, bot handles the rest")


# ==========================================
#           AUTOMATIC RESOURCE SENDER
#           Called from builder when out of
#           resources. No user interaction.
#           Finds donors and sends automatically.
# ==========================================

def auto_send_resources(driver, target_village, abort_flag, threshold=0.2, required_cost=None):
    """
    Automatically sends resources to target_village from other villages.
    No user interaction - scans, picks donors, and sends.
    Called by builder engine when stuck without enough resources.
    threshold: keep this % of capacity, send above it
    required_cost: optional dict with lumber/clay/iron/crop needed for the
                   immediate build. When provided, bot sends only shortfall.
    Returns True if any resources were sent, False otherwise.
    Logs arrival time of resources for scheduler to track.
    """
    import json
    import time
    import os
    
    info("\n[ResSend] Scan: looking for donor villages...")
    status(f"[target] {target_village['name']}")
    villages = get_all_villages(driver)
    
    if len(villages) <= 1:
        warn("[ResSend] Scan: only 1 village available, cannot send.")
        return False

    try:
        # Sort candidates by distance to target first â€” scan closest villages first
        target_coords = target_village.get("coords")
        candidates = [v for v in villages if v["id"] != target_village["id"]]
        candidates.sort(key=lambda v: calculate_distance(v.get("coords"), target_coords))

        # Get target free storage space once before scanning donors
        info(f"[ResSend] Target: [target] {target_village['name']} - checking storage and current stock...")
        switch_village_resources(driver, target_village)
        target_resources = get_resources(driver)
        shortfall = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}
        if target_resources and required_cost:
            for res in ("lumber", "clay", "iron", "crop"):
                shortfall[res] = max(0, int(required_cost.get(res, 0)) - int(target_resources[res]["current"]))
            if sum(shortfall.values()) == 0:
                ok("[ResSend] Shortfall: none (build already affordable).")
                return False

        target_free = {"lumber": 999999, "clay": 999999, "iron": 999999, "crop": 999999}
        target_headroom = {"lumber": 999999, "clay": 999999, "iron": 999999, "crop": 999999}
        if target_resources:
            for res in ("lumber", "clay", "iron", "crop"):
                current = target_resources[res]["current"]
                max_cap = target_resources[res]["max"]
                fill_to = int(max_cap * 0.9)
                free_to_max = max(0, max_cap - current)
                free_for_fill = max(0, fill_to - current)
                target_headroom[res] = free_to_max
                if required_cost:
                    target_free[res] = min(free_to_max, shortfall[res])
                else:
                    target_free[res] = free_for_fill

            if required_cost:
                info(f"[ResSend] Shortfall - L:{shortfall['lumber']} C:{shortfall['clay']} "
                     f"I:{shortfall['iron']} Cr:{shortfall['crop']}")
            info(f"[ResSend] Receivable - L:{target_free['lumber']} C:{target_free['clay']} "
                 f"I:{target_free['iron']} Cr:{target_free['crop']}")

        if required_cost and sum(target_free.values()) == 0:
            warn("[ResSend] Target storage receivable is 0 for all resources. Skipping donor scan.")
            return False

        # Scan in distance order â€” send from the first viable donor and stop
        total_sent = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}

        for village in candidates:
            if abort_flag and abort_flag[0]:
                return False

            status(f"[donor] {village['name']}")

            switch_village_resources(driver, village)
            resources = get_resources(driver)

            if resources is None:
                continue

            if get_crop_balance(driver):
                warn(f"  {village['name']} - crop deficit, skipping")
                continue

            surplus = calculate_surplus(resources, threshold)
            if sum(surplus.values()) == 0:
                continue

            # Marketplace presence already known from sidebar â€” skip dorf2 entirely
            if not village.get("has_market"):
                continue

            # Navigate directly via gid=17 â€” no need to find the slot
            driver.get(BASE_URL + f"build.php?gid=17&newdid={village['id']}")
            wait()
            merchants = get_merchant_count(driver)

            if merchants == 0:
                continue

            # Found a viable donor â€” calculate and send immediately
            dist = calculate_distance(village.get("coords"), target_coords)
            ok(f"\n[ResSend] Donor: {village['name']} ({dist:.0f} fields) -> [target] {target_village['name']}")

            donor_available = {}
            for res in ("lumber", "clay", "iron", "crop"):
                donor_available[res] = max(0, resources[res]["current"] - 200)

            if required_cost:
                merchant_capacity = get_merchant_capacity(driver)
                to_send = plan_full_merchant_load(
                    donor_available=donor_available,
                    required_shortfall=target_free,
                    target_free=target_headroom,
                    total_capacity=merchant_capacity,
                )
                if sum(to_send.values()) > sum(target_free.values()):
                    status("[ResSend] Efficient mode: shortfall covered, topping up with full merchants.")
            else:
                to_send = {}
                for res in ("lumber", "clay", "iron", "crop"):
                    to_send[res] = min(donor_available[res], target_free[res])

            if sum(to_send.values()) == 0:
                warn(f"[ResSend] Donor {village['name']}: nothing sendable (target full or below minimum).")
                continue

            if send_resources(driver, village, target_village, to_send, merchants):
                for res in total_sent:
                    total_sent[res] += to_send.get(res, 0)
                break  # First successful send â€” done

        sent_anything = sum(total_sent.values()) > 0
        if sent_anything:
            ok(f"[ResSend] Sent - L:{total_sent['lumber']}  C:{total_sent['clay']}  "
               f"I:{total_sent['iron']}  Cr:{total_sent['crop']}")
            
            # Log arrival time - estimate 5 minutes for typical distance
            arrival_time = time.time() + 300  # 5 minute estimate
            builder_task = {
                "status": "waiting_for_resources",
                "target_village": target_village,
                "sent_at": time.time(),
                "expected_arrival": arrival_time,
                "total_sent": total_sent
            }
            
            try:
                _BT = os.path.join(os.path.dirname(__file__), "builder_task.json")
                with open(_BT, "w") as f:
                    json.dump(builder_task, f, indent=2)
                ok(f"[ResSend] ETA logged (~5 minutes).")
            except Exception as e:
                warn(f"[ResSend] ETA log failed: {e}")
        else:
            warn("[ResSend] Result: no resources sent.")
        
        return sent_anything
    finally:
        # Keep builder/template context stable after scanning donor villages.
        try:
            switch_village_resources(driver, target_village)
        except Exception:
            pass

