# IL2CPP Code Generator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a tool that auto-fixes broken IL2CPP references and generates C++ header scaffolds from dump output.

**Architecture:** Two new library modules (`scripts/lib/fixer.py` for auto-fix logic, `scripts/lib/codegen.py` for scaffold generation) plus a CLI script (`scripts/il2cpp-codegen.py`). Requires enhancing the dump parser to capture full method signatures (with return types). Reuses all Stage 1/2 infrastructure.

**Tech Stack:** Python 3.12+ stdlib only

**Spec:** `docs/superpowers/specs/2026-03-23-il2cpp-codegen-design.md`

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `scripts/lib/dump_parser.py` | Modify | Enhance to store full method signatures (return type + modifiers + params) and field types |
| `scripts/lib/codegen.py` | Create | Type mapping, method signature parsing, C++ header scaffold generation |
| `scripts/lib/fixer.py` | Create | Auto-fix logic (assembly/namespace renames, nested type suffixes) and suggestion generation |
| `scripts/il2cpp-codegen.py` | Create | CLI with `fix`, `scaffold`, `scaffold-all` subcommands |

---

### Task 1: Enhance dump parser to store full method signatures

**Files:**
- Modify: `scripts/lib/dump_parser.py`

The current parser stores `SetDepth(NodeDepth value)` but the codegen needs `private void SetDepth(NodeDepth value) { }` (or at least the return type). Also, fields are stored as names only but the codegen needs the C# type (e.g., `float` for `private float _minimum;`).

- [ ] **Step 1: Update `_extract_method_name_and_sig` to capture the full declaration**

In `scripts/lib/dump_parser.py`, replace the `_extract_method_name_and_sig` function:

```python
def _extract_method_name_and_sig(line: str) -> tuple[str, str] | None:
    """Extract (method_name, full_signature) from an indented method line.

    The full_signature now includes modifiers, return type, name, and params.
    Example: "public static void SetDepth(float depth)"
    """
    stripped = line.strip()
    # Must end with { } (empty body) — possibly with trailing comment
    if not re.search(r'\{\s*\}\s*(?://.*)?$', stripped):
        return None
    # Remove trailing body { } and any comment
    decl = re.sub(r'\s*\{[^}]*\}\s*(?://.*)?$', '', stripped).strip()
    # Extract method name and params from the declaration
    m = re.match(
        r'(?:(?:public|private|protected|internal|sealed|abstract|static|readonly|override|virtual|new|extern|unsafe|async)\s+)*'
        r'(?:\S+\s+)+'   # return type (one or more tokens)
        r'([A-Za-z_.][A-Za-z0-9_.<>\[\]@`]*)'  # method name
        r'\s*(\([^)]*\))',    # parameter list
        stripped
    )
    if m:
        name = m.group(1)
        return name, decl
    return None
```

This changes the stored signature from `SetDepth(NodeDepth value)` to `private void SetDepth(NodeDepth value)` — the full declaration line without `{ }`.

- [ ] **Step 2: Update `DumpClass.fields` to store `(name, type)` tuples instead of just names**

In `scripts/lib/models.py`, change `DumpClass.fields` from `list[str]` to `dict[str, str]` (field name → C# type):

```python
fields: dict[str, str] = field(default_factory=dict)    # field_name → cs_type
```

Update the dump parser's field extraction to also capture the type. The raw line looks like `private float _minimum; // 0x10` — extract both `float` and `_minimum`.

Update `scripts/lib/validator.py` wherever it checks `ref.member_name in dc.fields` — change to `ref.member_name in dc.fields` (dict lookup works the same).

Update `scripts/lib/validator.py` sidecar building — where it appends field names to `entry["fields"]`, change to include the type as well or keep as list of names for backward compatibility.

- [ ] **Step 3: Verify the parser still works and signatures include return types**

```bash
cd /Users/ebendler/projects/stfc-mod/scripts && python3 -c "
from lib.dump_parser import parse_dump
from pathlib import Path
index = parse_dump(Path('../dump/1.000.48286/dump.cs'))
key = ('Assembly-CSharp', 'Digit.Prime.Navigation', 'NavigationZoom')
dc = index.by_qualified_name[key]
for name in ['SetDepth', 'Update', 'get_Distance', 'SetViewParameters']:
    sigs = dc.methods.get(name, [])
    for s in sigs:
        print(f'{name}: {s}')
print(f'Total classes: {len(index.by_qualified_name)}')
"
```

Expected: Signatures now include modifiers and return types, e.g., `private void SetDepth(NodeDepth value)`. Total class count unchanged (~24124).

- [ ] **Step 3: Verify Stage 2 validator still works** (signatures are used in sidecar diffing)

```bash
cd /Users/ebendler/projects/stfc-mod && python3 scripts/il2cpp-validate.py --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app" --format json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'Issues: {d[\"summary\"][\"missing\"]}')"
```

Expected: Same number of issues as before (65).

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/dump_parser.py
git commit -m "feat(codegen): enhance dump parser to store full method signatures with return types

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Type mapping and method signature parsing

