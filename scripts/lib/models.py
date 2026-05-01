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
    # True when source already handles a missing runtime member explicitly.
    optional_probe: bool = False


@dataclass(slots=True)
class DumpClass:
    """A class parsed from dump.cs with its members."""
    assembly: str
    namespace: str
    name: str
    methods: dict[str, list[str]] = field(default_factory=dict)     # name → [full signatures]
    fields: dict[str, str] = field(default_factory=dict)              # field_name → cs_type
    properties: list[str] = field(default_factory=list)              # property names
    nested_types: list[str] = field(default_factory=list)            # nested type names
    parents: list[str] = field(default_factory=list)                 # parent/interface names


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
