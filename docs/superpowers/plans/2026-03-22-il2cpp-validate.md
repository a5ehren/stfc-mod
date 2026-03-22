# IL2CPP Mod Reference Validator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a cross-platform Python script that extracts all string-based game references from the mod source, parses Il2CppDumper output, and reports missing or changed references.

**Architecture:** Single Python script (`scripts/il2cpp-validate.py`) with no external dependencies. Imports version detection from Stage 1, shells out to Stage 1 for dumping. Three core subsystems: mod source extractor, dump.cs parser, and cross-reference validator.

**Tech Stack:** Python 3.12+ stdlib only (`pathlib`, `re`, `json`, `subprocess`, `argparse`, `dataclasses`)

**Spec:** `docs/superpowers/specs/2026-03-22-il2cpp-validate-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/il2cpp-validate.py` | Create | CLI, orchestration, report output |
| `scripts/lib/__init__.py` | Create | Empty package init |
| `scripts/lib/mod_extractor.py` | Create | Parse mod source to extract game references |
| `scripts/lib/dump_parser.py` | Create | Parse dump.cs into structured class/member lookup |
| `scripts/lib/validator.py` | Create | Cross-reference mod refs against dump, diff sidecars |

The script is split into focused modules because each subsystem (extraction, parsing, validation) has distinct regex sets and data structures. The main script orchestrates and handles CLI/reporting.

---

### Task 1: Data models and package scaffolding

**Files:**
- Create: `scripts/lib/__init__.py`
- Create: `scripts/lib/models.py`

Shared data models used by all modules. Define them first so subsequent tasks can reference concrete types.

- [ ] **Step 1: Create the package and models file**

Create `scripts/lib/__init__.py` (empty file).

Create `scripts/lib/models.py`:

```python
"""Shared data models for il2cpp-validate."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto


class RefType(Enum):
    CLASS = auto()
    METHOD = auto()
    FIELD = auto()
    PROPERTY = auto()
    NESTED_TYPE = auto()
    PARENT_CLASS = auto()
    ICALL = auto()


@dataclass(frozen=True, slots=True)
class ModReference:
    """A single string-based game reference found in mod source."""
    type: RefType
    source_file: str
    source_line: int
    # For class/method/field/property/nested_type refs:
    assembly: str | None = None
    namespace: str | None = None
    class_name: str | None = None
    member_name: str | None = None
    arg_count: int | None = None
    # For parent_class refs:
    parent_name: str | None = None
    # For icall refs:
    icall_signature: str | None = None


@dataclass(slots=True)
class DumpClass:
    """A class parsed from dump.cs with its members."""
    assembly: str
    namespace: str
    name: str
    methods: dict[str, list[str]] = field(default_factory=dict)     # name → [full signatures]
    fields: list[str] = field(default_factory=list)                  # field names
    properties: list[str] = field(default_factory=list)              # property names
    nested_types: list[str] = field(default_factory=list)            # nested type names


@dataclass(slots=True)
class DumpIndex:
    """Lookup indexes built from dump.cs."""
    # Primary: (assembly, namespace, class) → DumpClass
    by_qualified_name: dict[tuple[str, str, str], DumpClass] = field(default_factory=dict)
    # Secondary: class_name → [DumpClass] (for GetParent name-only lookups)
    by_class_name: dict[str, list[DumpClass]] = field(default_factory=dict)
    # Tertiary: (namespace, class_name) → [DumpClass] (for icall lookups)
    by_ns_class: dict[tuple[str, str], list[DumpClass]] = field(default_factory=dict)


class Severity(Enum):
    MISSING = auto()
    SIGNATURE_CHANGED = auto()


@dataclass(frozen=True, slots=True)
class Issue:
    """A validation issue found during cross-referencing."""
    severity: Severity
    ref: ModReference
    message: str
    old_signature: str | None = None
    new_signature: str | None = None
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python3 -c "from lib.models import RefType, ModReference, DumpClass, DumpIndex, Issue, Severity; print('OK')"` from the `scripts/` directory.

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/__init__.py scripts/lib/models.py
git commit -m "feat(validate): add shared data models for il2cpp-validate"
```

---

### Task 2: Mod source extractor — class helper resolution

**Files:**
- Create: `scripts/lib/mod_extractor.py`

This is the most regex-heavy module. It scans `mods/src/**/*.{cc,h}` and extracts all `il2cpp_get_class_helper` calls and their variable assignments, then resolves member access calls back to their class.

- [ ] **Step 1: Write the extractor with class helper tracking**

Create `scripts/lib/mod_extractor.py`:

```python
"""Extract string-based game references from mod C++ source files."""

from __future__ import annotations

import re
from pathlib import Path

from .models import ModReference, RefType

# Regex patterns for extraction

# il2cpp_get_class_helper("Assembly", "Namespace", "Class")
CLASS_HELPER_RE = re.compile(
    r'il2cpp_get_class_helper\(\s*"([^"]+)"\s*,\s*"([^"]*)"\s*,\s*"([^"]+)"\s*\)'
)