**Files:**
- Create: `scripts/lib/codegen.py`

The core code generation module: C# → C++ type mapping and method signature parsing.

- [ ] **Step 1: Create codegen.py with type mapping and signature parser**

Create `scripts/lib/codegen.py`:

```python
"""C++ code generation from Il2CppDumper output.

Type mapping (C# → C++), method signature parsing, and header scaffold generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import DumpClass

# C# type → C++ type mapping
TYPE_MAP: dict[str, str] = {
    "bool":             "bool",
    "Boolean":          "bool",
    "System.Boolean":   "bool",
    "int":              "int32_t",
    "Int32":            "int32_t",
    "System.Int32":     "int32_t",
    "long":             "int64_t",
    "Int64":            "int64_t",
    "System.Int64":     "int64_t",
    "uint":             "uint32_t",
    "UInt32":           "uint32_t",
    "System.UInt32":    "uint32_t",
    "ulong":            "uint64_t",
    "UInt64":           "uint64_t",
    "System.UInt64":    "uint64_t",
    "float":            "float",
    "Single":           "float",
    "System.Single":    "float",
    "double":           "double",
    "Double":           "double",
    "System.Double":    "double",
    "string":           "Il2CppString*",
    "String":           "Il2CppString*",
    "System.String":    "Il2CppString*",
    "void":             "void",
    "Void":             "void",
    "System.Void":      "void",
    "byte":             "uint8_t",
    "Byte":             "uint8_t",
    "System.Byte":      "uint8_t",
    "sbyte":            "int8_t",
    "SByte":            "int8_t",
    "System.SByte":     "int8_t",
    "short":            "int16_t",
    "Int16":            "int16_t",
    "System.Int16":     "int16_t",
    "ushort":           "uint16_t",
    "UInt16":           "uint16_t",
    "System.UInt16":    "uint16_t",
    "char":             "uint16_t",
    "Char":             "uint16_t",
    "System.Char":      "uint16_t",
}

# Types that are primitive (passed by value, used with Get<T>)
PRIMITIVE_CPP_TYPES = {"bool", "int32_t", "int64_t", "uint32_t", "uint64_t",
                       "float", "double", "uint8_t", "int8_t", "int16_t", "uint16_t"}


def map_type(cs_type: str) -> str:
    """Map a C# type name to C++ equivalent.

    Returns the mapped type for known types, or 'void* /* OriginalType */' for unknown.
    Strips trailing [] for arrays (mapped to void*).
    Strips generic parameters (List<T> → void*).
    """
    # Strip array brackets
    if cs_type.endswith("[]"):
        return f"void* /* {cs_type} */"
    # Strip generic params
    if "<" in cs_type:
        return f"void* /* {cs_type} */"
    # Nullable<T> → void*
    if cs_type.endswith("?"):
        return f"void* /* {cs_type} */"

    mapped = TYPE_MAP.get(cs_type)
    if mapped:
        return mapped
    return f"void* /* {cs_type} */"


def is_primitive(cpp_type: str) -> bool:
    """Check if a C++ type is a primitive (not a pointer/void*)."""
    return cpp_type in PRIMITIVE_CPP_TYPES


@dataclass(frozen=True, slots=True)
class ParsedParam:
    cs_type: str
    name: str
    cpp_type: str


@dataclass(frozen=True, slots=True)
class ParsedMethod:
    name: str
    return_cs_type: str
    return_cpp_type: str
    params: tuple[ParsedParam, ...]
    is_static: bool
    raw_signature: str


def _split_params(param_str: str) -> list[str]:
    """Split a parameter list on commas, respecting <> nesting for generics.

    "Dictionary<int, string> dict, int x" → ["Dictionary<int, string> dict", "int x"]
    """
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for ch in param_str:
        if ch == "<":
            depth += 1
            current.append(ch)
        elif ch == ">":
            depth -= 1
            current.append(ch)
        elif ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    if current:
        parts.append("".join(current))
    return parts


def parse_method_signature(sig: str) -> ParsedMethod | None:
    """Parse a dump.cs method signature into structured form.

    Input example: "public static void SetDepth(float depth)"
    Input example: "private float get_Distance()"
    """
    # Strip leading/trailing whitespace
    sig = sig.strip()

    # Tokenize: split off modifiers, then return type, then name(params)
    modifiers = set()
    tokens = sig.split()

    modifier_keywords = {
        "public", "private", "protected", "internal",
        "static", "virtual", "abstract", "override",
        "sealed", "new", "extern", "unsafe", "async",
    }

    idx = 0
    while idx < len(tokens) and tokens[idx] in modifier_keywords:
        modifiers.add(tokens[idx])
        idx += 1

    # Remaining tokens: return_type method_name(params)
    # The return type may be multiple tokens for generics: "List<int>"
    # Find the token containing '(' — that's the method name + params
    rest = " ".join(tokens[idx:])

    m = re.match(r'(.+?)\s+([A-Za-z_.][A-Za-z0-9_.<>\[\]@`]*)\s*\(([^)]*)\)$', rest)
    if not m:
        return None

    return_type_str = m.group(1)
    method_name = m.group(2)
    param_str = m.group(3).strip()

    # Parse parameters — split on commas but respect <> nesting for generics
    params: list[ParsedParam] = []
    if param_str:
        for p in _split_params(param_str):
            p = p.strip()
            # "float depth" or "List<int> items" — last token is name, rest is type
            parts = p.rsplit(None, 1)
            if len(parts) == 2:
                cs_t, pname = parts
                params.append(ParsedParam(cs_type=cs_t, name=pname, cpp_type=map_type(cs_t)))
            elif len(parts) == 1:
                # No name, just type (rare in dump.cs)
                params.append(ParsedParam(cs_type=parts[0], name=f"arg{len(params)}", cpp_type=map_type(parts[0])))

    return ParsedMethod(
        name=method_name,
        return_cs_type=return_type_str,
        return_cpp_type=map_type(return_type_str),
        params=params,
        is_static="static" in modifiers,
        raw_signature=sig,
    )
