# ==========================================
#           NATARIS MULTI-VILLAGE BUILDER
#           Round-robin template runner.
#           Runs the same template on all
#           (or selected) villages in parallel
#           by rotating through them each loop.
#           Each village tracks its own progress
#           in village_progress.json.
#           Queue-busy and resource-waiting
#           villages are skipped each pass so
#           no time is wasted sitting idle.
# ==========================================

import os
import json
import time
from accounts import accounts
from selenium.webdriver.common.by import By
from helpers import (
    BASE_URL, wait, get_all_villages, switch_village,
    get_queue_status, get_upgrade_cost, has_enough_resources,
    get_building_level,
    get_village_resource_fields, get_village_buildings,
    autocomplete_if_two_in_queue, get_queue_finish_times,
    info, ok, warn, err, status
)
from template_loader import (
    load_all_templates, filter_templates_for_tribe,
    resolve_stages, execute_stage
)
from resource_upgrader import try_send_resources_from_nearby

PROGRESS_FILE = os.path.join(os.path.dirname(__file__), "village_progress.json")
ACCOUNT_STATE_FILE = os.path.join(os.path.dirname(__file__), "account_state.json")
TRACKED_BUILDINGS = [
    "Main Building",
    "Warehouse",
    "Granary",
    "Marketplace",
    "Rally Point",
    "Barracks",
    "Stable",
    "Academy",
    "Blacksmith",
    "Town Hall",
]

# Round-robin progression mode:
# - "template_first": follow selected template stage order immediately.
# - "fields_first": legacy behavior (resource fields to 10, then bonus buildings).
ROUND_ROBIN_BOOTSTRAP_MODE = "template_first"

# ==========================================
#           PROGRESS FILE HELPERS
# ==========================================

def load_progress():
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_progress(progress):
    try:
        with open(PROGRESS_FILE, "w") as f:
            json.dump(progress, f, indent=2)
    except Exception as e:
        warn(f"Could not save village_progress.json: {e}")

def init_village(progress, village, template_key):
    """
    Initialises a village entry if it doesn't exist yet.
    Does NOT reset existing progress.
    """
    vid = village["id"]
    if vid not in progress:
        progress[vid] = {
            "village_name":         village["name"],
            "template":             template_key,
            "stage_index":          0,
            "bootstrap_done":       (ROUND_ROBIN_BOOTSTRAP_MODE == "template_first"),
            "status":               "building",
            "queue_free_at":        None,
            "resources_arriving_at": None,
        }
    else:
        # Keep backward compatibility with existing progress files.
        progress[vid].setdefault("bootstrap_done", False)
        if ROUND_ROBIN_BOOTSTRAP_MODE == "template_first":
            progress[vid]["bootstrap_done"] = True
    return progress


def get_bonus_stage(all_templates, tribe):
    """
    Returns the first buildings stage from resource_buildings template,
    resolved for tribe overrides. Returns None when template is missing.
    """
    bonus_tpl = all_templates.get("resource_buildings")
    if not bonus_tpl:
        return None
    stages = resolve_stages(bonus_tpl, tribe)
    for st in stages:
        if st.get("type") == "buildings":
            return st
    return None


def describe_next_template_action(stage):
    """
    Human-readable preview of what this stage is about to do.
    """
    stype = stage.get("type")
    if stype == "main_building":
        return f"Main Building -> L{stage.get('target_level', 20)}"
    if stype == "buildings":
        steps = stage.get("steps", [])
        if not steps:
            return "No building steps in stage"
        preview = []
        for s in steps[:3]:
            preview.append(f"{s.get('building', '?')}->L{s.get('target_level', '?')}")
        more = " ..." if len(steps) > 3 else ""
        return "Buildings: " + ", ".join(preview) + more
    if stype == "resource_fields":
        return f"Resource fields -> L{stage.get('resource_target', '?')}"
    return stage.get("name", "Unknown action")


