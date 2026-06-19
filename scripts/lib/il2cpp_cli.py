"""Command-line entry points for the STFC IL2CPP tooling."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from . import dump_runner, il2cpp_workflow
from .codegen import generate_scaffold
from .fixer import analyze_issues, apply_fixes
from .mod_extractor import extract_references, extract_references_with_report
from .models import RefType, Severity
from .validator import (
    ValidationDiagnostics,
    build_sidecar,
    categorize_issues,
    diff_sidecars,
    find_previous_sidecar,
    validate,
    write_sidecar,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DUMP_DIR = PROJECT_ROOT / "dump"
MOD_SRC = PROJECT_ROOT / "mods" / "src"
PRIME_DIR = MOD_SRC / "prime"
GENERATED_DIR = PRIME_DIR / "generated"


def _print_error(exc: BaseException) -> None:
    print(str(exc), file=sys.stderr)


def _format_ref_location(ref) -> str:
    if ref.source_line:
        return f"{ref.source_file}:{ref.source_line}"
    return ref.source_file


def _issue_to_dict(issue) -> dict:
    ref = issue.ref
    d: dict = {
        "severity": issue.severity.name.lower(),
        "type": ref.type.name.lower(),
        "message": issue.message,
        "file": ref.source_file,
        "line": ref.source_line,
    }
    if ref.assembly is not None:
        d["assembly"] = ref.assembly
    if ref.namespace is not None:
        d["namespace"] = ref.namespace
    if ref.class_name is not None:
        d["class"] = ref.class_name
    if ref.member_name is not None:
        d["member"] = ref.member_name
    if ref.arg_count is not None:
        d["arg_count"] = ref.arg_count
    if ref.parent_name is not None:
        d["parent_name"] = ref.parent_name
    if ref.icall_signature is not None:
        d["icall_signature"] = ref.icall_signature
    if issue.old_signature is not None:
        d["old_signature"] = issue.old_signature
    if issue.new_signature is not None:
        d["new_signature"] = issue.new_signature
    return d


def _print_json(issues, refs, game_version: str, unity_version: str, diagnostics: ValidationDiagnostics) -> None:
    counts = Counter(r.type for r in refs)
    categories = categorize_issues(issues, diagnostics)
    report = {
        "game_version": game_version,
        "unity_version": unity_version,
        "summary": {
            "classes": counts[RefType.CLASS],
            "methods": counts[RefType.METHOD],
            "fields": counts[RefType.FIELD],
            "properties": counts[RefType.PROPERTY],
            "icalls": counts[RefType.ICALL],
            "missing": sum(1 for i in issues if i.severity == Severity.MISSING),
            "signature_changed": sum(1 for i in issues if i.severity == Severity.SIGNATURE_CHANGED),
            "categories": {name: len(items) for name, items in categories.items()},
        },
        "issues": [_issue_to_dict(i) for i in issues],
    }
    print(json.dumps(report, indent=2, ensure_ascii=False))


def _print_text(issues, refs, game_version: str, diagnostics: ValidationDiagnostics) -> None:
    print(f"\nValidating mod references against dump {game_version}...\n")
    categories = categorize_issues(issues, diagnostics)

    for issue in issues:
        ref = issue.ref
        if issue.severity == Severity.MISSING:
            rtype = ref.type
            if rtype == RefType.CLASS:
                label = "MISSING CLASS"
                detail = (
                    f"{ref.assembly} :: {ref.namespace}.{ref.class_name}"
                    if ref.namespace
                    else f"{ref.assembly} :: {ref.class_name}"
                )
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
            detail = issue.message
            for prefix in ("Signature changed: ", "Icall signature changed: "):
                if detail.startswith(prefix):
                    detail = detail[len(prefix):]
                    break
            print(f"SIGNATURE CHANGED: {detail}")
            if issue.old_signature:
                print(f"  Was:  {issue.old_signature}")
            if issue.new_signature:
                print(f"  Now:  {issue.new_signature}")
            print(f"  Referenced in: {_format_ref_location(ref)}")
            print()

    n_classes = sum(1 for r in refs if r.type == RefType.CLASS)
    n_methods = sum(1 for r in refs if r.type == RefType.METHOD)
    n_fields = sum(1 for r in refs if r.type == RefType.FIELD)
    n_properties = sum(1 for r in refs if r.type == RefType.PROPERTY)
    n_icalls = sum(1 for r in refs if r.type == RefType.ICALL)

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

    print("\nDrift categories:")
    labels = {
        "missing_current_refs": "real missing current refs",
        "signature_changed": "signature changes",
        "platform_skipped_refs": "platform-skipped refs",
        "inherited_base_refs": "inherited/base-class refs",
        "optional_probes": "optional probes",
        "tool_limitations": "tool/parser limitations",
    }
    for key, label in labels.items():
        print(f"  {label}: {len(categories[key])}")


def cmd_dump(args) -> int:
    try:
        dump_runner.dump_game(
            Path(args.game_dir),
            version_override=args.version,
            reinstall=args.reinstall,
            dump_root=DUMP_DIR,
        )
    except (ExceptionGroup, FileNotFoundError, RuntimeError) as exc:
        _print_error(exc)
        return 1
    return 0


def cmd_validate(args) -> int:
    def log(msg: str) -> None:
        print(msg, file=sys.stderr if args.format == "json" else sys.stdout)

    try:
        context = il2cpp_workflow.resolve_context(
            Path(args.game_dir),
            version_override=args.version,
            dump_root=DUMP_DIR,
        )
        log(f"Game version : {context.game_version}")
        log(f"Unity version: {context.unity_version}")
        il2cpp_workflow.ensure_dump(context, log=log)
    except (ExceptionGroup, FileNotFoundError, RuntimeError) as exc:
        _print_error(exc)
        return 1

    if args.dump_only:
        log("--dump-only flag set, skipping validation.")
        return 0

    log(f"\nExtracting mod references from mods/src/ (target: {args.target_platform})...")
    extraction = extract_references_with_report(MOD_SRC, target_platform=args.target_platform)
    refs = extraction.refs
    log(f"Found {len(refs)} raw references in mod source.")
    if extraction.platform_skipped_refs:
        log(f"Skipped {len(extraction.platform_skipped_refs)} platform-guarded reference(s).")

    index = il2cpp_workflow.parse_context_dump(context, log=log)
    diagnostics = ValidationDiagnostics(platform_skipped_refs=extraction.platform_skipped_refs)
    issues = validate(refs, index, diagnostics)

    prev_sidecar = find_previous_sidecar(context.dump_root, context.game_version)
    if prev_sidecar is not None:
        prev_version = prev_sidecar.get("game_version", "unknown")
        log(f"Diffing against previous sidecar (version {prev_version})...")
        issues = issues + diff_sidecars(prev_sidecar, refs, index)
    else:
        log("No previous sidecar found; skipping diff.")

    sidecar = build_sidecar(refs, index, context.game_version, context.unity_version)
    sidecar_path = context.dump_dir / "mod-references.json"
    write_sidecar(sidecar, sidecar_path)
    log(f"Sidecar written to {sidecar_path}")

    if args.format == "json":
        _print_json(issues, refs, context.game_version, context.unity_version, diagnostics)
    else:
        _print_text(issues, refs, context.game_version, diagnostics)

    return 1 if issues else 0


def cmd_fix(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    try:
        context, index = il2cpp_workflow.prepare_dump_index(
            game_dir,
            version_override=args.version,
            dump_root=DUMP_DIR,
        )
    except (ExceptionGroup, FileNotFoundError, RuntimeError) as exc:
        _print_error(exc)
        return 1

    print("\nExtracting mod references from mods/src/...", file=sys.stderr)
    refs = extract_references(MOD_SRC, target_platform=args.target_platform)
    print(f"Found {len(refs)} raw references.", file=sys.stderr)

    print("Validating references...", file=sys.stderr)
    issues = validate(refs, index)
    print(f"Found {len(issues)} issue(s).", file=sys.stderr)

    if not issues:
        print("\nAll references OK; nothing to fix.")
        return 0

    fixes, suggestions = analyze_issues(issues, index, PROJECT_ROOT)

    print(f"\n{'DRY-RUN: ' if args.dry_run else ''}Fix report for dump {context.game_version}")
    print(f"  Issues     : {len(issues)}")
    print(f"  Auto-fixes : {len(fixes)}")
    print(f"  Suggestions: {len(suggestions)}")

    if fixes:
        print("\nAuto-fixes:")
        for fix in fixes:
            rel = Path(fix.file).relative_to(PROJECT_ROOT) if Path(fix.file).is_absolute() else fix.file
            print(f"  [{rel}:{fix.line}] {fix.description}")

    if suggestions:
        print("\nSuggestions (manual review needed):")
        for suggestion in suggestions:
            rel = (
                Path(suggestion.file).relative_to(PROJECT_ROOT)
                if Path(suggestion.file).is_absolute()
                else suggestion.file
            )
            print(f"  [{rel}:{suggestion.line}] {suggestion.description}")

    modified = apply_fixes(fixes, PROJECT_ROOT, dry_run=args.dry_run)
    if args.dry_run:
        print(f"\n[dry-run] Would modify {modified} file(s).")
    else:
        print(f"\nModified {modified} file(s).")

    return 0


def cmd_scaffold(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    try:
        context, index = il2cpp_workflow.prepare_dump_index(
            game_dir,
            version_override=args.version,
            dump_root=DUMP_DIR,
        )
    except (ExceptionGroup, FileNotFoundError, RuntimeError) as exc:
        _print_error(exc)
        return 1

    class_arg = args.class_name
    dc = _find_scaffold_class(class_arg, index)
    if dc is None:
        return 1

    print(f"Generating scaffold for {dc.assembly} :: {dc.namespace}.{dc.name}...", file=sys.stderr)
    content = generate_scaffold(dc, context.game_version)

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


def _find_scaffold_class(class_arg: str, index):
    dc = None
    if "." in class_arg:
        ns, _, cn = class_arg.rpartition(".")
        candidates = [c for c in index.by_class_name.get(cn, []) if c.namespace == ns]
        if len(candidates) == 1:
            dc = candidates[0]
        elif len(candidates) > 1:
            print(f"Multiple matches for qualified name '{class_arg}':")
            for c in candidates:
                print(f"  {c.assembly} :: {c.namespace}.{c.name}")
            return None
        name_only = cn
    else:
        name_only = class_arg

    if dc is not None:
        return dc

    matches = index.by_class_name.get(name_only, [])
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        print(f"Multiple matches for '{name_only}'; specify a qualified name (Namespace.ClassName):")
        for c in matches:
            ns_str = f"{c.namespace}." if c.namespace else ""
            print(f"  {c.assembly} :: {ns_str}{c.name}")
        return None

    similar = _find_similar_classes(name_only, index)
    print(f"Class '{name_only}' not found in dump.")
    if similar:
        print("Similar class names:")
        for item in similar:
            ns_str = f"{item.namespace}." if item.namespace else ""
            print(f"  {item.assembly} :: {ns_str}{item.name}")
    return None


def _find_similar_classes(target: str, index) -> list:
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
    results.sort(key=lambda c: abs(len(c.name) - len(target)))
    return results[:10]


def cmd_scaffold_all(args) -> int:
    game_dir = Path(args.game_dir).resolve()
    if not game_dir.exists():
        print(f"Game directory not found: {game_dir}", file=sys.stderr)
        return 1

    try:
        context, index = il2cpp_workflow.prepare_dump_index(
            game_dir,
            version_override=args.version,
            dump_root=DUMP_DIR,
        )
    except (ExceptionGroup, FileNotFoundError, RuntimeError) as exc:
        _print_error(exc)
        return 1

    print("\nExtracting mod references from mods/src/...", file=sys.stderr)
    refs = extract_references(MOD_SRC, target_platform=args.target_platform)

    seen_class_keys: set[tuple] = set()
    class_refs = []
    for ref in refs:
        if ref.type != RefType.CLASS or ref.class_name is None:
            continue
        key = (ref.assembly, ref.namespace, ref.class_name)
        if key not in seen_class_keys:
            seen_class_keys.add(key)
            class_refs.append(ref)

    print(f"Found {len(class_refs)} unique class references.", file=sys.stderr)

    hand_written_stems = {h.stem for h in PRIME_DIR.glob("*.h")}
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)

    written = 0
    skipped = 0
    missing = 0

    for ref in class_refs:
        cn = ref.class_name
        cpp_name = cn.replace("`", "_") if cn else ""
        if cpp_name in hand_written_stems:
            skipped += 1
            continue

        dc = index.by_qualified_name.get((ref.assembly, ref.namespace, cn))
        if dc is None:
            print(f"  [SKIP] Not in dump: {ref.assembly} :: {ref.namespace}.{cn}", file=sys.stderr)
            missing += 1
            continue

        content = generate_scaffold(dc, context.game_version)
        out_path = GENERATED_DIR / f"{cpp_name}.h"
        out_path.write_text(content, encoding="utf-8")
        print(f"  Written: {out_path.name}")
        written += 1

    print(f"\nscaffold-all complete: {written} written, {skipped} skipped (hand-written), "
          f"{missing} not in dump.")
    return 0


def _add_game_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--game-dir", required=True, metavar="PATH",
                        help="Path to the game directory (.app on macOS, game root on Windows)")
    parser.add_argument("--version", metavar="VER",
                        help="Override the detected game version string")


def _add_target_platform_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--target-platform", choices=["auto", "macos", "windows", "all"], default="auto",
                        help="Preprocessor target for mod references (default: auto from host)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified STFC IL2CPP dump, validation, and codegen workflow.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_dump = sub.add_parser("dump", help="Generate dump.cs and script.json from a game install")
    _add_game_args(p_dump)
    p_dump.add_argument("--reinstall", action="store_true",
                        help="Force re-download of Il2CppDumper")
    p_dump.set_defaults(func=cmd_dump)

    p_validate = sub.add_parser("validate", help="Validate mod IL2CPP references against a dump")
    _add_game_args(p_validate)
    p_validate.add_argument("--dump-only", action="store_true",
                            help="Run dump but skip validation")
    p_validate.add_argument("--format", choices=["text", "json"], default="text",
                            help="Output format (default: text)")
    _add_target_platform_arg(p_validate)
    p_validate.set_defaults(func=cmd_validate)

    _add_codegen_subcommands(sub)
    return parser


def build_dump_parser() -> argparse.ArgumentParser:
    return dump_runner.build_parser()


def build_validate_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate mod IL2CPP references against a game dump.",
    )
    _add_game_args(parser)
    parser.add_argument("--dump-only", action="store_true",
                        help="Run dump but skip validation")
    parser.add_argument("--format", choices=["text", "json"], default="text",
                        help="Output format (default: text)")
    _add_target_platform_arg(parser)
    parser.set_defaults(func=cmd_validate)
    return parser


def build_codegen_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate C++ scaffolds and auto-fix IL2CPP references from a game dump.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = parser.add_subparsers(dest="command", required=True)
    _add_codegen_subcommands(sub)
    return parser


def _add_codegen_subcommands(sub) -> None:
    p_fix = sub.add_parser("fix", help="Auto-fix broken IL2CPP references in mod source")
    _add_game_args(p_fix)
    p_fix.add_argument("--dry-run", action="store_true",
                       help="Show what would be changed without writing files")
    _add_target_platform_arg(p_fix)
    p_fix.set_defaults(func=cmd_fix)

    p_scaffold = sub.add_parser("scaffold", help="Generate a C++ header scaffold for a single class")
    p_scaffold.add_argument("class_name", metavar="class-name",
                            help="Class name to scaffold (e.g. 'Camera' or 'UnityEngine.Camera')")
    _add_game_args(p_scaffold)
    p_scaffold.add_argument("--output", metavar="PATH",
                            help="Output file path (default: mods/src/prime/generated/<ClassName>.h)")
    p_scaffold.set_defaults(func=cmd_scaffold)

    p_all = sub.add_parser("scaffold-all", help="Generate headers for all classes referenced in mod source")
    _add_game_args(p_all)
    _add_target_platform_arg(p_all)
    p_all.set_defaults(func=cmd_scaffold_all)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def main_dump(argv: list[str] | None = None) -> int:
    parser = build_dump_parser()
    args = parser.parse_args(argv)
    dump_runner.dump_game(args.game_dir, version_override=args.version, reinstall=args.reinstall)
    return 0


def main_validate(argv: list[str] | None = None) -> int:
    parser = build_validate_parser()
    args = parser.parse_args(argv)
    return args.func(args)


def main_codegen(argv: list[str] | None = None) -> int:
    parser = build_codegen_parser()
    args = parser.parse_args(argv)
    return args.func(args)
