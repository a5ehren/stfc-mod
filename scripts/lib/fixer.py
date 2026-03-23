"""Auto-fix and suggestion logic for broken IL2CPP references.

Analyzes validation issues from Stage 2 and produces:
  - Fix objects for safe, unambiguous renames (assembly/namespace moves, nested type suffix changes)
  - Suggestion objects for ambiguous cases (multiple matches, similar member names)
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .models import DumpClass, DumpIndex, Issue, ModReference, RefType, Severity


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Fix:
    file: str          # absolute path to source file
    line: int          # 1-based line number where old_text appears
    old_text: str      # exact substring to replace
    new_text: str      # replacement substring
    description: str   # human-readable description


@dataclass(frozen=True, slots=True)
class Suggestion:
    file: str          # absolute path to source file
    line: int          # 1-based line number
    description: str   # human-readable description


# ---------------------------------------------------------------------------
# Levenshtein distance
# ---------------------------------------------------------------------------

def _levenshtein(a: str, b: str) -> int:
    """Compute the Levenshtein (edit) distance between two strings."""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la

    # Use two rows rolling approach for memory efficiency.
    prev = list(range(lb + 1))
    curr = [0] * (lb + 1)
    for i in range(1, la + 1):
        curr[0] = i
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(
                curr[j - 1] + 1,       # insert
                prev[j] + 1,           # delete
                prev[j - 1] + cost,    # substitute
            )
        prev, curr = curr, prev
    return prev[lb]


# ---------------------------------------------------------------------------
# Regex for nested type d__ suffix (e.g., "<MoveNext>d__170")
# ---------------------------------------------------------------------------

_RE_D_SUFFIX = re.compile(r'^(<.+>d__)(\d+)$')


def _d_prefix(name: str) -> str | None:
    """Return the '<Name>d__' prefix if *name* matches the d__ pattern, else None."""
    m = _RE_D_SUFFIX.match(name)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------

def _abs_path(source_file: str, project_root: Path) -> str:
    """Convert a project-relative source_file path to an absolute path string."""
    p = project_root / source_file
    return str(p.resolve())


# ---------------------------------------------------------------------------
# Core analysis
# ---------------------------------------------------------------------------

def analyze_issues(
    issues: list[Issue],
    index: DumpIndex,
    project_root: Path,
) -> tuple[list[Fix], list[Suggestion]]:
    """Process validation issues into auto-fixes and suggestions.

    Args:
        issues:       List of Issue instances from validate().
        index:        DumpIndex built from the current dump.cs.
        project_root: Root directory of the project (used to resolve file paths).

    Returns:
        (fixes, suggestions) where fixes are safe automated replacements and
        suggestions are guidance for changes that require human judgment.
    """
    project_root = Path(project_root)
    fixes: list[Fix] = []
    suggestions: list[Suggestion] = []

    # Deduplicate: track (file, line, old_text) already handled to avoid
    # emitting duplicate fixes when the same class_helper line triggers
    # multiple CLASS issues (unlikely but defensive).
    seen_fix_keys: set[tuple[str, int, str]] = set()

    for issue in issues:
        ref = issue.ref
        if ref.type == RefType.CLASS:
            _handle_class_issue(issue, index, project_root, fixes, suggestions, seen_fix_keys)
        elif ref.type in (RefType.METHOD, RefType.FIELD, RefType.PROPERTY, RefType.NESTED_TYPE):
            _handle_member_issue(issue, index, project_root, fixes, suggestions, seen_fix_keys)

    return fixes, suggestions


# ---------------------------------------------------------------------------
# Class-level issues
# ---------------------------------------------------------------------------

def _handle_class_issue(
    issue: Issue,
    index: DumpIndex,
    project_root: Path,
    fixes: list[Fix],
    suggestions: list[Suggestion],
    seen: set[tuple[str, int, str]],
) -> None:
    ref = issue.ref
    cn = ref.class_name
    if not cn:
        return

    matches = index.by_class_name.get(cn, [])
    if not matches:
        # Class simply missing from the dump — nothing we can do.
        return

    abs_file = _abs_path(ref.source_file, project_root)

    if len(matches) == 1:
        # Exactly one candidate — safe to auto-fix if assembly or namespace differs.
        dc = matches[0]
        if dc.assembly == ref.assembly and dc.namespace == ref.namespace:
            # Already correct — the issue might be spurious; skip.
            return

        old_call = _class_helper_text(ref.assembly, ref.namespace, cn)
        new_call = _class_helper_text(dc.assembly, dc.namespace, cn)

        if old_call == new_call:
            return

        key = (abs_file, ref.source_line, old_call)
        if key in seen:
            return
        seen.add(key)

        desc = (
            f"Rename class helper for {cn!r}: "
            f"{ref.assembly!r}/{ref.namespace!r} -> {dc.assembly!r}/{dc.namespace!r}"
        )
        fixes.append(Fix(
            file=abs_file,
            line=ref.source_line,
            old_text=old_call,
            new_text=new_call,
            description=desc,
        ))
    else:
        # Multiple candidates — ambiguous, produce a suggestion.
        options = "; ".join(
            f"{dc.assembly!r}/{dc.namespace!r}" for dc in matches
        )
        desc = (
            f"Ambiguous class {cn!r} (current: {ref.assembly!r}/{ref.namespace!r}): "
            f"found in dump as: {options}"
        )
        suggestions.append(Suggestion(
            file=abs_file,
            line=ref.source_line,
            description=desc,
        ))


def _class_helper_text(assembly: str | None, namespace: str | None, class_name: str) -> str:
    """Build the string fragment that appears inside il2cpp_get_class_helper(...)."""
    asm = assembly or ""
    ns = namespace or ""
    return f'"{asm}", "{ns}", "{class_name}"'


# ---------------------------------------------------------------------------
# Member-level issues (METHOD, FIELD, PROPERTY, NESTED_TYPE)
# ---------------------------------------------------------------------------

def _handle_member_issue(
    issue: Issue,
    index: DumpIndex,
    project_root: Path,
    fixes: list[Fix],
    suggestions: list[Suggestion],
    seen: set[tuple[str, int, str]],
) -> None:
    ref = issue.ref
    if not ref.class_name or not ref.member_name:
        return

    abs_file = _abs_path(ref.source_file, project_root)

    # Try to look up the class in the dump — needed for member candidate lists.
    dc = index.by_qualified_name.get((ref.assembly, ref.namespace, ref.class_name))
    if dc is None:
        # Class missing; no member candidates — handled by class-level logic.
        return

    member = ref.member_name

    # --- Nested type: d__ suffix change ---
    if ref.type == RefType.NESTED_TYPE:
        prefix = _d_prefix(member)
        if prefix is not None:
            # Look for a nested type in the dump with the same prefix but different number.
            candidates = [
                nt for nt in dc.nested_types
                if nt != member and nt.startswith(prefix) and _d_prefix(nt) == prefix
            ]
            if len(candidates) == 1:
                new_name = candidates[0]
                old_text = f'"{member}"'
                new_text = f'"{new_name}"'
                key = (abs_file, ref.source_line, old_text)
                if key not in seen:
                    seen.add(key)
                    fixes.append(Fix(
                        file=abs_file,
                        line=ref.source_line,
                        old_text=old_text,
                        new_text=new_text,
                        description=(
                            f"Update nested type suffix for {ref.class_name!r}: "
                            f"{member!r} -> {new_name!r}"
                        ),
                    ))
                return
            elif len(candidates) > 1:
                opts = ", ".join(repr(c) for c in candidates)
                suggestions.append(Suggestion(
                    file=abs_file,
                    line=ref.source_line,
                    description=(
                        f"Ambiguous d__ suffix for {ref.class_name}.{member!r}: "
                        f"candidates: {opts}"
                    ),
                ))
                return

    # --- General member: look for similar names (Levenshtein or substring) ---
    candidate_names = _member_candidates(dc, ref.type)
    if not candidate_names:
        return

    similar = _find_similar(member, candidate_names)
    if similar:
        opts = ", ".join(repr(s) for s in similar)
        desc = (
            f"Missing {ref.type.name.lower()} {ref.class_name}.{member!r} — "
            f"similar names in dump: {opts}"
        )
        suggestions.append(Suggestion(
            file=abs_file,
            line=ref.source_line,
            description=desc,
        ))


def _member_candidates(dc: DumpClass, ref_type: RefType) -> list[str]:
    """Return the list of existing member names on *dc* for the given ref_type."""
    if ref_type == RefType.METHOD:
        return list(dc.methods.keys())
    elif ref_type == RefType.FIELD:
        return list(dc.fields.keys())
    elif ref_type == RefType.PROPERTY:
        return list(dc.properties)
    elif ref_type == RefType.NESTED_TYPE:
        return list(dc.nested_types)
    return []


def _find_similar(target: str, candidates: list[str], max_distance: int = 3) -> list[str]:
    """Return candidates within Levenshtein distance or substring match."""
    result: list[str] = []
    target_lower = target.lower()
    for c in candidates:
        if c == target:
            continue
        c_lower = c.lower()
        if target_lower in c_lower or c_lower in target_lower:
            result.append(c)
        elif _levenshtein(target, c) <= max_distance:
            result.append(c)
    return result


# ---------------------------------------------------------------------------
# Apply fixes
# ---------------------------------------------------------------------------

def apply_fixes(
    fixes: list[Fix],
    project_root: Path,
    *,
    dry_run: bool = False,
) -> int:
    """Apply fixes to source files.

    Groups fixes by file, reads each file once, applies all string
    replacements, and writes back only if content changed.

    Args:
        fixes:        List of Fix instances to apply.
        project_root: Project root (used only for logging context).
        dry_run:      If True, do not write any files.

    Returns:
        Number of files actually modified (or that would be modified in dry_run).
    """
    # Group fixes by file.
    by_file: dict[str, list[Fix]] = {}
    for fix in fixes:
        by_file.setdefault(fix.file, []).append(fix)

    modified_count = 0

    for filepath, file_fixes in by_file.items():
        p = Path(filepath)
        try:
            original = p.read_text(encoding='utf-8')
        except OSError:
            continue

        content = original
        for fix in file_fixes:
            content = content.replace(fix.old_text, fix.new_text)

        if content != original:
            modified_count += 1
            if not dry_run:
                p.write_text(content, encoding='utf-8')

    return modified_count