def run_bootstrap_step(driver, village, bonus_stage, use_gold, abort_flag, max_queue_actions_per_pass=2):
    """
    Bootstrap phase that always runs first for each village in round robin:
      1) Ensure all resource fields are level 10.
      2) Ensure bonus buildings are level 5 via resource_buildings template stage.
    Returns: done(bool), result(str), wait_secs(int)
    """
    if ROUND_ROBIN_BOOTSTRAP_MODE == "template_first":
        return True, "bootstrap_done", 0

    # ---- Step 1: Resource fields to 10 ----
    fields = get_village_resource_fields(driver, village)
    pending_fields = sorted([f for f in fields if f["level"] < 10], key=lambda x: x["level"])
    if pending_fields:
        nxt = pending_fields[0]
        status(f"  [{village['name']}] Bootstrap: resource fields first (remaining: {len(pending_fields)}).")
        status(f"  [{village['name']}] Next field: {nxt['type']} L{nxt['level']} -> L{nxt['level'] + 1}")
        driver.get(nxt["url"])
        wait()

        cost = get_upgrade_cost(driver)
        if cost:
            status(
                f"  [{village['name']}] Cost L:{cost['lumber']} C:{cost['clay']} I:{cost['iron']} Cr:{cost['crop']}"
            )

        if not has_enough_resources(driver):
            warn(f"  [{village['name']}] Not enough resources for field upgrade. Requesting nearby send...")
            sent = try_send_resources_from_nearby(driver, village, nxt, abort_flag, send_threshold=0)
            if sent:
                switch_village(driver, village)
                return False, "sent", 300
            return False, "skipped", 60

        try:
            driver.find_element(By.CSS_SELECTOR, "a.build").click()
            ok(f"  [{village['name']}] Queued: {nxt['type']} L{nxt['level']} -> L{nxt['level'] + 1}")
            wait()
            autocomplete_if_two_in_queue(driver, use_gold)
            finish = get_queue_finish_times(driver)
            return False, "queued", finish[0] if finish else 120
        except Exception as e:
            err(f"  [{village['name']}] Could not queue field upgrade: {e}")
            return False, "failed", 30

    # ---- Step 2: Bonus buildings to 5 ----
    if not bonus_stage:
        ok(f"  [{village['name']}] Bootstrap: no resource_buildings template found. Skipping bonus step.")
        return True, "bootstrap_done", 0

    # Detect empties from dorf2 map titles directly; more reliable than counting occupied slots.
    driver.get(BASE_URL + "dorf2.php")
    wait()
    has_empty_slot = False
    for area in driver.find_elements(By.CSS_SELECTOR, "area[title]"):
        t = (area.get_attribute("title") or "").strip().lower()
        if (
            "building site" in t
            or "construct a new building" in t
            or "construct new building" in t
            or "baustelle" in t
            or "neues gebäude" in t
            or "empty" in t
        ):
            has_empty_slot = True
            break

    bldgs = get_village_buildings(driver)
    pending_bonus = []
    for step in bonus_stage.get("steps", []):
        bname  = step.get("building", "")
        target = step.get("target_level", 1)
        bdata = bldgs.get(bname.lower()) or next((v for k, v in bldgs.items() if bname.lower() in k), None)
        current = bdata["level"] if bdata else 0
        if current < target:
            pending_bonus.append((step, current, target))

    if pending_bonus:
        # If village is full and a bonus building does not exist yet (current=0),
        # that requirement is impossible. Filter those out so bootstrap won't loop forever.
        doable_bonus = [
            item for item in pending_bonus
            if item[1] > 0 or has_empty_slot
        ]

        if not doable_bonus:
            warn(f"  [{village['name']}] Bonus buildings missing but village has no empty slots - skipping bonus bootstrap.")
            return True, "bootstrap_done", 0

        step, current, target = doable_bonus[0]
        status(f"  [{village['name']}] Bootstrap: bonus buildings next (remaining: {len(pending_bonus)}).")
        status(f"  [{village['name']}] Next bonus: {step['building']} L{current} -> L{target}")
        mini_stage = {
            "type": "buildings",
            "name": f"Bootstrap bonus: {step['building']}",
            "steps": [step],
        }
        success = execute_stage(
            driver,
            mini_stage,
            use_gold,
            abort_flag,
            village,
            non_blocking=True,
            max_non_blocking_actions=max_queue_actions_per_pass,
        )
        if success == "deferred":
            finish = get_queue_finish_times(driver)
            secs = finish[0] if finish else 120
            return False, "queued", secs
        if not success:
            return False, "failed", 30
        return False, "bootstrap_progress", 0

    ok(f"  [{village['name']}] Bootstrap complete: fields>=10 and bonus buildings>=5.")
    return True, "bootstrap_done", 0