```

- [ ] **Step 2: Smoke test the type mapper and signature parser**

```bash
cd /Users/ebendler/projects/stfc-mod/scripts && python3 -c "
from lib.codegen import map_type, parse_method_signature

# Type mapping
for cs in ['void', 'float', 'int', 'bool', 'string', 'FleetPlayerData', 'List<int>', 'byte[]']:
    print(f'{cs:30s} → {map_type(cs)}')

print()

# Method parsing
sigs = [
    'private void SetDepth(NodeDepth value)',
    'public float get_Distance()',
    'public static void ClearZoomListeners()',
    'public void SetViewParameters(float radius, NodeDepth depth)',
    'internal bool IsBuffConditionMet(BuffCondition currentCondition, IBuffComparer buffComparer)',
]
for s in sigs:
    pm = parse_method_signature(s)
    if pm:
        print(f'{pm.name}: ret={pm.return_cpp_type}, static={pm.is_static}, params={[(p.name, p.cpp_type) for p in pm.params]}')
"
```

Expected: Primitives map correctly, unknown types become `void* /* Type */`. Methods parse with correct return types, static detection, and parameter mapping.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/codegen.py
git commit -m "feat(codegen): add C# → C++ type mapping and method signature parser

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Scaffold generator

**Files:**
- Modify: `scripts/lib/codegen.py`

Add the `generate_scaffold` function that produces a complete C++ header string from a `DumpClass`.

- [ ] **Step 1: Add scaffold generation to codegen.py**

Append to `scripts/lib/codegen.py`:

```python
def generate_scaffold(dc: DumpClass, game_version: str) -> str:
    """Generate a C++ header scaffold for a DumpClass."""
    class_name = dc.name
    # For backtick generics like CallbackContainer`1, use a clean C++ name
    cpp_class_name = class_name.replace("`", "_")

    lines: list[str] = []
    lines.append("#pragma once")
    lines.append(f"// Auto-generated from dump {game_version} — edit as needed")
    lines.append("")
    lines.append("#include <il2cpp/il2cpp_helper.h>")
    lines.append("#include <cstdint>")
    lines.append("")
    lines.append(f"struct {cpp_class_name} {{")
    lines.append("public:")

    # --- Properties ---
    if dc.properties:
        lines.append("  // --- Properties ---")
        for prop_name in dc.properties:
            # Find the getter method to determine the type
            getter_sig = dc.methods.get(f"get_{prop_name}", [None])[0] if f"get_{prop_name}" in dc.methods else None
            setter_exists = f"set_{prop_name}" in dc.methods

            cpp_ret = "void*"
            if getter_sig:
                parsed = parse_method_signature(getter_sig)
                if parsed:
                    cpp_ret = parsed.return_cpp_type

            if setter_exists:
                lines.append(f"  __declspec(property(get = __get_{prop_name}, put = __set_{prop_name})) {cpp_ret} {prop_name};")
            else:
                lines.append(f"  __declspec(property(get = __get_{prop_name})) {cpp_ret} {prop_name};")
        lines.append("")

    # --- Methods ---
    # Exclude property accessors (get_X, set_X) and compiler-generated methods
    method_names = [
        name for name in dc.methods
        if not name.startswith("get_") and not name.startswith("set_")
        and not name.startswith(".") and not name.startswith("<")
    ]

    if method_names:
        lines.append("  // --- Methods ---")
        for method_name in method_names:
            for sig in dc.methods[method_name]:
                parsed = parse_method_signature(sig)
                if not parsed:
                    lines.append(f"  // Could not parse: {sig}")
                    continue

                # Build parameter list for wrapper
                param_decls = ", ".join(f"{p.cpp_type} {p.name}" for p in parsed.params)
                param_names = ", ".join(p.name for p in parsed.params)

                # Build GetMethod template type
                if parsed.is_static:
                    template_params = ", ".join(p.cpp_type for p in parsed.params)
                    template_type = f"{parsed.return_cpp_type}({template_params})" if template_params else f"{parsed.return_cpp_type}()"
                else:
                    all_params = [f"{cpp_class_name}*"] + [p.cpp_type for p in parsed.params]
                    template_type = f"{parsed.return_cpp_type}({', '.join(all_params)})"

                # Determine if we need a return statement
                returns = parsed.return_cpp_type != "void"

                if parsed.is_static:
                    lines.append(f"  static {parsed.return_cpp_type} {method_name}({param_decls}) {{")
                    lines.append(f"    static auto m = get_class_helper().GetMethod<{template_type}>(\"{method_name}\");")
                    if returns:
                        lines.append(f"    return m({param_names});")
                    else:
                        call_args = param_names
                        lines.append(f"    m({call_args});")
                else:
                    lines.append(f"  {parsed.return_cpp_type} {method_name}({param_decls}) {{")
                    lines.append(f"    static auto m = get_class_helper().GetMethod<{template_type}>(\"{method_name}\");")
                    call_args = f"this, {param_names}" if param_names else "this"
                    if returns:
                        lines.append(f"    return m({call_args});")
                    else:
                        lines.append(f"    m({call_args});")
                lines.append("  }")
                lines.append("")

    # --- get_class_helper ---
    lines.append("private:")
    lines.append("  static IL2CppClassHelper& get_class_helper() {")
    lines.append(f"    static auto class_helper =")
    lines.append(f"        il2cpp_get_class_helper(\"{dc.assembly}\", \"{dc.namespace}\", \"{class_name}\");")
    lines.append("    return class_helper;")
    lines.append("  }")
    lines.append("")

    # --- Property accessors ---
    if dc.properties:
        lines.append("public:")
        lines.append("  // --- Property accessors ---")
        for prop_name in dc.properties:
            getter_sig = dc.methods.get(f"get_{prop_name}", [None])[0] if f"get_{prop_name}" in dc.methods else None
            setter_sig = dc.methods.get(f"set_{prop_name}", [None])[0] if f"set_{prop_name}" in dc.methods else None

            cpp_ret = "void*"
            if getter_sig:
                parsed = parse_method_signature(getter_sig)
                if parsed:
                    cpp_ret = parsed.return_cpp_type

            prim = is_primitive(cpp_ret)

            # Getter
            if prim:
                lines.append(f"  {cpp_ret} __get_{prop_name}() {{")
                lines.append(f"    static auto prop = get_class_helper().GetProperty(\"{prop_name}\");")
                lines.append(f"    return *prop.Get<{cpp_ret}>(this);")
            else:
                # For pointer types, strip trailing * and /* comment */ for GetRaw<T>
                raw_type = "void"
                if cpp_ret.startswith("void*"):
                    raw_type = "void"
                elif cpp_ret.endswith("*"):
                    raw_type = cpp_ret[:-1].strip()
                lines.append(f"  {cpp_ret} __get_{prop_name}() {{")
                lines.append(f"    static auto prop = get_class_helper().GetProperty(\"{prop_name}\");")
                lines.append(f"    return prop.GetRaw<{raw_type}>(this);")
            lines.append("  }")

            # Setter
            if setter_sig:
                lines.append(f"  void __set_{prop_name}({cpp_ret} v) {{")
                lines.append(f"    static auto prop = get_class_helper().GetProperty(\"{prop_name}\");")
                lines.append(f"    prop.SetRaw(this, v);")
                lines.append("  }")
            lines.append("")

    # --- Field accessors ---
    if dc.fields:
        if not dc.properties:
            lines.append("public:")
        lines.append("  // --- Field accessors ---")
        for field_name, cs_type in dc.fields.items():
            # Skip compiler-generated backing fields for properties
            if field_name.startswith("<") and field_name.endswith(">k__BackingField"):
                continue

            cpp_type = map_type(cs_type)
            prim = is_primitive(cpp_type)

            # Getter
            if prim:
                lines.append(f"  {cpp_type} __get_{field_name}() {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{field_name}\");")
                lines.append(f"    return *({cpp_type}*)((ptrdiff_t)this + field.offset());")
                lines.append("  }")
                # Setter
                lines.append(f"  void __set_{field_name}({cpp_type} v) {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{field_name}\");")
                lines.append(f"    *({cpp_type}*)((ptrdiff_t)this + field.offset()) = v;")
                lines.append("  }")
            else:
                lines.append(f"  {cpp_type} __get_{field_name}() {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{field_name}\");")
                lines.append(f"    return *({cpp_type}*)((ptrdiff_t)this + field.offset());")
                lines.append("  }")
            lines.append("")

    lines.append("};")
    lines.append("")

    return "\n".join(lines)