# Variable assignment: static auto/IL2CppClassHelper varname = ...
# Captures the variable name from lines like:
#   static auto class_helper = il2cpp_get_class_helper(...)
#   static IL2CppClassHelper class_helper = ...
VAR_ASSIGN_RE = re.compile(
    r'static\s+(?:auto|IL2CppClassHelper)\s+(\w+)\s*='
)

# get_class_helper() — the static method pattern in prime/*.h headers
# Matches both get_class_helper().Method(...) and varname.Method(...)
# The get_class_helper() call within a struct resolves to the il2cpp_get_class_helper
# inside that same struct's get_class_helper() method body.

# Member access patterns — all share the same structure:
# .MethodName("string_arg" [, optional_int_arg])
# We capture: the object expression, the method name, the string arg, and optional int arg

# GetMethod/GetMethodInfo/GetVirtualMethod/GetInvokeMethod with optional arg count
METHOD_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*(?:GetMethod|GetMethodInfo|GetVirtualMethod|GetInvokeMethod)'
    r'(?:<[^>]*>)?\s*\(\s*"([^"]+)"(?:\s*,\s*(\d+))?\s*[,)]'
)

# GetMethodSpecial/GetMethodInfoSpecial — method name is first string arg
METHOD_SPECIAL_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*(?:GetMethodSpecial|GetMethodInfoSpecial|GetMethodSpecial2)'
    r'(?:<[^>]*>)?\s*\([^"]*"([^"]+)"'
)

# GetField / GetStaticField
FIELD_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*(?:GetField|GetStaticField)\s*\(\s*"([^"]+)"'
)

# GetProperty
PROPERTY_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*GetProperty\s*\(\s*"([^"]+)"'
)

# GetNestedType
NESTED_TYPE_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*GetNestedType\s*\(\s*"([^"]+)"'
)

# GetParent
PARENT_RE = re.compile(
    r'(\w+(?:\(\))?)\s*\.\s*GetParent\s*\(\s*"([^"]+)"'
)

# il2cpp_resolve_icall_typed<T>("Full::Signature(Args)")
ICALL_RE = re.compile(
    r'il2cpp_resolve_icall_typed\s*<[^>]*>\s*\(\s*"([^"]+)"'
)


def extract_references(source_root: Path) -> list[ModReference]:
    """Scan all .cc and .h files under source_root for game references."""
    refs: list[ModReference] = []

    for pattern in ("**/*.cc", "**/*.h"):
        for filepath in sorted(source_root.glob(pattern)):
            refs.extend(_extract_from_file(filepath, source_root))

    return refs


def _extract_from_file(filepath: Path, source_root: Path) -> list[ModReference]:
    """Extract references from a single source file."""
    text = filepath.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    # Project-relative path for reporting (e.g., "mods/src/patches/parts/zoom.cc")
    try:
        rel_path = str(filepath.relative_to(source_root.parent.parent))
    except ValueError:
        rel_path = str(filepath)
    refs: list[ModReference] = []

    # Phase 1: Build variable → (assembly, namespace, class) mapping
    var_map: dict[str, tuple[str, str, str]] = {}

    # Detect the get_class_helper() static method pattern in prime/*.h headers.
    # The il2cpp_get_class_helper call inside a get_class_helper() function body
    # is the canonical class for "get_class_helper()" references in the file.
    file_class: tuple[str, str, str] | None = None

    for line_num, line in enumerate(lines, 1):
        m = CLASS_HELPER_RE.search(line)
        if m:
            class_info = (m.group(1), m.group(2), m.group(3))

            # Check if this is a variable assignment
            vm = VAR_ASSIGN_RE.search(line)
            if vm:
                var_map[vm.group(1)] = class_info

            # Set file_class from the first il2cpp_get_class_helper call.
            # In prime/*.h files, this is always the canonical class.
            # In patch .cc files with multiple helpers, variable resolution
            # handles the mapping instead.
            if file_class is None:
                file_class = class_info

            refs.append(ModReference(
                type=RefType.CLASS,
                source_file=rel_path,
                source_line=line_num,
                assembly=class_info[0],
                namespace=class_info[1],
                class_name=class_info[2],
            ))

    # Phase 2: Extract member references and resolve to their class
    def resolve_class(obj_expr: str) -> tuple[str, str, str] | None:
        """Resolve an object expression to its (assembly, ns, class)."""
        if obj_expr == "get_class_helper()":
            return file_class
        return var_map.get(obj_expr)

    for line_num, line in enumerate(lines, 1):
        # Methods (regular)
        for m in METHOD_RE.finditer(line):
            cls = resolve_class(m.group(1))
            arg_count = int(m.group(3)) if m.group(3) else None
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=rel_path,
                source_line=line_num,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=m.group(2),
                arg_count=arg_count,
            ))

        # Methods (special variants)
        for m in METHOD_SPECIAL_RE.finditer(line):
            cls = resolve_class(m.group(1))
            refs.append(ModReference(
                type=RefType.METHOD,
                source_file=rel_path,
                source_line=line_num,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=m.group(2),
            ))

        # Fields
        for m in FIELD_RE.finditer(line):
            cls = resolve_class(m.group(1))
            refs.append(ModReference(
                type=RefType.FIELD,
                source_file=rel_path,
                source_line=line_num,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=m.group(2),
            ))

        # Properties
        for m in PROPERTY_RE.finditer(line):
            cls = resolve_class(m.group(1))
            refs.append(ModReference(
                type=RefType.PROPERTY,
                source_file=rel_path,
                source_line=line_num,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=m.group(2),
            ))

        # Nested types
        for m in NESTED_TYPE_RE.finditer(line):
            cls = resolve_class(m.group(1))
            refs.append(ModReference(
                type=RefType.NESTED_TYPE,
                source_file=rel_path,
                source_line=line_num,
                assembly=cls[0] if cls else None,
                namespace=cls[1] if cls else None,
                class_name=cls[2] if cls else None,
                member_name=m.group(2),
            ))

        # Parent class
        for m in PARENT_RE.finditer(line):
            refs.append(ModReference(
                type=RefType.PARENT_CLASS,
                source_file=rel_path,
                source_line=line_num,
                parent_name=m.group(2),
            ))

        # Icalls
        for m in ICALL_RE.finditer(line):
            refs.append(ModReference(
                type=RefType.ICALL,
                source_file=rel_path,
                source_line=line_num,
                icall_signature=m.group(1),
            ))

    return refs