def mark_queue_busy(progress, village_id, seconds_remaining):
    progress[village_id]["status"]        = "waiting_queue"
    progress[village_id]["queue_free_at"] = time.time() + seconds_remaining
    save_progress(progress)

def mark_resources_sent(progress, village_id, travel_seconds):
    progress[village_id]["status"]               = "waiting_resources"
    progress[village_id]["resources_arriving_at"] = time.time() + travel_seconds
    save_progress(progress)

def mark_building(progress, village_id):
    progress[village_id]["status"]               = "building"
    progress[village_id]["queue_free_at"]        = None
    progress[village_id]["resources_arriving_at"] = None
    save_progress(progress)

def mark_done(progress, village_id):
    progress[village_id]["status"] = "done"
    save_progress(progress)


def _tracked_building_levels(buildings_map):
    """
    Converts the dorf2 buildings map into a fixed tracked-building level snapshot.
    Missing buildings are reported as level 0.
    """
    out = {}
    for bname in TRACKED_BUILDINGS:
        bdata = buildings_map.get(bname.lower()) or next(
            (v for k, v in buildings_map.items() if bname.lower() in k),
            None,
        )
        out[bname] = bdata["level"] if bdata else 0
    return out


def save_account_state_snapshot(selected_villages, progress, selected_template_key, tribe, snapshot_rows):
    """
    Writes a compact account-wide runtime snapshot for debugging/recovery.
    Generated on each full pre-run scan.
    """
    payload = {
        "schema_version": 1,
        "generated_at": time.time(),
        "account": {
            "slot": 0,
            "username": accounts[0].get("username", "unknown"),
            "tribe": tribe,
            "server": "project-nataris.com",
        },
        "template": selected_template_key,
        "tracked_buildings": TRACKED_BUILDINGS,
        "villages": snapshot_rows,
    }
    try:
        with open(ACCOUNT_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        ok(f"[Pre-run] Saved {os.path.basename(ACCOUNT_STATE_FILE)} snapshot.")
    except Exception as e:
        warn(f"Could not save account state snapshot: {e}")


def refresh_progress_from_live_scan(driver, selected_villages, progress, selected_template_key, stages, tribe, abort_flag=None):
    """
    Full pre-run scan to align village_progress.json with live in-game state.
    - Ensures template key matches current run, resetting stage progress if needed.
    - Reads queue status per village and refreshes waiting/building status + timers.
    This reduces stale timers and avoids getting stuck on outdated progress data.
    """
    info("\n[Pre-run] Refreshing progress from live village scan...")
    now = time.time()
    snapshot_rows = []

    for village in selected_villages:
        if abort_flag and abort_flag[0]:
            warn("[Pre-run] Refresh aborted by user.")
            break

        vid = village["id"]
        init_village(progress, village, selected_template_key)
        entry = progress[vid]

        # If user selected a different template this run, reset stage progress for safety.
        if entry.get("template") != selected_template_key:
            warn(f"  [{village['name']}] Template changed ({entry.get('template')} -> {selected_template_key}) - resetting stage progress.")
            entry["template"] = selected_template_key
            entry["stage_index"] = 0
            entry["status"] = "building"
            entry["queue_free_at"] = None
            entry["resources_arriving_at"] = None

        try:
            if abort_flag and abort_flag[0]:
                warn("[Pre-run] Refresh aborted by user.")
                break

            switch_village(driver, village)

            if abort_flag and abort_flag[0]:
                warn("[Pre-run] Refresh aborted by user.")
                break

            queue = get_queue_status(driver)

            if queue["slots_free"] == 0:
                finish_times = get_queue_finish_times(driver)
                secs = finish_times[0] if finish_times else 120
                entry["status"] = "waiting_queue"
                entry["queue_free_at"] = now + secs
            else:
                # Queue has room now, clear stale wait state.
                entry["status"] = "building"
                entry["queue_free_at"] = None

            # Keep resource-arrival timer only if still in the future.
            ra = entry.get("resources_arriving_at")
            if not ra or ra <= now:
                entry["resources_arriving_at"] = None

            # Build rich snapshot row from live village state.
            buildings_map = get_village_buildings(driver)
            tracked_levels = _tracked_building_levels(buildings_map)
            fields_snapshot = get_village_resource_fields(driver, village)
            field_levels = [
                {
                    "id": f.get("id"),
                    "type": f.get("type", ""),
                    "level": int(f.get("level", 0)),
                }
                for f in fields_snapshot
            ]
            levels_only = [f["level"] for f in field_levels]
            field_summary = {
                "count": len(field_levels),
                "min_level": min(levels_only) if levels_only else 0,
                "max_level": max(levels_only) if levels_only else 0,
                "avg_level": round(sum(levels_only) / len(levels_only), 2) if levels_only else 0,
                "below_10_count": sum(1 for lv in levels_only if lv < 10),
            }

            stage_index = int(entry.get("stage_index", 0) or 0)
            next_label = "Template complete"
            next_type = "none"
            next_cost = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}

            if not entry.get("bootstrap_done", False):
                fields = get_village_resource_fields(driver, village)
                pending = sorted([f for f in fields if f["level"] < 10], key=lambda x: x["level"])
                if pending:
                    nxt = pending[0]
                    next_type = "bootstrap_field"
                    next_label = f"{nxt['type']} L{nxt['level']} -> L{nxt['level'] + 1}"
                    driver.get(nxt["url"])
                    wait()
                    c = get_upgrade_cost(driver)
                    if c:
                        next_cost = c
                else:
                    next_type = "bootstrap_bonus"
                    next_label = "Bonus buildings to L5"
            elif stage_index < len(stages):
                next_type = "template_stage"
                next_label = describe_next_template_action(stages[stage_index])

            next_eligible_at = entry.get("queue_free_at") or entry.get("resources_arriving_at") or now
            wait_reason = "ready"
            if entry["status"] == "waiting_queue":
                wait_reason = "queue_full"
            elif entry["status"] == "waiting_resources":
                wait_reason = "resources_in_transit"

            snapshot_rows.append({
                "id": vid,
                "name": village["name"],
                "coords": village.get("coords"),
                "template": selected_template_key,
                "state": {
                    "status": entry.get("status", "building"),
                    "stage_index": stage_index,
                    "bootstrap_done": bool(entry.get("bootstrap_done", False)),
                    "queue_free_at": entry.get("queue_free_at") or 0,
                    "resources_arriving_at": entry.get("resources_arriving_at") or 0,
                    "next_eligible_at": next_eligible_at,
                    "wait_reason": wait_reason,
                },
                "next_action_preview": {
                    "type": next_type,
                    "label": next_label,
                    "cost": next_cost,
                },
                "resource_fields": {
                    "summary": field_summary,
                    "levels": field_levels,
                },
                "building_levels": tracked_levels,
            })

            ok(f"  [{village['name']}] Refreshed: status={entry['status']}, stage={entry.get('stage_index', 0)}")
        except Exception as e:
            warn(f"  [{village['name']}] Could not refresh live state ({e}); keeping stored progress.")

    save_progress(progress)
    save_account_state_snapshot(selected_villages, progress, selected_template_key, tribe, snapshot_rows)
    if abort_flag and abort_flag[0]:
        warn("[Pre-run] Progress refresh stopped early due to abort.")
    else:
        ok("[Pre-run] Progress refresh complete.")

