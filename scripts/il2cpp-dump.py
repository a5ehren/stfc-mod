#!/usr/bin/env python3
"""Dump IL2CPP class/method signatures from the STFC game binary using Il2CppInspectorRedux."""

from __future__ import annotations

import argparse
import json
import platform
import re
import shutil
import stat
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

type PlatformKey = tuple[str, str]

PLATFORM_MAP: dict[PlatformKey, tuple[str, str]] = {
    ("darwin", "arm64"):   ("osx", "arm64"),
    ("darwin", "x86_64"):  ("osx", "x64"),
    ("win32", "AMD64"):    ("win", "x64"),
    ("linux", "aarch64"):  ("linux", "arm64"),
    ("linux", "x86_64"):   ("linux", "x64"),
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TOOLS_DIR = PROJECT_ROOT / "tools" / "Il2CppInspectorRedux"
DUMP_DIR = PROJECT_ROOT / "dump"


def get_platform_tokens() -> tuple[str, str]:
    key: PlatformKey = (sys.platform, platform.machine())
    match PLATFORM_MAP.get(key):
        case (os_token, arch_token):
            return os_token, arch_token
        case None:
            sys.exit(f"Unsupported platform: {sys.platform}/{platform.machine()}")


def inspector_binary_name() -> str:
    return "Il2CppInspector.exe" if sys.platform == "win32" else "Il2CppInspector"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--game-dir", type=Path, required=True, help="Path to game directory (.app on macOS, game root on Windows)")
    parser.add_argument("--version", type=str, default=None, help="Override auto-detected game version (does not bypass --game-dir requirement)")
    parser.add_argument("--reinstall", action="store_true", help="Force re-download of Il2CppInspectorRedux")
    args = parser.parse_args()

    game_dir = args.game_dir.resolve()
    if not game_dir.exists():
        sys.exit(f"Game directory not found: {game_dir}")

    print(f"Platform: {sys.platform}/{platform.machine()}")
    os_token, arch_token = get_platform_tokens()
    print(f"Asset tokens: {os_token}-{arch_token}")


if __name__ == "__main__":
    main()
