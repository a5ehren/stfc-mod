"""Shared workflow primitives for STFC IL2CPP dump tooling."""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from . import dump_runner
from .dump_parser import parse_dump_cached

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUMP_DIR = PROJECT_ROOT / "dump"

LogFn = Callable[[str], None]
RunDumpFn = Callable[["DumpContext"], None]


@dataclass(frozen=True, slots=True)
class DumpContext:
    """Resolved game/dump paths for a single STFC version."""

    game_dir: Path
    game_files: dump_runner.GameFiles
    versions: dump_runner.VersionInfo
    dump_root: Path
    version_override: str | None = None

    @property
    def game_version(self) -> str:
        return self.versions.game_version

    @property
    def unity_version(self) -> str:
        return self.versions.unity_version or "unknown"

    @property
    def dump_dir(self) -> Path:
        return self.dump_root / self.game_version

    @property
    def dump_cs(self) -> Path:
        return self.dump_dir / "dump.cs"


def stderr_log(message: str) -> None:
    print(message, file=sys.stderr)


def resolve_context(
    game_dir: Path,
    *,
    version_override: str | None = None,
    dump_root: Path = DUMP_DIR,
) -> DumpContext:
    """Resolve game files, versions, and destination dump paths."""
    game_dir = Path(game_dir).resolve()
    if not game_dir.exists():
        raise FileNotFoundError(f"Game directory not found: {game_dir}")

    game_files = dump_runner.locate_game_files(game_dir)
    versions = dump_runner.detect_versions(
        game_files.global_game_managers,
        override=version_override,
    )

    return DumpContext(
        game_dir=game_dir,
        game_files=game_files,
        versions=versions,
        dump_root=Path(dump_root),
        version_override=version_override,
    )


def run_dump_for_context(context: DumpContext, *, reinstall: bool = False) -> None:
    dump_runner.dump_game(
        context.game_dir,
        version_override=context.version_override,
        reinstall=reinstall,
        dump_root=context.dump_root,
    )


def ensure_dump(
    context: DumpContext,
    *,
    reinstall: bool = False,
    run_dump: RunDumpFn | None = None,
    log: LogFn = stderr_log,
) -> Path:
    """Ensure ``dump.cs`` exists for *context*, running Il2CppDumper if needed."""
    if context.dump_cs.exists():
        log(f"Using existing dump: {context.dump_cs}")
        return context.dump_cs

    log(f"\ndump.cs not found for {context.game_version}; running dump stage...")
    runner = run_dump
    if runner is None:
        runner = lambda ctx: run_dump_for_context(ctx, reinstall=reinstall)
    runner(context)

    if not context.dump_cs.exists():
        raise RuntimeError(f"Dump stage finished but {context.dump_cs} is still missing")

    log(f"Dump written to {context.dump_cs}")
    return context.dump_cs


def parse_context_dump(context: DumpContext, *, log: LogFn = stderr_log):
    """Parse and cache the context's dump.cs."""
    log(f"Parsing {context.dump_cs.name} with cache...")
    index = parse_dump_cached(context.dump_cs)
    log(f"Parsed {len(index.by_qualified_name)} classes from dump.")
    return index


def prepare_dump_index(
    game_dir: Path,
    *,
    version_override: str | None = None,
    dump_root: Path = DUMP_DIR,
    log: LogFn = stderr_log,
) -> tuple[DumpContext, object]:
    """Resolve, ensure, and parse a dump in one reusable operation."""
    context = resolve_context(
        game_dir,
        version_override=version_override,
        dump_root=dump_root,
    )
    log(f"Game version : {context.game_version}")
    log(f"Unity version: {context.unity_version}")
    ensure_dump(context, log=log)
    index = parse_context_dump(context, log=log)
    return context, index
