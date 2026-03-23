"""C# → C++ type mapping and method signature parsing for IL2CPP codegen."""

from __future__ import annotations

import re
from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Type mapping
# ---------------------------------------------------------------------------

TYPE_MAP: dict[str, str] = {
    # C# aliases
    "bool": "bool",
    "int": "int32_t",
    "long": "int64_t",
    "uint": "uint32_t",
    "ulong": "uint64_t",
    "float": "float",
    "double": "double",
    "string": "Il2CppString*",
    "void": "void",
    "byte": "uint8_t",
    "sbyte": "int8_t",
    "short": "int16_t",
    "ushort": "uint16_t",
    "char": "uint16_t",
    # System.* fully-qualified names
    "System.Boolean": "bool",
    "System.Int32": "int32_t",
    "System.Int64": "int64_t",
    "System.UInt32": "uint32_t",
    "System.UInt64": "uint64_t",
    "System.Single": "float",
    "System.Double": "double",
    "System.String": "Il2CppString*",
    "System.Void": "void",
    "System.Byte": "uint8_t",
    "System.SByte": "int8_t",
    "System.Int16": "int16_t",
    "System.UInt16": "uint16_t",
    "System.Char": "uint16_t",
}

PRIMITIVE_CPP_TYPES: set[str] = {
    "bool",
    "int8_t",
    "int16_t",
    "int32_t",
    "int64_t",
    "uint8_t",
    "uint16_t",
    "uint32_t",
    "uint64_t",
    "float",
    "double",
    "void",
}


def map_type(cs_type: str) -> str:
    """Map a C# type string to a C++ type string.

    Unknown types, arrays, and generics become ``void* /* OriginalType */``.
    """
    cs_type = cs_type.strip()

    # Arrays and generics → opaque pointer
    if cs_type.endswith("[]") or "<" in cs_type:
        return f"void* /* {cs_type} */"

    result = TYPE_MAP.get(cs_type)
    if result is not None:
        return result

    # Unknown game type → opaque pointer
    return f"void* /* {cs_type} */"


def is_primitive(cpp_type: str) -> bool:
    """Return True if *cpp_type* is a value/primitive C++ type."""
    return cpp_type in PRIMITIVE_CPP_TYPES


# ---------------------------------------------------------------------------
# C++ header scaffold generator
# ---------------------------------------------------------------------------

def _cpp_class_name(name: str) -> str:
    """Convert a C# class name to a valid C++ identifier.

    Backtick-arity generics (``Foo`1``) become ``Foo_1``.
    """
    return name.replace("`", "_")


def _get_method_return_type(method: ParsedMethod, class_cpp_name: str) -> tuple[str, list[str]]:
    """Return (ret_cpp_type, [param_cpp_types_for_template]).

    For non-static methods the template param list starts with ``ClassName*``.
    """
    ret = method.return_cpp_type
    template_params: list[str] = []
    if not method.is_static:
        template_params.append(f"{class_cpp_name}*")
    for p in method.params:
        template_params.append(p.cpp_type)
    return ret, template_params


