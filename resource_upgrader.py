# ==========================================
#           NATARIS RESOURCE UPGRADER
#           Upgrades resource fields using
#           bottom-up greedy algorithm.
#           Always upgrades lowest level first.
#           Upgrades storage on demand only.
#           Autocompletes only when 2 in queue.
#           Waits in place if resources run out.
#           Never exits unless aborted or done.
# ==========================================

from selenium.webdriver.common.by import By
from buildings import BUILDINGS
from helpers import (
    BASE_URL, wait, idle,
    get_all_villages, switch_village_resources,
    get_storage_capacity, storage_is_sufficient, get_upgrade_cost,
    get_queue_status, autocomplete_if_two_in_queue, has_enough_resources,
    get_village_coords, chebyshev_distance,
    get_travel_time_between, get_server_time, get_server_lag_ms,
    get_queue_finish_seconds, get_queue_finish_times, format_queue_time,
    get_village_resource_fields,
    red, yellow, green, cyan, bold, info, ok, warn, err, status
)
from village_builder_engine import upgrade_storage_if_needed
from resource_sender import (
    scan_villages_for_surplus,
    send_resources,
    get_resources,
    get_merchant_count,
    get_crop_balance,
    get_merchant_capacity,
    plan_full_merchant_load,
)
import os
import json
import time

SETTINGS_FILE = os.path.join(os.path.dirname(__file__), "bot_settings.json")


def _load_res_send_tuning():
    """
    Loads optional ResSend tuning from bot settings.
    Returns (close_distance, donor_full_pct, topup_target_pct).
    """
    close_distance = 15
    donor_full_pct = 85
    topup_target_pct = 90
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                close_distance = int(data.get("res_send_close_distance", close_distance))
                donor_full_pct = int(data.get("res_send_donor_full_pct", donor_full_pct))
                topup_target_pct = int(data.get("res_send_topup_target_pct", topup_target_pct))
    except Exception:
        pass

    close_distance = max(1, min(100, close_distance))
    donor_full_pct = max(50, min(99, donor_full_pct))
    topup_target_pct = max(60, min(100, topup_target_pct))
    return close_distance, donor_full_pct, topup_target_pct

