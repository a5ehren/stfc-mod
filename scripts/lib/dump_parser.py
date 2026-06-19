"""Parser for Il2CppDumper's dump.cs output.

Parses the ~48MB dump.cs file into a structured DumpIndex with three
lookup indexes for class/member lookups by qualified name, class name,
and (namespace, class) pair.

Performance: line-by-line streaming, no full-file reads.
"""

from __future__ import annotations

import hashlib
import pickle
import re
from pathlib import Path

from .models import DumpClass, DumpIndex


_CACHE_VERSION = 1
_CACHE_SUFFIX = ".dump-index-cache.pkl"


# ---------------------------------------------------------------------------
# Pre-compiled regexes
# ---------------------------------------------------------------------------

# Image manifest at top: "// Image N: AssemblyName.dll - offset"
_RE_IMAGE = re.compile(r'^// Image \d+: (.+?)(?:\.dll)? - (\d+)$')

# Namespace line: "// Namespace: Some.Name" or "// Namespace:"
_RE_NAMESPACE = re.compile(r'^// Namespace:(.*)$')

# TypeDefIndex comment inside class declaration line
_RE_TYPEDEF_INDEX = re.compile(r'// TypeDefIndex: (\d+)')

# Class declaration line (at column 0, not indented).
# Matches: [modifiers] (class|struct|interface|enum) ClassName[<T,...>] [: base] // TypeDefIndex: N
# Modifiers: public, private, protected, internal, sealed, abstract, static, partial, readonly
_MODIFIERS = r'(?:(?:public|private|protected|internal|sealed|abstract|static|partial|readonly)\s+)*'
_RE_CLASS_DECL = re.compile(
    r'^' + _MODIFIERS + r'(?:class|struct|interface|enum)\s+'
    r'(.+?)'                         # class name, including generic parameters with spaces
    r'(?:\s*:\s*([^/{]*?))?'          # optional : base list (captured)
    r'\s*(?:\s*//\s*TypeDefIndex:\s*(\d+))?$'
)

# Field line: indented, ends with // 0xNN or = value;
# We just need to extract the identifier name from a member line.
_RE_FIELD = re.compile(
    r'^\t'
    r'(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|const|override|virtual|new|volatile|extern)\s+)*'
    r'(?:\[[^\]]*\]\s*)*'  # attributes inline (shouldn't normally appear, but be safe)
    r'(?:\S+\s+)'          # type (could be complex, just skip to name)
    r'([A-Za-z_<>@][A-Za-z0-9_<>@.,\[\]*?]*)'  # field name
    r'\s*(?:;|=|//)'
)

# Property line: indented, ends with { get; } or { get; set; } etc.
_RE_PROPERTY = re.compile(
    r'^\t'
    r'(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|override|virtual|new|extern)\s+)*'
    r'\S.*?\s+'          # type
    r'([A-Za-z_][A-Za-z0-9_.]*)'  # property name (can be qualified like Interface.Prop)
    r'\s*\{[^}]*(?:get|set)[^}]*\}'  # accessor block
)

# Method line: indented, ends with { } (empty body)
_RE_METHOD = re.compile(
    r'^\t'
    r'(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|override|virtual|new|extern|unsafe|async)\s+)*'
    r'\S.*?\s+'          # return type
    r'([A-Za-z_.][A-Za-z0-9_.<>@]*)'  # method name (may include explicit interface prefix)
    r'\s*\('             # opening paren
    r'([^)]*)'           # parameters
    r'\)'
    r'[^{]*\{\s*\}'      # empty body
)

# RVA comment line (precedes method declaration)
_RE_RVA = re.compile(r'^\t\s*//\s*RVA:')

# Attribute line: starts with \t[ or [ at column 0 (before class decl)
_RE_ATTRIBUTE = re.compile(r'^[\t\s]*\[')

# Section header comment inside class body
_RE_SECTION = re.compile(r'^\t// (?:Fields|Properties|Methods|Nested Types)')

# Generic type param count from C# syntax: Foo<T, U> → Foo`2
def _convert_generic_name(name: str) -> str:
    """Convert C# generic syntax Foo<T,U> to backtick-arity Foo`2."""
    m = re.match(r'^([^<]+)<(.+)>$', name, re.DOTALL)
    if not m:
        return name
    base = m.group(1)
    params = m.group(2)
    # Count top-level commas (not nested inside <>) to get arity
    depth = 0
    count = 1
    for ch in params:
        if ch == '<':
            depth += 1
        elif ch == '>':
            depth -= 1
        elif ch == ',' and depth == 0:
            count += 1
    return f'{base}`{count}'


