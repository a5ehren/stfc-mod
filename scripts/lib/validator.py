"""Cross-reference validator for IL2CPP mod references.

Validates ModReferences against a DumpIndex and manages sidecar JSON files
that snapshot which game members were present at a given game version.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import DumpIndex, Issue, ModReference, RefType, Severity


@dataclass(slots=True)
class ValidationDiagnostics:
    """Non-fatal validation details that should be reported separately."""

    platform_skipped_refs: list[ModReference] = field(default_factory=list)
    inherited_base_refs: list[ModReference] = field(default_factory=list)
    tool_limitations: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _count_params(signature: str) -> int:
    """Count parameters in a method signature string.

    Accepts either a bare param list like '(float depth, int n)' or a full
    signature like 'public void Foo(float depth) { }'.  Returns 0 for empty
    param lists.
    """
    # Extract the content inside the first pair of parentheses.
    m = re.search(r'\(([^)]*)\)', signature)
    if not m:
        return 0
    inner = m.group(1).strip()
    if not inner:
        return 0
    # Count top-level commas (ignore nested generics like List<int, string>).
    depth = 0
    count = 1
    for ch in inner:
        if ch in '<([':
            depth += 1
        elif ch in '>)]':
            depth -= 1
        elif ch == ',' and depth == 0:
            count += 1
    return count


def _parse_icall_signature(icall_sig: str) -> tuple[str, str, str] | None:
    """Decompose 'Namespace.Class::Method(Args)' into (namespace, class_name, method_name).

    Returns None if the signature cannot be parsed.
    """
    # Split on '::' — everything before is 'Namespace.Class', after is 'Method(Args)'
    if '::' not in icall_sig:
        return None
    left, right = icall_sig.split('::', 1)
    # method_name is everything before the '('
    method_name = right.split('(')[0].strip()
    # Split left on the last '.' to get (namespace, class_name)
    if '.' in left:
        last_dot = left.rfind('.')
        namespace = left[:last_dot]
        class_name = left[last_dot + 1:]
    else:
        namespace = ''
        class_name = left
    return namespace, class_name, method_name


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate(
    refs: list[ModReference],
    index: DumpIndex,
    diagnostics: ValidationDiagnostics | None = None,
) -> list[Issue]:
    """Cross-reference all mod references against the dump index.

    Args:
        refs:  List of ModReferences extracted from mod source.
        index: DumpIndex built from the current dump.cs.

    Returns:
        List of Issue instances, one per problem found.
    """
    issues: list[Issue] = []

    for ref in refs:
        if (
            diagnostics is not None
            and ref.type in (RefType.METHOD, RefType.FIELD, RefType.PROPERTY, RefType.NESTED_TYPE, RefType.PARENT_CLASS)
            and ref.class_name is None
        ):
            diagnostics.tool_limitations.append(
                f"Could not resolve class helper for {ref.type.name.lower()} "
                f"at {ref.source_file}:{ref.source_line}"
            )

        if ref.type == RefType.CLASS:
            _validate_class(ref, index, issues)
        elif ref.type == RefType.METHOD:
            _validate_method(ref, index, issues, diagnostics)
        elif ref.type == RefType.FIELD:
            _validate_field(ref, index, issues, diagnostics)
        elif ref.type == RefType.PROPERTY:
            _validate_property(ref, index, issues, diagnostics)
        elif ref.type == RefType.NESTED_TYPE:
            _validate_nested_type(ref, index, issues)
        elif ref.type == RefType.PARENT_CLASS:
            _validate_parent_class(ref, index, issues)
        elif ref.type == RefType.ICALL:
            _validate_icall(ref, index, issues)

    return issues


def categorize_issues(
    issues: list[Issue],
    diagnostics: ValidationDiagnostics | None = None,
) -> dict[str, list]:
    """Split drift into report buckets used by text and JSON output."""
    categories: dict[str, list] = {
        "missing_current_refs": [],
        "signature_changed": [],
        "platform_skipped_refs": _dedupe_list(diagnostics.platform_skipped_refs) if diagnostics else [],
        "inherited_base_refs": _dedupe_list(diagnostics.inherited_base_refs) if diagnostics else [],
        "optional_probes": [],
        "tool_limitations": _dedupe_list(diagnostics.tool_limitations) if diagnostics else [],
    }

    for issue in issues:
        if issue.ref.optional_probe:
            categories["optional_probes"].append(issue)
        elif issue.severity == Severity.SIGNATURE_CHANGED:
            categories["signature_changed"].append(issue)
        elif issue.severity == Severity.MISSING:
            categories["missing_current_refs"].append(issue)

    return categories


def _dedupe_list(items: list) -> list:
    """Deduplicate while preserving order."""
    result: list = []
    seen: set[str] = set()
    for item in items:
        key = repr(item)
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def _validate_class(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return
    key = (ref.assembly, ref.namespace, ref.class_name)
    if key not in index.by_qualified_name:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing class: {ref.assembly}::{ref.namespace}.{ref.class_name}"
            ),
        ))


def _lookup_class(ref: ModReference, index: DumpIndex) -> object | None:
    """Return the DumpClass for a ref, or None if the class is missing."""
    if ref.class_name is None:
        return None
    key = (ref.assembly, ref.namespace, ref.class_name)
    return index.by_qualified_name.get(key)


# Well-known Unity/System base class members that are always available at
# runtime via IL2CPP but may not appear on derived classes in the dump.
_UNITY_BASE_MEMBERS = {
    # UnityEngine.Object
    "name", "hideFlags",
    # UnityEngine.Component / MonoBehaviour
    "enabled", "transform", "gameObject", "tag", "isActiveAndEnabled",
}


def _has_member_in_hierarchy(
    dc,
    member_name: str,
    member_type: str,
    index: DumpIndex,
    visited: set | None = None,
) -> bool:
    """Check if *member_name* exists on *dc* or any of its parents.

    member_type is one of 'method', 'field', 'property'.
    Walks the inheritance chain up to 10 levels to avoid infinite loops.
    """
    if visited is None:
        visited = set()
    # Prevent cycles
    key = (dc.assembly, dc.namespace, dc.name)
    if key in visited:
        return False
    visited.add(key)
    if len(visited) > 10:
        return False

    # Check the class itself
    if member_type == 'method' and member_name in dc.methods:
        return True
    if member_type == 'field' and member_name in dc.fields:
        return True
    if member_type == 'property' and member_name in dc.properties:
        return True

    # Walk parents
    for parent_name in dc.parents:
        # Try to find parent class in the index by name
        parent_candidates = index.by_class_name.get(parent_name, [])
        for parent_dc in parent_candidates:
            if _has_member_in_hierarchy(parent_dc, member_name, member_type, index, visited):
                return True

    return False


def _record_inherited_ref(ref: ModReference, diagnostics: ValidationDiagnostics | None) -> None:
    if diagnostics is not None:
        diagnostics.inherited_base_refs.append(ref)


def _validate_method(
    ref: ModReference,
    index: DumpIndex,
    issues: list[Issue],
    diagnostics: ValidationDiagnostics | None = None,
) -> None:
    if ref.class_name is None:
        return
    dc = _lookup_class(ref, index)
    if dc is None:
        # Class is missing — a CLASS issue will be/was reported separately.
        return
    method_name = ref.member_name
    if method_name not in dc.methods:
        # Check inheritance chain before reporting
        if _has_member_in_hierarchy(dc, method_name, 'method', index):
            _record_inherited_ref(ref, diagnostics)
            return
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing method: {ref.class_name}.{method_name}()"
                f" in {ref.assembly}::{ref.namespace}.{ref.class_name}"
            ),
        ))
        return
    # Arg count check
    if ref.arg_count is not None:
        sigs = dc.methods[method_name]
        if not any(_count_params(sig) == ref.arg_count for sig in sigs):
            issues.append(Issue(
                severity=Severity.MISSING,
                ref=ref,
                message=(
                    f"No overload of {ref.class_name}.{method_name}() with "
                    f"{ref.arg_count} arg(s) in "
                    f"{ref.assembly}::{ref.namespace}.{ref.class_name}"
                ),
            ))


def _validate_field(
    ref: ModReference,
    index: DumpIndex,
    issues: list[Issue],
    diagnostics: ValidationDiagnostics | None = None,
) -> None:
    if ref.class_name is None:
        return
    dc = _lookup_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.fields:
        # Check inheritance chain before reporting
        if _has_member_in_hierarchy(dc, ref.member_name, 'field', index):
            _record_inherited_ref(ref, diagnostics)
            return
        # Check well-known Unity base members
        if ref.member_name in _UNITY_BASE_MEMBERS:
            _record_inherited_ref(ref, diagnostics)
            return
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing field: {ref.class_name}.{ref.member_name}"
                f" in {ref.assembly}::{ref.namespace}.{ref.class_name}"
            ),
        ))


def _validate_property(
    ref: ModReference,
    index: DumpIndex,
    issues: list[Issue],
    diagnostics: ValidationDiagnostics | None = None,
) -> None:
    if ref.class_name is None:
        return
    dc = _lookup_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.properties:
        # Check inheritance chain before reporting
        if _has_member_in_hierarchy(dc, ref.member_name, 'property', index):
            _record_inherited_ref(ref, diagnostics)
            return
        # Check well-known Unity base members
        if ref.member_name in _UNITY_BASE_MEMBERS:
            _record_inherited_ref(ref, diagnostics)
            return
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing property: {ref.class_name}.{ref.member_name}"
                f" in {ref.assembly}::{ref.namespace}.{ref.class_name}"
            ),
        ))


def _validate_nested_type(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return
    dc = _lookup_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.nested_types:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing nested type: {ref.class_name}.{ref.member_name}"
                f" in {ref.assembly}::{ref.namespace}.{ref.class_name}"
            ),
        ))


def _validate_parent_class(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    parent_name = ref.parent_name
    if parent_name is None:
        return
    if parent_name not in index.by_class_name:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"Missing parent class: {parent_name}",
        ))


def _validate_icall(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    sig = ref.icall_signature
    if not sig:
        return
    parsed = _parse_icall_signature(sig)
    if parsed is None:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"Cannot parse icall signature: {sig!r}",
        ))
        return
    namespace, class_name, method_name = parsed
    candidates = index.by_ns_class.get((namespace, class_name), [])
    if not candidates:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=(
                f"Missing icall class: {namespace}.{class_name}"
                f" (for icall {sig!r})"
            ),
        ))
        return
    # Check that the method exists on at least one candidate class.
    for dc in candidates:
        if method_name in dc.methods:
            return
    issues.append(Issue(
        severity=Severity.MISSING,
        ref=ref,
        message=(
            f"Missing icall method: {class_name}.{method_name}()"
            f" (for icall {sig!r})"
        ),
    ))


# ---------------------------------------------------------------------------
# Sidecar building
# ---------------------------------------------------------------------------

def build_sidecar(
    refs: list[ModReference],
    index: DumpIndex,
    game_version: str,
    unity_version: str,
) -> dict:
    """Build a sidecar dict from the current refs and dump index.

    The sidecar captures which game members were referenced by the mod and
    what their current signatures look like, enabling future diff detection.

    Structure::

        {
            "game_version": "1.000.48286",
            "unity_version": "6000.0.59f2",
            "references": {
                "Assembly-CSharp::Digit.Prime.Navigation.NavigationZoom": {
                    "methods": {"SetDepth": ["public void SetDepth(float depth) { }"]},
                    "fields": ["_depth"],
                    "properties": ["Distance"],
                }
            },
            "icalls": {
                "UnityEngine.Input::GetKeyDownInt": {
                    "class": "UnityEngine.Input",
                    "signatures": ["private static bool GetKeyDownInt(KeyCode key) { }"],
                }
            }
        }
    """
    sidecar_refs: dict[str, dict] = {}
    sidecar_icalls: dict[str, dict] = {}

    for ref in refs:
        if ref.type == RefType.ICALL:
            _add_icall_to_sidecar(ref, index, sidecar_icalls)
        else:
            _add_ref_to_sidecar(ref, index, sidecar_refs)

    return {
        "game_version": game_version,
        "unity_version": unity_version,
        "references": sidecar_refs,
        "icalls": sidecar_icalls,
    }


def _class_key(assembly: str | None, namespace: str | None, class_name: str | None) -> str:
    """Build the sidecar dict key for a class reference."""
    asm = assembly or ""
    ns = namespace or ""
    cls = class_name or ""
    full_class = f"{ns}.{cls}" if ns else cls
    return f"{asm}::{full_class}"


def _add_ref_to_sidecar(
    ref: ModReference,
    index: DumpIndex,
    sidecar_refs: dict[str, dict],
) -> None:
    """Add a non-icall reference to the sidecar, pulling signatures from the index."""
    if ref.class_name is None:
        return

    key = _class_key(ref.assembly, ref.namespace, ref.class_name)
    if key not in sidecar_refs:
        sidecar_refs[key] = {"methods": {}, "fields": [], "properties": []}
    entry = sidecar_refs[key]

    # Look up the class in the index to capture actual dump content.
    dc = index.by_qualified_name.get((ref.assembly, ref.namespace, ref.class_name))

    if ref.type == RefType.METHOD and ref.member_name:
        if ref.member_name not in entry["methods"]:
            sigs = (dc.methods.get(ref.member_name, []) if dc else [])
            entry["methods"][ref.member_name] = list(sigs)

    elif ref.type == RefType.FIELD and ref.member_name:
        if ref.member_name not in entry["fields"]:
            entry["fields"].append(ref.member_name)

    elif ref.type == RefType.PROPERTY and ref.member_name:
        if ref.member_name not in entry["properties"]:
            entry["properties"].append(ref.member_name)


def _add_icall_to_sidecar(
    ref: ModReference,
    index: DumpIndex,
    sidecar_icalls: dict[str, dict],
) -> None:
    """Add an icall reference to the sidecar."""
    sig = ref.icall_signature
    if not sig:
        return
    parsed = _parse_icall_signature(sig)
    if parsed is None:
        return
    namespace, class_name, method_name = parsed

    # Use the icall signature as the dict key (everything before the first '(')
    icall_key = sig.split('(')[0]

    if icall_key in sidecar_icalls:
        return

    full_class = f"{namespace}.{class_name}" if namespace else class_name
    candidates = index.by_ns_class.get((namespace, class_name), [])
    signatures: list[str] = []
    for dc in candidates:
        sigs = dc.methods.get(method_name, [])
        for s in sigs:
            if s not in signatures:
                signatures.append(s)

    sidecar_icalls[icall_key] = {
        "class": full_class,
        "signatures": signatures,
    }


# ---------------------------------------------------------------------------
# Sidecar I/O
# ---------------------------------------------------------------------------

def write_sidecar(sidecar: dict, path: Path) -> None:
    """Write the sidecar dict to a JSON file at *path*."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(sidecar, fh, indent=2, ensure_ascii=False)
        fh.write('\n')


