# IL2CPP Tools

Scripts for keeping the mod's IL2CPP bindings up to date when Scopely ships game updates.

## Prerequisites

- Python 3.12+
- .NET SDK/runtime 7+ (`dotnet` on PATH)
- Game installed locally

## The Pipeline

The three scripts form a pipeline. Each stage builds on the previous:

```
il2cpp-dump.py → il2cpp-validate.py → il2cpp-codegen.py
   (dump)            (check)              (fix/generate)
```

You can run them independently, but the later stages will automatically invoke the earlier ones if their output is missing.

## Stage 1: Dump (`scripts/il2cpp-dump.py`)

Extracts all class/method/field/property signatures from the game binary using [Il2CppDumper](https://github.com/Perfare/Il2CppDumper). Downloads and installs the tool automatically on first run.

```bash
python3 scripts/il2cpp-dump.py \
  --game-dir "/path/to/Star Trek Fleet Command.app"
```

Output goes to `dump/{version}/` (e.g., `dump/1.000.48286/`):

| File | Size | Description |
|---|---|---|
| `dump.cs` | ~48 MB | C# class/method/field/property signatures |
| `script.json` | ~130 MB | Structured method metadata with addresses |
| `il2cpp.h` | ~116 MB | C++ header definitions |
| `stringliteral.json` | ~3 MB | String literal table |
| `DummyDll/` | ~155 files | Shim .NET assemblies |

**Flags:**
- `--version <ver>` — Override auto-detected game version
- `--reinstall` — Force re-download of Il2CppDumper

**Notes:**
- On macOS with Homebrew dotnet, the script auto-detects `DOTNET_ROOT`
- Patches Il2CppDumper's runtimeconfig.json for .NET forward compatibility
- Handles FAT binary platform selection automatically (selects arm64)

## Stage 2: Validate (`scripts/il2cpp-validate.py`)

Scans the mod source (`mods/src/`) for all string-based IL2CPP references and checks them against the dump. Reports missing classes, methods, fields, properties, and signature changes between game versions.

```bash
# Human-readable report
python3 scripts/il2cpp-validate.py \
  --game-dir "/path/to/Star Trek Fleet Command.app"

# Machine-readable JSON (progress on stderr, JSON on stdout)
python3 scripts/il2cpp-validate.py \
  --game-dir "/path/to/Star Trek Fleet Command.app" \
  --format json
```

Example output:

```
MISSING CLASS: UnityEngine.UI :: UnityEngine.UI.Canvas
  Referenced in: mods/src/prime/Canvas.h:12

MISSING METHOD: Digit.PrimeServer.Core.GameServerModelRegistry.ProcessResultInternal
  Referenced in: mods/src/patches/parts/sync.cc:2122

SIGNATURE CHANGED: NavigationZoom.Update
  Was:  public void Update()
  Now:  public void Update(float deltaTime)
  Referenced in: mods/src/patches/parts/zoom.cc:55

Checked 137 classes, 120 methods, 118 fields, 97 properties, 15 icalls
Found 65 missing references
```

**Flags:**
- `--version <ver>` — Override game version
- `--format {text,json}` — Output format (default: text)
- `--dump-only` — Just ensure the dump exists, skip validation

**What it checks:**
- `il2cpp_get_class_helper("Assembly", "Namespace", "Class")` calls
- `.GetMethod()`, `.GetMethodInfo()`, `.GetMethodSpecial()`, `.GetVirtualMethod()`, `.GetInvokeMethod()` calls
- `.GetField()`, `.GetStaticField()` calls
- `.GetProperty()` calls
- `.GetNestedType()`, `.GetParent()` calls
- `il2cpp_resolve_icall_typed<T>()` calls

**Sidecar:** Writes `dump/{version}/mod-references.json` — a snapshot of what the mod references and their signatures. When you validate against a new game version, it diffs against the previous sidecar to detect signature changes.

**Exit codes:** 0 = clean, 1 = issues found.

## Stage 3: Codegen (`scripts/il2cpp-codegen.py`)

Fixes broken references and generates C++ header scaffolds from the dump.

### Fix broken references

```bash
# Preview what would change
python3 scripts/il2cpp-codegen.py fix \
  --game-dir "/path/to/Star Trek Fleet Command.app" \
  --dry-run

# Apply fixes
python3 scripts/il2cpp-codegen.py fix \
  --game-dir "/path/to/Star Trek Fleet Command.app"
```

**Auto-fixes:**
- Assembly renamed (e.g., `UnityEngine.UI` → `UnityEngine.UIModule`)
- Namespace renamed
- Both assembly and namespace renamed (looked up by class name)
- Compiler-generated nested type suffix changed (e.g., `<Tow>d__170` → `<Tow>d__200`)

**Suggestions** (printed but not applied):
- Member possibly renamed (fuzzy match by name similarity)
- Class found in multiple locations (ambiguous)

### Generate a header scaffold

```bash
# By class name
python3 scripts/il2cpp-codegen.py scaffold NavigationZoom \
  --game-dir "/path/to/Star Trek Fleet Command.app"

# By qualified name
python3 scripts/il2cpp-codegen.py scaffold Digit.Prime.Navigation.NavigationZoom \
  --game-dir "/path/to/Star Trek Fleet Command.app"

# Custom output path
python3 scripts/il2cpp-codegen.py scaffold Camera \
  --game-dir "/path/to/Star Trek Fleet Command.app" \
  --output mods/src/prime/Camera.h
```

Generates a C++ header in `mods/src/prime/generated/ClassName.h` following the project's conventions: `__declspec(property)`, `get_class_helper()`, typed `GetMethod<>` templates, offset-based field access.

Primitive types (`float`, `int`, `bool`, etc.) are mapped automatically. Game types become `void* /* OriginalType */` — edit these to use the actual C++ types from your other headers.

### Generate scaffolds for all referenced classes

```bash
python3 scripts/il2cpp-codegen.py scaffold-all \
  --game-dir "/path/to/Star Trek Fleet Command.app"
```

Generates headers for every class the mod references that doesn't already have a hand-written header in `mods/src/prime/`. Output goes to `mods/src/prime/generated/`.

## Typical Workflow

When Scopely ships a game update:

```bash
GAME="/path/to/Star Trek Fleet Command.app"

# 1. Dump the new version
python3 scripts/il2cpp-dump.py --game-dir "$GAME"

# 2. Check what broke
python3 scripts/il2cpp-validate.py --game-dir "$GAME"

# 3. Auto-fix what we can
python3 scripts/il2cpp-codegen.py fix --game-dir "$GAME" --dry-run  # preview
python3 scripts/il2cpp-codegen.py fix --game-dir "$GAME"            # apply

# 4. Re-validate to see what's left
python3 scripts/il2cpp-validate.py --game-dir "$GAME"

# 5. Manually fix remaining issues using the suggestions and dump.cs
```

## Known Limitations

- **Inherited members** are not resolved. If the mod accesses `.enabled` on `CanvasController` but `enabled` is declared on the Unity base class `Behaviour`, the validator reports it as missing. The mod code works at runtime because IL2CPP traverses the class hierarchy — but the validator only checks the declaring class.

- **Property types in scaffolds** are derived from getter method return types. If no getter exists in the dump, the type defaults to `void*`.

- **Game types in scaffolds** (anything not a primitive) are generated as `void*` pointers. Edit these to reference your existing `prime/` headers.

- **Overloaded methods** are validated by name and arg count only, not parameter types. If two overloads have the same name and same number of parameters with different types, the validator won't distinguish them.