def generate_scaffold(dc: "DumpClass", game_version: str) -> str:  # noqa: F821
    """Generate a complete C++ header from a :class:`~models.DumpClass`.

    The output follows the conventions of hand-written IL2CPP wrapper headers
    in ``mods/src/prime/``.
    """
    from .models import DumpClass  # local import to avoid circular deps

    lines: list[str] = []
    cpp_name = _cpp_class_name(dc.name)

    # ------------------------------------------------------------------
    # Preamble
    # ------------------------------------------------------------------
    lines.append("#pragma once")
    lines.append(f"// Auto-generated from dump {game_version} — edit as needed")
    lines.append("")
    lines.append("#include <il2cpp/il2cpp_helper.h>")
    lines.append("#include <cstdint>")

    # ------------------------------------------------------------------
    # Collect usable methods (skip property accessors, compiler-generated)
    # ------------------------------------------------------------------
    property_set: set[str] = set(dc.properties)

    # Determine which properties have setters (set_X method exists)
    props_with_setter: set[str] = set()
    for prop_name in dc.properties:
        set_method = f"set_{prop_name}"
        if set_method in dc.methods:
            props_with_setter.add(prop_name)

    def _should_skip_method(name: str) -> bool:
        """Return True if this method should be omitted from the method wrappers."""
        if name.startswith(".") or name.startswith("<"):
            return True
        # Property accessor methods
        if name.startswith("get_") and name[4:] in property_set:
            return True
        if name.startswith("set_") and name[4:] in property_set:
            return True
        return False

    # Collect methods to emit (first signature for each overload group)
    usable_methods: list[ParsedMethod] = []
    for method_name, sigs in dc.methods.items():
        if _should_skip_method(method_name):
            continue
        # Use the first (or only) signature; emit one wrapper per distinct overload
        for sig in sigs:
            parsed = parse_method_signature(sig)
            if parsed is None:
                continue
            usable_methods.append(parsed)

    # ------------------------------------------------------------------
    # Collect fields to expose (skip compiler backing fields)
    # ------------------------------------------------------------------
    def _is_backing_field(fname: str) -> bool:
        return fname.endswith("k__BackingField") or (fname.startswith("<") and ">" in fname)

    usable_fields: list[tuple[str, str]] = [
        (fname, ftype)
        for fname, ftype in dc.fields.items()
        if not _is_backing_field(fname)
    ]

    # ------------------------------------------------------------------
    # Struct body
    # ------------------------------------------------------------------
    lines.append("")
    lines.append(f"struct {cpp_name} {{")
    lines.append("public:")

    # --- Properties (declspec declarations) ---
    if dc.properties:
        lines.append("  // --- Properties ---")
        for prop_name in dc.properties:
            if prop_name in props_with_setter:
                lines.append(
                    f"  __declspec(property(get = __get_{prop_name},"
                    f" put = __set_{prop_name})) void* /* {prop_name} */ {prop_name};"
                )
            else:
                lines.append(
                    f"  __declspec(property(get = __get_{prop_name})) void* /* {prop_name} */ {prop_name};"
                )

    # --- Field property declarations ---
    if usable_fields:
        lines.append("  // --- Fields ---")
        for fname, ftype in usable_fields:
            cpp_type = map_type(ftype)
            if is_primitive(cpp_type) and cpp_type != "void":
                lines.append(
                    f"  __declspec(property(get = __get_{fname},"
                    f" put = __set_{fname})) {cpp_type} {fname};"
                )
            else:
                # Non-primitive: read-only or opaque pointer
                lines.append(
                    f"  __declspec(property(get = __get_{fname})) {cpp_type} {fname};"
                )

    # --- Method wrappers ---
    if usable_methods:
        lines.append("")
        lines.append("  // --- Methods ---")
        for m in usable_methods:
            ret_cpp, tmpl_params = _get_method_return_type(m, cpp_name)
            # Build C++ parameter list (arg0, arg1, ...)
            cpp_params_decl = ", ".join(
                f"{p.cpp_type} {p.name if p.name else f'arg{i}'}"
                for i, p in enumerate(m.params)
            )
            # Build argument list for the call
            cpp_args = ", ".join(
                p.name if p.name else f"arg{i}" for i, p in enumerate(m.params)
            )
            tmpl_str = f"{ret_cpp}({', '.join(tmpl_params)})"

            if m.is_static:
                lines.append(f"  static {ret_cpp} {m.name}({cpp_params_decl}) {{")
                lines.append(f"    static auto m = get_class_helper().GetMethod<{tmpl_str}>(\"{m.name}\");")
                if ret_cpp == "void":
                    lines.append(f"    m({cpp_args});")
                else:
                    lines.append(f"    return m({cpp_args});")
                lines.append("  }")
            else:
                lines.append(f"  {ret_cpp} {m.name}({cpp_params_decl}) {{")
                lines.append(f"    static auto m = get_class_helper().GetMethod<{tmpl_str}>(\"{m.name}\");")
                this_call = f"this, {cpp_args}" if cpp_args else "this"
                if ret_cpp == "void":
                    lines.append(f"    m({this_call});")
                else:
                    lines.append(f"    return m({this_call});")
                lines.append("  }")

    # --- get_class_helper (private) ---
    lines.append("")
    lines.append("private:")
    lines.append("  static IL2CppClassHelper& get_class_helper() {")
    lines.append("    static auto class_helper =")
    lines.append(
        f"        il2cpp_get_class_helper(\"{dc.assembly}\", \"{dc.namespace}\", \"{dc.name}\");"
    )
    lines.append("    return class_helper;")
    lines.append("  }")

    # --- Property accessors (public) ---
    has_accessors = bool(dc.properties) or bool(usable_fields)
    if has_accessors:
        lines.append("")
        lines.append("public:")

    if dc.properties:
        lines.append("  // --- Property accessors ---")
        for prop_name in dc.properties:
            # We don't know the type from the dump model — use void*/GetRaw pattern
            lines.append(f"  void* __get_{prop_name}() {{")
            lines.append(f"    static auto prop = get_class_helper().GetProperty(\"{prop_name}\");")
            lines.append(f"    return prop.GetRaw<void>(this);")
            lines.append("  }")
            if prop_name in props_with_setter:
                lines.append(f"  void __set_{prop_name}(void* v) {{")
                lines.append(f"    static auto prop = get_class_helper().GetProperty(\"{prop_name}\");")
                lines.append(f"    prop.SetRaw(this, v);")
                lines.append("  }")

    if usable_fields:
        lines.append("  // --- Field accessors ---")
        for fname, ftype in usable_fields:
            cpp_type = map_type(ftype)
            if is_primitive(cpp_type) and cpp_type != "void":
                # Getter
                lines.append(f"  {cpp_type} __get_{fname}() {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{fname}\");")
                lines.append(f"    return *({cpp_type}*)((ptrdiff_t)this + field.offset());")
                lines.append("  }")
                # Setter
                lines.append(f"  void __set_{fname}({cpp_type} v) {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{fname}\");")
                lines.append(f"    *({cpp_type}*)((ptrdiff_t)this + field.offset()) = v;")
                lines.append("  }")
            else:
                # Non-primitive getter only (opaque pointer).
                # cpp_type may be "void* /* OrigType */" — use bare void* in the cast.
                lines.append(f"  {cpp_type} __get_{fname}() {{")
                lines.append(f"    static auto field = get_class_helper().GetField(\"{fname}\");")
                lines.append(f"    return *(void**)((ptrdiff_t)this + field.offset());")
                lines.append("  }")

    lines.append("};")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Parsed data classes
