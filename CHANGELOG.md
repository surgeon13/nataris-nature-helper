# Changelog

## v1.1 (2026-04-26)

- Cleaned runtime artifacts and captcha images from source tree for release export.
- Sanitized `accounts.py` credentials — now ships with placeholder values.
- Fixed duplicate MIT license text in `LICENSE`.
- Updated all documentation references from `v1.01` to `v1.1`.
- Refined project structure and verified packaging pipeline.

## v1.01 (2026-04-14)

- Documentation overhaul and release alignment for friend/GitHub handoff.
- Updated README and technical guide to match the current live menu and settings.
- Documented farmlist sender flow (`0`), settings submenu (`S`), idle key (`I`), and abort key (`X`).
- Documented all resource sender tuning options and runtime persistence behavior.
- Added explicit release and GitHub upload checklist.
- Bumped project version metadata to `1.01`.

## v1.0 (feature baseline)

- Menu-driven workflow with template build, resource upgrade, round-robin, destroyer, sender, and checkup.
- Scheduler daemon with flag-only design and periodic checkup scheduling.
- Chrome crash recovery with restart/relogin behavior.
- Module hot reload support for core bot modules.
- Runtime settings persistence in `bot_settings.json`.
- Farmlist sender with captcha helper image pipeline.
- Donor-aware resource sending and in-transit anti-spam guard.

## v0.9 (maintenance)

- Round-robin default switched to template-first progression mode.
- Stage advancement hardening for unfinished `main_building` stages.
- Per-pass queue fill of up to two actions where possible.
- Worker-busy handling to avoid waiting-loop stalls.
- Donor scan context restoration and in-transit send guard.

## v0.8

- Multi-village round-robin builder with `village_progress.json`.
- Crop-cap detection and automatic cheapest-crop escalation.
- Slot-conflict fallback for occupied template slots.
- Bonus `resource_buildings` template integration.
- Hot reload, menu redesign, and settings submenu introduction.

## v0.7

- Slot-aware construction and prerequisite checks.
- Merchant-capacity-aware send planning.
- Chebyshev distance travel calculations.

## v0.6

- Crash recovery and login retry improvements.
- Send threshold control and need-aware donor scanning.
- Colorized terminal output and broader input validation.

## v0.5 and earlier

- Initial template engine, multi-village support, demolition persistence, and scheduler foundation.