```

- [ ] **Step 2: Smoke test the extractor against actual mod source**

Run from `scripts/` directory:

```bash
python3 -c "
from lib.mod_extractor import extract_references
from pathlib import Path
refs = extract_references(Path('../mods/src'))
from collections import Counter
counts = Counter(r.type.name for r in refs)
for t, c in sorted(counts.items()):
    print(f'{t}: {c}')
unresolved = [r for r in refs if r.type.name in ('METHOD','FIELD','PROPERTY') and r.class_name is None]
if unresolved:
    print(f'\nUnresolved ({len(unresolved)}):')
    for r in unresolved[:5]:
        print(f'  {r.source_file}:{r.source_line} {r.member_name}')
"
```

Expected: Counts for CLASS, METHOD, FIELD, PROPERTY, ICALL, etc. matching roughly what we found in exploration (85+ classes, 50+ methods, 70+ fields, etc.). Some unresolved refs are expected — warn but don't fail.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/mod_extractor.py
git commit -m "feat(validate): add mod source reference extractor"
```

---

### Task 3: dump.cs parser

**Files:**
- Create: `scripts/lib/dump_parser.py`

Parses Il2CppDumper's dump.cs into a structured `DumpIndex`. This is a line-by-line state machine that tracks current assembly, namespace, class nesting, and member declarations.

- [ ] **Step 1: Write the dump.cs parser**

Create `scripts/lib/dump_parser.py`:

```python
"""Parse Il2CppDumper's dump.cs into a structured class/member lookup."""

from __future__ import annotations

import re
from pathlib import Path

from .models import DumpClass, DumpIndex

# Regex patterns for dump.cs parsing

# // Image N: AssemblyName.dll - offset
IMAGE_RE = re.compile(r'^// Image \d+: (.+?)(?:\.dll)? - \d+$')

# // Namespace: Some.Namespace
NAMESPACE_RE = re.compile(r'^// Namespace: (.*)$')

# Class/struct/interface/enum declarations
# public [sealed|abstract|static] [class|struct|interface|enum] Name[<T>] [: Base, IFace] // TypeDefIndex: N
CLASS_RE = re.compile(
    r'^(?:public|internal|private|protected)'
    r'(?:\s+(?:sealed|abstract|static))*'
    r'\s+(?:class|struct|interface|enum)\s+'
    r'(\S+)'  # class name (may include <T>)
)

# Field declarations: [modifiers] Type name; // 0xNN
# Also: [modifiers] Type name = value; // 0xNN
# Also: private const float Name = 0.01;
FIELD_RE = re.compile(
    r'^\t(?:public|private|protected|internal)'
    r'(?:\s+(?:static|readonly|const|volatile|new|override))*'
    r'\s+\S+\s+'           # type
    r'(\w+)\s*'            # field name
    r'(?:=\s*[^;]+)?'      # optional initializer
    r';'                   # semicolon
)

# Property declarations: [modifiers] Type Name { get; set; }
PROPERTY_RE = re.compile(
    r'^\t(?:public|private|protected|internal)'
    r'(?:\s+(?:static|virtual|abstract|override|sealed|new))*'
    r'\s+\S+\s+'           # type
    r'(\w+)\s*'            # property name
    r'\{'                  # opening brace of accessor block
)

# Method declarations: [modifiers] ReturnType Name(params) { }
# May have attributes on preceding lines, but the method line itself is:
# \t[modifiers] ReturnType Name(params) { }
METHOD_RE = re.compile(
    r'^\t(?:public|private|protected|internal)'
    r'(?:\s+(?:static|virtual|abstract|override|sealed|extern|new|unsafe))*'
    r'\s+\S+\s+'           # return type
    r'(\w+)\s*'            # method name
    r'\(([^)]*)\)'         # parameter list
    r'\s*\{[^}]*\}'        # body { }
)


def _convert_generic_name(name: str) -> str:
    """Convert C# generic syntax to backtick-arity format.

    Foo<T>       → Foo`1
    Foo<T, U>    → Foo`2
    Foo          → Foo (unchanged)

    Note: Only converts simple names. Dotted nested names like
    Parent.Child<T> are not expected from dump.cs class declarations
    (generics and nesting are separate concerns in IL2CPP metadata).
    """
    m = re.match(r'^(\w+)<(.+)>$', name)
    if not m:
        return name
    base = m.group(1)
    params = m.group(2)
    arity = params.count(',') + 1
    return f"{base}`{arity}"


