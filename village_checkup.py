# ==========================================
#           NATARIS VILLAGE CHECKUP
#           Reads and displays village status.
#           Checks resources, crop balance,
#           build queue, demolition queue,
#           merchants, and donation eligibility.
#           Color coded terminal output.
#           No icons - pure text output.
# ==========================================

from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from buildings import BUILDINGS
from helpers import BASE_URL, wait, switch_village, switch_village_resources, get_all_villages, find_building_slot, red, yellow, green, cyan, bold, info, ok, warn, err, status
import time

# ==========================================
#           DATA READERS
# ==========================================

def read_resources(driver):
    """
    Reads current resource amounts and max capacity.
    Returns dict with current, max, and percentage for each resource.
    Reads from resource bar elements l1-l4.
    """
    WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "l4")))
    def parse(el_id):
        parts   = driver.find_element(By.ID, el_id).text.split("/")
        current = int(parts[0].replace(",", ""))
        maximum = int(parts[1].replace(",", ""))
        pct     = int((current / maximum) * 100) if maximum > 0 else 0
        return {"current": current, "max": maximum, "pct": pct}
    return {
        "lumber": parse("l4"),
        "clay":   parse("l3"),
        "iron":   parse("l2"),
        "crop":   parse("l1"),
    }

def read_production_rates(driver):
    """
    Reads per-hour production rates from the production table.
    Navigates to dorf1.php statistics tab to get rates.
    Returns dict with lumber, clay, iron, crop rates per hour.
    """
    try:
        driver.get(BASE_URL + "dorf1.php?s=5")
        wait()
        rows  = driver.find_elements(By.CSS_SELECTOR, "tbody tr")
        rates = {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}
        keys  = ["lumber", "clay", "iron", "crop"]
        count = 0
        for row in rows:
            try:
                num = row.find_element(By.CSS_SELECTOR, "td.num")
                val = int(num.text.replace(",", ""))
                if count < 4:
                    rates[keys[count]] = val
                    count += 1
            except Exception:
                continue
        return rates
    except Exception:
        return {"lumber": 0, "clay": 0, "iron": 0, "crop": 0}

def read_crop_balance(driver):
    """
    Reads crop production vs consumption from l5 element.
    Format is consumption/production e.g. 7247/9703.
    Returns dict with consumption, production, balance, and deficit flag.
    """
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.ID, "l5")))
        text        = driver.find_element(By.ID, "l5").text
        parts       = text.split("/")
        consumption = int(parts[0].replace(",", ""))
        production  = int(parts[1].replace(",", ""))
        balance     = production - consumption
        return {
            "consumption": consumption,
            "production":  production,
            "balance":     balance,
            "deficit":     balance < 0,
        }
    except Exception:
        return {
            "consumption": 0,
            "production":  0,
            "balance":     0,
            "deficit":     False,
        }

def read_build_queue(driver):
    """
    Reads current build queue from building_contract table.
    Returns list of queued builds with name, level, timer, done_at.
    Each row in the queue table represents one queued build.
    """
    try:
        rows  = driver.find_elements(By.CSS_SELECTOR, "#building_contract tbody tr")
        queue = []
        for row in rows:
            try:
                name_el    = row.find_element(By.CSS_SELECTOR, "td a[href*='build.php']")
                name       = name_el.text.strip()
                level_td   = row.find_element(By.CSS_SELECTOR, "td:nth-child(2)")
                level_text = level_td.text.strip()
                try:
                    level = int(level_text.split("Level ")[-1].replace(")", "").strip().split()[0])
                except Exception:
                    level = 0
                try:
                    timer = row.find_element(By.CSS_SELECTOR, "span[id^='timer']").text.strip()
                except Exception:
                    timer = "?"
                try:
                    done_td = row.find_element(By.CSS_SELECTOR, "td:nth-child(4)")
                    done_at = done_td.text.strip().replace("done at", "").strip()
                except Exception:
                    done_at = "?"
                queue.append({
                    "name":    name,
                    "level":   level,
                    "timer":   timer,
                    "done_at": done_at,
                })
            except Exception:
                continue
        return queue
    except Exception:
        return []

def read_demolition_queue(driver):
    """
    Reads active demolition from Main Building page.
    Demolitions only appear on the Main Building page,
    not in the regular build queue.
    Returns demolition info if active, None if not.
    """
    try:
        driver.get(BASE_URL + "build.php?id=26")  # Main Building - fixed slot
        wait()
        rows = driver.find_elements(By.CSS_SELECTOR, "#building_contract tbody tr")
        for row in rows:
            text = row.text.lower()
            if "demolish" in text or "destroy" in text:
                try:
                    timer = row.find_element(By.CSS_SELECTOR, "span[id^='timer']").text.strip()
                except Exception:
                    timer = "?"
                return {"active": True, "timer": timer}
        return {"active": False}
    except Exception:
        return {"active": False}