```

- [ ] **Step 2: Test scaffold generation with a real class**

```bash
cd /Users/ebendler/projects/stfc-mod/scripts && python3 -c "
from lib.dump_parser import parse_dump
from lib.codegen import generate_scaffold
from pathlib import Path

index = parse_dump(Path('../dump/1.000.48286/dump.cs'))
key = ('Assembly-CSharp', 'Digit.Prime.Navigation', 'NavigationZoom')
dc = index.by_qualified_name[key]
print(generate_scaffold(dc, '1.000.48286')[:2000])
"
```

Expected: A compilable-looking header with properties, methods (with `GetMethod<>` templates), field accessors, and `get_class_helper()`.

- [ ] **Step 3: Test with a simpler class (Camera)**

```bash
cd /Users/ebendler/projects/stfc-mod/scripts && python3 -c "
from lib.dump_parser import parse_dump
from lib.codegen import generate_scaffold
from pathlib import Path

index = parse_dump(Path('../dump/1.000.48286/dump.cs'))
# Camera is in UnityEngine.CoreModule
for key, dc in index.by_qualified_name.items():
    if dc.name == 'Camera' and 'UnityEngine' in key[1]:
        print(generate_scaffold(dc, '1.000.48286')[:2000])
        break
"
```

Expected: Header with `farClipPlane`/`nearClipPlane` properties using `float` type.

- [ ] **Step 4: Commit**

```bash
git add scripts/lib/codegen.py
git commit -m "feat(codegen): add C++ header scaffold generator

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Fixer module — auto-fix and suggestions