def _count_params(param_str: str) -> int:
    """Count parameters in a C# parameter list string."""
    param_str = param_str.strip()
    if not param_str:
        return 0
    return param_str.count(',') + 1


def parse_dump(dump_path: Path) -> DumpIndex:
    """Parse dump.cs and build lookup indexes.

    IMPORTANT: Il2CppDumper outputs nested types as separate top-level
    class declarations with dotted names (e.g., 'FleetPlayerData.CanRepairRequirement'),
    NOT as brace-nested classes. The parser handles this by splitting dotted names
    and registering them as nested types on their parent class.
    """
    index = DumpIndex()

    current_assembly = ""
    current_namespace = ""
    current_dc: DumpClass | None = None

    for line in dump_path.open(encoding="utf-8", errors="replace"):
        stripped = line.rstrip('\n')

        # Track assembly — strip .dll suffix
        m = IMAGE_RE.match(stripped)
        if m:
            current_assembly = m.group(1)
            continue

        # Track namespace
        m = NAMESPACE_RE.match(stripped)
        if m:
            current_namespace = m.group(1)
            continue

        # Class declaration
        m = CLASS_RE.match(stripped)
        if m:
            raw_name = m.group(1)
            class_name = _convert_generic_name(raw_name)

            # Handle nested types: Il2CppDumper outputs them as
            # "ParentClass.NestedClass" at the top level
            parent_name: str | None = None
            if "." in class_name:
                dot_idx = class_name.index(".")
                parent_name = class_name[:dot_idx]
                nested_name = class_name[dot_idx + 1:]
            else:
                nested_name = None

            dc = DumpClass(
                assembly=current_assembly,
                namespace=current_namespace,
                name=class_name,
            )

            # Register in primary index
            key = (current_assembly, current_namespace, class_name)
            index.by_qualified_name[key] = dc

            # Register in name-only index
            index.by_class_name.setdefault(class_name, []).append(dc)

            # Register in (namespace, class) index
            ns_key = (current_namespace, class_name)
            index.by_ns_class.setdefault(ns_key, []).append(dc)

            # If this is a nested type, register on the parent class
            if parent_name and nested_name:
                parent_key = (current_assembly, current_namespace, parent_name)
                parent_dc = index.by_qualified_name.get(parent_key)
                if parent_dc and nested_name not in parent_dc.nested_types:
                    parent_dc.nested_types.append(nested_name)

            current_dc = dc
            continue

        # Reset current class on closing brace at column 0
        if stripped == '}':
            current_dc = None
            continue

        # Only parse members if we're inside a class
        if current_dc is None:
            continue

        # Method declaration
        m = METHOD_RE.match(stripped)
        if m:
            method_name = m.group(1)
            full_sig = stripped.strip()
            current_dc.methods.setdefault(method_name, []).append(full_sig)
            continue

        # Property declaration (must check before field due to overlap)
        m = PROPERTY_RE.match(stripped)
        if m:
            prop_name = m.group(1)
            if prop_name not in current_dc.properties:
                current_dc.properties.append(prop_name)
            continue

        # Field declaration
        m = FIELD_RE.match(stripped)
        if m:
            field_name = m.group(1)
            if field_name not in current_dc.fields:
                current_dc.fields.append(field_name)
            continue

    return index
```

- [ ] **Step 2: Smoke test the parser against actual dump.cs**

Run from `scripts/` directory:

```bash
python3 -c "
from lib.dump_parser import parse_dump
from pathlib import Path
index = parse_dump(Path('../dump/1.000.48286/dump.cs'))
print(f'Classes: {len(index.by_qualified_name)}')
print(f'Name-only entries: {len(index.by_class_name)}')