def load_sidecar(path: Path) -> dict | None:
    """Load a sidecar JSON file, returning None if missing or unparseable."""
    path = Path(path)
    if not path.exists():
        return None
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None


# ---------------------------------------------------------------------------
# Sidecar diffing
# ---------------------------------------------------------------------------

def diff_sidecars(
    old: dict,
    new_refs: list[ModReference],
    index: DumpIndex,
) -> list[Issue]:
    """Compare a previous sidecar against the current dump and refs.

    For every method that exists in both the old sidecar and the current dump,
    check whether the full set of signatures has changed.  Reports
    SIGNATURE_CHANGED issues.

    Args:
        old:      Previously saved sidecar dict.
        new_refs: Current mod references (used to build a fresh sidecar for
                  comparison; game_version/unity_version not needed here).
        index:    DumpIndex from the current dump.cs.

    Returns:
        List of SIGNATURE_CHANGED Issue instances.
    """
    issues: list[Issue] = []

    old_refs_map: dict[str, dict] = old.get("references", {})
    old_icalls_map: dict[str, dict] = old.get("icalls", {})

    # Build a fresh sidecar from current data for comparison.
    new_sidecar = build_sidecar(new_refs, index, "", "")
    new_refs_map: dict[str, dict] = new_sidecar.get("references", {})
    new_icalls_map: dict[str, dict] = new_sidecar.get("icalls", {})

    # Diff class methods
    for class_key, old_entry in old_refs_map.items():
        new_entry = new_refs_map.get(class_key)
        if new_entry is None:
            continue  # class missing entirely — a MISSING issue via validate()
        old_methods: dict[str, list[str]] = old_entry.get("methods", {})
        new_methods: dict[str, list[str]] = new_entry.get("methods", {})
        for method_name, old_sigs in old_methods.items():
            new_sigs = new_methods.get(method_name)
            if new_sigs is None:
                continue  # method missing — reported by validate()
            if sorted(old_sigs) != sorted(new_sigs):
                # Build a synthetic ref for context (best-effort).
                synthetic_ref = _synthetic_ref_for_class_key(class_key, method_name, new_refs)
                old_sig_str = "; ".join(old_sigs) if old_sigs else "(no signature)"
                new_sig_str = "; ".join(new_sigs) if new_sigs else "(no signature)"
                issues.append(Issue(
                    severity=Severity.SIGNATURE_CHANGED,
                    ref=synthetic_ref,
                    message=(
                        f"Signature changed: {class_key}.{method_name}()"
                    ),
                    old_signature=old_sig_str,
                    new_signature=new_sig_str,
                ))

    # Diff icalls
    for icall_key, old_icall in old_icalls_map.items():
        new_icall = new_icalls_map.get(icall_key)
        if new_icall is None:
            continue  # missing — reported by validate()
        old_sigs = old_icall.get("signatures", [])
        new_sigs = new_icall.get("signatures", [])
        if sorted(old_sigs) != sorted(new_sigs):
            synthetic_ref = _synthetic_ref_for_icall(icall_key, new_refs)
            old_sig_str = "; ".join(old_sigs) if old_sigs else "(no signature)"
            new_sig_str = "; ".join(new_sigs) if new_sigs else "(no signature)"
            issues.append(Issue(
                severity=Severity.SIGNATURE_CHANGED,
                ref=synthetic_ref,
                message=f"Icall signature changed: {icall_key}",
                old_signature=old_sig_str,
                new_signature=new_sig_str,
            ))

    return issues