def try_send_resources_from_nearby(driver, target_village, field, abort_flag, send_threshold=0, fill_target_pct=25):
    """
    Called when the upgrader can't afford a build.
    Reads the exact cost needed, scans other villages for surplus,
    and sends only the exact shortfall.
    Then waits for merchants to arrive (60s per scan cycle).
    Falls back to idle if no donors found.
    Returns True when resources were sent (or are already in transit), False otherwise.
    """
    warn("\n[ResSend] Shortfall detected - scanning nearby villages...")
    status(f"[target] {target_village['name']}")

    try:
        # Anti-spam guard: if resources are already in transit for this village,
        # wait for arrival instead of dispatching another merchant wave.
        try:
            import json
            import os
            now = time.time()
            _BT = os.path.join(os.path.dirname(__file__), "builder_task.json")
            if os.path.exists(_BT):
                with open(_BT, "r") as f:
                    task = json.load(f)
                target = task.get("target_village", {}) if isinstance(task, dict) else {}
                eta = float(task.get("expected_arrival", 0) or 0)
                if (
                    isinstance(task, dict)
                    and task.get("status") == "waiting_for_resources"
                    and str(target.get("id", "")) == str(target_village.get("id", ""))
                    and eta > now
                ):
                    wait_secs = int(eta - now)
                    warn(f"[ResSend] Already in transit to {target_village['name']} (~{wait_secs}s). Skipping new send.")
                    idle(abort_flag, "Waiting for incoming resources.")
                    return True
        except Exception:
            pass

        # Read what we currently have and what we need
        driver.get(field["url"])
        wait()

        # When the UI shows "Building max level under construction" (or similar), the
        # upgrade is already running at its highest level so there is no cost to read.
        # Treat this as satisfied so we don't try to send resources for a non-existent
        # shortfall.
        try:
            none_texts = [
                (el.text or "").strip().lower()
                for el in driver.find_elements(By.CSS_SELECTOR, "span.none")
            ]
        except Exception:
            none_texts = []

        max_level_queued = any(
            "max level" in txt or "maximal" in txt or "building max" in txt
            for txt in none_texts
        )
        if max_level_queued:
            ok("[ResSend] Target field already at/queued for max level - skipping send.")
            return True

        cost = get_upgrade_cost(driver)
        if cost is None and field.get("gid_num"):
            # Construction-list page: #contract doesn't exist because multiple buildings
            # are shown.  Navigate to the specific building's link (a={gid_num}) so we
            # land on the single-building page where #contract is always present.
            gid_num = field["gid_num"]
            try:
                build_link = driver.find_element(
                    By.XPATH, f"//a[contains(@href,'a={gid_num}')]"
                )
                build_href = build_link.get_attribute("href")
                if build_href:
                    driver.get(build_href)
                    wait()
                    cost = get_upgrade_cost(driver)
            except Exception:
                pass
        if not cost:
            warn("[ResSend] Cost unavailable - skipping send to avoid overfill.")
            return False

        # Get current resources in target village
        info(f"[ResSend] Target: [target] {target_village['name']}")
        switch_village_resources(driver, target_village)
        current = get_resources(driver)

        if current is None:
            err("Could not read target village resources - falling back to idle wait.")
            return idle(abort_flag, "Not enough resources.")

        # Calculate exact shortfall only.
        needed = {}
        for res, key in [("lumber","lumber"),("clay","clay"),("iron","iron"),("crop","crop")]:
            shortfall = cost[key] - current[res]["current"]
            needed[res] = max(0, shortfall)

        # Opportunistic storage top-up target:
        # if a donor is very close and heavily stocked, try to fill target storage
        # toward this percentage in the same send to reduce future micro-sends.
        close_distance, donor_full_pct, topup_target_pct = _load_res_send_tuning()
        topup_needed = {}
        for res in ("lumber", "clay", "iron", "crop"):
            fill_to = int(current[res]["max"] * (topup_target_pct / 100.0))
            topup_needed[res] = max(0, fill_to - current[res]["current"])

        if sum(needed.values()) == 0:
            # Resources arrived since last check, just retry
            return True

        # Show request summary
        status(f"[ResSend] Shortfall - L:{needed['lumber']} C:{needed['clay']} I:{needed['iron']} Cr:{needed['crop']}")

        # Get all villages except the target
        all_villages = get_all_villages(driver)
        donors = [v for v in all_villages if v["id"] != target_village["id"]]

        # Rank donors by map proximity first so near villages are evaluated
        # before far ones when deciding if shortfall coverage is sufficient.
        target_coords = get_village_coords(driver, target_village)

        def donor_distance(v):
            c = get_village_coords(driver, v)
            if not target_coords or not c:
                return 10**9
            return chebyshev_distance(c, target_coords)

        donors.sort(key=donor_distance)

        if not donors:
            warn("[ResSend] No donor villages available - falling back to idle wait.")
            return idle(abort_flag, "Not enough resources.")

        # Need-aware scan - stop as soon as we found enough donors to satisfy the request.
        # This avoids scanning every village before sending and speeds up build cycles.
        surplus_villages = []
        covered = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}
        # With distance-sorted donors, allow early exit quickly once coverage is met.
        min_village_checks = 1
        villages_checked = 0

        def request_fully_covered():
            return all(covered[r] >= needed[r] for r in covered)

        for village in donors:
            villages_checked += 1
            status(f"[donor] {village['name']}")
            switch_village_resources(driver, village)
            resources = get_resources(driver)

            if resources is None:
                warn(f"  {village['name']} - could not read resources, skipping")
                continue

            crop_deficit = get_crop_balance(driver)  # True if production < consumption

            # Always show stats for every village so user can see what's going on
            r = resources
            status(f"  {village['name']:<25} "
                   f"L:{r['lumber']['current']:<6} C:{r['clay']['current']:<6} "
                   f"I:{r['iron']['current']:<6} Cr:{r['crop']['current']:<6}")

            if crop_deficit:
                err(f"    ^ CROP DEFICIT - skipping")
                continue

            # Calculate what this village can send towards our shortfall
            # Keep send_threshold % of warehouse + absolute minimum of 200
            donor_coords = get_village_coords(driver, village)
            donor_dist = chebyshev_distance(donor_coords, target_coords) if donor_coords and target_coords else 10**9
            close_donor = donor_dist <= close_distance
            rich_donor = all(
                resources[r]["current"] >= int(resources[r]["max"] * (donor_full_pct / 100.0))
                for r in ("lumber", "clay", "iron", "crop")
            )
            opportunistic_topup = close_donor and rich_donor

            donor_available = {}
            can_send = {}
            for res in ("lumber", "clay", "iron", "crop"):
                keep = max(200, int(resources[res]["max"] * send_threshold / 100))
                available = max(0, resources[res]["current"] - keep)
                donor_available[res] = available
                target_need = max(needed[res], topup_needed[res]) if opportunistic_topup else needed[res]
                can_send[res] = min(available, target_need)

            if sum(can_send.values()) == 0:
                continue  # nothing to send, no output needed

            # Check marketplace exists
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
                warn(f"  {village['name']} - no marketplace, skipping")
                continue

            driver.get(BASE_URL + f"build.php?newdid={village['id']}&gid=17")
            wait()
            merchants = get_merchant_count(driver)
            if merchants == 0:
                warn(f"  {village['name']} - no merchants available")
                continue

            send_plan = dict(can_send)
            if opportunistic_topup:
                merchant_capacity = get_merchant_capacity(driver)
                full_plan = plan_full_merchant_load(
                    donor_available=donor_available,
                    required_shortfall=needed,
                    target_free={
                        "lumber": max(0, current["lumber"]["max"] - current["lumber"]["current"]),
                        "clay":   max(0, current["clay"]["max"] - current["clay"]["current"]),
                        "iron":   max(0, current["iron"]["max"] - current["iron"]["current"]),
                        "crop":   max(0, current["crop"]["max"] - current["crop"]["current"]),
                    },
                    total_capacity=merchant_capacity,
                )
                if sum(full_plan.values()) > sum(send_plan.values()):
                    send_plan = full_plan

            travel_s = get_travel_time_between(driver, village, target_village)
            travel_min = max(1, travel_s // 60) if travel_s else 0
            ok(f"  {village['name']} - can send L:{send_plan['lumber']} C:{send_plan['clay']} I:{send_plan['iron']} Cr:{send_plan['crop']}"
               f"  ({travel_min}m)")
            if opportunistic_topup:
                status(
                    f"    [ResSend] Close+full donor detected ({donor_dist} fields, <= {close_distance}; "
                    f"full >= {donor_full_pct}%) - topping target toward {topup_target_pct}% storage."
                )
            entry = {
                "village":   village,
                "surplus":   send_plan,
                "merchants": merchants,
                "resources": resources,
                "travel_s":  travel_s,
            }
            surplus_villages.append(entry)

            # Update covered totals and stop scanning once request can be fully met.
            for res in covered:
                covered[res] += can_send[res]
            if villages_checked >= min_village_checks and request_fully_covered():
                ok("  [ResSend] Donor capacity sufficient - sending now.")
                break

        if not surplus_villages:
            warn("No nearby villages can help - falling back to idle wait.")
            return idle(abort_flag, "Not enough resources.")

        import datetime as dt

        # Send from donors closest first. Prefer nearby donors first and use farther
        # ones only when close donors cannot fully satisfy the request.
        surplus_villages.sort(key=lambda e: e.get("travel_s", 10**9))

        remaining = dict(needed)
        sent_any  = False
        max_travel = 0

        for entry in surplus_villages:
            if sum(remaining.values()) == 0:
                break
            if abort_flag and abort_flag[0]:
                return False

            donor   = entry["village"]
            surplus = entry["surplus"]

            # Only send what we still need and what the donor has
            to_send = {}
            for res in remaining:
                to_send[res] = min(remaining[res], surplus[res])

            if sum(to_send.values()) == 0:
                continue

            switch_village_resources(driver, donor)
            if send_resources(driver, donor, target_village, to_send):
                sent_any = True
                travel_s = entry.get("travel_s")
                if travel_s is None:
                    travel_s = get_travel_time_between(driver, donor, target_village)
                if travel_s > max_travel:
                    max_travel = travel_s
                for res in remaining:
                    remaining[res] = max(0, remaining[res] - to_send[res])

        if sent_any:
            lag_ms   = get_server_lag_ms(driver)
            lag_note = f" (server lag: {lag_ms}ms)" if lag_ms is not None else ""
            server_now = get_server_time(driver)
            if server_now:
                arrive_at = server_now + dt.timedelta(seconds=max_travel)
                ok(f"[ResSend] Sent. Server time: {server_now.strftime('%H:%M:%S')}{lag_note}")
                ok(f"[ResSend] ETA: {arrive_at.strftime('%H:%M:%S')} ({max_travel}s travel)")
            else:
                ok(f"[ResSend] Sent. Merchants on the way ({max_travel}s travel){lag_note}")

            # Persist ETA so later retries don't resend before arrivals land.
            try:
                import json
                _BT = os.path.join(os.path.dirname(__file__), "builder_task.json")
                with open(_BT, "w") as f:
                    json.dump({
                        "status": "waiting_for_resources",
                        "target_village": target_village,
                        "sent_at": time.time(),
                        "expected_arrival": time.time() + max(60, int(max_travel or 300)),
                    }, f, indent=2)
            except Exception:
                pass

            ok("[ResSend] Returning to main menu. Awaiting arrival.")
            return True
        else:
            err("[ResSend] No donor could send resources - falling back to idle wait.")
            return False
    finally:
        # Always restore context to the original target village after any donor scan/send.
        try:
            switch_village_resources(driver, target_village)
        except Exception:
            pass

def get_resource_fields(driver, village=None):
    """
    Reads all resource fields from dorf1 in a single page load.
    Delegates to get_village_resource_fields() in helpers.py.
    Kept here for backward compatibility with any direct callers.
    """
    return get_village_resource_fields(driver, village)

def run_resource_upgrade(driver, use_gold, batch_autocomplete=False, master_builder=False, abort_flag=None, send_threshold=0, tribe=None):
    """
    Main resource upgrader (menu option 2).
    Uses bottom-up greedy algorithm - always upgrades lowest level field first.
    Upgrades storage on demand only when costs exceed capacity.
    Autocompletes only when 2 builds are in queue.
    Waits in place if resources are insufficient.
    When target_level is 10 and all fields complete, offers to run the
    resource_buildings bonus template (Sawmill, Brickyard, etc.) automatically.
    """
    info("\n========== RESOURCE FIELD UPGRADER ==========")
    villages = get_all_villages(driver)

    print("Available villages:")
    for i, village in enumerate(villages):
        print(f"  {i + 1}. {village['name']}")

    while True:
        choice = input("\nWhich village to upgrade resources in? (enter number): ").strip()
        try:
            index = int(choice) - 1
            if 0 <= index < len(villages):
                selected = villages[index]
                break
            else:
                print(f"Please enter a number between 1 and {len(villages)}.")
        except Exception:
            err("Invalid input.")

    while True:
        level_input = input("Upgrade fields to what level? (1-10): ").strip()
        try:
            target_level = int(level_input)
            if 1 <= target_level <= 10:
                break
            else:
                print("Please enter a level between 1 and 10.")
        except Exception:
            err("Invalid input.")

    switch_village_resources(driver, selected)

    while True:
        if abort_flag and abort_flag[0]:
            err("Aborted!")
            return

        # Pass selected village into get_resource_fields so it always
        # navigates with newdid - prevents context drift after idle/wait.
        fields = get_resource_fields(driver, selected)
        fields_to_upgrade = sorted(
            [f for f in fields if f["level"] < target_level],
            key=lambda f: f["level"]
        )

        if not fields_to_upgrade:
            ok("All resource fields already at target level!")
            if target_level == 10 and not (abort_flag and abort_flag[0]):
                print()
                ok("All resource fields are at level 10!")
                info("You can now build bonus production buildings (Sawmill, Brickyard, Iron Foundry, Grain Mill, Bakery).")
                info("Running bonus buildings template now...")
                if True:
                    from template_loader import load_all_templates, execute_template
                    all_templates = load_all_templates()
                    bonus = all_templates.get("resource_buildings")
                    if bonus:
                        # If tribe not passed, read from accounts as fallback
                        t = tribe
                        if not t:
                            try:
                                from accounts import accounts as _accs
                                t = _accs[0].get("tribe", "roman")
                            except Exception:
                                t = "roman"
                        execute_template(driver, bonus, t, use_gold, abort_flag, selected)
                    else:
                        err("resource_buildings template not found in templates/ folder.")
            return

        print(f"\n{len(fields_to_upgrade)} fields still below level {target_level}.")

        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            freed = autocomplete_if_two_in_queue(driver, use_gold)
            if freed:
                continue  # slot freed by gold - retry immediately
            finish_times = get_queue_finish_times(driver)
            if finish_times:
                warn(f"Queue full. Waiting {format_queue_time(finish_times)} for slot to free up...")
            else:
                warn("Queue full. Waiting for slot to free up...")
            if not idle(abort_flag, "Queue full."):
                return
            continue

        upgraded = 0
        resources_insufficient = False

        for field in fields_to_upgrade:
            if abort_flag and abort_flag[0]:
                err("Aborted!")
                return
            if upgraded >= 2:
                break

            info(f"\nChecking {field['type']} level {field['level']}...")
            driver.get(field["url"])
            wait()

            # If page already shows target/max level, skip immediately.
            try:
                level_text = driver.find_element(By.CSS_SELECTOR, "h1 span.level").text
                page_level = int("".join(ch for ch in level_text if ch.isdigit()) or "0")
            except Exception:
                page_level = 0

            try:
                none_texts = [s.text.strip().lower() for s in driver.find_elements(By.CSS_SELECTOR, "span.none")]
            except Exception:
                none_texts = []

            max_level_hit = any(
                ("max level" in t) or ("already at max" in t) or ("maxim" in t and "stufe" in t)
                for t in none_texts
            )

            if page_level >= target_level or max_level_hit:
                ok(f"{field['type']} already at target/max level (L{page_level}). Skipping.")
                continue

            # Detect "Not enough food. Expand cropland." — game blocks all builds when
            # crop production can't support the next population increase.
            # Upgrade the lowest-level crop field immediately to resolve the deficit.
            try:
                crop_blocked = any(
                    any(k in s.text.strip().lower() for k in ("food", "cropland", "expand", "getreide"))
                    for s in driver.find_elements(By.CSS_SELECTOR, "span.none")
                )
            except Exception:
                crop_blocked = False

            if crop_blocked:
                warn("Crop cap reached — upgrading lowest crop field first...")
                crop_fields = sorted(
                    [f for f in fields if any(k in f["type"].lower() for k in ("wheat", "crop", "grain", "getreide", "cropland"))],
                    key=lambda f: f["level"]
                )
                queued_crop = False
                for cf in crop_fields:
                    driver.get(cf["url"])
                    wait()
                    try:
                        btn = driver.find_element(By.CSS_SELECTOR, "a.build")
                        href = btn.get_attribute("href") or ""
                        if "master=" not in href:
                            btn.click()
                            ok(f"Crop field {cf['type']} L{cf['level']} → L{cf['level']+1} queued to resolve crop cap.")
                            wait()
                            autocomplete_if_two_in_queue(driver, use_gold)
                            queued_crop = True
                            break
                    except Exception:
                        continue
                if not queued_crop:
                    if crop_fields:
                        # Crop fields exist but are resource-blocked — send resources
                        # from nearby villages to fund the cheapest crop field upgrade.
                        warn("Crop fields are resource-blocked — requesting resources from nearby villages...")
                        if not try_send_resources_from_nearby(driver, selected, crop_fields[0], abort_flag, send_threshold):
                            return
                    else:
                        warn("No crop fields found in village — waiting...")
                        if not idle(abort_flag, "Crop cap — no crop fields found."):
                            return
                break  # restart the outer loop so field list is refreshed

            queue = get_queue_status(driver)
            if queue["slots_free"] == 0:
                autocomplete_if_two_in_queue(driver, use_gold)
                break

            # Direct cost vs resources comparison - much more reliable than button-href check.
            # Falls back to button check only when cost/resources can't be read from the page.
            cost = get_upgrade_cost(driver)
            current_res = get_resources(driver)
            if cost is not None and current_res is not None:
                missing = {
                    "lumber": max(0, cost["lumber"] - current_res["lumber"]["current"]),
                    "clay":   max(0, cost["clay"]   - current_res["clay"]["current"]),
                    "iron":   max(0, cost["iron"]   - current_res["iron"]["current"]),
                    "crop":   max(0, cost["crop"]   - current_res["crop"]["current"]),
                }
                lacks_res = any(v > 0 for v in missing.values())
                if lacks_res:
                    warn(f"Not enough resources for {field['type']} L{field['level']+1}."
                         f" Need L:{cost['lumber']} C:{cost['clay']} I:{cost['iron']} Cr:{cost['crop']}"
                         f" | Have L:{current_res['lumber']['current']} C:{current_res['clay']['current']}"
                         f" I:{current_res['iron']['current']} Cr:{current_res['crop']['current']}"
                         f" | Missing L:{missing['lumber']} C:{missing['clay']} I:{missing['iron']} Cr:{missing['crop']}")
            else:
                # Fallback: can't read cost/resources from page - use button state
                lacks_res = not has_enough_resources(driver)
                if lacks_res:
                    warn(f"Not enough resources for {field['type']} - waiting (button check)...")

            if lacks_res and not master_builder:
                resources_insufficient = True
                break
            elif lacks_res:
                print("Master builder ON - queuing anyway...")

            try:
                driver.find_element(By.CSS_SELECTOR, "a.build").click()
                ok(f"{field['type']} level {field['level']} queued!")
                wait()
                upgraded += 1
                autocomplete_if_two_in_queue(driver, use_gold)
            except Exception:
                err(f"Could not queue {field['type']}.")
                break

        if resources_insufficient:
            if not try_send_resources_from_nearby(driver, selected, fields_to_upgrade[0], abort_flag, send_threshold):
                return
            continue

        info(f"\nQueued {upgraded} field(s) this cycle, checking for more...")
