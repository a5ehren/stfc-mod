# IL2CPP Code Generator Design

## Purpose

Automate maintenance of the mod's `prime/` C++ headers by:
1. **Fixing** broken string references (assembly/namespace renames) found by Stage 2
2. **Scaffolding** new C++ headers from the Il2CppDumper output, following existing codebase conventions

This is Stage 3 of the IL2CPP pipeline: Stage 1 dumps, Stage 2 validates, Stage 3 fixes and generates.

## Context

- The mod has ~90 hand-written `prime/*.h` headers that wrap IL2CPP game classes
- Each header contains `il2cpp_get_class_helper("Assembly", "Namespace", "Class")` with string-based member access
- When the game updates, assembly names, namespaces, and member names can change
- Stage 2 (`il2cpp-validate.py --format json`) reports exactly what broke
- Developers currently fix these manually by diffing dump.cs — tedious and error-prone
- New headers are written from scratch by reading dump.cs — also tedious

## Script: `scripts/il2cpp-codegen.py`

**Language:** Python 3.12+ (stdlib only, no pip dependencies)

### CLI Interface

```
scripts/il2cpp-codegen.py fix --game-dir <path> [--dry-run]
scripts/il2cpp-codegen.py scaffold <class-name> --game-dir <path> [--output <path>]
scripts/il2cpp-codegen.py scaffold-all --game-dir <path>
```

| Subcommand | Description |
|---|---|
| `fix` | Auto-fix safe renames in existing source, print suggestions for ambiguous changes |
| `scaffold <name>` | Generate a header for one class by fully-qualified name (e.g., `Digit.Prime.Navigation.NavigationZoom`) |
| `scaffold-all` | Generate headers for all classes currently referenced by the mod |

| Flag | Applies to | Description |
|---|---|---|
| `--game-dir` | all | Path to game directory (passed to Stage 1/2 if dump needed) |
| `--version` | all | Override game version |
| `--dry-run` | fix | Show what would change without writing files |
| `--output` | scaffold | Override output path (default: `mods/src/prime/generated/ClassName.h`) |

`--version` is passed through to Stage 1 (dump) and Stage 2 (validation) when they are invoked internally.

### Shared Setup

All subcommands share the same startup:
1. Detect game version — import from `il2cpp-dump.py`
2. Ensure dump exists — shell out to Stage 1 if needed
3. Parse dump.cs into `DumpIndex` — reuse `scripts/lib/dump_parser.py`
4. Extract mod references — reuse `scripts/lib/mod_extractor.py` (for `fix` and `scaffold-all`)

### Subcommand: `fix`

**Input:** Stage 2 validation issues (run `validate()` internally, not via subprocess).

**Auto-fixable cases** (applied directly to source files):

| Case | Detection | Fix |
|---|---|---|
| Assembly renamed | Class name + namespace identical, different assembly in dump | Replace assembly string in `il2cpp_get_class_helper(...)` call |
| Namespace renamed | Class name + assembly identical, different namespace in dump | Replace namespace string |
| Both renamed | Class name identical, found via name-only lookup in dump | Replace both assembly and namespace strings |
| Nested type suffix changed | Pattern `<Name>d__NNN` — same `<Name>d__` prefix, different number | Replace the full nested type string |

For each auto-fix, the tool:
1. Reads the source file
2. Finds the exact `il2cpp_get_class_helper("old", "old", "ClassName")` string
3. Replaces with the corrected assembly/namespace from the dump
4. Writes the file back

For nested type suffix changes (e.g., `<Tow>d__170` → `<Tow>d__200`), the tool finds the `GetNestedType("old")` call and replaces the string argument.

**Suggested fixes** (printed, not applied):

| Case | Detection | Output |
|---|---|---|
| Member possibly renamed | Member missing, similar name exists on same class (substring or Levenshtein ≤ 3) | Print old → new suggestion with file:line |
| Class moved entirely | Class name found in dump under different assembly + namespace | Print old → new location |

**Dry-run mode (`--dry-run`):** Prints all changes that would be made without writing any files. Same output format as normal mode but prefixed with `[dry-run]`.

