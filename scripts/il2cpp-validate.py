#!/usr/bin/env python3
"""Validate mod IL2CPP references against a game dump.

Ties together il2cpp-dump.py (Stage 1), mod_extractor, dump_parser, and
validator to produce a human-readable compatibility report and a sidecar
JSON snapshot.

Usage:
    scripts/il2cpp-validate.py --game-dir <path> [--version <ver>] [--dump-only]
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Path constants
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = PROJECT_ROOT / "dump"
MOD_SRC = PROJECT_ROOT / "mods" / "src"
DUMP_SCRIPT = PROJECT_ROOT / "scripts" / "il2cpp-dump.py"

# Make sure lib/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.mod_extractor import extract_references
from lib.dump_parser import parse_dump
from lib.validator import (
    validate,
    build_sidecar,
    write_sidecar,
    diff_sidecars,
    find_previous_sidecar,
)
from lib.models import RefType, Severity


# ---------------------------------------------------------------------------
# Stage-1 import
# ---------------------------------------------------------------------------

def _load_dump_module():
    """Import il2cpp-dump.py (hyphenated name) via importlib."""
    spec = importlib.util.spec_from_file_location("il2cpp_dump", DUMP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec so @dataclass can resolve the module
    sys.modules["il2cpp_dump"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------

def _format_ref_location(ref) -> str:
    """Return 'file:line' or just 'file' if line is 0."""
    if ref.source_line:
        return f"{ref.source_file}:{ref.source_line}"
    return ref.source_file


def _print_report(issues, refs, game_version: str) -> None:
    """Print the human-readable validation report to stdout."""
    print(f"\nValidating mod references against dump {game_version}...\n")

    for issue in issues:
        ref = issue.ref
        if issue.severity == Severity.MISSING:
            # Determine label from ref type
            rtype = ref.type
            if rtype == RefType.CLASS:
                label = "MISSING CLASS"
                detail = f"{ref.assembly} :: {ref.namespace}.{ref.class_name}" if ref.namespace else f"{ref.assembly} :: {ref.class_name}"
            elif rtype == RefType.METHOD:
                label = "MISSING METHOD"
                cls_fqn = f"{ref.namespace}.{ref.class_name}" if ref.namespace else ref.class_name
                detail = f"{cls_fqn}.{ref.member_name}"
                if ref.arg_count is not None:
                    detail += f" (expected {ref.arg_count} arg{'s' if ref.arg_count != 1 else ''})"
            elif rtype == RefType.FIELD:
                label = "MISSING FIELD"
                cls_fqn = f"{ref.namespace}.{ref.class_name}" if ref.namespace else ref.class_name
                detail = f"{cls_fqn}.{ref.member_name}"
            elif rtype == RefType.PROPERTY:
                label = "MISSING PROPERTY"
                cls_fqn = f"{ref.namespace}.{ref.class_name}" if ref.namespace else ref.class_name
                detail = f"{cls_fqn}.{ref.member_name}"
            elif rtype == RefType.NESTED_TYPE:
                label = "MISSING NESTED TYPE"
                cls_fqn = f"{ref.namespace}.{ref.class_name}" if ref.namespace else ref.class_name
                detail = f"{cls_fqn}.{ref.member_name}"
            elif rtype == RefType.PARENT_CLASS:
                label = "MISSING PARENT CLASS"
                detail = ref.parent_name or ""
            elif rtype == RefType.ICALL:
                label = "MISSING ICALL"
                detail = ref.icall_signature or ""
            else:
                label = "MISSING"
                detail = issue.message

            print(f"{label}: {detail}")
            print(f"  Referenced in: {_format_ref_location(ref)}")
            print()

        elif issue.severity == Severity.SIGNATURE_CHANGED:
            label = "SIGNATURE CHANGED"
            # Extract what changed from the message
            detail = issue.message
            # Strip leading "Signature changed: " or "Icall signature changed: " prefix
            for prefix in ("Signature changed: ", "Icall signature changed: "):
                if detail.startswith(prefix):
                    detail = detail[len(prefix):]
                    break
            print(f"{label}: {detail}")
            if issue.old_signature:
                print(f"  Was:  {issue.old_signature}")
            if issue.new_signature:
                print(f"  Now:  {issue.new_signature}")
            print(f"  Referenced in: {_format_ref_location(ref)}")
            print()

    # Summary counts
    n_classes   = sum(1 for r in refs if r.type == RefType.CLASS)
    n_methods   = sum(1 for r in refs if r.type == RefType.METHOD)
    n_fields    = sum(1 for r in refs if r.type == RefType.FIELD)
    n_properties = sum(1 for r in refs if r.type == RefType.PROPERTY)
    n_icalls    = sum(1 for r in refs if r.type == RefType.ICALL)

    print(f"Checked {n_classes} classes, {n_methods} methods, {n_fields} fields, "
          f"{n_properties} properties, {n_icalls} icalls")

    n_missing = sum(1 for i in issues if i.severity == Severity.MISSING)
    n_changed = sum(1 for i in issues if i.severity == Severity.SIGNATURE_CHANGED)

    parts: list[str] = []
    if n_missing:
        parts.append(f"{n_missing} missing reference{'s' if n_missing != 1 else ''}")
    if n_changed:
        parts.append(f"{n_changed} signature change{'s' if n_changed != 1 else ''}")

    if parts:
        print(f"Found {', '.join(parts)}")
    else:
        print("All references OK")


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate mod IL2CPP references against a game dump.",
    )
    parser.add_argument("--game-dir", required=True, metavar="PATH",
                        help="Path to the game directory (e.g. the .app bundle on macOS)")
    parser.add_argument("--version", metavar="VER",
                        help="Override the detected game version string")
    parser.add_argument("--dump-only", action="store_true",
                        help="Run dump but skip validation")
    args = parser.parse_args()

    game_dir = Path(args.game_dir)
    version_override: str | None = args.version

    # ------------------------------------------------------------------
    # Step 1: Detect game version via Stage-1 helpers
    # ------------------------------------------------------------------
    il2cpp_dump = _load_dump_module()
    game_files = il2cpp_dump.locate_game_files(game_dir)
    versions = il2cpp_dump.detect_versions(
        game_files.global_game_managers,
        override=version_override,
    )
    game_version = versions.game_version
    unity_version = versions.unity_version or "unknown"

    print(f"Game version : {game_version}")
    print(f"Unity version: {unity_version}")

    # ------------------------------------------------------------------
    # Step 2: Ensure dump.cs exists — shell out to il2cpp-dump.py if not
    # ------------------------------------------------------------------
    dump_cs = DUMP_DIR / game_version / "dump.cs"

    if not dump_cs.exists():
        print(f"\ndump.cs not found for {game_version} — running il2cpp-dump.py...")
        cmd = [sys.executable, str(DUMP_SCRIPT), "--game-dir", str(game_dir)]
        if version_override:
            cmd += ["--version", version_override]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("il2cpp-dump.py failed — aborting.", file=sys.stderr)
            return 1
        if not dump_cs.exists():
            print(f"il2cpp-dump.py finished but {dump_cs} still missing — aborting.",
                  file=sys.stderr)
            return 1
        print(f"Dump written to {dump_cs}")
    else:
        print(f"Using existing dump: {dump_cs}")

    # ------------------------------------------------------------------
    # Step 3: --dump-only early exit
    # ------------------------------------------------------------------
    if args.dump_only:
        print("--dump-only flag set, skipping validation.")
        return 0

    # ------------------------------------------------------------------
    # Step 4: Extract mod references
    # ------------------------------------------------------------------
    print("\nExtracting mod references from mods/src/...")
    refs = extract_references(MOD_SRC)
    print(f"Found {len(refs)} raw references in mod source.")

    # ------------------------------------------------------------------
    # Step 5: Parse dump.cs
    # ------------------------------------------------------------------
    print(f"Parsing {dump_cs.name}...")
    index = parse_dump(dump_cs)
    n_classes_in_dump = len(index.by_qualified_name)
    print(f"Parsed {n_classes_in_dump} classes from dump.")

    # ------------------------------------------------------------------
    # Step 6: Validate
    # ------------------------------------------------------------------
    issues = validate(refs, index)

    # ------------------------------------------------------------------
    # Step 7: Diff against previous sidecar (if exists)
    # ------------------------------------------------------------------
    prev_sidecar = find_previous_sidecar(DUMP_DIR, game_version)
    if prev_sidecar is not None:
        prev_version = prev_sidecar.get("game_version", "unknown")
        print(f"Diffing against previous sidecar (version {prev_version})...")
        diff_issues = diff_sidecars(prev_sidecar, refs, index)
        issues = issues + diff_issues
    else:
        print("No previous sidecar found — skipping diff.")

    # ------------------------------------------------------------------
    # Step 8: Write sidecar
    # ------------------------------------------------------------------
    sidecar = build_sidecar(refs, index, game_version, unity_version)
    sidecar_path = DUMP_DIR / game_version / "mod-references.json"
    write_sidecar(sidecar, sidecar_path)
    print(f"Sidecar written to {sidecar_path}")

    # ------------------------------------------------------------------
    # Step 9: Print report
    # ------------------------------------------------------------------
    _print_report(issues, refs, game_version)

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
