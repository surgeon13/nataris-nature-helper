"""Build a distributable zip that excludes local-only artifacts.

Usage:
    python package_release.py [--version 1.1]

Creates dist/nataris-nature-helper-v<version>.zip containing the cleaned
source tree (no runtime state files, caches, or dist artifacts).
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Iterable
import zipfile

ROOT = Path(__file__).parent
DIST_DIR = ROOT / "dist"
VERSION_FILE = ROOT / "VERSION"

EXCLUDED_DIRS = {".git", "__pycache__", "dist", ".vscode"}
EXCLUDED_FILES = {
    "account_state.json",
    "builder_task.json",
    "bot_settings.json",
    "demolition_state.json",
    "scheduler_tasks.json",
    "village_progress.json",
}
EXCLUDED_SUFFIXES = {".pyc", ".pyo", ".log", ".zip"}


def load_version() -> str:
    if VERSION_FILE.exists():
        return VERSION_FILE.read_text(encoding="utf-8").strip()
    return "dev"


def iter_files(root: Path) -> Iterable[Path]:
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = Path(dirpath).relative_to(root)
        dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
        if any(part in EXCLUDED_DIRS for part in rel_dir.parts):
            continue

        for filename in filenames:
            file_path = Path(dirpath) / filename
            rel = file_path.relative_to(root)
            if rel.name in EXCLUDED_FILES:
                continue
            if file_path.suffix in EXCLUDED_SUFFIXES:
                continue
            if any(part in EXCLUDED_DIRS for part in rel.parents):
                continue
            yield file_path


def slug_version(version: str) -> str:
    version = version.strip()
    if version.lower().startswith("v"):
        version = version[1:]
    return version or "dev"


def build_zip(version: str) -> Path:
    DIST_DIR.mkdir(exist_ok=True)
    slug = slug_version(version)
    zip_path = DIST_DIR / f"nataris-nature-helper-v{slug}.zip"

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for file_path in iter_files(ROOT):
            rel_path = file_path.relative_to(ROOT)
            zf.write(file_path, rel_path.as_posix())

    return zip_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Package the project into a distributable zip.")
    parser.add_argument("--version", help="Version tag to embed in the archive (defaults to VERSION file).")
    args = parser.parse_args()

    version = args.version or load_version()
    archive = build_zip(version)
    print(f"Created {archive}")


if __name__ == "__main__":  # pragma: no cover
    main()
