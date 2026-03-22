# IL2CPP Mod Reference Validator Design

## Purpose

Detect broken or changed game API references in the mod's source code by cross-referencing against an Il2CppDumper dump of the current game binary. When Scopely ships a game update that renames, removes, or changes the signature of classes/methods/fields/properties, this script reports exactly what broke and where in the mod source it's referenced.

## Context

- The mod resolves 85+ game classes, 50+ methods, 70+ fields, 60+ properties, 16 icalls, and a few nested types — all by string name at runtime
- Currently, breakages are discovered after the fact via crashes or debug logs
- Stage 1 (`scripts/il2cpp-dump.py`) produces a versioned dump including `dump.cs` (C# signatures) and `script.json` (method metadata)
- Both dump.cs and the IL2CPP runtime API read names from the same `global-metadata.dat`, so string matching is reliable
- No existing tool in the IL2CPP ecosystem does this — modders typically diff dump.cs manually or discover breakage at runtime

## Script: `scripts/il2cpp-validate.py`

**Language:** Python 3.12+ (stdlib only, no pip dependencies)

### CLI Interface

```
scripts/il2cpp-validate.py \
  --game-dir <path> \
  [--version <override>] \
  [--dump-only]
```

| Argument | Required | Description |
|---|---|---|
| `--game-dir` | yes | Path to game directory (passed through to Stage 1 if dump needed) |
| `--version` | no | Override game version (passed through to Stage 1) |
| `--dump-only` | no | Run the dump but skip validation |

### Data Flow

1. Detect game version — import `detect_versions()` and `locate_game_files()` from `il2cpp-dump.py` (the script is importable via `__name__` guard). Do not duplicate this logic.
2. Check if `dump/{version}/dump.cs` exists — if not, shell out to `python3 scripts/il2cpp-dump.py --game-dir ... [--version ...]` as a subprocess
3. If `--dump-only`, stop here
4. Parse mod source (`mods/src/**/*.{cc,h}`) to extract all string-based game references
5. Parse `dump.cs` to build a class/member lookup
6. Cross-reference every mod reference against the dump lookup
7. Diff against previous version's sidecar (if one exists) to detect signature changes
8. Write `dump/{version}/mod-references.json` sidecar
9. Print report, exit 0 if clean, exit 1 if issues found

### Step 1: Mod Source Extraction

Scan `mods/src/**/*.{cc,h}` with regex to extract all string-based game references. Each file is parsed independently — `#include` directives are not followed. Each reference is tagged with source file and line number.

**Patterns to extract:**

| Pattern | Produces |
|---|---|
| `il2cpp_get_class_helper("Assembly", "Namespace", "Class")` | Class reference |
| `.GetMethod("Name")` / `.GetMethod("Name", N)` | Method reference (with optional arg count) |
| `.GetMethodInfo("Name")` / `.GetMethodInfo("Name", N)` | Method reference (with optional arg count) |
| `.GetMethodSpecial<T>("Name", ...)` / `.GetMethodSpecial2<T>(obj, "Name")` | Method reference |
| `.GetMethodInfoSpecial("Name", ...)` | Method reference |
| `.GetVirtualMethod<T>("Name")` / `.GetVirtualMethod<T>("Name", N)` | Method reference (with optional arg count) |
| `.GetInvokeMethod<T>("Name")` / `.GetInvokeMethod<T>("Name", N)` | Method reference (with optional arg count) |
| `.GetField("Name")` / `.GetStaticField("Name")` | Field reference |
| `.GetProperty("Name")` | Property reference |
| `.GetNestedType("Name")` | Nested type reference |
| `.GetParent("Name")` | Parent class reference (class hierarchy traversal) |
| `il2cpp_resolve_icall_typed<T>("Full::Signature(Args)")` | Icall reference |

All `GetMethod*` and `GetVirtualMethod` variants produce method references. The `Special` variants include a type filter lambda for overload resolution, but we only validate the method name exists (type-level matching is Stage 3 territory).

**Variable-to-class resolution:**

Methods/fields/properties are called on class helper variables, not directly on `il2cpp_get_class_helper`. Two patterns are used:

Pattern 1 — Direct assignment in patch files:
```cpp
static auto class_helper = il2cpp_get_class_helper("Assembly", "NS", "Foo");
static auto method = class_helper.GetMethod("Bar");
```

Pattern 2 — Static method in `prime/*.h` headers:
```cpp
struct Foo {
    static IL2CppClassHelper& get_class_helper() {
        static auto helper = il2cpp_get_class_helper("Assembly", "NS", "Foo");
        return helper;
    }
    // later:
    auto m = get_class_helper().GetMethod("Bar");
};
```

The extractor tracks assignments of `il2cpp_get_class_helper(...)` to variable names, scoped per file. When it sees `varname.GetMethod(...)` or `get_class_helper().GetMethod(...)`, it resolves back to the class. This works because the codebase consistently uses `static auto` assignments.

**GetParent resolution:**

`GetParent("Name")` traverses the IL2CPP class hierarchy to find a parent class by name. Example:
```cpp
static IL2CppClassHelper class_helper = Y::get_class_helper().GetParent("Widget`1");
```

For validation purposes, `GetParent` produces a class reference — we verify the parent class name exists in the dump. The class is looked up by name only (not by assembly/namespace), since it could be in any ancestor. The validator checks that a class with that name exists somewhere in the dump.

**Output:** A list of reference objects, each with:
- `type`: class | method | field | property | nested_type | parent_class | icall
- `assembly`, `namespace`, `class_name`: the resolved class (not for icalls or parent_class)
- `member_name`: the method/field/property/nested type name (not for class, parent_class, or icall refs)
- `parent_name`: for parent_class refs, the parent class name to look up
- `arg_count`: for methods, if specified (else None)
- `icall_signature`: for icalls, the full signature string
- `source_file`, `source_line`: location in mod source

### Step 2: dump.cs Parsing

Parse Il2CppDumper's `dump.cs` output to build a structured lookup: `(assembly, namespace, class)` → class info.

**Class info structure:**
```python
@dataclass
class DumpClass:
    methods: dict[str, list[str]]   # name → [full signatures]
    fields: list[str]               # field names
    properties: list[str]           # property names
    nested_types: list[str]         # nested type names
```

**Parsing strategy:**

dump.cs is structured pseudo-C# with consistent formatting:

```cs
// Image 0: Assembly-CSharp.dll - 0

// Namespace: Digit.Prime.Navigation
public class NavigationZoom : MonoBehaviour
{
    public float _depth; // 0x18
    public float Distance { get; }
    public void SetDepth(float depth) { }
}
```

The parser tracks:
- **Current assembly** from `// Image N: AssemblyName.dll` comment lines — strip the `.dll` suffix to match the mod's assembly strings (e.g., `Assembly-CSharp.dll` → `Assembly-CSharp`)
- **Current namespace** from `// Namespace: X` comment lines
- **Class declarations** with their nesting depth (brace counting) for nested type resolution
- **Members** within each class: field declarations, property declarations, method declarations

**A secondary lookup by class name only** (without assembly/namespace) is also built, for `GetParent()` validation where only the class name is known.

**Edge cases:**

| Case | dump.cs format | Mod format | Resolution |
|---|---|---|---|
| Assembly suffix | `Assembly-CSharp.dll` | `Assembly-CSharp` | Strip `.dll` from Image lines |
| Nested types | Nested class block inside parent | `"Parent.Child"` | Track nesting depth, build dot-separated key |
| Generics | `Foo<T>` | `"Foo\`1"` | Convert dump.cs generic syntax to backtick-arity |
| Overloaded methods | Multiple methods with same name | `GetMethod("Name", N)` | Store all overloads, match by arg count |
| Compiler-generated | `<Name>d__134` | `"<Name>d__134"` | Names match exactly, no conversion needed |

### Step 3: Icall Validation

Icall signatures in the mod use the format `Namespace.Class::MethodName(ParamTypes)` (e.g., `UnityEngine.Input::GetKeyDownInt(UnityEngine.KeyCode)`). These methods do appear in dump.cs as regular method declarations on their respective classes. Validation decomposes the icall signature into class + method name and checks the method exists on the class in the dump, the same as any other method reference.

For example, `UnityEngine.Input::GetKeyDownInt(UnityEngine.KeyCode)` is split on `::` to get `UnityEngine.Input` and `GetKeyDownInt`. The class portion is then split on the last `.` to get namespace `UnityEngine` and class `Input`. Since icall strings don't carry an assembly name, the lookup uses a `(namespace, class)` index into the dump (matching any assembly). This is more precise than the name-only lookup used for `GetParent`.

### Step 4: Cross-Reference Validation

For each mod reference, check against the dump lookup:

| Reference type | Validation |
|---|---|
| Class | `(assembly, namespace, class)` tuple exists in dump |
| Method | Method name exists on class. If arg count specified, verify an overload with that parameter count exists |
| Field | Field name exists on class |
| Property | Property name exists on class |
| Nested type | Nested type name exists within parent class |
| Parent class | Class name exists somewhere in the dump (name-only lookup) |
| Icall | Decomposed to class + method name, validated like a regular method |

### Step 5: Signature Sidecar

After validation, write `dump/{version}/mod-references.json`:

```json
{
  "game_version": "1.000.48286",
  "unity_version": "6000.0.59f2",
  "references": {
    "Assembly-CSharp::Digit.Prime.Navigation.NavigationZoom": {
      "methods": {
        "SetDepth": ["public void SetDepth(float depth)"],
        "Update": ["public void Update()"]
      },
      "fields": ["_depth", "_viewRadius", "_zoomDelta"],
      "properties": ["Distance"]
    }
  },
  "icalls": {
    "UnityEngine.Input::GetKeyDownInt": {
      "class": "UnityEngine.Input",
      "signatures": ["private static bool GetKeyDownInt(KeyCode key)"]
    }
  }
}
```

The sidecar captures the full dump.cs signatures for every reference the mod uses. This enables signature change detection across game versions.

**Diffing logic:**
- On each run, look for `mod-references.json` in other version directories under `dump/`, sorted by version descending — use the most recent previous version
- If a previous sidecar exists, compare: for each reference that exists in both, check if signatures changed
- Report signature changes alongside missing references
- Methods with no arg count specified: still diff their full signature lists between versions to detect changes

### Step 6: Report

Human-readable report to stdout:

```
Validating mod references against dump 1.000.48286...

MISSING CLASS: Assembly-CSharp :: Digit.Prime.Chat.ChatPreviewController
  Referenced in: mods/src/patches/parts/chat.cc:42

MISSING METHOD: NavigationZoom.SetDepth (expected 1 arg, found 2)
  Referenced in: mods/src/patches/parts/zoom.cc:18

SIGNATURE CHANGED: NavigationZoom.Update
  Was:  public void Update()
  Now:  public void Update(float deltaTime)
  Referenced in: mods/src/patches/parts/zoom.cc:55

MISSING ICALL: UnityEngine.Input::GetKeyDownInt
  Referenced in: mods/src/patches/parts/hotkeys.cc:12

Checked 85 classes, 50 methods, 70 fields, 60 properties, 16 icalls
Found 2 missing references, 1 signature change
```

**Exit codes:**
- 0: all references valid, no signature changes
- 1: missing references or signature changes found

## Directory Structure

No new directories. Output goes into the existing dump version directory:

```
dump/
  1.000.48286/
    dump.cs               # from Stage 1 (gitignored)
    script.json           # from Stage 1 (tracked)
    mod-references.json   # from Stage 2 (tracked — small, structured)
    ...
scripts/
  il2cpp-dump.py          # Stage 1
  il2cpp-validate.py      # Stage 2
```

`mod-references.json` should be tracked in git — it's small and serves as the baseline for detecting signature changes across game updates.

## Error Handling

- Missing game directory: clear message, exit
- Stage 1 failure: propagate il2cpp-dump.py's error output and exit code
- Unparseable dump.cs: warn about lines that couldn't be parsed, continue with what was extracted
- Unresolvable variable in mod source (e.g., `GetMethod` on a variable that wasn't traced to a class): warn with file:line, skip that reference
- No previous sidecar: skip signature diffing, just validate existence

## Future Work

- **Stage 3:** Auto-generate/update `prime/` headers from the dump, using the validation output to identify what needs changing
- **CI integration:** JSON output mode for machine-readable results
- **Hook signature matching:** Parse C++ `SPUD_STATIC_DETOUR` parameter lists and match against dump.cs method signatures (requires IL2CPP-to-C# type mapping)
