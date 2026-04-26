# Nataris Bot v1.1 — Checklist & Technical Reference

---

## 1. Slot IDs — project-nataris.com layout

⚠️ This server uses a non-standard dorf2 layout.
Slots below are confirmed from live game HTML **and** template JSON files.
Do not use standard Travian 3.6 slot references for this server.

| Slot | Building                      | Status              |
|------|-------------------------------|---------------------|
| 19   | Warehouse                     | ✅ confirmed (template + game) |
| 22   | Grain Mill                    | ✅ confirmed (resource_buildings.json) |
| 23   | Sawmill                       | ✅ confirmed (resource_buildings.json) |
| 24   | Granary                       | ✅ confirmed (template + game) |
| 25   | Hero's Mansion                | ⚠️ unverified on this server |
| 26   | Main Building (fixed)         | ✅ confirmed |
| 27   | Brickyard                     | ✅ confirmed (resource_buildings.json) |
| 28   | Blacksmith                    | ✅ confirmed (village_stage_01.json) |
| 29   | Brewery (Teuton, capital only)| ⚠️ assigned, unverified |
| 30   | Town Hall (non-Gaul)          | ✅ confirmed (village_stage_01.json) |
| 30   | Trapper (Gaul only)           | ⚠️ assigned — same slot as Town Hall, mutually exclusive |
| 31   | Iron Foundry                  | ✅ confirmed (resource_buildings.json) |
| 32   | Academy                       | ✅ confirmed (village_stage_01.json, basic.json) |
| 33   | Marketplace                   | ✅ confirmed |
| 34   | Bakery                        | ✅ confirmed (resource_buildings.json) |
| 37   | Barracks                      | ✅ confirmed |
| 38   | Stable                        | ✅ confirmed |
| 39   | Rally Point (fixed)           | ✅ confirmed |
| 40   | Wall (tribe-specific, fixed)  | ✅ confirmed |

Slots not yet confirmed on this server (standard positions differ):
- Residence / Palace — standard slot 22 conflicts with Grain Mill above
- Workshop            — standard slot 34 conflicts with Bakery above
- Verify both by inspecting dorf2 construction dropdown in-game

---

## 2. GID Numbers

| Building     | gid_num | Status              | Source                             |
|--------------|---------|---------------------|------------------------------------|
| Warehouse    | 10      | ✅ confirmed        | dorf2.php?a=10 in href             |
| Granary      | 11      | ✅ confirmed        | dorf2.php?a=11 in href             |
| Blacksmith   | 12      | ✅ confirmed        | Popup(12,4) in Stable prereqs      |
| Stable       | 20      | ✅ confirmed        | img class="building g20"           |
| Academy      | 22      | ✅ confirmed        | Popup(22,4) in Stable prereqs      |
| Cranny       | 23      | ✅ confirmed        | dorf2.php?a=23 in href             |
| Brewery      | 35      | ✅ confirmed        | Popup(35,4) - capital only         |
| Main Building| 15      | ✅ confirmed        | fixed slot 26                      |
| Rally Point  | 16      | ✅ confirmed        | fixed slot 39                      |
| Grain Mill   | 8       | ✅ confirmed        | resource_buildings template        |
| Sawmill      | 5       | ✅ confirmed        | resource_buildings template        |
| Brickyard    | 6       | ✅ confirmed        | resource_buildings template        |
| Iron Foundry | 7       | ✅ confirmed        | resource_buildings template        |
| Bakery       | 9       | ✅ confirmed        | resource_buildings template        |
| Marketplace  | 17      | ✅ confirmed        | gid=17 in marketplace URL          |
| Town Hall    | 24      | ✅ confirmed        | Popup(24,4) observed               |
| Barracks     | 19      | ✅ confirmed        | Popup(19,4) observed               |
| Workshop     | 21      | ⚠️ unverified      | standard gid — not yet seen on this server |
| Palace       | 14      | ⚠️ unverified      | not yet seen in HTML               |
| Trapper      | 36      | ⚠️ unverified      | Gaul only — not yet seen           |
| City Wall    | 29      | ⚠️ unverified      | Roman only — not yet seen         |
| Palisade     | 28      | ⚠️ unverified      | Gaul only — not yet seen          |
| Earth Wall   | 27      | ⚠️ unverified      | Teuton only — not yet seen        |

