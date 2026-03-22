"""Mod source reference extractor.

Scans mods/src/**/*.{cc,h} and extracts all string-based IL2CPP game references.
"""

from __future__ import annotations

import re
from pathlib import Path

from .models import ModReference, RefType

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


def _normalize_object(obj: str) -> str:
    """Normalize 'get_class_helper()' and similar variants to a canonical form."""
    s = obj.strip()
    if re.match(r'get_class_helper\s*\(\s*\)', s):
        return 'get_class_helper()'
    return s


def extract_references(source_root: Path) -> list[ModReference]:
    """Scan all .cc and .h files under source_root and extract game references.

    Args:
        source_root: Path to mods/src directory.

    Returns:
        List of ModReference instances.
    """
    refs: list[ModReference] = []

    files: list[Path] = []
    for ext in ('cc', 'h'):
        files.extend(source_root.rglob(f'*.{ext}'))
    files.sort()

    for filepath in files:
        refs.extend(_extract_from_file(filepath, source_root))

    return refs


def _build_var_map(text: str) -> tuple[dict[str, tuple[str, str, str]], tuple[str, str, str] | None]:
    """Build variable → (assembly, namespace, class_name) map from full file text.

    Returns (var_to_class, file_class) where file_class is the first
    il2cpp_get_class_helper call found in the file.
    """
    var_to_class: dict[str, tuple[str, str, str]] = {}
    file_class: tuple[str, str, str] | None = None

    # Find the first il2cpp_get_class_helper call for file_class
    m0 = _RE_CLASS_HELPER_BARE.search(text)
    if m0:
        file_class = (m0.group(1), m0.group(2), m0.group(3))

    # Find all variable assignments (multi-line OK due to re.DOTALL)
    for m in _RE_CLASS_HELPER_ASSIGN.finditer(text):
        varname = m.group(1)
        cls = (m.group(2), m.group(3), m.group(4))
        var_to_class[varname] = cls

    return var_to_class, file_class


def _extract_from_file(filepath: Path, source_root: Path) -> list[ModReference]:
    """Extract all references from a single file."""
    try:
        text = filepath.read_text(encoding='utf-8', errors='replace')
    except OSError:
        return []

    source_file = _source_path(filepath, source_root)
    lines = text.splitlines()

    # Pass 1: build variable → class map from full text
    var_to_class, file_class = _build_var_map(text)

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
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
            ))

        # GetMethodSpecial
        for m in _RE_GET_METHOD_SPECIAL.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
            ))

        # GetMethodSpecial2
        for m in _RE_GET_METHOD_SPECIAL2.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
            ))

        # GetMethodInfoSpecial
        for m in _RE_GET_METHOD_INFO_SPECIAL.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
            ))

        # GetVirtualMethod
        for m in _RE_GET_VIRTUAL_METHOD.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            arg_count = int(m.group(3)) if m.group(3) else None
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
            ))

        # GetInvokeMethod
        for m in _RE_GET_INVOKE_METHOD.finditer(line):
            obj = _normalize_object(m.group(1))
            method_name = m.group(2)
            arg_count = int(m.group(3)) if m.group(3) else None
            cls = _resolve_class(obj, var_to_class, file_class)
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=source_file,
                source_line=lineno,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=method_name,
                arg_count=arg_count,
            ))

        # GetField / GetStaticField
        for m in _RE_GET_FIELD.finditer(line):
            obj = _normalize_object(m.group(1))
            field_name = m.group(2)
            cls = _resolve_class(obj, var_to_class, file_class)
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
            cls = _resolve_class(obj, var_to_class, file_class)
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
            cls = _resolve_class(obj, var_to_class, file_class)
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
            cls = _resolve_class(obj, var_to_class, file_class)
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
    file_class: tuple[str, str, str] | None,
) -> tuple[str, str, str] | None:
    """Resolve an object expression to (assembly, namespace, class_name).

    - 'get_class_helper()' → file_class
    - known variable name → var_to_class[name]
    - otherwise → None
    """
    if obj == 'get_class_helper()':
        return file_class
    return var_to_class.get(obj)
