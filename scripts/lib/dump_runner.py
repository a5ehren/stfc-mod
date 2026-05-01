"""Run Il2CppDumper against an installed STFC game directory."""

from __future__ import annotations

import argparse
import json
import os
import platform
import pty
import re
import select
import shutil
import subprocess
import sys
import time
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

PROJECT_ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = PROJECT_ROOT / "tools" / "Il2CppDumper"
DUMP_DIR = PROJECT_ROOT / "dump"

GITHUB_API_URL = "https://api.github.com/repos/Perfare/Il2CppDumper/releases/latest"

# Il2CppDumper ships a net7 cross-platform build (runs via dotnet CLI)
# and a net7-win self-contained build. We use the cross-platform one.
ASSET_NAME = "Il2CppDumper-net7"


def find_dotnet() -> Path:
    """Find the dotnet CLI and return its path."""
    result = shutil.which("dotnet")
    if result is None:
        sys.exit(
            "dotnet CLI not found.\n"
            "Install .NET SDK/runtime: https://dot.net/download"
        )
    return Path(result)


def get_dotnet_root(dotnet: Path) -> str | None:
    """Determine DOTNET_ROOT for framework-dependent apps.

    Homebrew installs dotnet in a non-standard location that .NET apphosts
    cannot find. Detect that layout and return the correct root path.
    """
    result = subprocess.run(
        [str(dotnet), "--info"],
        capture_output=True,
        text=True,
    )
    for line in result.stdout.splitlines():
        if "Base Path:" in line:
            base = Path(line.split(":", 1)[1].strip())
            root = base.parent.parent
            if (root / "shared").exists():
                return str(root)
    return None


def install_dumper(*, reinstall: bool = False) -> Path:
    """Install Il2CppDumper from GitHub releases. Returns path to the DLL."""
    dll = TOOLS_DIR / "Il2CppDumper.dll"

    if not reinstall and dll.exists() and dll.stat().st_size > 0:
        print(f"Il2CppDumper already installed: {TOOLS_DIR}")
        return dll

    if reinstall and TOOLS_DIR.exists():
        print("Removing existing Il2CppDumper install...")
        shutil.rmtree(TOOLS_DIR)

    print("Fetching latest Il2CppDumper release from GitHub...")
    try:
        req = Request(GITHUB_API_URL, headers={"Accept": "application/vnd.github+json"})
        with urlopen(req) as resp:
            release = json.loads(resp.read())
    except URLError as e:
        sys.exit(f"Failed to fetch release info: {e}\nCheck your network connection and try again.")

    asset_url: str | None = None
    asset_name = ""
    for asset in release["assets"]:
        name: str = asset["name"]
        if name.startswith(ASSET_NAME) and "-win" not in name:
            asset_url = asset["browser_download_url"]
            asset_name = name
            break

    if asset_url is None:
        sys.exit(f"Could not find '{ASSET_NAME}' asset in release '{release['tag_name']}'")

    print(f"Downloading {asset_name}...")
    try:
        with urlopen(asset_url) as resp:
            zip_data = BytesIO(resp.read())
    except URLError as e:
        sys.exit(f"Failed to download: {e}\nUse --reinstall to retry.")

    print(f"Extracting to {TOOLS_DIR}...")
    TOOLS_DIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_data) as zf:
        zf.extractall(TOOLS_DIR)

    runtimeconfig = TOOLS_DIR / "Il2CppDumper.runtimeconfig.json"
    if runtimeconfig.exists():
        config = json.loads(runtimeconfig.read_text())
        config["runtimeOptions"]["rollForward"] = "Major"
        runtimeconfig.write_text(json.dumps(config, indent=2))
        print("Patched runtimeconfig.json for .NET forward compatibility")

    print(f"Installed Il2CppDumper: {TOOLS_DIR}")
    return dll


def get_platform_tokens() -> tuple[str, str]:
    key: PlatformKey = (sys.platform, platform.machine())
    match PLATFORM_MAP.get(key):
        case (os_token, arch_token):
            return os_token, arch_token
        case None:
            sys.exit(f"Unsupported platform: {sys.platform}/{platform.machine()}")