# ---------------------------------------------------------------------------

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
    params: tuple[ParsedParam, ...]  # tuple (frozen dataclass)
    is_static: bool
    raw_signature: str


# ---------------------------------------------------------------------------
# Signature parsing helpers
# ---------------------------------------------------------------------------

_MODIFIER_KEYWORDS: frozenset[str] = frozenset({
    "public", "private", "protected", "internal",
    "static", "virtual", "abstract", "override",
    "sealed", "new", "extern", "unsafe", "async",
    "readonly", "partial",
})


def _split_params(param_str: str) -> list[str]:
    """Split a parameter list string on commas, respecting ``<>`` nesting.

    Example::

        "Dictionary<int, string> dict, int x"
        → ["Dictionary<int, string> dict", "int x"]
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
            parts.append("".join(current).strip())
            current = []
        else:
            current.append(ch)

    tail = "".join(current).strip()
    if tail:
        parts.append(tail)

    return parts


# Pattern: optional trailing comment/RVA annotation after the closing paren
# e.g. "public void Foo(int x) // 0x12345" — strip everything after //
_SIG_RE = re.compile(
    r"""
    ^
    (?P<modifiers>(?:\w+\s+)*)   # zero or more modifier keywords
    (?P<ret_type>\S+)             # return type (no spaces for simple types)
    \s+
    (?P<name>\w+)                 # method name
    \s*\(
    (?P<params>[^)]*)             # parameter list (no nested parens expected)
    \)
    """,
    re.VERBOSE,
)


def parse_method_signature(sig: str) -> ParsedMethod | None:
    """Parse a dump.cs method signature into a :class:`ParsedMethod`.

    Returns ``None`` if the signature cannot be parsed.
    """
    # Strip inline comments (// RVA annotations, etc.)
    sig_clean = sig.split("//")[0].strip()
    # Also strip trailing semicolons common in dump.cs
    sig_clean = sig_clean.rstrip(";").strip()

    m = _SIG_RE.match(sig_clean)
    if m is None:
        return None

    modifiers_str: str = m.group("modifiers").strip()
    ret_cs_type: str = m.group("ret_type").strip()
    method_name: str = m.group("name").strip()
    params_str: str = m.group("params").strip()

    modifier_tokens = set(modifiers_str.split()) if modifiers_str else set()
    is_static = "static" in modifier_tokens

    # Parse parameters
    parsed_params: list[ParsedParam] = []
    if params_str:
        for raw_param in _split_params(params_str):
            raw_param = raw_param.strip()
            if not raw_param:
                continue
            # Last token is the parameter name; everything before is the type
            tokens = raw_param.rsplit(None, 1)
            if len(tokens) == 2:
                param_cs_type, param_name = tokens
            else:
                # Fallback: no name, treat whole thing as type
                param_cs_type = tokens[0]
                param_name = ""
            cpp_type = map_type(param_cs_type)
            parsed_params.append(ParsedParam(
                cs_type=param_cs_type,
                name=param_name,
                cpp_type=cpp_type,
            ))

    return ParsedMethod(
        name=method_name,
        return_cs_type=ret_cs_type,
        return_cpp_type=map_type(ret_cs_type),
        params=tuple(parsed_params),
        is_static=is_static,
        raw_signature=sig,
    )