def _parse_base_list(bases_str: str) -> list[str]:
    """Parse a comma-separated list of base classes/interfaces, stripping generics.

    Input:  'CanvasContext, IFleetsContext, IReactiveObservable'
    Output: ['CanvasContext', 'IFleetsContext', 'IReactiveObservable']

    Handles generic types like 'Widget<BattleTargetData>' → 'Widget`1'
    and nested generics. Strips 'where' clauses.
    """
    # Remove anything after 'where' (generic constraints)
    where_idx = bases_str.find(' where ')
    if where_idx >= 0:
        bases_str = bases_str[:where_idx]

    # Split on commas, respecting generic nesting
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in bases_str:
        if ch in '<(':
            depth += 1
            current.append(ch)
        elif ch in '>)':
            depth -= 1
            current.append(ch)
        elif ch == ',' and depth == 0:
            parts.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    if current:
        parts.append(''.join(current).strip())

    result: list[str] = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        # Convert generic syntax to backtick-arity
        converted = _convert_generic_name(part)
        result.append(converted)
    return result


def _parse_image_manifest(line: str) -> tuple[str, int] | None:
    """Parse '// Image N: AssemblyName.dll - offset' lines."""
    m = _RE_IMAGE.match(line)
    if m:
        return m.group(1), int(m.group(2))
    return None