def is_ready(entry):
    """
    Returns True if this village is ready to act this pass.
    Skips queue-busy and resource-waiting villages whose timers
    have not expired yet.
    """
    status_val = entry.get("status", "building")
    now = time.time()

    if status_val == "done":
        return False

    if status_val == "waiting_queue":
        free_at = entry.get("queue_free_at") or 0
        if now < free_at:
            remaining = int(free_at - now)
            return False  # still busy
        # Timer expired — mark as building so we visit it
        return True

    if status_val == "waiting_resources":
        arriving_at = entry.get("resources_arriving_at") or 0
        if now < arriving_at:
            return False  # still in transit
        return True

    return True  # "building"


# ==========================================
#           SINGLE-VILLAGE PASS
#           Performs one action for one village
#           then returns immediately.
#           Returns: "done" | "queued" | "skipped" | "failed"
# ==========================================

def do_one_action(
    driver,
    village,
    entry,
    stages,
    bonus_stage,
    use_gold,
    abort_flag,
    tribe,
    max_queue_actions_per_pass=2,
):
    """
    Attempts one build action for this village.
        - First runs bootstrap (fields to 10, bonus buildings to 5)
    - If queue is full: stamps queue_free_at and returns "queued"
    - If the current stage step completes: advances stage_index
        Returns: (result, wait_secs, advanced_steps)
            result in: "done" | "queued" | "sent" | "advanced" | "failed" | "bootstrap_done" | "bootstrap_progress"
    """
    stage_index = entry.get("stage_index", 0)

    if stage_index >= len(stages):
                return "done", 0, 0

    # Switch to this village
    switch_village(driver, village)

    # Bootstrap always runs first in round-robin for every village.
    if not entry.get("bootstrap_done", False):
        done, result, secs = run_bootstrap_step(
            driver,
            village,
            bonus_stage,
            use_gold,
            abort_flag,
            max_queue_actions_per_pass=max_queue_actions_per_pass,
        )
        if done:
            return "bootstrap_done", 0, 0
        return result, secs, 0

    # Check queue first
    queue = get_queue_status(driver)
    if queue["slots_free"] == 0:
        autocomplete_if_two_in_queue(driver, use_gold)
        # Re-check after autocomplete attempt
        queue = get_queue_status(driver)
        if queue["slots_free"] == 0:
            finish_times = get_queue_finish_times(driver)
            secs = finish_times[0] if finish_times else 120
            warn(f"  [{village['name']}] Queue full — skipping for {secs}s")
            return "queued", secs, 0

    # Keep moving through stages in the same pass and try to fill both queue
    # slots for this village when possible.
    advanced_steps = 0
    queued_actions = 0
    max_hops = len(stages) - stage_index

    for _ in range(max_hops):
        if stage_index >= len(stages):
            break

        stage = stages[stage_index]
        status(f"  [{village['name']}] Next action: {describe_next_template_action(stage)}")

        before = get_queue_status(driver)
        ok(f"  [{village['name']}] Running stage {stage_index + 1}/{len(stages)}: {stage.get('name', '')}")
        success = execute_stage(
            driver,
            stage,
            use_gold,
            abort_flag,
            village,
            non_blocking=True,
            max_non_blocking_actions=max_queue_actions_per_pass,
        )

        if abort_flag[0]:
            return "failed", 0, advanced_steps

        if success == "deferred":
            finish_times = get_queue_finish_times(driver)
            secs = finish_times[0] if finish_times else 120
            warn(f"  [{village['name']}] Stage deferred until construction appears. Rechecking in {secs}s.")
            return "queued", secs, advanced_steps

        if not success:
            err(f"  [{village['name']}] Stage failed.")
            return "failed", 0, advanced_steps

        # main_building stages may queue work and return before reaching target.
        # Only advance stage_index when the target level is actually reached.
        if stage.get("type") == "main_building":
            target_level = int(stage.get("target_level", 20) or 20)
            slot_id = int(stage.get("slot", 26) or 26)
            driver.get(BASE_URL + f"build.php?id={slot_id}&newdid={village['id']}")
            wait()
            live_level = get_building_level(driver)
            if live_level < target_level:
                queue_now = get_queue_status(driver)
                if queue_now["slots_free"] == 0:
                    finish_times = get_queue_finish_times(driver)
                    secs = finish_times[0] if finish_times else 120
                    return "queued", secs, advanced_steps
                return "advanced", 0, advanced_steps

        advanced_steps += 1
        stage_index += 1

        after = get_queue_status(driver)
        queued_delta = max(0, after["slots_used"] - before["slots_used"])
        queued_actions += queued_delta

        # If queue filled up, defer village until the first slot frees.
        if after["slots_free"] == 0:
            finish_times = get_queue_finish_times(driver)
            secs = finish_times[0] if finish_times else 120
            return "queued", secs, advanced_steps

        # If we queued one action and there is still room, continue this pass
        # and try to queue a second action for better throughput.
        if queued_actions >= max_queue_actions_per_pass:
            return "advanced", 0, advanced_steps

    if stage_index >= len(stages):
        return "done", 0, advanced_steps

    return "advanced", 0, advanced_steps