def _synthetic_ref_for_class_key(
    class_key: str,
    method_name: str,
    refs: list[ModReference],
) -> ModReference:
    """Find an existing ModReference matching the class_key/method, or build a minimal one."""
    # class_key format: "Assembly::Namespace.ClassName"
    assembly, _, full_class = class_key.partition('::')
    if '.' in full_class:
        last_dot = full_class.rfind('.')
        namespace = full_class[:last_dot]
        class_name = full_class[last_dot + 1:]
    else:
        namespace = ''
        class_name = full_class

    for ref in refs:
        if (
            ref.type == RefType.METHOD
            and ref.assembly == assembly
            and ref.namespace == namespace
            and ref.class_name == class_name
            and ref.member_name == method_name
        ):
            return ref

    # Fall back to a minimal synthetic ref.
    return ModReference(
        type=RefType.METHOD,
        source_file='<sidecar-diff>',
        source_line=0,
        assembly=assembly,
        namespace=namespace,
        class_name=class_name,
        member_name=method_name,
    )


def _synthetic_ref_for_icall(icall_key: str, refs: list[ModReference]) -> ModReference:
    """Find an existing icall ModReference, or build a minimal synthetic one."""
    for ref in refs:
        if ref.type == RefType.ICALL and ref.icall_signature and ref.icall_signature.startswith(icall_key):
            return ref
    return ModReference(
        type=RefType.ICALL,
        source_file='<sidecar-diff>',
        source_line=0,
        icall_signature=icall_key,
    )


# ---------------------------------------------------------------------------
# Previous sidecar discovery
# ---------------------------------------------------------------------------

def find_previous_sidecar(dump_dir: Path, current_version: str) -> dict | None:
    """Scan dump_dir for mod-references.json files from versions != current_version.

    Takes the most recent version (sorted descending by version string).

    Args:
        dump_dir:        Path to the dump/ directory (contains versioned subdirs).
        current_version: Current game version string (e.g. '1.000.48286').

    Returns:
        Loaded sidecar dict, or None if no previous sidecar exists.
    """
    dump_dir = Path(dump_dir)
    candidates: list[tuple[str, Path]] = []

    for child in dump_dir.iterdir():
        if not child.is_dir():
            continue
        version = child.name
        if version == current_version:
            continue
        sidecar_path = child / 'mod-references.json'
        if sidecar_path.exists():
            candidates.append((version, sidecar_path))

    if not candidates:
        return None

    # Sort by version string descending (lexicographic works for 1.000.NNNNN style).
    candidates.sort(key=lambda t: t[0], reverse=True)
    _, best_path = candidates[0]
    return load_sidecar(best_path)