**Output format:**

```
Auto-fixed 3 references:
  Canvas: assembly UnityEngine.UI → UnityEngine.UIModule
    mods/src/prime/Canvas.h:12
  HttpJob: assembly Digit.Engine.HTTPClient.Runtime → Digit.Engine.Network
    mods/src/prime/HttpJob.h:29
  <Tow>d__170 → <Tow>d__200
    mods/src/prime/FleetsManager.h:41

Suggestions (manual review needed):
  AppConfig._appConfig not found, possible match: _applicationConfig
    mods/src/patches/parts/testing.cc:96
  SectionStorage._sectionStorage not found, possible match: _storage
    mods/src/prime/Hub.h:233
```

Exit codes:
- 0 = all Stage 2 issues were either auto-fixed or are soft suggestions (possible renames, inherited members)
- 1 = issues remain that could not be auto-fixed and are not mere suggestions (e.g., class completely missing from dump with no similar match)

### Subcommand: `scaffold <class-name>`

**Input:** A fully-qualified class name (e.g., `Digit.Prime.Navigation.NavigationZoom` or just `NavigationZoom` for name-only lookup).

**Output:** A C++ header file following existing `prime/` conventions.

**Lookup:** Try qualified name first (splitting on last `.` for namespace vs class). If not found, fall back to name-only lookup. If multiple matches, list them and ask the user to qualify.

**Type mapping:**

| C# type | C++ type |
|---|---|
| `bool` / `System.Boolean` | `bool` |
| `int` / `System.Int32` | `int32_t` |
| `long` / `System.Int64` | `int64_t` |
| `uint` / `System.UInt32` | `uint32_t` |
| `ulong` / `System.UInt64` | `uint64_t` |
| `float` / `System.Single` | `float` |
| `double` / `System.Double` | `double` |
| `string` / `System.String` | `Il2CppString*` |
| `void` / `System.Void` | `void` |
| `byte` / `System.Byte` | `uint8_t` |
| `sbyte` / `System.SByte` | `int8_t` |
| `short` / `System.Int16` | `int16_t` |
| `ushort` / `System.UInt16` | `uint16_t` |
| `char` / `System.Char` | `uint16_t` |
| Any other type | `void* /* OriginalTypeName */` |

**Method signature parsing:**

The dump parser currently stores method signatures as full strings like `public void SetDepth(float depth) { }`. The codegen module must parse these to extract:
- Return type (e.g., `void`, `float`, `FleetPlayerData`)
- Parameter types and names (e.g., `float depth`, `int index`)

This parsing is done in the codegen module (not the dump parser) since it's specific to code generation. The parser extracts: access modifier, optional `static`/`virtual`/`abstract`/`override` modifiers, return type, method name, and parameter list. Each parameter is split into type and name.

The return type and parameter types are then mapped through the type mapping table above. For the `GetMethod` template parameter, the C++ function pointer signature is constructed as `ReturnType(ClassName*, MappedArg1, MappedArg2, ...)` — the first parameter is always a pointer to the class (the implicit `this`).

**Generated header structure:**

