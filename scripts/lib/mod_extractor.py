"""Mod source reference extractor.

Scans mods/src/**/*.{cc,h} and extracts all string-based IL2CPP game references.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .models import ModReference, RefType


TargetPlatform = str | None


@dataclass(slots=True)
class ExtractionReport:
    """References plus non-fatal extraction diagnostics."""

    refs: list[ModReference]
    target_platform: str
    platform_skipped_refs: list[ModReference] = field(default_factory=list)
    tool_limitations: list[str] = field(default_factory=list)

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# il2cpp_get_class_helper("Assembly", "Namespace", "ClassName")
# Capture just the three string args; variable assignment is handled separately.
_RE_CLASS_HELPER_BARE = re.compile(
    r'il2cpp_get_class_helper\s*\(\s*'
    r'"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]+)"\s*\)',
)

# Variable assignment of il2cpp_get_class_helper result (multi-line aware).
# Covers:
#   static auto varname = il2cpp_get_class_helper(...)
#   auto varname = il2cpp_get_class_helper(...)
#   if (auto varname = il2cpp_get_class_helper(...))
#   if (auto varname = il2cpp_get_class_helper(...); ...)
# Uses re.DOTALL so whitespace/newline can appear between = and il2cpp_...
_RE_CLASS_HELPER_ASSIGN = re.compile(
    r'\b(?:auto|IL2CppClassHelper)\s+(\w+)\s*=\s*'
    r'il2cpp_get_class_helper\s*\(\s*'
    r'"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]+)"\s*\)',
    re.DOTALL,
)

# GetMethod / GetMethodInfo (with optional template params)
_RE_GET_METHOD = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetMethod(?:Info)?\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"'
    r'(?:\s*,\s*(\d+))?',
)

# GetMethodSpecial<T>("Name", ...) — first string arg is method name
_RE_GET_METHOD_SPECIAL = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetMethodSpecial\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"',
)

# GetMethodSpecial2<T>(obj, "Name")
_RE_GET_METHOD_SPECIAL2 = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetMethodSpecial2\s*(?:<[^>]*>)?\s*\(\s*[^,]+,\s*"([^"]+)"',
)

# GetMethodInfoSpecial("Name", ...)
_RE_GET_METHOD_INFO_SPECIAL = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetMethodInfoSpecial\s*\(\s*"([^"]+)"',
)

# GetVirtualMethod<T>("Name") / GetVirtualMethod<T>("Name", N)
_RE_GET_VIRTUAL_METHOD = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetVirtualMethod\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"'
    r'(?:\s*,\s*(\d+))?',
)

# GetInvokeMethod<T>("Name") / GetInvokeMethod<T>("Name", N)
_RE_GET_INVOKE_METHOD = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetInvokeMethod\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"'
    r'(?:\s*,\s*(\d+))?',
)

# GetField / GetStaticField
_RE_GET_FIELD = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'Get(?:Static)?Field\s*\(\s*"([^"]+)"',
)

# GetProperty
_RE_GET_PROPERTY = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetProperty\s*\(\s*"([^"]+)"',
)

# GetNestedType
_RE_GET_NESTED_TYPE = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetNestedType\s*\(\s*"([^"]+)"',
)

# GetParent
_RE_GET_PARENT = re.compile(
    r'(\w+|get_class_helper\s*\(\s*\))\s*\.\s*'
    r'GetParent\s*\(\s*"([^"]+)"',
)

# il2cpp_resolve_icall_typed<T>("Full::Signature(Args)")
_RE_ICALL = re.compile(
    r'il2cpp_resolve_icall_typed\s*(?:<[^>]*>)?\s*\(\s*"([^"]+)"',
)


def _source_path(filepath: Path, source_root: Path) -> str:
    """Return project-relative path, e.g. mods/src/patches/parts/zoom.cc."""
    try:
        return str(filepath.relative_to(source_root.parent.parent))
    except ValueError:
        return str(filepath)


def _strip_line(line: str) -> str:
    """Remove single-line C++ comments from a line."""
    result = []
    in_string = False
    i = 0
    while i < len(line):
        c = line[i]
        if in_string:
            if c == '\\':
                result.append(c)
                i += 1
                if i < len(line):
                    result.append(line[i])
            elif c == '"':
                result.append(c)
                in_string = False
            else:
                result.append(c)
        else:
            if c == '"':
                result.append(c)
                in_string = True
            elif c == '/' and i + 1 < len(line) and line[i + 1] == '/':
                break  # rest is comment
            else:
                result.append(c)
        i += 1
    return ''.join(result)


def _normalize_target_platform(target_platform: TargetPlatform) -> str:
    """Return one of macos/windows/all from a CLI/API target value."""
    if target_platform in (None, "", "auto"):
        return "windows" if sys.platform == "win32" else "macos"
    if target_platform not in ("macos", "windows", "all"):
        raise ValueError(f"Unsupported target platform: {target_platform!r}")
    return target_platform


def _is_platform_condition(expr: str) -> bool:
    normalized = re.sub(r'\s+', '', expr)
    return normalized in (
        '_WIN32',
        'defined(_WIN32)',
        '!_WIN32',
        '!defined(_WIN32)',
    )


def _eval_preprocessor_condition(expr: str, target_platform: TargetPlatform = None) -> bool:
    """Evaluate the small subset of C preprocessor conditions used here."""
    normalized = re.sub(r'\s+', '', expr)
    platform = _normalize_target_platform(target_platform)
    is_win32 = platform == 'windows'

    if normalized == '0':
        return False
    if normalized == '1':
        return True
    if normalized in ('_WIN32', 'defined(_WIN32)'):
        return is_win32
    if normalized in ('!_WIN32', '!defined(_WIN32)'):
        return not is_win32

    # Unknown conditions are treated as active so validation stays conservative.
    return True


def _filter_inactive_preprocessor_lines(lines: list[str], target_platform: TargetPlatform = None) -> list[str]:
    """Blank lines hidden behind simple inactive #if/#else/#endif branches.

    The extractor is not a full preprocessor, but it must ignore common
    platform guards such as ``#if _WIN32`` while validating a macOS dump.
    ``target_platform='all'`` keeps both sides of platform guards active.
    Blank inactive lines preserve source line numbers for diagnostics.
    """
    target = _normalize_target_platform(target_platform)
    active_lines: list[str] = []
    # parent_active, current_active, branch_taken, keep_all_platform_branches
    stack: list[tuple[bool, bool, bool, bool]] = []
    current_active = True

    for line in lines:
        stripped = line.strip()

        if stripped.startswith('#if '):
            parent_active = current_active
            expr = stripped[3:].strip()
            keep_all_platform_branches = target == "all" and _is_platform_condition(expr)
            condition_active = True if keep_all_platform_branches else _eval_preprocessor_condition(expr, target)
            current_active = parent_active and condition_active
            stack.append((parent_active, current_active, current_active, keep_all_platform_branches))
            active_lines.append('')
            continue

        if stripped.startswith('#ifdef '):
            parent_active = current_active
            expr = f"defined({stripped[7:].strip()})"
            keep_all_platform_branches = target == "all" and _is_platform_condition(expr)
            condition_active = True if keep_all_platform_branches else _eval_preprocessor_condition(expr, target)
            current_active = parent_active and condition_active
            stack.append((parent_active, current_active, current_active, keep_all_platform_branches))
            active_lines.append('')
            continue

        if stripped.startswith('#ifndef '):
            parent_active = current_active
            expr = f"defined({stripped[8:].strip()})"
            keep_all_platform_branches = target == "all" and _is_platform_condition(expr)
            condition_active = True if keep_all_platform_branches else not _eval_preprocessor_condition(expr, target)
            current_active = parent_active and condition_active
            stack.append((parent_active, current_active, current_active, keep_all_platform_branches))
            active_lines.append('')
            continue

        if stripped.startswith('#elif '):
            if stack:
                parent_active, _, branch_taken, keep_all_platform_branches = stack.pop()
                expr = stripped[5:].strip()
                if keep_all_platform_branches and _is_platform_condition(expr):
                    current_active = parent_active
                    branch_taken = False
                else:
                    condition_active = _eval_preprocessor_condition(expr, target)
                    current_active = parent_active and not branch_taken and condition_active
                stack.append((parent_active, current_active, branch_taken or current_active, keep_all_platform_branches))
            active_lines.append('')
            continue

        if stripped == '#else':
            if stack:
                parent_active, _, branch_taken, keep_all_platform_branches = stack.pop()
                if keep_all_platform_branches:
                    current_active = parent_active
                    stack.append((parent_active, current_active, False, keep_all_platform_branches))
                else:
                    current_active = parent_active and not branch_taken
                    stack.append((parent_active, current_active, True, keep_all_platform_branches))
            active_lines.append('')
            continue

        if stripped == '#endif':
            if stack:
                parent_active, _, _, _ = stack.pop()
                current_active = parent_active
            active_lines.append('')
            continue

        active_lines.append(line if current_active else '')

    return active_lines


def _normalize_object(obj: str) -> str:
    """Normalize 'get_class_helper()' and similar variants to a canonical form."""
    s = obj.strip()
    if re.match(r'get_class_helper\s*\(\s*\)', s):
        return 'get_class_helper()'
    return s


def extract_references(source_root: Path, *, target_platform: TargetPlatform = None) -> list[ModReference]:
    """Scan all .cc and .h files under source_root and extract game references.

    Args:
        source_root: Path to mods/src directory.
        target_platform: auto/None, macos, windows, or all.

    Returns:
        List of ModReference instances.
    """
    return extract_references_with_report(source_root, target_platform=target_platform).refs


def extract_references_with_report(source_root: Path, *, target_platform: TargetPlatform = None) -> ExtractionReport:
    """Extract references and report refs skipped by platform selection."""
    target = _normalize_target_platform(target_platform)
    refs = _extract_references_for_platform(source_root, target_platform=target)
    skipped_refs: list[ModReference] = []

    if target in ("macos", "windows"):
        skipped_target = "windows" if target == "macos" else "macos"
        all_refs = _extract_references_for_platform(source_root, target_platform=skipped_target)
        active_keys = {_ref_identity(r) for r in refs}
        skipped_refs = [r for r in all_refs if _ref_identity(r) not in active_keys]

    limitations = [
        f"Unresolved class helper for {r.source_file}:{r.source_line}"
        for r in refs
        if r.type in (RefType.METHOD, RefType.FIELD, RefType.PROPERTY, RefType.NESTED_TYPE, RefType.PARENT_CLASS)
        and r.class_name is None
    ]
    return ExtractionReport(
        refs=refs,
        target_platform=target,
        platform_skipped_refs=skipped_refs,
        tool_limitations=limitations,
    )


def _extract_references_for_platform(source_root: Path, *, target_platform: str) -> list[ModReference]:
    """Extract references for a normalized target platform."""
    refs: list[ModReference] = []

    files: list[Path] = []
    for ext in ('cc', 'h'):
        files.extend(source_root.rglob(f'*.{ext}'))
    files.sort()

    for filepath in files:
        refs.extend(_extract_from_file(filepath, source_root, target_platform=target_platform))

    return refs


def _ref_identity(ref: ModReference) -> tuple:
    """Stable identity for comparing active refs against all-platform refs."""
    return (
        ref.type,
        ref.source_file,
        ref.source_line,
        ref.assembly,
        ref.namespace,
        ref.class_name,
        ref.member_name,
        ref.arg_count,
        ref.parent_name,
        ref.icall_signature,
    )


def _build_scope_map(
    lines: list[str],
) -> dict[int, tuple[str, str, str]]:
    """Build line → (assembly, namespace, class_name) map using C++ scope tracking.

    Parses brace scopes and associates each line with the innermost scope that
    defines an ``il2cpp_get_class_helper`` call.

    Returns a dict mapping line_number → class tuple for lines that are inside
    a scope with a class helper.
    """
    # Step 1: find all il2cpp_get_class_helper calls with line numbers
    helpers: dict[int, tuple[str, str, str]] = {}
    for lineno, line in enumerate(lines, start=1):
        for m in _RE_CLASS_HELPER_BARE.finditer(line):
            helpers[lineno] = (m.group(1), m.group(2), m.group(3))

    # Step 2: build all brace scope ranges.
    scopes: list[tuple[int, int]] = []
    scope_stack: list[int] = []

    for lineno, line in enumerate(lines, start=1):
        stripped = _strip_line(line)
        for ch in stripped:
            if ch == '{':
                scope_stack.append(lineno)
            elif ch == '}':
                if scope_stack:
                    scopes.append((scope_stack.pop(), lineno))

    # Step 3: bind each helper to its innermost containing scope.
    scope_to_class: dict[tuple[int, int], tuple[str, str, str]] = {}
    for helper_line, cls in helpers.items():
        candidates = sorted(
            [scope for scope in scopes if scope[0] <= helper_line <= scope[1]],
            key=lambda scope: scope[1] - scope[0],
        )
        if candidates:
            scope = candidates[0]
            # Helpers declared inside a C++ static get_class_helper() method
            # describe the surrounding wrapper class, not the method body.
            if len(candidates) > 1:
                start, _ = scope
                context = '\n'.join(lines[max(0, start - 3):helper_line])
                if 'get_class_helper' in context:
                    scope = candidates[1]
            scope_to_class[scope] = cls

    # Step 4: for each line, pick the innermost class-bearing scope.
    line_to_class: dict[int, tuple[str, str, str]] = {}
    for lineno in range(1, len(lines) + 1):
        candidates = [
            (scope, cls)
            for scope, cls in scope_to_class.items()
            if scope[0] <= lineno <= scope[1]
        ]
        if candidates:
            _, cls = min(candidates, key=lambda item: item[0][1] - item[0][0])
            line_to_class[lineno] = cls

    return line_to_class


def _build_var_map(
    text: str,
    lines: list[str],
) -> tuple[dict[str, tuple[str, str, str]], dict[int, tuple[str, str, str]]]:
    """Build variable → (assembly, namespace, class_name) map from full file text.

    Returns (var_to_class, scope_map) where scope_map maps each line number
    to the class helper defined in the same C++ scope.
    """
    var_to_class: dict[str, tuple[str, str, str]] = {}

    # Build scope-aware line → class map
    scope_map = _build_scope_map(lines)

    # Find all variable assignments (multi-line OK due to re.DOTALL)
    for m in _RE_CLASS_HELPER_ASSIGN.finditer(text):
        varname = m.group(1)
        cls = (m.group(2), m.group(3), m.group(4))
        var_to_class[varname] = cls

    return var_to_class, scope_map


def _extract_from_file(filepath: Path, source_root: Path, *, target_platform: TargetPlatform = None) -> list[ModReference]:
    """Extract all references from a single file."""
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    source_file = _source_path(filepath, source_root)
    lines = _filter_inactive_preprocessor_lines(text.splitlines(), target_platform=target_platform)
    text = '\n'.join(lines)

    # Pass 1: build variable → class map from full text
    var_to_class, scope_map = _build_var_map(text, lines)

    # Pass 2: extract references line by line
    refs: list[ModReference] = []

    for lineno, raw_line in enumerate(lines, start=1):
        line = _strip_line(raw_line)

        # IL2CPP class helper → CLASS ref
        for m in _RE_CLASS_HELPER_BARE.finditer(line):
            refs.append(ModReference(
                type=RefType.CLASS,
                source_file=source_file,
                source_line=lineno,
                assembly=m.group(1),
                namespace=m.group(2),
                class_name=m.group(3),
            ))

        # ICALL
        for m in _RE_ICALL.finditer(line):
            refs.append(ModReference(
                type=RefType.ICALL,
                source_file=source_file,
                source_line=lineno,
                icall_signature=m.group(1),
            ))

        # GetMethod / GetMethodInfo
        for m in _RE_GET_METHOD.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            arg_count = int(m.group(3)) if m.group(3) else None
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetMethodSpecial
        for m in _RE_GET_METHOD_SPECIAL.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetMethodSpecial2
        for m in _RE_GET_METHOD_SPECIAL2.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetMethodInfoSpecial
        for m in _RE_GET_METHOD_INFO_SPECIAL.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetVirtualMethod
        for m in _RE_GET_VIRTUAL_METHOD.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            arg_count = int(m.group(3)) if m.group(3) else None
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetInvokeMethod
        for m in _RE_GET_INVOKE_METHOD.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            arg_count = int(m.group(3)) if m.group(3) else None
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
                optional_probe=_looks_optional_probe(lines, lineno, method_name),
            ))

        # GetField / GetStaticField
        for m in _RE_GET_FIELD.finditer(line):
            obj = _normalize_object(m.group(1))
            field_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.FIELD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=field_name,
            ))

        # GetProperty
        for m in _RE_GET_PROPERTY.finditer(line):
            obj = _normalize_object(m.group(1))
            prop_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.PROPERTY,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=prop_name,
            ))

        # GetNestedType
        for m in _RE_GET_NESTED_TYPE.finditer(line):
            obj = _normalize_object(m.group(1))
            nested_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.NESTED_TYPE,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=nested_name,
            ))

        # GetParent
        for m in _RE_GET_PARENT.finditer(line):
            obj = _normalize_object(m.group(1))
            parent_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, scope_map, lineno)
            refs.append(ModReference(
                type=RefType.PARENT_CLASS,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                parent_name=parent_name,
            ))

    return refs


def _resolve_class(
    obj: str,
    var_to_class: dict[str, tuple[str, str, str]],
    scope_map: dict[int, tuple[str, str, str]],
    current_line: int,
) -> tuple[str, str, str] | None:
    """Resolve an object expression to (assembly, namespace, class_name).

    - 'get_class_helper()' → class helper in the same C++ scope
    - known variable name → var_to_class[name]
    - otherwise → None
    """
    if obj == 'get_class_helper()':
        return scope_map.get(current_line)
    return var_to_class.get(obj)


def _looks_optional_probe(lines: list[str], lineno: int, member_name: str) -> bool:
    """Return True when nearby source already handles a missing member."""
    start = max(0, lineno - 1)
    end = min(len(lines), lineno + 6)
    window = '\n'.join(lines[start:end])
    if 'ErrorMsg::MissingMethod' in window:
        return True
    if member_name and re.search(rf'\b{re.escape(member_name)}\b', window):
        return 'nullptr' in window or 'NULL' in window
    return False
