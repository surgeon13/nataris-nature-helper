# Nataris Bot - Nature Helper v1.1 Technical Guide

This technical guide is the handoff reference for the current bot state.
Use it when sharing with collaborators or preparing a GitHub release.

## 1. Scope

- Target game/server: `project-nataris.com` (Travian 3.6 ruleset)
- Runtime: Python + Selenium + Chrome
- Primary objective: reliable, resume-friendly automation with minimal manual babysitting

## 2. Architecture

### Main Thread

- Owns Selenium driver lifecycle.
- Renders menu and executes all workflows.
- Handles crash recovery and browser restarts.

### Scheduler Thread

- Runs independently every 60 seconds.
- Never touches Selenium directly.
- Sets flags (`demolition_ready`, `checkup_due`, etc.) for main-thread handling.
- Persists tasks in `scheduler_tasks.json`.

### Persistence Layer

JSON state files keep long-running workflows resumable:

- `village_progress.json` for round-robin stage progress
- `builder_task.json` for in-transit resource send ETA gating
- `demolition_state.json` for demolition resume
- `account_state.json` pre-run snapshot of village/account status
- `bot_settings.json` runtime tuning persistence

## 3. Runtime Entry and Menu

Entry point:

```bash
python nataris_login_bot.py
```

Menu keys in current runtime:

| Key | Function |
| --- | --- |
| `0` | Farmlist send |
| `1` | Single-village template build |
| `2` | Resource field upgrader |
| `3` | Multi-village round-robin builder |
| `4` | Demolisher |
| `5` | Resource sender |
| `6` | Village checkup |
| `S` | Settings |
| `I` | Idle wait |
| `X` | Abort active workflow |
| `Q` | Quit |

## 4. v1.1 Documentation Sync and Optimization Summary

This release consolidates and documents the behavior already implemented in code.

### A. Menu and UX Alignment

- Main menu docs updated to `0/1/2/3/4/5/6/S/I/X/Q`.
- Settings docs expanded to all 11 configurable entries.

### B. Resource Sending Optimizations

- Proximity-first donor scanning for shortfalls.
- In-transit anti-spam check using `builder_task.json` ETA.
- Close-and-full donor opportunistic top-up using configurable thresholds.

### C. Round-Robin Throughput and Resilience

- Configurable queue fill cap per pass (`1-2` actions).
- Live pre-run refresh to avoid stale queue/resource timing data.
- State persistence and resume-safe behavior across restarts.

### D. Farmlist Captcha Workflow

- Captcha screenshot capture (`captcha_raid.png`).
- Enhanced zoom/contrast helper image (`captcha_raid_zoom.png`).
- Optional ASCII preview in terminal with size toggle.

### E. Runtime Reliability

- Core dependency bootstrap at startup (`selenium`, `webdriver-manager`).
- Optional `Pillow` install-on-demand for captcha preview.
- Crash recovery and module hot-reload remain active.

## 5. Module Responsibility Map

| File | Responsibility |
| --- | --- |
| `nataris_login_bot.py` | Startup, dependency checks, menu, runtime settings, crash recovery |
| `template_loader.py` | Template loading, stage resolution, slot-aware execution |
| `multi_village_builder.py` | Round-robin orchestration and progress persistence |
| `resource_upgrader.py` | Field upgrade loop + nearby donor integration |
| `resource_sender.py` | Manual/auto marketplace sends + captcha handling |
| `farmlist_sender.py` | Farmlist flow and captcha capture/entry |
| `village_builder_engine.py` | Main-building-centric upgrade logic + storage escalation |
| `destroyer.py` | Demolition queue and resume handling |
| `scheduler.py` | Background task timing and flag signaling |
| `helpers.py` | Shared navigation, timing, parsing, queue/resource helpers |

## 6. Release and Distribution Workflow

1. Set `VERSION` to target release (`1.1`).
2. Package release:

```bash
python package_release.py --version 1.1
```

3. Confirm archive:

```text
dist/nataris-nature-helper-v1.1.zip
```

4. Smoke test before sharing:
- Start bot
- Confirm login
- Run option `6` (Village checkup)
- Run option `0` farmlist page open without sending (sanity only)

## 7. GitHub Readiness Checklist

- Ensure `accounts.py` contains placeholders only.
- Ensure runtime JSON artifacts are not committed.
- Include updated docs:
  - `README.md`
  - `DOCUMENTATION.md`
  - `CHANGELOG.md`
- Tag release as `v1.1` after push.

## 8. Known Notes

- This working directory may not include `.git` metadata (for example, unpacked zip copy).
- If `.git` is missing, initialize/reconnect repo before pushing.
- `resource_sender.py` and `resource_upgrader.py` both support donor logic, but with different flow goals (interactive send vs upgrade shortfall recovery).