GAME_VERSION_RE = re.compile(rb"\d+\.\d{3}\.\d{5}")
UNITY_VERSION_RE = re.compile(rb"\d+\.\d+\.\d+[a-zA-Z]\d+")


@dataclass(frozen=True, slots=True)
class VersionInfo:
    game_version: str
    unity_version: str | None


def detect_versions(ggm_path: Path, *, override: str | None = None) -> VersionInfo:
    header = ggm_path.read_bytes()[:4096]

    unity_match = UNITY_VERSION_RE.search(header)
    unity_version = unity_match.group(0).decode("ascii") if unity_match else None

    if override is not None:
        return VersionInfo(game_version=override, unity_version=unity_version)

    game_match = GAME_VERSION_RE.search(header)
    if game_match is None:
        sys.exit(
            "Could not detect game version from globalgamemanagers.\n"
            "Use --version to specify it manually."
        )

    if unity_version is None:
        print("Warning: could not detect Unity version.", file=sys.stderr)

    game_version = game_match.group(0).decode("ascii")
    return VersionInfo(game_version=game_version, unity_version=unity_version)


@dataclass(frozen=True, slots=True)
class GameFiles:
    assembly: Path
    metadata: Path
    global_game_managers: Path


def locate_game_files(game_dir: Path) -> GameFiles:
    """Locate GameAssembly, global-metadata.dat, and globalgamemanagers.

    Detection is file-based: probes for .dylib (macOS .app bundle), .dll
    (Windows), and .so (Linux) layouts so that any platform's files can be
    processed on any host OS.
    """
    errors: list[Exception] = []
    assembly: Path | None = None
    data_dir: Path | None = None

    dylib = game_dir / "Contents" / "Frameworks" / "GameAssembly.dylib"
    if dylib.exists():
        assembly = dylib
        data_dir = game_dir / "Contents" / "Resources" / "Data"

    if assembly is None:
        for ext in ("dll", "so"):
            candidate = game_dir / f"GameAssembly.{ext}"
            if candidate.exists():
                assembly = candidate
                break

        if assembly is not None:
            data_dirs = sorted(game_dir.glob("*_Data"))
            match data_dirs:
                case [single]:
                    data_dir = single
                case []:
                    errors.append(FileNotFoundError("No *_Data directory found in game root"))
                case multiple:
                    names = ", ".join(d.name for d in multiple)
                    errors.append(FileNotFoundError(f"Multiple *_Data directories found: {names}"))

    if assembly is None:
        errors.append(FileNotFoundError(
            f"GameAssembly not found; looked for .dylib, .dll, and .so in {game_dir}"
        ))
    if data_dir is None and not errors:
        errors.append(FileNotFoundError("Could not determine data directory"))

    if errors:
        raise ExceptionGroup("Missing game files", errors)

    assert assembly is not None and data_dir is not None
    metadata = data_dir / "il2cpp_data" / "Metadata" / "global-metadata.dat"
    ggm = data_dir / "globalgamemanagers"

    if not metadata.exists():
        errors.append(FileNotFoundError(f"Metadata not found: {metadata}"))
    if not ggm.exists():
        errors.append(FileNotFoundError(f"globalgamemanagers not found: {ggm}"))

    if errors:
        raise ExceptionGroup("Missing game files", errors)

    return GameFiles(assembly=assembly, metadata=metadata, global_game_managers=ggm)


def run_dumper(
    dotnet: Path,
    dumper_dll: Path,
    game_files: GameFiles,
    output_dir: Path,
    *,
    dotnet_root: str | None = None,
) -> None:
    """Run Il2CppDumper via dotnet CLI."""
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        str(dotnet),
        str(dumper_dll),
        str(game_files.assembly),
        str(game_files.metadata),
        str(output_dir),
    ]

    env = dict(os.environ)
    if dotnet_root:
        env["DOTNET_ROOT"] = dotnet_root

    print("\nRunning Il2CppDumper...")
    print(f"Output directory: {output_dir}\n")

    if sys.platform == "win32":
        result = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        if result.returncode != 0:
            sys.exit(f"Il2CppDumper failed (exit code {result.returncode}).")
    else:
        _run_dumper_pty(cmd, env)