```cpp
#pragma once
// Auto-generated from dump {version} — edit as needed

#include <il2cpp/il2cpp_helper.h>
#include <cstdint>

struct ClassName {
public:
  // --- Properties ---
  __declspec(property(get = __get_PropName)) float PropName;
  __declspec(property(get = __get_ObjProp)) void* /* GameType */ ObjProp;

  // --- Methods ---
  void MethodName(float arg0) {
    static auto m = get_class_helper().GetMethod<void(ClassName*, float)>("MethodName");
    m(this, arg0);
  }

  float GetValue() {
    static auto m = get_class_helper().GetMethod<float(ClassName*)>("GetValue");
    return m(this);
  }

  // Methods with unmapped types use void* and require manual editing:
  void* /* GameType */ GetSomething(void* /* OtherType */ arg0) {
    static auto m = get_class_helper().GetMethod<void* /* GameType */ (ClassName*, void* /* OtherType */)>("GetSomething");
    return m(this, arg0);
  }

private:
  static IL2CppClassHelper& get_class_helper() {
    static auto class_helper =
        il2cpp_get_class_helper("Assembly", "Namespace", "ClassName");
    return class_helper;
  }

public:
  // --- Property accessors ---
  float __get_PropName() {
    static auto prop = get_class_helper().GetProperty("PropName");
    return *prop.Get<float>(this);
  }

  void* /* GameType */ __get_ObjProp() {
    static auto prop = get_class_helper().GetProperty("ObjProp");
    return prop.GetRaw<void>(this);
  }

  // --- Field accessors ---
  float __get__fieldName() {
    static auto field = get_class_helper().GetField("_fieldName");
    return *(float*)((ptrdiff_t)this + field.offset());
  }

  void __set__fieldName(float v) {
    static auto field = get_class_helper().GetField("_fieldName");
    *(float*)((ptrdiff_t)this + field.offset()) = v;
  }
};
```

**Conventions followed:**
- `#pragma once` header guard
- `struct` (not `class`) — existing headers use both, generator standardizes on `struct`
- `__declspec(property)` for properties with getters (and setters if dump shows both `get` and `set`)
- Property accessors: `Get<T>` for primitive value types (with dereference), `GetRaw<T>` for object/pointer types. Existing headers are inconsistent on this (`Camera.h` uses `GetRaw` for floats, `NavigationZoom.h` uses `Get`); the generator standardizes on `Get<T>` for primitives which is the correct IL2CPP unboxing path.
- Field accessors use offset-based access matching existing pattern
- Method wrappers use `GetMethod<ReturnType(ClassName*, Args...)>("Name")` with the full function pointer type template parameter — this is required for the returned function pointer to be callable
- Static `get_class_helper()` private method
- All members included (public, protected, private) — private fields are commonly accessed by the mod
- Property accessor methods (`get_X`, `set_X`) are excluded from the methods section since they're covered by property declarations
- Static methods omit the `this` pointer from both the wrapper and the `GetMethod` template

**Output location:**
- Default: `mods/src/prime/generated/ClassName.h`
- Override with `--output`

### Subcommand: `scaffold-all`

Runs `scaffold` for every class referenced by the mod (extracted via `mod_extractor.extract_references()`). Deduplicates by `(assembly, namespace, class_name)`. Skips classes that already have a hand-written header in `mods/src/prime/` — detected by checking if a file with the class name exists in `mods/src/prime/` (not in the `generated/` subdirectory). For example, if `mods/src/prime/NavigationZoom.h` exists, `NavigationZoom` is skipped.

Output: `mods/src/prime/generated/` with one file per class.

## Directory Structure

```
mods/src/prime/
  generated/           # auto-generated scaffolds (gitignored or tracked, user choice)
    NavigationZoom.h
    FleetPlayerData.h
    ...
  NavigationZoom.h     # hand-written (existing, unchanged)
  FleetPlayerData.h    # hand-written (existing, unchanged)
  ...
scripts/
  il2cpp-codegen.py    # Stage 3
  il2cpp-validate.py   # Stage 2
  il2cpp-dump.py       # Stage 1
  lib/
    models.py
    mod_extractor.py
    dump_parser.py
    validator.py
    codegen.py          # new: scaffold generation + type mapping
    fixer.py            # new: auto-fix + suggestion logic
```

## Error Handling

- Missing dump: auto-runs Stage 1
- Class not found for scaffold: list similar names from dump, suggest qualified name
- Multiple matches for unqualified name: list all matches with assembly/namespace
- Fix applied to file that has other syntax on the same line: warn, skip that fix
- Source file is read-only or missing: warn, skip

## Future Work

- **Full C++ type resolution:** Map game types to existing `prime/` headers (e.g., if `HullSpec.h` exists, use `HullSpec*` instead of `void*`)
- **Incremental scaffold updates:** When game updates, regenerate scaffolds and show diff
- **Hook signature validation:** Match `SPUD_STATIC_DETOUR` parameter types against dump (Stage 2 future work)
