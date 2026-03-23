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