# ==========================================
#           ROUND-ROBIN LOOP
# ==========================================

def run_multi_village_builder(driver, use_gold, abort_flag, tribe, max_queue_actions_per_pass=2):
    """
    Main entry point for multi-village round-robin builder.
    Lets user pick a template, select villages, then loops
    round-robin until all villages have finished the template.
    """
    info("\n========== MULTI-VILLAGE BUILDER ==========")

    all_templates = load_all_templates()
    available     = filter_templates_for_tribe(all_templates, tribe)

    if not available:
        err("No templates available for your tribe.")
        return

    # Pick template
    template_keys = list(available.keys())
    print(f"\nAvailable templates ({tribe.capitalize()}):")
    for i, key in enumerate(template_keys):
        t = available[key]
        print(f"  {i + 1}. {t['name']}")

    while True:
        choice = input("\nWhich template to run on all villages? (number): ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(template_keys):
                selected_key = template_keys[idx]
                break
            warn(f"Enter a number between 1 and {len(template_keys)}.")
        except ValueError:
            warn("Invalid input.")

    template   = all_templates[selected_key]
    stages     = resolve_stages(template, tribe)
    bonus_stage = get_bonus_stage(all_templates, tribe)
    total_stages = len(stages)
    try:
        max_queue_actions_per_pass = int(max_queue_actions_per_pass)
    except Exception:
        max_queue_actions_per_pass = 2
    if max_queue_actions_per_pass < 1:
        max_queue_actions_per_pass = 1
    if max_queue_actions_per_pass > 2:
        max_queue_actions_per_pass = 2
    ok(f"Template: {template['name']} | {total_stages} stages")
    info(f"Round-robin queue fill cap per village pass: {max_queue_actions_per_pass} action(s)")
    if ROUND_ROBIN_BOOTSTRAP_MODE == "template_first":
        info("Round-robin policy: Template-first mode (follow selected template stages immediately).")
    else:
        info("Round-robin policy: Bootstrap first for every village -> fields to L10, bonus buildings to L5, then selected template stages.")

    # Pick villages
    all_villages = get_all_villages(driver)
    print("\nAvailable villages:")
    for i, v in enumerate(all_villages):
        print(f"  {i + 1}. {v['name']}")
    print(f"  0. All villages")

    while True:
        choice = input("\nWhich villages? (number(s) comma-separated, or 0 for all): ").strip()
        if choice == "0":
            selected_villages = all_villages
            break
        try:
            indices = [int(x.strip()) - 1 for x in choice.replace(",", " ").split()]
            if all(0 <= i < len(all_villages) for i in indices):
                selected_villages = [all_villages[i] for i in indices]
                break
            warn(f"Enter numbers between 1 and {len(all_villages)}, or 0 for all.")
        except ValueError:
            warn("Invalid input.")

    if not selected_villages:
        warn("No villages selected.")
        return

    # Load or initialise progress
    progress = load_progress()
    for village in selected_villages:
        init_village(progress, village, selected_key)
    refresh_progress_from_live_scan(driver, selected_villages, progress, selected_key, stages, tribe, abort_flag)

    if abort_flag[0]:
        warn("Round-robin launch aborted before main loop.")
        return

    ok(f"\nStarting round-robin on {len(selected_villages)} village(s)...")

    # ---- Main round-robin loop ----
    while not abort_flag[0]:
        # Collect villages that still have work to do
        active = [
            v for v in selected_villages
            if progress.get(v["id"], {}).get("status") != "done"
        ]

        if not active:
            ok("\nAll villages have completed the template!")
            break

        # Count ready vs waiting
        ready      = [v for v in active if is_ready(progress.get(v["id"], {}))]
        waiting    = len(active) - len(ready)

        if not ready:
            # Opportunistic recovery: if all villages are waiting on queue timers,
            # try gold autocomplete once before sleeping so we can keep building.
            freed_any = False
            for v in active:
                e = progress.get(v["id"], {})
                if e.get("status") != "waiting_queue":
                    continue
                try:
                    switch_village(driver, v)
                    queue_state = get_queue_status(driver)

                    # Queue freed early (manual cancel, gold finish, etc.) — resume immediately.
                    if queue_state.get("slots_free", 0) > 0:
                        mark_building(progress, v["id"])
                        ok(f"  [{v['name']}] Queue slot freed - resuming now.")
                        freed_any = True
                        continue

                    # Queue still full: refresh stored timer so we don't wait on stale data.
                    finish_times = get_queue_finish_times(driver)
                    if finish_times:
                        progress[v["id"]]["queue_free_at"] = time.time() + finish_times[0]
                        save_progress(progress)

                    # Respect original rule: autocomplete only when queue has 2 builds.
                    if queue_state.get("slots_used", 0) < 2:
                        continue

                    if autocomplete_if_two_in_queue(driver, use_gold):
                        # Re-read queue to confirm a slot is now free.
                        q_after = get_queue_status(driver)
                        if q_after.get("slots_free", 0) > 0:
                            mark_building(progress, v["id"])
                            ok(f"  [{v['name']}] Two-queue autocomplete freed a slot - resuming now.")
                            freed_any = True
                except Exception as ex:
                    warn(f"  [{v['name']}] Could not attempt autocomplete: {ex}")

            if freed_any:
                continue

            # All villages are waiting for queue/resources — sleep briefly
            min_wait = None
            min_wait_village = None
            min_wait_reason = None
            for v in active:
                e = progress.get(v["id"], {})
                ts = e.get("queue_free_at") or e.get("resources_arriving_at")
                if ts:
                    if min_wait is None or ts < min_wait:
                        min_wait = ts
                        min_wait_village = v.get("name", "unknown")
                        min_wait_reason = "queue" if e.get("queue_free_at") else "resources"

            raw_sleep_secs = max(10, int((min_wait or time.time() + 30) - time.time()))
            # Do not sleep for very long in one chunk; wake periodically to stay responsive.
            sleep_secs = min(raw_sleep_secs, 120)

            if min_wait_village:
                warn(
                    f"\nAll {len(active)} villages waiting. "
                    f"Next ready: {min_wait_village} ({min_wait_reason}) in ~{raw_sleep_secs}s. "
                    f"Sleeping {sleep_secs}s..."
                )
            else:
                warn(f"\nAll {len(active)} villages waiting. Sleeping {sleep_secs}s...")
            for _ in range(sleep_secs):
                if abort_flag[0]:
                    break
                time.sleep(1)
            continue

        info(f"\n--- Pass: {len(ready)} ready, {waiting} waiting ---")

        for village in ready:
            if abort_flag[0]:
                break

            vid   = village["id"]
            entry = progress[vid]

            # Re-check timer (may have changed during this pass)
            if not is_ready(entry):
                continue

            # Reset expired timers to "building" state before acting
            if entry["status"] in ("waiting_queue", "waiting_resources"):
                mark_building(progress, vid)
                entry = progress[vid]

            stage_index = entry["stage_index"]
            if entry.get("bootstrap_done", False) and stage_index >= total_stages:
                mark_done(progress, vid)
                ok(f"  [{village['name']}] All stages complete!")
                continue

            result, secs, advanced_steps = do_one_action(
                driver,
                village,
                entry,
                stages,
                bonus_stage,
                use_gold,
                abort_flag,
                tribe,
                max_queue_actions_per_pass=max_queue_actions_per_pass,
            )

            if result == "bootstrap_done":
                progress[vid]["bootstrap_done"] = True
                mark_building(progress, vid)
                ok(f"  [{village['name']}] Bootstrap finished. Moving to template stages.")
                continue

            elif result == "bootstrap_progress":
                mark_building(progress, vid)
                continue

            if result == "done":
                if advanced_steps:
                    progress[vid]["stage_index"] += advanced_steps
                mark_done(progress, vid)
                ok(f"  [{village['name']}] Template complete!")

            elif result == "advanced":
                progressed_from = progress[vid]["stage_index"]
                if advanced_steps > 0:
                    progress[vid]["stage_index"] += advanced_steps
                mark_building(progress, vid)
                moved = progress[vid]["stage_index"] - progressed_from
                if moved > 0:
                    ok(f"  [{village['name']}] Advanced {moved} stage(s). "
                       f"Next: stage {progress[vid]['stage_index'] + 1}/{total_stages}")
                else:
                    status(f"  [{village['name']}] Stage in progress - no stage completed this pass.")

            elif result == "queued":
                if advanced_steps:
                    progress[vid]["stage_index"] += advanced_steps
                mark_queue_busy(progress, vid, secs)

            elif result == "sent":
                mark_resources_sent(progress, vid, secs)

            elif result == "skipped":
                # Temporary skip — try again next pass after short delay
                progress[vid]["queue_free_at"] = time.time() + secs
                progress[vid]["status"]        = "waiting_queue"
                save_progress(progress)

            elif result == "failed":
                err(f"  [{village['name']}] Action failed. Will retry next pass.")
                progress[vid]["queue_free_at"] = time.time() + 30
                progress[vid]["status"]        = "waiting_queue"
                save_progress(progress)

        # Small pause between passes to avoid hammering the server
        if not abort_flag[0]:
            time.sleep(3)

    info("\n========== MULTI-VILLAGE BUILDER DONE ==========\n")
    try:
        driver.get(BASE_URL + "dorf2.php")
    except Exception:
        pass