**Files:**
- Create: `scripts/lib/fixer.py`

Auto-fixes safe assembly/namespace renames and generates suggestions for ambiguous changes.

- [ ] **Step 1: Create fixer.py**

Create `scripts/lib/fixer.py`:

```python
"""Auto-fix broken IL2CPP references and generate suggestions.

Processes Stage 2 validation issues:
- Auto-fixes: assembly/namespace renames, nested type suffix changes
- Suggestions: possible member renames (Levenshtein), class relocations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .models import DumpIndex, Issue, ModReference, RefType, Severity


@dataclass(frozen=True, slots=True)
class Fix:
    """An auto-applicable fix."""
    file: str
    line: int
    old_text: str
    new_text: str
    description: str


@dataclass(frozen=True, slots=True)
class Suggestion:
    """A suggested fix requiring manual review."""
    file: str
    line: int
    description: str


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if len(b) == 0:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr.append(min(curr[j] + 1, prev[j + 1] + 1, prev[j] + cost))
        prev = curr
    return prev[len(b)]


def analyze_issues(
    issues: list[Issue],
    index: DumpIndex,
    project_root: Path,
) -> tuple[list[Fix], list[Suggestion]]:
    """Analyze validation issues and produce fixes and suggestions."""
    fixes: list[Fix] = []
    suggestions: list[Suggestion] = []

    for issue in issues:
        ref = issue.ref
        match ref.type:
            case RefType.CLASS:
                _analyze_missing_class(ref, index, project_root, fixes, suggestions)
            case RefType.METHOD | RefType.FIELD | RefType.PROPERTY:
                _analyze_missing_member(ref, index, suggestions)
            case RefType.NESTED_TYPE:
                _analyze_missing_nested(ref, index, project_root, fixes, suggestions)
            case _:
                pass  # PARENT_CLASS, ICALL — no auto-fix logic

    return fixes, suggestions


def _analyze_missing_class(
    ref: ModReference,
    index: DumpIndex,
    project_root: Path,
    fixes: list[Fix],
    suggestions: list[Suggestion],
) -> None:
    if not ref.class_name:
        return

    # Check if the class exists under a different assembly/namespace
    matches = index.by_class_name.get(ref.class_name, [])

    if len(matches) == 1:
        dc = matches[0]
        if dc.assembly != ref.assembly or dc.namespace != ref.namespace:
            # Safe auto-fix: class name is unique, just the location changed
            src_path = project_root / ref.source_file
            if src_path.exists():
                old_call = f'il2cpp_get_class_helper("{ref.assembly}", "{ref.namespace}", "{ref.class_name}")'
                new_call = f'il2cpp_get_class_helper("{dc.assembly}", "{dc.namespace}", "{ref.class_name}")'

                parts: list[str] = []
                if dc.assembly != ref.assembly:
                    parts.append(f"assembly {ref.assembly} → {dc.assembly}")
                if dc.namespace != ref.namespace:
                    parts.append(f"namespace {ref.namespace} → {dc.namespace}")

                fixes.append(Fix(
                    file=ref.source_file,
                    line=ref.source_line,
                    old_text=old_call,
                    new_text=new_call,
                    description=f"{ref.class_name}: {', '.join(parts)}",
                ))
    elif len(matches) > 1:
        # Multiple matches — suggest, don't auto-fix
        locs = [f"({dc.assembly}, {dc.namespace})" for dc in matches]
        suggestions.append(Suggestion(
            file=ref.source_file,
            line=ref.source_line,
            description=f"{ref.class_name} found in multiple locations: {', '.join(locs)}",
        ))


def _analyze_missing_member(
    ref: ModReference,
    index: DumpIndex,
    suggestions: list[Suggestion],
) -> None:
    if not ref.class_name or not ref.member_name or not ref.assembly:
        return

    # Get the class from the dump
    key = (ref.assembly, ref.namespace or "", ref.class_name)
    dc = index.by_qualified_name.get(key)
    if dc is None:
        return  # Class itself is missing — handled by class fix

    # Find similar member names
    member_name = ref.member_name
    candidates: list[str] = []

    match ref.type:
        case RefType.METHOD:
            candidates = list(dc.methods.keys())
        case RefType.FIELD:
            candidates = dc.fields
        case RefType.PROPERTY:
            candidates = dc.properties

    # Check for substring matches and Levenshtein distance
    close_matches: list[str] = []
    for c in candidates:
        if c == member_name:
            continue
        # Substring match
        if member_name.lower() in c.lower() or c.lower() in member_name.lower():
            close_matches.append(c)
            continue
        # Levenshtein
        if _levenshtein(member_name.lower(), c.lower()) <= 3:
            close_matches.append(c)

    if close_matches:
        matches_str = ", ".join(close_matches[:3])
        suggestions.append(Suggestion(
            file=ref.source_file,
            line=ref.source_line,
            description=f"{ref.class_name}.{member_name} not found, possible match: {matches_str}",
        ))


def _analyze_missing_nested(
    ref: ModReference,
    index: DumpIndex,
    project_root: Path,
    fixes: list[Fix],
    suggestions: list[Suggestion],
) -> None:
    if not ref.class_name or not ref.member_name or not ref.assembly:
        return

    key = (ref.assembly, ref.namespace or "", ref.class_name)
    dc = index.by_qualified_name.get(key)
    if dc is None:
        return

    # Check for suffix change: <Name>d__NNN
    m = re.match(r'^(<\w+>d__)\d+$', ref.member_name)
    if m:
        prefix = m.group(1)
        for nt in dc.nested_types:
            if nt.startswith(prefix) and nt != ref.member_name:
                # Found matching prefix with different suffix — auto-fix
                src_path = project_root / ref.source_file
                if src_path.exists():
                    fixes.append(Fix(
                        file=ref.source_file,
                        line=ref.source_line,
                        old_text=f'"{ref.member_name}"',
                        new_text=f'"{nt}"',
                        description=f"{ref.member_name} → {nt}",
                    ))
                return

    # No prefix match — suggest
    if dc.nested_types:
        suggestions.append(Suggestion(
            file=ref.source_file,
            line=ref.source_line,
            description=f"{ref.class_name}.{ref.member_name} not found, available nested types: {', '.join(dc.nested_types[:5])}",
        ))


def apply_fixes(fixes: list[Fix], project_root: Path, *, dry_run: bool = False) -> int:
    """Apply fixes to source files. Returns count of fixes applied."""
    # Group fixes by file
    by_file: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_file.setdefault(fix.file, []).append(fix)

    applied = 0
    for file_path, file_fixes in by_file.items():
        full_path = project_root / file_path
        if not full_path.exists():
            continue

        content = full_path.read_text(encoding="utf-8")
        original = content
        for fix in file_fixes:
            if fix.old_text in content:
                if not dry_run:
                    content = content.replace(fix.old_text, fix.new_text, 1)
                applied += 1

        if not dry_run and content != original:
            full_path.write_text(content, encoding="utf-8")

    return applied
```

