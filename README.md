# Nataris Bot - Nature Helper v1.1

Selenium automation bot for Project Nataris (Travian 3.6).

It supports template-driven village building, resource field upgrading, multi-village round-robin execution, resource sending, farmlist sending, demolition, scheduled checkups, crash recovery, and hot module reload.

## v1.1 Highlights

- Cleaned and sanitized release export — no runtime artifacts or credentials in source tree.
- Documentation fully synced with current runtime behavior and menu layout.
- Main menu now documented as `0/1/2/3/4/5/6/S/I/X/Q`.
- Settings submenu documented with all 11 options, including headless mode and ResSend tuning.
- Farmlist captcha flow documented (manual terminal input, enhanced preview images, ASCII preview sizing).
- Release and GitHub handoff steps updated for clean sharing.

## Requirements

- Python 3.8+
- Google Chrome (latest)

Install dependencies:

```bash
pip install -r requirements.txt
```

`nataris_login_bot.py` also auto-installs missing core dependencies (`selenium`, `webdriver-manager`) at startup.
`Pillow` is optional but used for terminal captcha preview and will be auto-installed when needed.

## Quick Start

1. Edit `accounts.py` with your local account.
2. Run:

```bash
python nataris_login_bot.py
```

3. Use `6` (Village checkup) first as a safe read-only validation.

## Main Menu

| Key | Action |
| --- | --- |
| `0` | Farmlist send |
| `1` | Build village from template |
| `2` | Upgrade resource fields |
| `3` | Build all villages (round-robin) |
| `4` | Demolish buildings |
| `5` | Send resources between villages |
| `6` | Village checkup and analysis |
| `S` | Settings submenu |
| `I` | Idle/wait between cycles |
| `X` | Abort current running workflow |
| `Q` | Quit bot |

## Settings Menu

| Option | Description | Range/Behavior |
| --- | --- | --- |
| `1` | Gold autocomplete | Toggle ON/OFF |
| `2` | Batch autocomplete | Toggle ON/OFF |
| `3` | Master builder | Next run only |
| `4` | Resource send threshold | `0-90%` |
| `5` | Round-robin queue actions/pass | `1-2` |
| `6` | ResSend close donor distance | `1-100` fields |
| `7` | ResSend donor full threshold | `50-99%` |
| `8` | ResSend top-up target | `60-100%` |
| `9` | Headless mode | Toggle, then Chrome restart |
| `10` | Farmlist captcha mode | `manual_terminal` / `auto` (auto falls back to manual) |
| `11` | Farmlist preview size | `small`, `medium`, `large` |
| `B` | Back to main menu | No state reset |

## Core Features and Optimizations

### Stability and Recovery

- Chrome crash recovery with automatic browser relaunch and relogin.
- Scheduler runs in a background thread and only raises flags (main thread owns Selenium).
- Hot module reload for core bot modules without full process restart.

### Template and Round-Robin Engine

- JSON template loader with tribe filtering and tribe-specific stage overrides.
- Slot-aware construction with preflight conflict detection and fallback empty-slot resolution.
- Round-robin supports up to 2 queued actions per village pass.
- Per-village progress persisted in `village_progress.json`.
- Pre-run live scan refreshes queue/status and writes `account_state.json` snapshot.

### Resource Automation

- Resource field upgrader uses bottom-up greedy logic.
- On shortfall, donor villages are scanned by proximity and capacity.
- In-transit anti-spam guard prevents repeated duplicate sends before arrival.
- ResSend tuning supports close-donor top-up behavior via settings.

### Farmlist and Captcha Handling

- Menu option `0` opens Rally Point farmlist flow (`t=99`) and submits one-shot raid.
- Captcha image capture with enhanced high-contrast helper output.
- Optional terminal ASCII captcha preview with size control.

## Project Layout

```text
nataris-nature-helper-main/
|- nataris_login_bot.py
|- accounts.py
|- helpers.py
|- template_loader.py
|- multi_village_builder.py
|- resource_upgrader.py
|- resource_sender.py
|- farmlist_sender.py
|- village_builder_engine.py
|- destroyer.py
|- village_checkup.py
|- scheduler.py
|- buildings.py
|- units.py
|- units.json
|- templates/
|  |- village_stage_01.json
|  |- village_stage_02.json
|  |- resource_buildings.json
|  |- resource_fields_01_to_10.json
|- README.md
|- DOCUMENTATION.md
|- CHANGELOG.md
|- CHECKLIST.md
|- package_release.py
|- VERSION
```

## Runtime Artifacts

Generated runtime files are local state and safe to delete between sessions:

- `account_state.json`
- `builder_task.json`
- `demolition_state.json`
- `scheduler_tasks.json`
- `village_progress.json`
- `bot_settings.json`

The main runtime files are already ignored in `.gitignore`.

## Security Before Sharing

- Never push real credentials in `accounts.py`.
- Keep `accounts.py` placeholders in GitHub and set local values privately.
- Do not commit runtime JSON files with village/account state.

## Packaging and Release (v1.1)

1. Confirm `VERSION` is `1.1`.
2. Build release zip:

```bash
python package_release.py --version 1.1
```

3. Share the archive from:

```text
dist/nataris-nature-helper-v1.1.zip
```

The packaging script excludes `dist/`, caches, compiled files, and known runtime state files.

## GitHub Upload Checklist

1. Verify `accounts.py` has placeholder credentials.
2. Confirm docs are up to date (`README.md`, `DOCUMENTATION.md`, `CHANGELOG.md`).
3. Run a local smoke test (`python nataris_login_bot.py` -> login -> option `6`).
4. Commit and push to your repository.
5. Optionally attach the zip from `dist/` to a GitHub Release.

## License

MIT License. See `LICENSE`.

## Changelog

See `CHANGELOG.md` for detailed release history.