def read_merchants(driver):
    """
    Reads merchant availability from marketplace page.
    Format is available/total e.g. 20/20.
    Returns dict with available and total merchants.
    """
    try:
        market_slot = find_building_slot(driver, "Marketplace")
        if not market_slot:
            return {"available": 0, "total": 0}
        driver.get(BASE_URL + f"build.php?id={market_slot}")
        wait()
        text      = driver.find_element(By.CSS_SELECTOR, "td.mer").text.strip()
        parts     = text.replace("Merchants", "").strip().split("/")
        available = int(parts[0].strip())
        total     = int(parts[1].strip())
        return {"available": available, "total": total}
    except Exception:
        return {"available": 0, "total": 0}

# ==========================================
#           CALCULATIONS
# ==========================================

def calculate_time_to_full(resource, rate):
    """
    Calculates how long until a resource hits max capacity.
    Returns formatted string H:MM or FULL if already at max.
    Returns never if production rate is zero or negative.
    """
    if rate <= 0:
        return "never"
    remaining = resource["max"] - resource["current"]
    if remaining <= 0:
        return "FULL"
    hours = remaining / rate
    h     = int(hours)
    m     = int((hours - h) * 60)
    return f"{h}:{m:02d}"

def calculate_donation_eligibility(resources, crop_balance, threshold=0.5):
    """
    Determines if a village can donate resources.
    Blocked if crop is in deficit.
    Blocked if no resource is above the threshold.
    Returns dict with can_donate flag and reason string.
    """
    if crop_balance["deficit"]:
        return {"can_donate": False, "reason": "crop deficit"}

    has_surplus = any(
        r["current"] > r["max"] * threshold
        for r in resources.values()
    )

    if not has_surplus:
        return {"can_donate": False, "reason": "below threshold"}

    return {"can_donate": True, "reason": "OK"}

# ==========================================
#           DISPLAY
# ==========================================

def fmt(n):
    """Compact number: 1,234 -> 1.2k, 12,345 -> 12k."""
    if n >= 1000:
        return f"{n/1000:.0f}k"
    return str(n)


def fmt_rate(n):
    """Format production rate with sign and compact notation."""
    sign = "+" if n >= 0 else "-"
    return f"{sign}{fmt(abs(n))}"


def format_number(n):
    return f"{n:,}"


def _trim(text, max_len):
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "~"