- [ ] **Step 2: Smoke test the fixer against real validation issues**

```bash
cd /Users/ebendler/projects/stfc-mod/scripts && python3 -c "
from lib.mod_extractor import extract_references
from lib.dump_parser import parse_dump
from lib.validator import validate
from lib.fixer import analyze_issues
from pathlib import Path

project_root = Path('..')
refs = extract_references(project_root / 'mods' / 'src')
index = parse_dump(project_root / 'dump' / '1.000.48286' / 'dump.cs')
issues = validate(refs, index)

fixes, suggestions = analyze_issues(issues, index, project_root)
print(f'Auto-fixable: {len(fixes)}')
for f in fixes[:5]:
    print(f'  {f.description}')
    print(f'    {f.file}:{f.line}')
print(f'\nSuggestions: {len(suggestions)}')
for s in suggestions[:5]:
    print(f'  {s.description}')
    print(f'    {s.file}:{s.line}')
"
```

Expected: Some auto-fixable issues (assembly renames like Canvas, HttpJob) and some suggestions.

- [ ] **Step 3: Commit**

```bash
git add scripts/lib/fixer.py
git commit -m "feat(codegen): add auto-fix and suggestion logic for broken references

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Main CLI script

**Files:**
- Create: `scripts/il2cpp-codegen.py`

The CLI with three subcommands: `fix`, `scaffold`, `scaffold-all`.

- [ ] **Step 1: Create il2cpp-codegen.py**

Create `scripts/il2cpp-codegen.py`:

```python
#!/usr/bin/env python3
"""Generate and fix IL2CPP C++ header scaffolds from game dump data.

Subcommands:
  fix           Auto-fix broken references, suggest ambiguous renames
  scaffold      Generate a header for one class
  scaffold-all  Generate headers for all mod-referenced classes
"""

from __future__ import annotations

