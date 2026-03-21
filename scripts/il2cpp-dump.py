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

GITHUB_API_URL = "https://api.github.com/repos/LukeFZ/Il2CppInspectorRedux/releases/latest"


def install_inspector(*, reinstall: bool = False) -> Path:
    binary = inspector_binary_path()

    if not reinstall and binary.exists() and binary.stat().st_size > 0:
        print(f"Il2CppInspectorRedux already installed: {binary}")
        return binary

    if reinstall and TOOLS_DIR.exists():
        print("Removing existing Il2CppInspectorRedux install...")
        shutil.rmtree(TOOLS_DIR)

    os_token, arch_token = get_platform_tokens()
    asset_pattern = f"Il2CppInspectorRedux.CLI-{os_token}-{arch_token}.zip"

    print(f"Fetching latest release info from GitHub...")
    try:
        req = Request(GITHUB_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urlopen(req) as resp:
            release = json.loads(resp.read())
    except URLError as e:
        sys.exit(f"Failed to fetch release info: {e}\nCheck your network connection and try again.")

    asset_url: str | None = None
    for asset in release["assets"]:
        name: str = asset["name"]
        if name == asset_pattern and ".Legacy." not in name:
            asset_url = asset["browser_download_url"]
            break

    if asset_url is None:
        sys.exit(f"Could not find asset matching '{asset_pattern}' in release '{release['tag_name']}'")

    print(f"Downloading {asset_pattern}...")
    try:
        with urlopen(asset_url) as resp:
            zip_data = BytesIO(resp.read())
    except URLError as e:
        sys.exit(f"Failed to download {asset_pattern}: {e}\nUse --reinstall to retry.")

    print(f"Extracting to {TOOLS_DIR}...")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_data) as zf:
        zf.extractall(TOOLS_DIR)

    if sys.platform != "win32":
        binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Installed Il2CppInspectorRedux: {binary}")
    return binary


def get_platform_tokens() -> tuple[str, str]:
    key: PlatformKey = (sys.platform, platform.machine())
    match PLATFORM_MAP.get(key):
        case (os_token, arch_token):
            return os_token, arch_token
        case None:
            sys.exit(f"Unsupported platform: {sys.platform}/{platform.machine()}")


def inspector_binary_name() -> str:
    return "Il2CppInspector.Redux.CLI.exe" if sys.platform == "win32" else "Il2CppInspector.Redux.CLI"


def inspector_binary_path() -> Path:
    os_token, arch_token = get_platform_tokens()
    subdir = f"Il2CppInspectorRedux.CLI-{os_token}-{arch_token}"
    return TOOLS_DIR / subdir / inspector_binary_name()


GAME_VERSION_RE = re.compile(rb"\d+\.\d{3}\.\d{5}")
UNITY_VERSION_RE = re.compile(rb"\d+\.\d+\.\d+[a-zA-Z]\d+")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    game_version: str
    unity_version: str | None


def detect_versions(ggm_path: Path, *, override: str | None = None) -> VersionInfo:
    if override is not None:
        print(f"Using provided game version: {override}")
        # Still try to extract Unity version
        header = ggm_path.read_bytes()[:4096]
        unity_match = UNITY_VERSION_RE.search(header)
        unity_version = unity_match.group(0).decode("ascii") if unity_match else None
        return VersionInfo(game_version=override, unity_version=unity_version)

    header = ggm_path.read_bytes()[:4096]

    game_match = GAME_VERSION_RE.search(header)
    if game_match is None:
        sys.exit(
            "Could not detect game version from globalgamemanagers.\n"
            "Use --version to specify it manually."
        )

    unity_match = UNITY_VERSION_RE.search(header)
    unity_version = unity_match.group(0).decode("ascii") if unity_match else None
    if unity_version is None:
        print("Warning: could not detect Unity version. --unity-version will be omitted.", file=sys.stderr)

    game_version = game_match.group(0).decode("ascii")
    return VersionInfo(game_version=game_version, unity_version=unity_version)


@dataclass(frozen=True, slots=True)
class GameFiles:
    assembly: Path
    metadata: Path
    global_game_managers: Path


def locate_game_files(game_dir: Path) -> GameFiles:
    errors: list[Exception] = []

    match sys.platform:
        case "darwin":
            assembly = game_dir / "Contents" / "Frameworks" / "GameAssembly.dylib"
            data_dir = game_dir / "Contents" / "Resources" / "Data"
        case "win32":
            assembly = game_dir / "GameAssembly.dll"
            data_dirs = sorted(game_dir.glob("*_Data"))
            match data_dirs:
                case [single]:
                    data_dir = single
                case []:
                    errors.append(FileNotFoundError("No *_Data directory found in game root"))
                    data_dir = Path()  # placeholder — will fail below
                case multiple:
                    names = ", ".join(d.name for d in multiple)
                    errors.append(FileNotFoundError(f"Multiple *_Data directories found: {names}"))
                    data_dir = Path()
        case _:
            # Linux: assume Windows-like flat layout
            assembly = game_dir / "GameAssembly.so"
            data_dirs = sorted(game_dir.glob("*_Data"))
            match data_dirs:
                case [single]:
                    data_dir = single
                case _:
                    errors.append(FileNotFoundError("Could not determine *_Data directory"))
                    data_dir = Path()

    metadata = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    ggm = data_dir / "globalgamemanagers"

    if not assembly.exists():
        errors.append(FileNotFoundError(f"Game assembly not found: {assembly}"))
    if not metadata.exists():
        errors.append(FileNotFoundError(f"Metadata not found: {metadata}"))
    if not ggm.exists():
        errors.append(FileNotFoundError(f"globalgamemanagers not found: {ggm}"))

    if errors:
        raise ExceptionGroup("Missing game files", errors)

    return GameFiles(assembly=assembly, metadata=metadata, global_game_managers=ggm)


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

    inspector = install_inspector(reinstall=args.reinstall)
    print(f"Inspector binary: {inspector}")

    game_files = locate_game_files(game_dir)
    print(f"Assembly: {game_files.assembly}")
    print(f"Metadata: {game_files.metadata}")
    print(f"Managers: {game_files.global_game_managers}")

    versions = detect_versions(game_files.global_game_managers, override=args.version)
    print(f"Game version: {versions.game_version}")
    print(f"Unity version: {versions.unity_version or 'unknown'}")


if __name__ == "__main__":
    main()