def display_checkup(village_name, resources, rates, crop_balance, build_queue, demolition, merchants, donation, coords=None, compact_table=False):
    """One-liner per village checkup."""
    coord_str  = f"({coords[0]}|{coords[1]}) " if coords else ""
    res_parts  = []
    any_full   = False
    any_warn   = False
    for key, label in [("lumber","L"), ("clay","C"), ("iron","I"), ("crop","Cr")]:
        r   = resources[key]
        pct = r["pct"]
        part = f"{label}:{fmt(r['current'])}/{fmt(r['max'])}({pct}%)"
        if pct >= 100:
            any_full = True
        elif pct >= 90:
            any_warn = True
        res_parts.append(part)

    res_str = "  ".join(res_parts)

    rate_parts = []
    for key, label in [("lumber","L"), ("clay","C"), ("iron","I"), ("crop","Cr")]:
        rate_parts.append(f"{label}:{fmt_rate(rates[key])}")
    rate_str = "  ".join(rate_parts)

    bal      = crop_balance["balance"]
    bal_str  = f"{'+' if bal >= 0 else ''}{format_number(bal)}/hr"
    deficit  = crop_balance["deficit"]

    if build_queue:
        q0 = build_queue[0]
        q_str = f"{q0['name']} L{q0['level']} [{q0['timer']}]"
        if len(build_queue) > 1:
            q1    = build_queue[1]
            q_str += f"  {q1['name']} L{q1['level']} [{q1['timer']}]"
    else:
        q_str = "queue empty"

    merch_str  = f"merch {merchants['available']}/{merchants['total']}"
    donate_str = "donate:YES" if donation["can_donate"] else f"donate:NO({donation['reason']})"
    demol_str  = f"  DEMOL[{demolition['timer']}]" if demolition["active"] else ""

    if compact_table:
        # Compact single-row output for narrow terminals.
        name = _trim((coord_str + village_name).strip(), 18)
        l_s  = f"{resources['lumber']['pct']:>3}%"
        c_s  = f"{resources['clay']['pct']:>3}%"
        i_s  = f"{resources['iron']['pct']:>3}%"
        cr_s = f"{resources['crop']['pct']:>3}%"
        pr_s = _trim("  ".join([f"{label}:{fmt_rate(rates[key])}" for key, label in [("lumber","L"), ("clay","C"), ("iron","I"), ("crop","Cr")]]), 20)
        bal_s = _trim(f"{'+' if bal >= 0 else ''}{int(bal/1000)}k", 6)
        m_s = f"{merchants['available']}/{merchants['total']}"
        if build_queue:
            q0 = build_queue[0]
            q_s = _trim(f"{q0['name']} L{q0['level']} {q0['timer']}", 16)
        else:
            q_s = "-"
        d_s = "Y" if donation["can_donate"] else "N"

        row = f"  {name:<18} {l_s:>4} {c_s:>4} {i_s:>4} {cr_s:>4} {pr_s:<20} {bal_s:>6} {m_s:>6} {_trim(q_s,16):<16} {d_s:>1}"
        color = red if (deficit or any_full) else yellow if any_warn else (green if donation["can_donate"] else None)
        print(color(row) if color else row)
        return

    indent = "  " + " " * (len(coord_str) + 26) + "  "
    line1 = f"  {coord_str}{village_name}"
    line2 = f"{indent}{res_str}"
    line3 = f"{indent}{rate_str}"
    line4 = (
        f"{indent}"
        f"crop:{bal_str}{'[DEF]' if deficit else ''}  "
        f"{merch_str}  "
        f"{q_str}  "
        f"{donate_str}"
        f"{demol_str}"
    )

    color = red if (deficit or any_full) else yellow if any_warn else (green if donation["can_donate"] else None)
    if color:
        print(color(line1))
        print(color(line2))
        print(color(line3))
        print(color(line4))
    else:
        print(line1)
        print(line2)
        print(line3)
        print(line4)

# ==========================================
#           MAIN CHECKUP RUNNER
# ==========================================

def run_village_checkup(driver, villages):
    """
    Runs a full checkup on all villages or a selected village.
    Reads all data in priority order:
      1. Resources
      2. Crop balance
      3. Production rates
      4. Build queue
      5. Demolition queue
      6. Merchants
      7. Donation eligibility calculation
    Displays compact color coded report per village.
    Returns results list for use by scheduler.
    """
    info("\n========== VILLAGE CHECKUP ==========")
    print("1. All villages")
    for i, village in enumerate(villages):
        print(f"{i + 2}. {village['name']}")

    while True:
        choice = input("\nWhich village to check? (enter number): ").strip()
        try:
            index = int(choice)
            if index == 1:
                selected = villages
                break
            elif 2 <= index <= len(villages) + 1:
                selected = [villages[index - 2]]
                break
            else:
                print(f"Please enter a number between 1 and {len(villages) + 1}.")
        except Exception:
            err("Invalid input.")

    # Print header once for multi-village runs
    if len(selected) > 1:
        print(cyan(f"\n  {'VILLAGE':<18} {'L':>4} {'C':>4} {'I':>4} {'Cr':>4} {'RATE':<20} {'BAL':>6} {'MER':>6} {'QUEUE':<16} {'D'}"))
        print("-" * 99)

    results = []

    for village in selected:
        info(f"\nChecking {village['name']}...")

        # Navigate to village resource page
        switch_village_resources(driver, village)

        # Read all data in priority order
        resources    = read_resources(driver)
        crop_balance = read_crop_balance(driver)
        rates        = read_production_rates(driver)
        build_queue  = read_build_queue(driver)
        demolition   = read_demolition_queue(driver)
        merchants    = read_merchants(driver)
        donation     = calculate_donation_eligibility(resources, crop_balance)

        # Display report
        display_checkup(
            village["name"],
            resources,
            rates,
            crop_balance,
            build_queue,
            demolition,
            merchants,
            donation,
            coords=village.get("coords"),
            compact_table=(len(selected) > 1),
        )

        # Store results for scheduler
        results.append({
            "village":    village,
            "resources":  resources,
            "rates":      rates,
            "crop":       crop_balance,
            "queue":      build_queue,
            "demolition": demolition,
            "merchants":  merchants,
            "donation":   donation,
            "checked_at": time.time(),
        })

    if len(selected) > 1:
        print("-" * 82)

    return results