import argparse
import importlib.util
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DUMP_DIR = PROJECT_ROOT / "dump"
MOD_SRC = PROJECT_ROOT / "mods" / "src"
PRIME_DIR = MOD_SRC / "prime"
GENERATED_DIR = PRIME_DIR / "generated"
DUMP_SCRIPT = PROJECT_ROOT / "scripts" / "il2cpp-dump.py"

sys.path.insert(0, str(Path(__file__).resolve().parent))

from lib.codegen import generate_scaffold
from lib.dump_parser import parse_dump
from lib.fixer import analyze_issues, apply_fixes
from lib.mod_extractor import extract_references
from lib.models import DumpIndex, RefType
from lib.validator import validate


def _load_dump_module():
    spec = importlib.util.spec_from_file_location("il2cpp_dump", DUMP_SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["il2cpp_dump"] = mod
    spec.loader.exec_module(mod)
    return mod


def _shared_setup(args) -> tuple[str, str, DumpIndex]:
    """Shared startup: detect version, ensure dump, parse dump.cs."""
    game_dir = Path(args.game_dir)
    version_override = getattr(args, "version", None)

    il2cpp_dump = _load_dump_module()
    game_files = il2cpp_dump.locate_game_files(game_dir)
    versions = il2cpp_dump.detect_versions(
        game_files.global_game_managers, override=version_override
    )
    game_version = versions.game_version
    unity_version = versions.unity_version or "unknown"

    print(f"Game version : {game_version}", file=sys.stderr)
    print(f"Unity version: {unity_version}", file=sys.stderr)

    dump_cs = DUMP_DIR / game_version / "dump.cs"
    if not dump_cs.exists():
        print(f"Running il2cpp-dump.py...", file=sys.stderr)
        cmd = [sys.executable, str(DUMP_SCRIPT), "--game-dir", str(game_dir)]
        if version_override:
            cmd += ["--version", version_override]
        result = subprocess.run(cmd)
        if result.returncode != 0:
            sys.exit("il2cpp-dump.py failed")

    print(f"Parsing dump.cs...", file=sys.stderr)
    index = parse_dump(dump_cs)
    print(f"Parsed {len(index.by_qualified_name)} classes", file=sys.stderr)

    return game_version, unity_version, index


def cmd_fix(args) -> int:
    game_version, _, index = _shared_setup(args)

    print(f"Extracting mod references...", file=sys.stderr)
    refs = extract_references(MOD_SRC)
    issues = validate(refs, index)

    if not issues:
        print("No issues found — all references valid.")
        return 0

    fixes, suggestions = analyze_issues(issues, index, PROJECT_ROOT)

    dry_run = args.dry_run
    prefix = "[dry-run] " if dry_run else ""

    if fixes:
        applied = apply_fixes(fixes, PROJECT_ROOT, dry_run=dry_run)
        print(f"\n{prefix}Auto-fixed {applied} references:")
        for f in fixes:
            print(f"  {f.description}")
            print(f"    {f.file}:{f.line}")
    else:
        print("\nNo auto-fixable issues found.")

    if suggestions:
        print(f"\nSuggestions (manual review needed):")
        for s in suggestions:
            print(f"  {s.description}")
            print(f"    {s.file}:{s.line}")

    # Count remaining unfixable issues
    fixable_files_lines = {(f.file, f.line) for f in fixes}
    suggestion_files_lines = {(s.file, s.line) for s in suggestions}
    unfixable = [
        i for i in issues
        if (i.ref.source_file, i.ref.source_line) not in fixable_files_lines
        and (i.ref.source_file, i.ref.source_line) not in suggestion_files_lines
    ]

    if unfixable:
        print(f"\n{len(unfixable)} issues could not be resolved:")
        for i in unfixable[:10]:
            print(f"  {i.message}")
            print(f"    {i.ref.source_file}:{i.ref.source_line}")
        return 1

    return 0


def cmd_scaffold(args) -> int:
    game_version, _, index = _shared_setup(args)

    class_name = args.class_name

    # Try qualified lookup: split on last dot
    dc = None
    cls = class_name  # may be overwritten below
    if "." in class_name:
        last_dot = class_name.rfind(".")
        ns = class_name[:last_dot]
        cls = class_name[last_dot + 1:]
        # Search all assemblies for this namespace + class
        matches = index.by_ns_class.get((ns, cls), [])
        if len(matches) == 1:
            dc = matches[0]
        elif len(matches) > 1:
            print(f"Multiple matches for {class_name}:")
            for m in matches:
                print(f"  ({m.assembly}, {m.namespace}, {m.name})")
            return 1

    # Fallback: name-only lookup (use extracted class name, not full qualified string)
    if dc is None:
        lookup_name = cls if "." in class_name else class_name
        matches = index.by_class_name.get(lookup_name, [])
        if len(matches) == 1:
            dc = matches[0]
        elif len(matches) > 1:
            print(f"Multiple matches for '{class_name}', please qualify:")
            for m in matches:
                fqn = f"{m.namespace}.{m.name}" if m.namespace else m.name
                print(f"  {fqn} (assembly: {m.assembly})")
            return 1

    if dc is None:
        # Try fuzzy match
        print(f"Class '{class_name}' not found in dump.")
        similar = [n for n in index.by_class_name if class_name.lower() in n.lower()][:5]
        if similar:
            print("Similar names:")
            for s in similar:
                print(f"  {s}")
        return 1

    header = generate_scaffold(dc, game_version)

    output_path = Path(args.output) if args.output else GENERATED_DIR / f"{dc.name.replace('`', '_')}.h"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(header, encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


def cmd_scaffold_all(args) -> int:
    game_version, _, index = _shared_setup(args)

    print(f"Extracting mod references...", file=sys.stderr)
    refs = extract_references(MOD_SRC)

    # Deduplicate referenced classes
    seen: set[tuple[str, str, str]] = set()
    classes_to_generate: list[tuple[str, str, str]] = []
    for ref in refs:
        if ref.type == RefType.CLASS and ref.assembly and ref.namespace is not None and ref.class_name:
            key = (ref.assembly, ref.namespace, ref.class_name)
            if key not in seen:
                seen.add(key)
                classes_to_generate.append(key)

    # Check for existing hand-written headers
    existing_headers = {p.stem for p in PRIME_DIR.glob("*.h") if p.parent == PRIME_DIR}

    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    generated = 0
    skipped = 0

    for assembly, namespace, class_name in classes_to_generate:
        # Skip if hand-written header exists
        clean_name = class_name.replace("`", "_")
        if clean_name in existing_headers:
            skipped += 1
            continue

        dc = index.by_qualified_name.get((assembly, namespace, class_name))
        if dc is None:
            print(f"  Skipping {class_name} — not found in dump", file=sys.stderr)
            continue

        header = generate_scaffold(dc, game_version)
        output_path = GENERATED_DIR / f"{clean_name}.h"
        output_path.write_text(header, encoding="utf-8")
        generated += 1

    print(f"Generated {generated} headers in {GENERATED_DIR}")
    print(f"Skipped {skipped} classes with existing hand-written headers")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    # fix
    p_fix = sub.add_parser("fix", help="Auto-fix broken references")
    p_fix.add_argument("--game-dir", required=True)
    p_fix.add_argument("--version")
    p_fix.add_argument("--dry-run", action="store_true")

    # scaffold
    p_scaffold = sub.add_parser("scaffold", help="Generate header for one class")
    p_scaffold.add_argument("class_name")
    p_scaffold.add_argument("--game-dir", required=True)
    p_scaffold.add_argument("--version")
    p_scaffold.add_argument("--output")

    # scaffold-all
    p_all = sub.add_parser("scaffold-all", help="Generate headers for all mod-referenced classes")
    p_all.add_argument("--game-dir", required=True)
    p_all.add_argument("--version")

    args = parser.parse_args()

    match args.command:
        case "fix":
            return cmd_fix(args)
        case "scaffold":
            return cmd_scaffold(args)
        case "scaffold-all":
            return cmd_scaffold_all(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 2: Make it executable**

```bash
chmod +x scripts/il2cpp-codegen.py
```

- [ ] **Step 3: Commit**

```bash
git add scripts/il2cpp-codegen.py
git commit -m "feat(codegen): add il2cpp-codegen CLI with fix, scaffold, scaffold-all

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: End-to-end testing

**Files:**
- Modify: any files as needed to fix issues

- [ ] **Step 1: Test `scaffold` with a single class**

```bash
python3 scripts/il2cpp-codegen.py scaffold NavigationZoom --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app"
```

Expected: Writes `mods/src/prime/generated/NavigationZoom.h`. Inspect the output for correct structure.

- [ ] **Step 2: Test `scaffold` with a qualified name**

```bash
python3 scripts/il2cpp-codegen.py scaffold Digit.Prime.Navigation.NavigationZoom --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app"
```

Expected: Same result as step 1.

- [ ] **Step 3: Test `scaffold-all`**

```bash
python3 scripts/il2cpp-codegen.py scaffold-all --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app"
```

Expected: Generates headers in `mods/src/prime/generated/` for classes that don't have hand-written headers. Reports count of generated and skipped.

- [ ] **Step 4: Test `fix --dry-run`**

```bash
python3 scripts/il2cpp-codegen.py fix --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app" --dry-run
```

Expected: Shows auto-fixable issues and suggestions without modifying files. Should find assembly renames like Canvas, HttpJob, etc.

- [ ] **Step 5: Test `fix` (actual)**

```bash
python3 scripts/il2cpp-codegen.py fix --game-dir "/Users/ebendler/Library/Application Support/Star Trek Fleet Command/Games/Star Trek Fleet Command/Star Trek Fleet Command/default/game/Star Trek Fleet Command.app"
```

Expected: Applies fixes to source files. Verify with `git diff` that the changes look correct (assembly strings updated).

- [ ] **Step 6: Fix any issues found, commit**

```bash
git add scripts/
git commit -m "fix(codegen): address issues found during end-to-end testing

Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>"
```

Only commit if there were actual changes. Do NOT commit the generated headers or the auto-fixed source changes — those are for the user to review.