def _dump_hash(dump_path: Path) -> str:
    """Return a SHA-256 hash for cache invalidation."""
    digest = hashlib.sha256()
    with open(dump_path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _dump_cache_path(dump_path: Path) -> Path:
    """Return the on-disk cache path for *dump_path*."""
    return dump_path.with_name(f"{dump_path.name}{_CACHE_SUFFIX}")


def _dump_cache_key(dump_path: Path) -> dict[str, object]:
    """Build a cache key from path identity, mtime, size, and content hash."""
    stat = dump_path.stat()
    return {
        "cache_version": _CACHE_VERSION,
        "name": dump_path.name,
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
        "sha256": _dump_hash(dump_path),
    }


def parse_dump_cached(dump_path: Path) -> DumpIndex:
    """Parse *dump_path*, reusing an on-disk DumpIndex cache when valid."""
    dump_path = Path(dump_path)
    cache_path = _dump_cache_path(dump_path)
    key = _dump_cache_key(dump_path)

    try:
        with open(cache_path, "rb") as fh:
            payload = pickle.load(fh)
        if payload.get("key") == key and isinstance(payload.get("index"), DumpIndex):
            return payload["index"]
    except (OSError, EOFError, pickle.PickleError, AttributeError):
        pass

    index = parse_dump(dump_path)
    try:
        with open(cache_path, "wb") as fh:
            pickle.dump({"key": key, "index": index}, fh, protocol=pickle.HIGHEST_PROTOCOL)
    except OSError:
        pass
    return index


def _assembly_for_typedef(type_def_index: int, ranges: list[tuple[int, str]]) -> str:
    """Binary-search sorted ranges to find which assembly owns this TypeDefIndex."""
    lo, hi = 0, len(ranges) - 1
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if ranges[mid][0] <= type_def_index:
            lo = mid
        else:
            hi = mid - 1
    return ranges[lo][1]


def _extract_field_name_and_type(line: str) -> tuple[str, str] | None:
    """Extract (field_name, cs_type) from an indented field line.

    Example: ``\tprivate float _minimum; // 0x10`` → ``('_minimum', 'float')``
    The cs_type is the last type token before the field name (accounting for
    modifiers being stripped first).
    """
    stripped = line.rstrip()
    # Remove trailing comment
    no_comment = re.sub(r'\s*//.*$', '', stripped)
    no_comment = no_comment.rstrip(';').strip()
    # Strip leading modifiers
    no_modifiers = re.sub(
        r'^(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|const|override|virtual|new|volatile|extern)\s+)+',
        '', no_comment
    )
    # Remaining tokens: first is the type, last is the field name
    parts = no_modifiers.split()
    if len(parts) >= 2:
        field_name = parts[-1]
        cs_type = parts[0]
        # Validate field name
        if re.match(r'^[A-Za-z_@<][A-Za-z0-9_<>@.]*$', field_name):
            return field_name, cs_type
    return None


def _extract_property_name(line: str) -> str | None:
    """Extract property name from an indented property line."""
    # e.g.: "\tpublic float Distance { get; }"
    m = re.match(
        r'^\t(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|override|virtual|new|extern)\s+)*'
        r'(?:\S+\s+)+'      # one or more type tokens
        r'([A-Za-z_][A-Za-z0-9_.]*)'
        r'\s*\{',
        line
    )
    if m:
        return m.group(1)
    return None


def _extract_method_name_and_sig(line: str) -> tuple[str, str] | None:
    """Extract (method_name, full_signature) from an indented method line.

    The full_signature includes modifiers and return type but omits the trailing
    empty body ``{ }`` and any trailing comment.
    Example: ``\tprivate void SetDepth(NodeDepth value) { }``
    → ``('SetDepth', 'private void SetDepth(NodeDepth value)')``
    """
    stripped = line.strip()
    # Must end with { } (empty body) — possibly with trailing comment
    if not re.search(r'\{\s*\}\s*(?://.*)?$', stripped):
        return None
    # Remove trailing { } and optional trailing comment, keep everything before
    decl = re.sub(r'\s*\{\s*\}\s*(?://.*)?$', '', stripped).rstrip()
    # Extract method name from the declaration
    m = re.match(
        r'(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|override|virtual|new|extern|unsafe|async)\s+)*'
        r'(?:\S+\s+)+'   # return type (one or more tokens)
        r'([A-Za-z_.][A-Za-z0-9_.<>\[\]@`]*)'  # method name
        r'\s*\(',        # opening paren
        stripped
    )
    if m:
        name = m.group(1)
        return name, decl
    return None


# ---------------------------------------------------------------------------
# Main parser
# ---------------------------------------------------------------------------

def parse_dump(dump_path: Path) -> DumpIndex:
    """Parse dump.cs and return a fully populated DumpIndex.

    Uses a line-by-line streaming state machine. ~48MB file parsed in a
    single pass without loading into memory.
    """
    index = DumpIndex()

    # Pass 1: collect the assembly manifest (first ~200 lines)
    # ranges: sorted list of (start_typedef_index, assembly_name)
    ranges: list[tuple[int, str]] = []
    with open(dump_path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            line = line.rstrip('\n').rstrip('\r')
            result = _parse_image_manifest(line)
            if result:
                asm_name, start_idx = result
                ranges.append((start_idx, asm_name))
            elif line and not line.startswith('//') and not line.startswith(' '):
                # Once we hit non-comment, non-blank content, manifest is done
                break

    if not ranges:
        raise ValueError(f"No assembly manifest found in {dump_path}")

    # Sort by start index (should already be sorted, but be safe)
    ranges.sort(key=lambda r: r[0])

    # Pass 2: parse class declarations and members
    current_namespace: str = ''
    current_dc: DumpClass | None = None
    in_generic_comment = False  # inside /* GenericInstMethod: */ block
    pending_attributes: list[str] = []  # attribute lines pending before class decl
    # Deferred nested registrations: list of (assembly, dotted_name, nested_part)
    # for when the parent class was not yet seen at registration time
    deferred_nested: list[tuple[str, str, str]] = []

    with open(dump_path, encoding='utf-8', errors='replace') as fh:
        for raw_line in fh:
            line = raw_line.rstrip('\n').rstrip('\r')

            # --- Track GenericInstMethod comment blocks (skip content inside) ---
            if in_generic_comment:
                if line.strip().endswith('*/') or line.strip() == '*/':
                    in_generic_comment = False
                continue
            if line.strip().startswith('/*'):
                in_generic_comment = True
                continue

            # --- Assembly manifest lines (already processed above, skip) ---
            if line.startswith('// Image '):
                continue

            # --- Namespace line ---
            m_ns = _RE_NAMESPACE.match(line)
            if m_ns:
                current_namespace = m_ns.group(1).strip()
                pending_attributes.clear()
                continue

            # --- End of class: closing brace at column 0 ---
            if line == '}':
                current_dc = None
                pending_attributes.clear()
                continue

            # --- Empty line ---
            if not line:
                continue

            # --- Attribute lines (at col 0, before class decl) ---
            if not line.startswith('\t') and line.startswith('['):
                pending_attributes.append(line)
                continue

            # --- RVA comment line inside class (precedes method line) ---
            if _RE_RVA.match(line):
                continue  # just a comment, method follows

            # --- Section headers inside class body ---
            if _RE_SECTION.match(line):
                continue

            # --- Generic inline comment (compiler-generated attribute) ---
            if line.startswith('\t[') or (not line.startswith('\t') and line.startswith('[') and current_dc is None):
                # Inside class body: attribute on a member, skip it
                if current_dc is not None and line.startswith('\t['):
                    continue
                # Before class decl at col 0: accumulated above
                continue

            # --- Class declaration at column 0 ---
            if not line.startswith('\t') and not line.startswith('//') and not line.startswith('{') and not line.startswith('}'):
                # Try to match a class/struct/interface/enum declaration
                m_cls = _RE_CLASS_DECL.match(line)
                if m_cls:
                    raw_name = m_cls.group(1).strip()
                    bases_str = m_cls.group(2)
                    typedef_str = m_cls.group(3)
                    typedef_idx = int(typedef_str) if typedef_str else -1

                    # Determine assembly from TypeDefIndex
                    if typedef_idx >= 0:
                        assembly = _assembly_for_typedef(typedef_idx, ranges)
                    else:
                        # Fallback: unknown
                        assembly = 'Unknown'

                    # Convert generic syntax to backtick-arity
                    class_name_converted = _convert_generic_name(raw_name)

                    # Parse parent/interface names from the base list
                    parent_names: list[str] = []
                    if bases_str:
                        parent_names = _parse_base_list(bases_str.strip())

                    # Create the DumpClass
                    dc = DumpClass(
                        assembly=assembly,
                        namespace=current_namespace,
                        name=class_name_converted,
                        parents=parent_names,
                    )
                    current_dc = dc

                    # Register in indexes
                    _register_class(index, dc)

                    # Handle nested types (dotted names like FleetPlayerData.CanRepairRequirement)
                    if '.' in class_name_converted:
                        registered = _register_nested_type(index, dc, class_name_converted)
                        if not registered:
                            # Parent not yet seen; defer
                            first_dot = class_name_converted.index('.')
                            parent_name = class_name_converted[:first_dot]
                            nested_part = class_name_converted[first_dot + 1:]
                            deferred_nested.append((assembly, parent_name, nested_part))

                    pending_attributes.clear()
                    continue

            # --- Member lines (inside class body) ---
            if current_dc is None:
                continue

            if line.startswith('\t'):
                stripped = line[1:]  # remove one level of indentation

                # Skip section comments and attributes
                if stripped.startswith('//'):
                    continue
                if stripped.startswith('['):
                    continue
                if stripped.startswith('{') or stripped.startswith('}'):
                    continue
                if not stripped or stripped.isspace():
                    continue

                # Detect what kind of member this is based on content
                # Properties: have { get; } or { set; } accessor blocks
                if re.search(r'\{\s*(?:get|set)', stripped):
                    prop_name = _extract_property_name(line)
                    if prop_name and prop_name not in current_dc.properties:
                        current_dc.properties.append(prop_name)
                    continue

                # Methods: end with { } (empty body)
                if re.search(r'\{\s*\}\s*(?://.*)?$', stripped):
                    result = _extract_method_name_and_sig(line)
                    if result:
                        name, sig = result
                        if name not in current_dc.methods:
                            current_dc.methods[name] = []
                        current_dc.methods[name].append(sig)
                    continue

                # Fields: end with ; or // offset comment, or = value;
                # (after filtering out properties and methods above)
                field_result = _extract_field_name_and_type(line)
                if field_result and field_result[0] not in current_dc.fields:
                    field_name, cs_type = field_result
                    current_dc.fields[field_name] = cs_type

    # Resolve deferred nested type registrations (parent declared after nested types)
    for assembly, parent_name, nested_part in deferred_nested:
        candidates = index.by_class_name.get(parent_name, [])
        for candidate in candidates:
            if candidate.assembly == assembly:
                if nested_part not in candidate.nested_types:
                    candidate.nested_types.append(nested_part)
                break

    return index


def _register_class(index: DumpIndex, dc: DumpClass) -> None:
    """Add a DumpClass to all three indexes."""
    key = (dc.assembly, dc.namespace, dc.name)
    # Qualified name: overwrite if duplicate (last wins — shouldn't matter)
    index.by_qualified_name[key] = dc

    # Class name only
    if dc.name not in index.by_class_name:
        index.by_class_name[dc.name] = []
    index.by_class_name[dc.name].append(dc)

    # (namespace, class_name)
    ns_key = (dc.namespace, dc.name)
    if ns_key not in index.by_ns_class:
        index.by_ns_class[ns_key] = []
    index.by_ns_class[ns_key].append(dc)


def _register_nested_type(index: DumpIndex, dc: DumpClass, dotted_name: str) -> bool:
    """For a class with a dotted name (e.g. Parent.Nested), register nested type on parent.

    The nested class may have an empty namespace while the parent has a real namespace,
    so we search by assembly + class name rather than requiring namespace to match.

    Returns True if parent was found and registered, False if parent not yet in index.
    """
    first_dot = dotted_name.index('.')
    parent_name = dotted_name[:first_dot]
    nested_part = dotted_name[first_dot + 1:]

    # First try: exact (assembly, namespace, parent_name) match
    parent_key = (dc.assembly, dc.namespace, parent_name)
    parent_dc = index.by_qualified_name.get(parent_key)
    if parent_dc is not None:
        if nested_part not in parent_dc.nested_types:
            parent_dc.nested_types.append(nested_part)
        return True

    # Fallback: search by_class_name within same assembly (namespace may differ for nested types)
    candidates = index.by_class_name.get(parent_name, [])
    for candidate in candidates:
        if candidate.assembly == dc.assembly:
            if nested_part not in candidate.nested_types:
                candidate.nested_types.append(nested_part)
            return True

    # Parent not yet seen — caller should defer registration
    return False