To verify: open dorf2, inspect construction dropdown,
check Popup(X, 4) or img class="building gX".
| Blacksmith | 12      | ✅ confirmed | Popup(12,4) in Stable prereqs      |
| Stable     | 20      | ✅ confirmed | img class="building g20"           |
| Academy    | 22      | ✅ confirmed | Popup(22,4) in Stable prereqs      |
| Cranny     | 23      | ✅ confirmed | dorf2.php?a=23 in href             |
| Brewery    | 35      | ✅ confirmed | Popup(35,4) - capital only         |
| Palace     | 14      | ⚠️ unverified | not yet seen in HTML              |
| Trapper    | 36      | ⚠️ unverified | Gaul only — not yet seen          |
| City Wall  | 29      | ⚠️ unverified | Roman only — not yet seen         |
| Palisade   | 28      | ⚠️ unverified | Gaul only — not yet seen          |

To verify: open dorf2, inspect construction dropdown,
check Popup(X, 4) or img class="building gX".

---

## 3. HTML Selectors — FULLY CONFIRMED ✅

| Element              | Selector                        | Notes                                          |
|----------------------|---------------------------------|------------------------------------------------|
| Server time          | `#tp1`                          | Hidden span, use get_attribute("textContent")  |
| User local time      | `#tp1_user`                     | Visible span, fallback only                    |
| Server lag (ms)      | `#ltimeWrap b`                  | e.g. "28"                                      |
| Build queue table    | `#building_contract`            | tbody tr = rows, max 2 items                   |
| Queue timer slot 1   | `#timer1`                       | Format h:mm:ss e.g. "0:21:40"                  |
| Queue timer slot 2   | `#timer2`                       | Present only when 2 items queued               |
| Autocomplete link    | `a[href*='buildingFinish=1']`   | In thead, fires gold spend                     |
| Marketplace r1-r4    | `#r1` `#r2` `#r3` `#r4`        | maxlength=5, max 99,999 per field per send      |
| Marketplace submit   | `#btn_ok`                       | Falls back to input[name='s1'] on confirm page |
| Target by name       | `input[name='dname']`           | Village name field                             |
| Target by coords     | `input[name='x']` `input[name='y']` | Preferred over name — always reliable      |
| Village coords       | `#vlist span.coords-text`       | Format (-44|-22), present on every page        |
| Village list         | `#vlist tbody tr`               | Each row = one village                         |
| Active village       | `td.dot.hl`                     | hl class = currently active                    |
| Merchant count       | `td.mer`                        | Text format "available/total" e.g. "9/9"       |
| Demolish select      | `#demolition_type`              | Hidden while demolish is active                |
| Demolish button      | `#btn_demolish`                 | Submit demolish form                           |

---

## 4. Marketplace Behavior

- Form submits to build.php with ft=check (preview step) then confirm step
- Two btn_ok clicks required — first submits form, second confirms
- Max 99,999 per resource field (maxlength=5) — auto multi-trip if needed
- Prefer coordinates (x/y) over village name as target — more reliable
- Fallback to input[name='s1'] if btn_ok not found on confirmation page

---

## 5. Demolition Queue

- Demolition has its own separate queue from building construction
- While a demolish is active, #demolition_type select is hidden/absent
- Must wait for active demolish to finish before queuing next one
- is_demolish_active() checks select visibility to detect this state
- State saved to demolition_state.json after every queued demolish

---

## 6. Accounts Setup

- [ ] Set real username and password in accounts.py (field is `username`, not `email`)
- [ ] Confirm tribe is exactly "roman", "teuton", or "gaul"

---

## 7. Recommended First Run

- [ ] Start bot — confirm Chrome opens and login succeeds
- [ ] Press `6` (Village Checkup) — read-only, safest first test
- [ ] Press `1` → village_stage_01 → fresh village
- [ ] Watch Stage 1 (Main Building to 10) for a few cycles
- [ ] Watch Stage 2–3 (Warehouse / Granary) — confirm slot 19 and 24
- [ ] Press `X` to abort — confirm clean return to menu
- [ ] Press `Q` to exit — confirm Chrome closes cleanly
- [ ] If a GID is wrong: bot prints "Could not find X in slot Y"
      → check in-game HTML → update buildings.py

