"""
modularity.py — Modularity Analysis L2 and L3 for Phase 1.

Detects module boundaries from build manifests (L3) and language-defined
package structure (L2), then assigns FileEntry IDs to each module.

L1 (file-level) is always implied by FileEntry — not stored here.
L2 (language package): Python __init__.py dirs, Go dir packages, Java package decls.
L3 (build unit): directories containing build manifests located by scanning disk.

No network calls; stdlib + pathlib only.
"""

from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from blueprint import ConfigEntry, FileEntry, ModuleEntry
from phase0 import _BUILD_CONFIGS, _GENERATED_DIR_NAMES, _SKIP_DIRS as _PHASE0_SKIP_DIRS

# Directories never entered: VCS/tool dirs + generated/build output dirs.
_SKIP_DIRS: frozenset = _PHASE0_SKIP_DIRS | _GENERATED_DIR_NAMES

# Regex for a Java package declaration: `package com.example.foo;`
_JAVA_PACKAGE_RE = re.compile(r"^\s*package\s+([\w.]+)\s*;", re.MULTILINE)

# Regex for a Go package declaration: `package foo` (first non-comment line)
_GO_PACKAGE_RE = re.compile(r"^\s*package\s+(\w+)\b", re.MULTILINE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _posix(p: Path) -> str:
    """Return a posix string (forward slashes), empty string for '.'."""
    s = p.as_posix()
    return "" if s == "." else s


def _rel(path_str: str, root: Path) -> Path:
    """Convert a file entry path (possibly relative) to a Path relative to root."""
    p = Path(path_str)
    if p.is_absolute():
        try:
            return p.relative_to(root)
        except ValueError:
            return p
    return p


def _file_dir(file_entry: FileEntry, root: Path) -> str:
    """Return the posix directory of a FileEntry relative to root."""
    rel = _rel(file_entry.path, root)
    return _posix(rel.parent)


# ---------------------------------------------------------------------------
# L3: Build unit detection
# ---------------------------------------------------------------------------

def _scan_build_configs(root: Path) -> List[Tuple[str, str]]:
    """Walk the tree under *root* and return (rel_dir_posix, kind) pairs.

    Skips _SKIP_DIRS and only descends into subdirectories.
    Returns dirs sorted by depth then path so parents come before children.
    """
    found: List[Tuple[str, str]] = []

    def _walk(current: Path, rel: Path) -> None:
        for child in sorted(current.iterdir()):
            if child.is_file() and child.name in _BUILD_CONFIGS:
                found.append((_posix(rel), _BUILD_CONFIGS[child.name]))
            elif child.is_dir() and child.name not in _SKIP_DIRS:
                _walk(child, rel / child.name)

    try:
        _walk(root, Path("."))
    except PermissionError:
        pass

    # Sort: shallower paths first, then lexicographic
    found.sort(key=lambda t: (t[0].count("/"), t[0]))
    # Deduplicate: keep first kind per dir (e.g. setup.py + pyproject.toml → first seen)
    seen: Dict[str, str] = {}
    deduped: List[Tuple[str, str]] = []
    for dir_path, kind in found:
        if dir_path not in seen:
            seen[dir_path] = kind
            deduped.append((dir_path, kind))
    return deduped


def _detect_l3(
    root: Path,
    file_entries: List[FileEntry],
    configs: Optional[List[ConfigEntry]] = None,
) -> List[ModuleEntry]:
    """Detect L3 modules (build units) from build manifests on disk.

    If *configs* is provided (a list of ConfigEntry from blueprint_io._collect_configs),
    it is used directly — no filesystem walk occurs.  Falls back to _scan_build_configs
    when *configs* is None (legacy / standalone invocation).
    """
    if configs is not None:
        # Derive (dir_path, kind, name) triples from pre-collected ConfigEntry objects.
        # Deduplicate by dir_path keeping the first (shallowest) entry.
        seen_dirs: Dict[str, Tuple[str, Optional[str]]] = {}
        for ce in sorted(configs, key=lambda c: (c.root_path.count("/"), c.root_path)):
            if ce.root_path not in seen_dirs:
                seen_dirs[ce.root_path] = (ce.kind, ce.name)
        raw_configs: List[Tuple[str, str, Optional[str]]] = [
            (dir_path, kind, name) for dir_path, (kind, name) in seen_dirs.items()
        ]
    else:
        raw_configs = [
            (dir_path, kind, None) for dir_path, kind in _scan_build_configs(root)
        ]

    if not raw_configs:
        return []

    modules: List[ModuleEntry] = []
    for dir_path, kind, cfg_name in raw_configs:
        # Assign files whose paths start with this dir_path prefix
        file_ids: List[str] = []
        for fe in file_entries:
            fe_dir = _file_dir(fe, root)
            # File is inside dir_path if its directory equals or is under it
            if dir_path == "":
                # Root-level config — all files belong unless a deeper config claims them
                file_ids.append(fe.id)
            else:
                rel_fe = fe_dir
                if rel_fe == dir_path or rel_fe.startswith(dir_path + "/"):
                    file_ids.append(fe.id)

        # For root-level config, remove files that a deeper config already claimed
        # (handled by the caller after all modules are created)

        # Use declared name from ConfigEntry when available; fall back to path.
        name = cfg_name if cfg_name else (dir_path if dir_path else ".")
        modules.append(ModuleEntry(
            id="",               # assigned later
            level="L3",
            name=name,
            root_path=dir_path,
            file_ids=file_ids,
            build_kind=kind,
        ))

    # If there are nested L3 modules, trim the root module's file_ids to only
    # files not claimed by any nested module.
    if len(modules) > 1:
        # Collect dirs of non-root modules
        nested_dirs = {m.root_path for m in modules if m.root_path != ""}
        root_mod = next((m for m in modules if m.root_path == ""), None)
        if root_mod is not None:
            root_mod.file_ids = [
                fid for fid in root_mod.file_ids
                if not _id_in_nested(fid, file_entries, root, nested_dirs)
            ]

    return modules


def _id_in_nested(
    fid: str,
    file_entries: List[FileEntry],
    root: Path,
    nested_dirs: set,
) -> bool:
    """Return True if the file with *fid* lives under any of *nested_dirs*."""
    fe = next((f for f in file_entries if f.id == fid), None)
    if fe is None:
        return False
    fe_dir = _file_dir(fe, root)
    for nd in nested_dirs:
        if fe_dir == nd or fe_dir.startswith(nd + "/"):
            return True
    return False


# ---------------------------------------------------------------------------
# L2: Language package detection
# ---------------------------------------------------------------------------

def _detect_l2(
    root: Path,
    file_entries: List[FileEntry],
) -> List[ModuleEntry]:
    """Detect L2 modules (language packages).

    Python: directories containing __init__.py are packages; all .py files
            in that directory (non-recursively) belong to it.
    Go:     all .go files in the same directory share a package; name from
            first `package` declaration found.
    Java:   .java files grouped by their `package` declaration.
    """
    modules: List[ModuleEntry] = []
    modules.extend(_detect_python_packages(root, file_entries))
    modules.extend(_detect_go_packages(root, file_entries))
    modules.extend(_detect_java_packages(root, file_entries))
    return modules


def _detect_python_packages(
    root: Path,
    file_entries: List[FileEntry],
) -> List[ModuleEntry]:
    """Python packages: directories that contain an __init__.py file."""
    # Find all __init__.py files in the file list
    init_dirs: set = set()
    for fe in file_entries:
        if Path(fe.path).name == "__init__.py":
            init_dirs.add(_file_dir(fe, root))

    if not init_dirs:
        return []

    modules: List[ModuleEntry] = []
    for pkg_dir in sorted(init_dirs):
        # Collect .py files whose *immediate* parent is this directory
        file_ids: List[str] = [
            fe.id for fe in file_entries
            if fe.ext == ".py" and _file_dir(fe, root) == pkg_dir
        ]
        # Derive a dotted package name from the directory path
        name = pkg_dir.replace("/", ".") if pkg_dir else "."
        modules.append(ModuleEntry(
            id="",
            level="L2",
            name=name,
            root_path=pkg_dir,
            file_ids=file_ids,
        ))
    return modules


def _detect_go_packages(
    root: Path,
    file_entries: List[FileEntry],
) -> List[ModuleEntry]:
    """Go packages: all .go files in the same directory form a package."""
    # Group .go files by directory
    by_dir: Dict[str, List[FileEntry]] = {}
    for fe in file_entries:
        if fe.ext == ".go":
            d = _file_dir(fe, root)
            by_dir.setdefault(d, []).append(fe)

    if not by_dir:
        return []

    modules: List[ModuleEntry] = []
    for dir_path, entries in sorted(by_dir.items()):
        # Try to read the package name from the first file
        pkg_name = _read_go_package_name(entries[0], root)
        name = pkg_name or (dir_path.split("/")[-1] if dir_path else "main")
        modules.append(ModuleEntry(
            id="",
            level="L2",
            name=name,
            root_path=dir_path,
            file_ids=[fe.id for fe in entries],
        ))
    return modules


def _read_go_package_name(fe: FileEntry, root: Path) -> Optional[str]:
    p = Path(fe.path)
    if not p.is_absolute():
        p = root / p
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        m = _GO_PACKAGE_RE.search(content)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None


def _detect_java_packages(
    root: Path,
    file_entries: List[FileEntry],
) -> List[ModuleEntry]:
    """Java packages: .java files grouped by their `package` declaration."""
    by_package: Dict[str, List[FileEntry]] = {}
    no_package: List[FileEntry] = []

    for fe in file_entries:
        if fe.ext != ".java":
            continue
        pkg = _read_java_package_name(fe, root)
        if pkg:
            by_package.setdefault(pkg, []).append(fe)
        else:
            no_package.append(fe)

    if not by_package and not no_package:
        return []

    modules: List[ModuleEntry] = []
    for pkg_name, entries in sorted(by_package.items()):
        # root_path: use the directory of the first file as a heuristic
        dir_path = _file_dir(entries[0], root)
        modules.append(ModuleEntry(
            id="",
            level="L2",
            name=pkg_name,
            root_path=dir_path,
            file_ids=[fe.id for fe in entries],
        ))
    # Java files without a package declaration go to the default package
    if no_package:
        dir_path = _file_dir(no_package[0], root)
        modules.append(ModuleEntry(
            id="",
            level="L2",
            name="(default)",
            root_path=dir_path,
            file_ids=[fe.id for fe in no_package],
        ))
    return modules


def _read_java_package_name(fe: FileEntry, root: Path) -> Optional[str]:
    p = Path(fe.path)
    if not p.is_absolute():
        p = root / p
    try:
        content = p.read_text(encoding="utf-8", errors="replace")
        m = _JAVA_PACKAGE_RE.search(content)
        if m:
            return m.group(1)
    except OSError:
        pass
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_modules(
    root: Path,
    file_entries: List[FileEntry],
    configs: Optional[List[ConfigEntry]] = None,
) -> List[ModuleEntry]:
    """Detect L2 and L3 module boundaries for *file_entries* under *root*.

    Pass *configs* (a list of ConfigEntry) to skip the internal filesystem walk
    and reuse already-collected build config data from sourcegraph_to_blueprint.

    Returns a list of ModuleEntry objects with stable IDs assigned.
    ID scheme: modules sorted by (level, root_path), then "m0", "m1", ...
    """
    l3 = _detect_l3(root, file_entries, configs)
    l2 = _detect_l2(root, file_entries)

    all_modules = l3 + l2
    # Sort: L3 first (by root_path depth then path), then L2
    all_modules.sort(key=lambda m: (
        0 if m.level == "L3" else 1,
        m.root_path.count("/"),
        m.root_path,
    ))

    # Assign stable IDs
    for i, mod in enumerate(all_modules):
        object.__setattr__(mod, "id", f"m{i}") if hasattr(mod, "__setattr__") else None
        mod.id = f"m{i}"

    return all_modules