# Check a known class
key = ('Assembly-CSharp', 'Digit.Prime.Navigation', 'NavigationZoom')
dc = index.by_qualified_name.get(key)
if dc:
    print(f'\nNavigationZoom:')
    print(f'  Methods: {len(dc.methods)} ({list(dc.methods.keys())[:5]}...)')
    print(f'  Fields: {len(dc.fields)} ({dc.fields[:5]}...)')
    print(f'  Properties: {len(dc.properties)} ({dc.properties[:3]}...)')
else:
    print('NavigationZoom NOT FOUND — check parser')
"
```

Expected: Thousands of classes parsed. NavigationZoom found with its methods, fields, and properties.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/dump_parser.py
git commit -m "feat(validate): add dump.cs parser with class/member extraction"
```

---

### Task 4: Validator — cross-reference and sidecar diffing

**Files:**
- Create: `scripts/lib/validator.py`

Cross-references mod references against the dump index. Also handles sidecar reading/writing and diffing.

- [ ] **Step 1: Write the validator**

Create `scripts/lib/validator.py`:

```python
"""Cross-reference mod references against dump index, produce issues."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .models import DumpIndex, Issue, ModReference, RefType, Severity


def validate(refs: list[ModReference], index: DumpIndex) -> list[Issue]:
    """Validate all mod references against the dump index."""
    issues: list[Issue] = []

    for ref in refs:
        match ref.type:
            case RefType.CLASS:
                _validate_class(ref, index, issues)
            case RefType.METHOD:
                _validate_method(ref, index, issues)
            case RefType.FIELD:
                _validate_field(ref, index, issues)
            case RefType.PROPERTY:
                _validate_property(ref, index, issues)
            case RefType.NESTED_TYPE:
                _validate_nested_type(ref, index, issues)
            case RefType.PARENT_CLASS:
                _validate_parent_class(ref, index, issues)
            case RefType.ICALL:
                _validate_icall(ref, index, issues)

    return issues


def _get_class(ref: ModReference, index: DumpIndex):
    """Look up the class for a reference. Returns None if class not found."""
    if ref.assembly and ref.namespace is not None and ref.class_name:
        key = (ref.assembly, ref.namespace, ref.class_name)
        return index.by_qualified_name.get(key)
    return None


def _validate_class(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if _get_class(ref, index) is None:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING CLASS: {ref.assembly} :: {ref.namespace}.{ref.class_name}",
        ))


def _validate_method(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return  # unresolved variable — already warned during extraction
    dc = _get_class(ref, index)
    if dc is None:
        return  # class missing — will be reported by class validation
    if ref.member_name not in dc.methods:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING METHOD: {ref.class_name}.{ref.member_name}",
        ))
        return
    if ref.arg_count is not None:
        sigs = dc.methods[ref.member_name]
        # Count params in each overload signature
        # Signatures look like: "public void Foo(int a, float b) { }"
        # We need to extract the param list and count commas
        has_matching = any(
            _count_params_from_sig(sig) == ref.arg_count for sig in sigs
        )
        if not has_matching:
            found_counts = sorted(set(_count_params_from_sig(s) for s in sigs))
            issues.append(Issue(
                severity=Severity.MISSING,
                ref=ref,
                message=(
                    f"MISSING METHOD: {ref.class_name}.{ref.member_name}"
                    f" (expected {ref.arg_count} args, found {found_counts})"
                ),
            ))


def _count_params_from_sig(sig: str) -> int:
    """Count parameters in a dump.cs method signature."""
    m = re.search(r'\(([^)]*)\)', sig)
    if not m:
        return 0
    params = m.group(1).strip()
    if not params:
        return 0
    return params.count(',') + 1


def _validate_field(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return
    dc = _get_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.fields:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING FIELD: {ref.class_name}.{ref.member_name}",
        ))


def _validate_property(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return
    dc = _get_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.properties:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING PROPERTY: {ref.class_name}.{ref.member_name}",
        ))


def _validate_nested_type(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.class_name is None:
        return
    dc = _get_class(ref, index)
    if dc is None:
        return
    if ref.member_name not in dc.nested_types:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING NESTED TYPE: {ref.class_name}.{ref.member_name}",
        ))


def _validate_parent_class(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if ref.parent_name and ref.parent_name not in index.by_class_name:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING PARENT CLASS: {ref.parent_name}",
        ))


def _validate_icall(ref: ModReference, index: DumpIndex, issues: list[Issue]) -> None:
    if not ref.icall_signature:
        return
    # Split "Namespace.Class::Method(Args)" into class + method
    if "::" not in ref.icall_signature:
        return
    class_part, method_with_args = ref.icall_signature.split("::", 1)
    method_name = method_with_args.split("(", 1)[0]

    # Split class_part on last dot: "UnityEngine.Input" → ("UnityEngine", "Input")
    if "." in class_part:
        last_dot = class_part.rfind(".")
        ns = class_part[:last_dot]
        cls_name = class_part[last_dot + 1:]
    else:
        ns = ""
        cls_name = class_part

    matches = index.by_ns_class.get((ns, cls_name), [])
    if not matches:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING ICALL CLASS: {class_part}",
        ))
        return

    # Check method exists on any matching class
    found = any(method_name in dc.methods for dc in matches)
    if not found:
        issues.append(Issue(
            severity=Severity.MISSING,
            ref=ref,
            message=f"MISSING ICALL: {class_part}::{method_name}",
        ))


# --- Sidecar ---

def build_sidecar(
    refs: list[ModReference],
    index: DumpIndex,
    game_version: str,
    unity_version: str | None,
) -> dict:
    """Build the mod-references.json sidecar data."""
    sidecar: dict = {
        "game_version": game_version,
        "unity_version": unity_version,
        "references": {},
        "icalls": {},
    }

    for ref in refs:
        if ref.type == RefType.ICALL and ref.icall_signature:
            _add_icall_to_sidecar(ref, index, sidecar)
            continue

        if ref.assembly is None or ref.class_name is None:
            continue

        class_key = f"{ref.assembly}::{ref.namespace}.{ref.class_name}"
        entry = sidecar["references"].setdefault(class_key, {
            "methods": {},
            "fields": [],
            "properties": [],
        })

        dc = _get_class(ref, index)

        match ref.type:
            case RefType.METHOD if ref.member_name:
                if dc and ref.member_name in dc.methods:
                    entry["methods"][ref.member_name] = dc.methods[ref.member_name]
            case RefType.FIELD if ref.member_name:
                if ref.member_name not in entry["fields"]:
                    entry["fields"].append(ref.member_name)
            case RefType.PROPERTY if ref.member_name:
                if ref.member_name not in entry["properties"]:
                    entry["properties"].append(ref.member_name)

    return sidecar


def _add_icall_to_sidecar(ref: ModReference, index: DumpIndex, sidecar: dict) -> None:
    if not ref.icall_signature or "::" not in ref.icall_signature:
        return
    class_part, method_with_args = ref.icall_signature.split("::", 1)
    method_name = method_with_args.split("(", 1)[0]

    if "." in class_part:
        last_dot = class_part.rfind(".")
        ns = class_part[:last_dot]
        cls_name = class_part[last_dot + 1:]
    else:
        ns = ""
        cls_name = class_part

    sigs = []
    for dc in index.by_ns_class.get((ns, cls_name), []):
        sigs.extend(dc.methods.get(method_name, []))

    sidecar["icalls"][f"{class_part}::{method_name}"] = {
        "class": class_part,
        "signatures": sigs,
    }


def write_sidecar(sidecar: dict, output_path: Path) -> None:
    """Write the sidecar JSON file."""
    output_path.write_text(json.dumps(sidecar, indent=2, ensure_ascii=False))


def load_sidecar(path: Path) -> dict | None:
    """Load a sidecar JSON file, or None if not found."""
    if not path.exists():
        return None
    return json.loads(path.read_text())


def diff_sidecars(old: dict, new_refs: list[ModReference], index: DumpIndex) -> list[Issue]:
    """Compare a previous sidecar against current dump to find signature changes."""
    issues: list[Issue] = []
    old_refs = old.get("references", {})

    for class_key, old_entry in old_refs.items():
        old_methods = old_entry.get("methods", {})
        for method_name, old_sigs in old_methods.items():
            # Find the class in current index
            # class_key format: "Assembly::Namespace.ClassName"
            parts = class_key.split("::", 1)
            if len(parts) != 2:
                continue
            assembly = parts[0]
            ns_class = parts[1]
            last_dot = ns_class.rfind(".")
            if last_dot >= 0:
                ns = ns_class[:last_dot]
                cls_name = ns_class[last_dot + 1:]
            else:
                ns = ""
                cls_name = ns_class

            dc = index.by_qualified_name.get((assembly, ns, cls_name))
            if dc is None:
                continue  # class missing — reported elsewhere

            new_sigs = dc.methods.get(method_name, [])
            if new_sigs and old_sigs and sorted(new_sigs) != sorted(old_sigs):
                # Find which mod ref this corresponds to
                matching_ref = next(
                    (r for r in new_refs
                     if r.class_name == cls_name and r.member_name == method_name),
                    None,
                )
                if matching_ref:
                    issues.append(Issue(
                        severity=Severity.SIGNATURE_CHANGED,
                        ref=matching_ref,
                        message=f"SIGNATURE CHANGED: {cls_name}.{method_name}",
                        old_signature=old_sigs[0] if old_sigs else None,
                        new_signature=new_sigs[0] if new_sigs else None,
                    ))

    return issues


def find_previous_sidecar(dump_dir: Path, current_version: str) -> dict | None:
    """Find the most recent mod-references.json from a different version."""
    sidecars: list[tuple[str, Path]] = []
    for version_dir in dump_dir.iterdir():
        if not version_dir.is_dir() or version_dir.name == current_version:
            continue
        sidecar_path = version_dir / "mod-references.json"
        if sidecar_path.exists():
            sidecars.append((version_dir.name, sidecar_path))

    if not sidecars:
        return None

    # Sort by version string descending, take most recent
    sidecars.sort(key=lambda x: x[0], reverse=True)
    return load_sidecar(sidecars[0][1])
```