---

## 8. Future Work

### High priority
- [ ] Verify Trapper GID (36) and slot (30) — needed for Gaul basic template Stage 2b
- [ ] Verify Palace GID (14) and slot — needed for advanced template Palace branch
- [ ] Confirm Residence slot — standard slot 22 conflicts with Grain Mill on this server
- [ ] Confirm Workshop slot — standard slot 34 conflicts with Bakery on this server
- [ ] Verify td.mer merchant count selector from live marketplace HTML
- [ ] Teuton capital template — Brewery requires capital, Granary 20, Rally Point 10

### Medium priority
- [ ] dorf3.php?s=2 — resources per village (inspect HTML when ready)
- [ ] dorf3.php?s=3 — warehouse capacity + crop starvation time-to-empty alert
- [ ] dorf3.php?s=4 — CP dashboard (selectors confirmed, implementation pending)
- [ ] Celebration automation — trigger when town hall slot available + CP needed
- [ ] dorf3.php?s=5 — troops per village (units.json ready, needs selector confirm)
- [ ] village_stage_03.json — late-game template (Palace, Hero's Mansion, second village prep)
- [ ] Settings-only: add merchant fill aggressiveness option (tiny shortfall only vs full-merchant top-up mode)

### Low priority / future
- [ ] Troop training automation
- [ ] Troop sending / rally point automation
- [ ] Smithy/blacksmith upgrade tracking (upgrade_stats in units.json is reserved)
- [ ] Multi-account support (currently only accounts[0] is used)
- [ ] City Wall / Palisade / Earth Wall GID verification

---

## 9. dorf3.php — Village Overview (Planned, post-template)

Do not implement until village templates are complete.

### Sub-pages

| URL             | Table ID         | Key data                                                        |
|-----------------|------------------|-----------------------------------------------------------------|
| dorf3.php       | #overview        | Village name+id, attacks, building queue, troops, merchants     |
| dorf3.php?s=2   | TBD              | Resources (current + rates) per village                         |
| dorf3.php?s=3   | TBD              | Warehouse/granary capacity, time-to-full, time-to-empty (crop!) |
| dorf3.php?s=4   | #culture_points  | CP/day, celebration active, town hall slots, sum row            |
| dorf3.php?s=5   | TBD              | Troops per village, 11 columns positional (tribe-dependent)     |

### Confirmed selectors — Overview (dorf3.php)
- Village rows: `#overview tbody tr`
- Village name + newdid: `td.vil.fc a`
- Attacks incoming: `td.att` (empty = no attacks)
- Building queue: `td.bui span.none` = idle, otherwise building name
- Merchants: `td.tra.lc a` — text format "available/total"
- Troops present: `td.tro a img` — title e.g. "174x Spearman"

### Confirmed selectors — CP (dorf3.php?s=4)
- Village rows: `#culture_points tbody tr` (skip tr.sum)
- CP/day: `td.cps`
- Celebration active: `td.cel a` present = active, otherwise empty
- Town hall slots: `td.slo.lc` — format "used/total"
- Sum row: `tr.sum`

### Confirmed selectors — Sidebar (every page)
- Village list: `#vlist tbody tr`
- Village name + newdid: `td.link a`
- Coordinates: `td.aligned_coords span.coords-text` — format (-44|-22)
- Active village: `td.dot.hl`

---

## 10. units.json Status

| Tribe   | Status       | Notes                                    |
|---------|--------------|------------------------------------------|
| Romans  | ✅ complete  | Verify against kirilloid                 |
| Teutons | ✅ complete  | Verify against kirilloid                 |
| Gauls   | ✅ complete  | Verify against kirilloid                 |
| Nature  | ✅ complete  | Standard animals, no custom Nataris ones |
| Natars  | ✅ complete  | Verify stats against Nataris server      |

upgrade_stats field is null on all units — reserved for future
smithy/blacksmith tracking. Do not remove.