def _run_dumper_pty(cmd: list[str], env: dict[str, str]) -> None:
    """Run Il2CppDumper in a pseudo-terminal to satisfy Console.ReadKey()."""
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        env=env,
        close_fds=True,
    )
    os.close(slave_fd)

    output = ""
    try:
        while True:
            ready, _, _ = select.select([master_fd], [], [], 1.0)
            if ready:
                try:
                    chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                except OSError:
                    break
                if not chunk:
                    break
                print(chunk, end="", flush=True)
                output += chunk

                if "Select Platform:" in output and "2.64bit" in output:
                    time.sleep(0.1)
                    os.write(master_fd, b"2")
                    output = ""

                if "Press any key to exit..." in output:
                    time.sleep(0.1)
                    os.write(master_fd, b"\n")
                    output = ""

            if process.poll() is not None:
                while True:
                    ready, _, _ = select.select([master_fd], [], [], 0.1)
                    if not ready:
                        break
                    try:
                        chunk = os.read(master_fd, 4096).decode("utf-8", errors="replace")
                        if not chunk:
                            break
                        print(chunk, end="", flush=True)
                    except OSError:
                        break
                break
    finally:
        os.close(master_fd)
        process.wait()

    if process.returncode != 0:
        sys.exit(
            f"Il2CppDumper failed (exit code {process.returncode}).\n"
            "Check output above for details."
        )


def verify_output(output_dir: Path) -> None:
    required = ["dump.cs", "script.json"]
    missing = [f for f in required if not (output_dir / f).exists()]
    if missing:
        sys.exit(f"Dump incomplete; missing files: {', '.join(missing)}")

    print(f"\nDump complete in {output_dir}:")
    for item in sorted(output_dir.iterdir()):
        if item.is_file():
            print(f"  {item.name} ({item.stat().st_size:,} bytes)")
        elif item.is_dir():
            count = sum(1 for _ in item.rglob("*") if _.is_file())
            print(f"  {item.name}/ ({count} files)")


def dump_game(
    game_dir: Path,
    *,
    version_override: str | None = None,
    reinstall: bool = False,
    dump_root: Path = DUMP_DIR,
) -> VersionInfo:
    """Run the full dump stage and return the detected/provided versions."""
    game_dir = Path(game_dir).resolve()
    if not game_dir.exists():
        sys.exit(f"Game directory not found: {game_dir}")

    print(f"Platform: {sys.platform}/{platform.machine()}")

    dotnet = find_dotnet()
    dotnet_root = get_dotnet_root(dotnet)
    print(f"dotnet: {dotnet}" + (f" (root: {dotnet_root})" if dotnet_root else ""))

    dumper_dll = install_dumper(reinstall=reinstall)

    game_files = locate_game_files(game_dir)
    print(f"Assembly: {game_files.assembly}")
    print(f"Metadata: {game_files.metadata}")

    versions = detect_versions(game_files.global_game_managers, override=version_override)
    print(f"Game version: {versions.game_version}")
    print(f"Unity version: {versions.unity_version or 'unknown'}")

    output_dir = Path(dump_root) / versions.game_version
    run_dumper(dotnet, dumper_dll, game_files, output_dir, dotnet_root=dotnet_root)
    verify_output(output_dir)
    return versions


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dump IL2CPP class/method signatures from the STFC game binary.")
    parser.add_argument("--game-dir", type=Path, required=True,
                        help="Path to game directory (.app on macOS, game root on Windows)")
    parser.add_argument("--version", type=str, default=None,
                        help="Override auto-detected game version")
    parser.add_argument("--reinstall", action="store_true",
                        help="Force re-download of Il2CppDumper")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    dump_game(args.game_dir, version_override=args.version, reinstall=args.reinstall)
    return 0