- [ ] **Step 2: Verify the validator runs against real data**

Run from `scripts/` directory:

```bash
python3 -c "
from lib.mod_extractor import extract_references
from lib.dump_parser import parse_dump
from lib.validator import validate
from pathlib import Path

refs = extract_references(Path('../mods/src'))
index = parse_dump(Path('../dump/1.000.48286/dump.cs'))
issues = validate(refs, index)

print(f'Total issues: {len(issues)}')
for issue in issues[:10]:
    print(f'  {issue.message}')
    print(f'    {issue.ref.source_file}:{issue.ref.source_line}')
"
```

Expected: Zero or very few issues (since this is the current game version the mod is built against). Any issues found are likely parser bugs or unresolved variables — investigate and fix.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/validator.py
git commit -m "feat(validate): add cross-reference validator and sidecar diffing"
```

---

### Task 5: Main script — CLI, orchestration, reporting

**Files:**
- Create: `scripts/il2cpp-validate.py`

Ties everything together: CLI parsing, Stage 1 integration, and the human-readable report.

- [ ] **Step 1: Write the main script**

Create `scripts/il2cpp-validate.py`:

```python
#!/usr/bin/env python3
"""Validate mod source references against an Il2CppDumper dump of the STFC game binary."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import Counter
from pathlib import Path

# Add scripts/ to path for lib imports
sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.dump_parser import parse_dump
from lib.mod_extractor import extract_references
from lib.models import Issue, RefType, Severity
from lib.validator import (
    build_sidecar,
    diff_sidecars,
    find_previous_sidecar,
    validate,
    write_sidecar,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = PROJECT_ROOT / "dump"
MOD_SRC = PROJECT_ROOT / "mods" / "src"
DUMP_SCRIPT = PROJECT_ROOT / "scripts" / "il2cpp-dump.py"


def detect_game_version(game_dir: Path, version_override: str | None) -> tuple[str, str | None]:
    """Detect game version by importing from il2cpp-dump.py."""
    # Import Stage 1 functions
    sys.path.insert(0, str(DUMP_SCRIPT.parent))
    import importlib
    spec = importlib.util.spec_from_file_location("il2cpp_dump", DUMP_SCRIPT)
    il2cpp_dump = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(il2cpp_dump)

    game_files = il2cpp_dump.locate_game_files(game_dir)
    versions = il2cpp_dump.detect_versions(
        game_files.global_game_managers, override=version_override
    )
    return versions.game_version, versions.unity_version


def ensure_dump(game_dir: Path, version: str, version_override: str | None) -> Path:
    """Ensure a dump exists for the given version. Run Stage 1 if needed."""
    dump_dir = DUMP_DIR / version
    dump_cs = dump_dir / "dump.cs"

    if dump_cs.exists() and dump_cs.stat().st_size > 0:
        print(f"Dump already exists: {dump_dir}")
        return dump_dir

    print(f"No dump found for version {version}. Running il2cpp-dump.py...")
    cmd = [sys.executable, str(DUMP_SCRIPT), "--game-dir", str(game_dir)]
    if version_override:
        cmd.extend(["--version", version_override])

    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"il2cpp-dump.py failed (exit code {result.returncode})")

    if not dump_cs.exists():
        sys.exit(f"Dump script completed but dump.cs not found at {dump_cs}")

    return dump_dir


def print_report(issues: list[Issue], ref_counts: Counter) -> None:
    """Print the human-readable validation report."""
    if not issues:
        print("\nAll references valid.")
    else:
        print()
        for issue in issues:
            print(issue.message)
            if issue.severity == Severity.SIGNATURE_CHANGED:
                if issue.old_signature:
                    print(f"  Was:  {issue.old_signature}")
                if issue.new_signature:
                    print(f"  Now:  {issue.new_signature}")
            print(f"  Referenced in: {issue.ref.source_file}:{issue.ref.source_line}")
            print()

    missing = sum(1 for i in issues if i.severity == Severity.MISSING)
    changed = sum(1 for i in issues if i.severity == Severity.SIGNATURE_CHANGED)

    print(
        f"Checked {ref_counts[RefType.CLASS]} classes, "
        f"{ref_counts[RefType.METHOD]} methods, "
        f"{ref_counts[RefType.FIELD]} fields, "
        f"{ref_counts[RefType.PROPERTY]} properties, "
        f"{ref_counts[RefType.ICALL]} icalls"
    )

    if issues:
        parts = []
        if missing:
            parts.append(f"{missing} missing")
        if changed:
            parts.append(f"{changed} signature changed")
        print(f"Found {', '.join(parts)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-dir", type=Path, required=True,
        help="Path to game directory (.app on macOS, game root on Windows)",
    )
    parser.add_argument(
        "--version", type=str, default=None,
        help="Override auto-detected game version",
    )
    parser.add_argument(
        "--dump-only", action="store_true",
        help="Run the dump but skip validation",
    )
    args = parser.parse_args()

    game_dir = args.game_dir.resolve()
    if not game_dir.exists():
        sys.exit(f"Game directory not found: {game_dir}")

    # Step 1: Detect version
    game_version, unity_version = detect_game_version(game_dir, args.version)
    print(f"Game version: {game_version}")
    print(f"Unity version: {unity_version or 'unknown'}")

    # Step 2: Ensure dump exists
    dump_dir = ensure_dump(game_dir, game_version, args.version)

    if args.dump_only:
        print("--dump-only: skipping validation.")
        return

    # Step 3: Extract mod references
    print(f"\nScanning mod source: {MOD_SRC}")
    refs = extract_references(MOD_SRC)

    ref_counts = Counter(r.type for r in refs)
    unresolved = [r for r in refs if r.type in (RefType.METHOD, RefType.FIELD, RefType.PROPERTY)
                  and r.class_name is None]
    if unresolved:
        print(f"Warning: {len(unresolved)} references could not be resolved to a class",
              file=sys.stderr)
        for r in unresolved[:5]:
            print(f"  {r.source_file}:{r.source_line} .{r.member_name}", file=sys.stderr)

    # Step 4: Parse dump.cs
    dump_cs = dump_dir / "dump.cs"
    print(f"Parsing {dump_cs.name} ({dump_cs.stat().st_size / 1_000_000:.0f} MB)...")
    index = parse_dump(dump_cs)
    print(f"Parsed {len(index.by_qualified_name)} classes")

    # Step 5: Validate
    print(f"\nValidating mod references against dump {game_version}...")
    issues = validate(refs, index)

    # Step 6: Diff against previous sidecar
    prev_sidecar = find_previous_sidecar(DUMP_DIR, game_version)
    if prev_sidecar:
        prev_version = prev_sidecar.get("game_version", "unknown")
        print(f"Comparing signatures against previous version {prev_version}...")
        sig_issues = diff_sidecars(prev_sidecar, refs, index)
        issues.extend(sig_issues)

    # Step 7: Write sidecar
    sidecar = build_sidecar(refs, index, game_version, unity_version)
    sidecar_path = dump_dir / "mod-references.json"
    write_sidecar(sidecar, sidecar_path)
    print(f"Wrote {sidecar_path}")

    # Step 8: Report
    print_report(issues, ref_counts)
    sys.exit(1 if issues else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/il2cpp-validate.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/il2cpp-validate.py
git commit -m "feat(validate): add main il2cpp-validate script with CLI and reporting"
```

---

### Task 6: End-to-end testing and tuning

**Files:**
- Modify: any of the above files as needed to fix issues

This task runs the full pipeline against the real game data and fixes any issues discovered.

- [ ] **Step 1: Run the full pipeline**

```bash
python3 scripts/il2cpp-validate.py --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app"
```

Expected: Should parse the existing dump (not re-dump), extract all mod references, validate them, and report results. Since this is the current game version the mod targets, there should be zero or very few issues. Any issues are likely parser/extractor bugs.

- [ ] **Step 2: Investigate and fix any false positives**

Common issues to expect:
- Regex not matching some dump.cs patterns (attributes, generics, unusual modifiers)
- Variable resolution failing for chained calls
- Brace counting off due to single-line braces or comment blocks

Fix each issue in the relevant module, re-run to verify.

- [ ] **Step 3: Verify `--dump-only` works**

```bash
python3 scripts/il2cpp-validate.py --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app" --dump-only
```

Expected: Detects version, confirms dump exists, stops without validation.

- [ ] **Step 4: Verify `mod-references.json` was written and looks correct**

```bash
python3 -c "
import json
from pathlib import Path
sidecar = json.loads(Path('dump/1.000.48286/mod-references.json').read_text())
print(f'Version: {sidecar[\"game_version\"]}')
print(f'Classes tracked: {len(sidecar[\"references\"])}')
print(f'Icalls tracked: {len(sidecar[\"icalls\"])}')
# Show one entry
for key, val in list(sidecar['references'].items())[:1]:
    print(f'\n{key}:')
    print(json.dumps(val, indent=2)[:500])
"
```

Expected: Sidecar has entries for all referenced classes with their methods/fields/properties.

- [ ] **Step 5: Commit any fixes**

```bash
git add scripts/
git commit -m "fix(validate): address issues found during end-to-end testing"
```

Only commit if there were actual changes.

- [ ] **Step 6: Update dump/.gitignore if needed**

Check that `mod-references.json` is not gitignored (it shouldn't be — the existing `.gitignore` only ignores `*.cs`, `*.py`, `*.h`, `DummyDll/`). Verify:

```bash
git status dump/1.000.48286/mod-references.json
```

Expected: Shows as untracked (not ignored). If ignored, update `dump/.gitignore`.
