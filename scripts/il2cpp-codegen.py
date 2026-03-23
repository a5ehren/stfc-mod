#!/usr/bin/env python3
"""Generate C++ scaffold headers and auto-fix IL2CPP references from a game dump.

Subcommands:
  fix           Analyze mod source for broken references and apply auto-fixes.
  scaffold      Generate a single C++ header scaffold for a named class.
  scaffold-all  Generate headers for all classes referenced in mod source.

Usage:
    scripts/il2cpp-codegen.py fix --game-dir <path> [--version <ver>] [--dry-run]
    scripts/il2cpp-codegen.py scaffold <class-name> --game-dir <path> [--version <ver>] [--output <path>]
    scripts/il2cpp-codegen.py scaffold-all --game-dir <path> [--version <ver>]
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
DUMP_DIR     = PROJECT_ROOT / "dump"
MOD_SRC      = PROJECT_ROOT / "mods" / "src"
PRIME_DIR    = MOD_SRC / "prime"
GENERATED_DIR = PRIME_DIR / "generated"
DUMP_SCRIPT  = PROJECT_ROOT / "scripts" / "il2cpp-dump.py"

# Make sure lib/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.dump_parser   import parse_dump
from lib.mod_extractor import extract_references
from lib.validator     import validate
from lib.fixer         import analyze_issues, apply_fixes
from lib.codegen       import generate_scaffold
from lib.models        import RefType


# ---------------------------------------------------------------------------
# Stage-1 import (il2cpp-dump.py has a hyphen, so importlib is required)
# ---------------------------------------------------------------------------

def _load_dump_module():
    """Import il2cpp-dump.py (hyphenated name) via importlib."""
    spec = importlib.util.spec_from_file_location("il2cpp_dump", DUMP_SCRIPT)
    mod  = importlib.util.module_from_spec(spec)
    sys.modules["il2cpp_dump"] = mod
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Shared setup: version detection + dump existence check + parse
# ---------------------------------------------------------------------------

def _shared_setup(game_dir: Path, version_override: str | None):
    """Detect game version, ensure dump.cs exists, parse it.

    Returns (dump_index, game_version, unity_version).
    Progress messages go to stderr.
    """
    il2cpp_dump = _load_dump_module()

    game_files = il2cpp_dump.locate_game_files(game_dir)
    versions   = il2cpp_dump.detect_versions(
        game_files.global_game_managers,
        override=version_override,
    )
    game_version  = versions.game_version
    unity_version = versions.unity_version or "unknown"

    print(f"Game version : {game_version}", file=sys.stderr)
    print(f"Unity version: {unity_version}", file=sys.stderr)

    # Ensure dump.cs exists — run il2cpp-dump.py if not
    dump_cs = DUMP_DIR / game_version / "dump.cs"
    if not dump_cs.exists():
        print(f"\ndump.cs not found for {game_version} — running il2cpp-dump.py...",
              file=sys.stderr)
        cmd = [sys.executable, str(DUMP_SCRIPT), "--game-dir", str(game_dir)]
        if version_override:
            cmd += ["--version", version_override]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            print("il2cpp-dump.py failed — aborting.", file=sys.stderr)
            sys.exit(1)
        if not dump_cs.exists():
            print(f"il2cpp-dump.py finished but {dump_cs} still missing — aborting.",
                  file=sys.stderr)
            sys.exit(1)
        print(f"Dump written to {dump_cs}", file=sys.stderr)
    else:
        print(f"Using existing dump: {dump_cs}", file=sys.stderr)

    # Parse dump.cs
    print(f"Parsing {dump_cs.name}...", file=sys.stderr)
    index = parse_dump(dump_cs)
    print(f"Parsed {len(index.by_qualified_name)} classes from dump.", file=sys.stderr)

    return index, game_version, unity_version


# ---------------------------------------------------------------------------
# Subcommand: fix
# ---------------------------------------------------------------------------

def cmd_fix(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    index, game_version, _ = _shared_setup(game_dir, args.version)

    # Extract mod references
    print("\nExtracting mod references from mods/src/...", file=sys.stderr)
    refs = extract_references(MOD_SRC)
    print(f"Found {len(refs)} raw references.", file=sys.stderr)

    # Validate
    print("Validating references...", file=sys.stderr)
    issues = validate(refs, index)
    print(f"Found {len(issues)} issue(s).", file=sys.stderr)

    if not issues:
        print("\nAll references OK — nothing to fix.")
        return 0

    # Analyze issues → fixes + suggestions
    fixes, suggestions = analyze_issues(issues, index, PROJECT_ROOT)

    # Report
    print(f"\n{'DRY-RUN: ' if args.dry_run else ''}Fix report for dump {game_version}")
    print(f"  Issues    : {len(issues)}")
    print(f"  Auto-fixes: {len(fixes)}")
    print(f"  Suggestions: {len(suggestions)}")

    if fixes:
        print("\nAuto-fixes:")
        for fix in fixes:
            rel = Path(fix.file).relative_to(PROJECT_ROOT) if Path(fix.file).is_absolute() else fix.file
            print(f"  [{rel}:{fix.line}] {fix.description}")

    if suggestions:
        print("\nSuggestions (manual review needed):")
        for s in suggestions:
            rel = Path(s.file).relative_to(PROJECT_ROOT) if Path(s.file).is_absolute() else s.file
            print(f"  [{rel}:{s.line}] {s.description}")

    # Apply fixes
    modified = apply_fixes(fixes, PROJECT_ROOT, dry_run=args.dry_run)
    if args.dry_run:
        print(f"\n[dry-run] Would modify {modified} file(s).")
    else:
        print(f"\nModified {modified} file(s).")

    return 0


# ---------------------------------------------------------------------------
# Subcommand: scaffold
# ---------------------------------------------------------------------------

def cmd_scaffold(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    index, game_version, _ = _shared_setup(game_dir, args.version)

    class_arg = args.class_name

    # Try qualified lookup first (split on last dot → namespace.ClassName)
    dc = None
    if "." in class_arg:
        ns, _, cn = class_arg.rpartition(".")
        # Search by_ns_class or by_class_name with namespace filter
        candidates = [
            c for c in index.by_class_name.get(cn, [])
            if c.namespace == ns
        ]
        if len(candidates) == 1:
            dc = candidates[0]
        elif len(candidates) > 1:
            print(f"Multiple matches for qualified name '{class_arg}':")
            for c in candidates:
                print(f"  {c.assembly} :: {c.namespace}.{c.name}")
            return 1
        # else fall through to name-only search using just cn
        name_only = cn
    else:
        name_only = class_arg

    if dc is None:
        # Name-only fallback
        matches = index.by_class_name.get(name_only, [])
        if len(matches) == 1:
            dc = matches[0]
        elif len(matches) > 1:
            print(f"Multiple matches for '{name_only}' — specify a qualified name (Namespace.ClassName):")
            for c in matches:
                ns_str = f"{c.namespace}." if c.namespace else ""
                print(f"  {c.assembly} :: {ns_str}{c.name}")
            return 1
        else:
            # Not found — show similar names
            similar = _find_similar_classes(name_only, index)
            print(f"Class '{name_only}' not found in dump.")
            if similar:
                print("Similar class names:")
                for s in similar:
                    ns_str = f"{s.namespace}." if s.namespace else ""
                    print(f"  {s.assembly} :: {ns_str}{s.name}")
            return 1

    # Generate scaffold
    print(f"Generating scaffold for {dc.assembly} :: {dc.namespace}.{dc.name}...", file=sys.stderr)
    content = generate_scaffold(dc, game_version)

    # Determine output path
    if args.output:
        out_path = Path(args.output)
    else:
        cpp_name = dc.name.replace("`", "_")
        GENERATED_DIR.mkdir(parents=True, exist_ok=True)
        out_path = GENERATED_DIR / f"{cpp_name}.h"

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(content, encoding="utf-8")
    print(f"Written: {out_path}")
    return 0


def _find_similar_classes(target: str, index) -> list:
    """Return DumpClass instances with names similar to target (case-insensitive substring)."""
    target_lower = target.lower()
    results = []
    seen: set[str] = set()
    for name, classes in index.by_class_name.items():
        if target_lower in name.lower() or name.lower() in target_lower:
            for c in classes:
                key = f"{c.assembly}::{c.namespace}.{c.name}"
                if key not in seen:
                    seen.add(key)
                    results.append(c)
    # Also try Levenshtein-style: keep first 10 by name length proximity
    results.sort(key=lambda c: abs(len(c.name) - len(target)))
    return results[:10]


# ---------------------------------------------------------------------------
# Subcommand: scaffold-all
# ---------------------------------------------------------------------------

def cmd_scaffold_all(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    index, game_version, _ = _shared_setup(game_dir, args.version)

    # Extract mod references
    print("\nExtracting mod references from mods/src/...", file=sys.stderr)
    refs = extract_references(MOD_SRC)

    # Deduplicate CLASS references by (assembly, namespace, class_name)
    seen_class_keys: set[tuple] = set()
    class_refs = []
    for ref in refs:
        if ref.type != RefType.CLASS:
            continue
        if ref.class_name is None:
            continue
        key = (ref.assembly, ref.namespace, ref.class_name)
        if key not in seen_class_keys:
            seen_class_keys.add(key)
            class_refs.append(ref)

    print(f"Found {len(class_refs)} unique class references.", file=sys.stderr)

    # Determine which hand-written headers already exist in prime/ (not generated/)
    hand_written_stems: set[str] = set()
    for h in PRIME_DIR.glob("*.h"):
        hand_written_stems.add(h.stem)

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    written  = 0
    skipped  = 0
    missing  = 0

    for ref in class_refs:
        cn = ref.class_name
        cpp_name = cn.replace("`", "_") if cn else ""

        # Skip if hand-written header already exists
        if cpp_name in hand_written_stems:
            skipped += 1
            continue

        # Look up the class in dump
        dc = index.by_qualified_name.get((ref.assembly, ref.namespace, cn))
        if dc is None:
            print(f"  [SKIP] Not in dump: {ref.assembly} :: {ref.namespace}.{cn}", file=sys.stderr)
            missing += 1
            continue

        content = generate_scaffold(dc, game_version)
        out_path = GENERATED_DIR / f"{cpp_name}.h"
        out_path.write_text(content, encoding="utf-8")
        print(f"  Written: {out_path.name}")
        written += 1

    print(f"\nscaffold-all complete: {written} written, {skipped} skipped (hand-written), "
          f"{missing} not in dump.")
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="subcommand", required=True)

    # --- fix ---
    p_fix = sub.add_parser("fix", help="Auto-fix broken IL2CPP references in mod source")
    p_fix.add_argument("--game-dir", required=True, metavar="PATH",
                       help="Path to the game directory (.app on macOS, game root on Windows)")
    p_fix.add_argument("--version", metavar="VER",
                       help="Override the detected game version string")
    p_fix.add_argument("--dry-run", action="store_true",
                       help="Show what would be changed without writing files")

    # --- scaffold ---
    p_scaf = sub.add_parser("scaffold", help="Generate a C++ header scaffold for a single class")
    p_scaf.add_argument("class_name", metavar="class-name",
                        help="Class name to scaffold (e.g. 'Camera' or 'UnityEngine.Camera')")
    p_scaf.add_argument("--game-dir", required=True, metavar="PATH",
                        help="Path to the game directory")
    p_scaf.add_argument("--version", metavar="VER",
                        help="Override the detected game version string")
    p_scaf.add_argument("--output", metavar="PATH",
                        help="Output file path (default: mods/src/prime/generated/<ClassName>.h)")

    # --- scaffold-all ---
    p_all = sub.add_parser("scaffold-all",
                           help="Generate headers for all classes referenced in mod source")
    p_all.add_argument("--game-dir", required=True, metavar="PATH",
                       help="Path to the game directory")
    p_all.add_argument("--version", metavar="VER",
                       help="Override the detected game version string")

    return parser


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = build_parser()
    args   = parser.parse_args()

    dispatch = {
        "fix":          cmd_fix,
        "scaffold":     cmd_scaffold,
        "scaffold-all": cmd_scaffold_all,
    }
    return dispatch[args.subcommand](args)


if __name__ == "__main__":
    sys.exit(main())
