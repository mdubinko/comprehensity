"""
blueprint_io.py — Convert between SourceGraph and Blueprint.

sourcegraph_to_blueprint  :  SourceGraph → Blueprint
blueprint_to_sourcegraph  :  Blueprint   → SourceGraph
"""

from __future__ import annotations

import fnmatch
import re
import shutil
import subprocess
import time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

try:
    from tqdm import tqdm as _tqdm
    HAS_TQDM = True
except ImportError:
    _tqdm = None  # type: ignore[assignment]
    HAS_TQDM = False

import applog
from blueprint import (
    AnalysisWarning, Blueprint, ConfigEntry, DeadSymbol, DiagnosticEntry, ExternalEntry,
    FileEntry, LockfileEntry, ReferenceEdge, SymbolEntry,
)
from lsp_client import LspClient
from phase0 import _BUILD_CONFIGS as _PHASE0_BUILD_CONFIGS, detect_js_package_manager
from srcgraph import SourceGraph

# ---------------------------------------------------------------------------
# Code-relevance allowlist
# ---------------------------------------------------------------------------
# Only files whose extension is in this set are included in blueprint.files.
# Non-code files (images, fonts, docs, data) are excluded regardless of whether
# they appear in the SourceGraph.
#
# IMPORTANT: When adding a new language parser, add its file extension(s) here
# too. Omitting an extension means the language's files will be silently dropped
# from the blueprint — imports to those files will surface as ExternalEntry nodes
# and symbol extraction will never run on them. See CLAUDE.md "Adding New
# Language Support" for the full checklist.
_CODE_EXTENSIONS: frozenset = frozenset({
    # Python
    ".py", ".pyi",
    # JavaScript / TypeScript
    ".js", ".jsx", ".cjs", ".mjs", ".ts", ".tsx", ".cts", ".mts",
    # Java / JVM
    ".java", ".kt", ".kts", ".groovy", ".gradle", ".scala", ".clj", ".cljs",
    # Systems languages
    ".c", ".h", ".cpp", ".cc", ".cxx", ".hpp", ".hxx", ".cs", ".go", ".rs", ".swift",
    # Scripting
    ".rb", ".php", ".pl", ".pm", ".lua",
    # Functional
    ".r", ".hs", ".elm", ".ex", ".exs", ".fs", ".fsx", ".ml", ".mli",
    # Other compiled
    ".dart", ".m", ".mm", ".vb", ".f90", ".f95",
    # Shell
    ".sh", ".bash", ".zsh", ".fish", ".bat", ".ps1", ".cmd",
    # Build / config / schema (kept for future build-config analysis)
    ".toml", ".yaml", ".yml", ".json", ".xml", ".properties",
    ".cmake",
    # Data-definition languages
    ".proto", ".graphql", ".gql", ".sql", ".xsd", ".wsdl",
    # Notebooks
    ".ipynb",
})

# Language → extensions, for grouping treepeat runs by primary language.
# Covers the languages treepeat can meaningfully process.
_LANG_TO_EXTS: Dict[str, frozenset] = {
    "python":     frozenset({".py", ".pyw"}),
    "javascript": frozenset({".js", ".jsx", ".mjs", ".cjs"}),
    "typescript": frozenset({".ts", ".tsx"}),
    "java":       frozenset({".java"}),
    "c":          frozenset({".c", ".h"}),
    "cpp":        frozenset({".cpp", ".cxx", ".cc", ".hpp", ".hxx"}),
    "go":         frozenset({".go"}),
    "rust":       frozenset({".rs"}),
    "ruby":       frozenset({".rb"}),
    "csharp":     frozenset({".cs"}),
    "kotlin":     frozenset({".kt", ".kts"}),
    "swift":      frozenset({".swift"}),
}
# Minimum file count for a language to get its own treepeat run.
_PRIMARY_CLONE_THRESHOLD = 10

# Directory names that treepeat skips entirely — test code has expected
# repetition and excluding it meaningfully reduces runtime on large repos.
_TEST_DIR_NAMES: frozenset = frozenset({
    "test", "tests", "spec", "specs", "__tests__", "__test__",
})


# ---------------------------------------------------------------------------
# Build-config file discovery and parsing
# ---------------------------------------------------------------------------
# Files are identified by name (not extension) so we use a separate allowlist.
# Parsers extract a small common core: name, version, raw_deps, modules.

# Derived from phase0._BUILD_CONFIGS — single source of truth for build manifest filenames.
_CONFIG_FILE_NAMES: frozenset = frozenset(_PHASE0_BUILD_CONFIGS.keys())

# Glob patterns matched against filenames (not paths)
_CONFIG_FILE_PATTERNS: tuple = (
    "requirements*.txt",
)

# Directories to skip while walking for config files
_CONFIG_SKIP_DIRS: frozenset = frozenset({
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".venv", "venv", "env",
    "target", "build", "dist", "out", ".gradle", ".mvn",
    ".idea", ".vscode", ".cache",
})

# Lockfile filenames → lock manager kind.
# Lockfile presence is a basic reproducibility signal: someone ran the package
# manager and committed the result.  Absence means installs may differ across
# machines or over time.
_LOCKFILE_NAMES: Dict[str, str] = {
    "package-lock.json": "npm",
    "yarn.lock":         "yarn",
    "pnpm-lock.yaml":   "pnpm",
    "poetry.lock":       "poetry",
    "Cargo.lock":        "cargo",
    "go.sum":            "go",
    "Gemfile.lock":      "bundler",
    "composer.lock":     "composer",
    "Pipfile.lock":      "pipenv",
    "bun.lockb":         "bun",
}


def _collect_lockfiles(root: Path) -> List[LockfileEntry]:
    """Walk *root* and return a LockfileEntry for every lockfile found."""
    results: List[LockfileEntry] = []
    for dirpath, dirnames, filenames in root.walk() if hasattr(root, "walk") else _os_walk(root):
        dirnames[:] = [d for d in dirnames if d not in _CONFIG_SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            kind = _LOCKFILE_NAMES.get(fname)
            if kind is not None:
                try:
                    rel = (Path(dirpath) / fname).relative_to(root)
                except ValueError:
                    rel = Path(dirpath) / fname
                results.append(LockfileEntry(path=rel.as_posix(), kind=kind))
    return sorted(results, key=lambda e: e.path)


def _config_kind(p: Path) -> Optional[str]:
    """Return the kind string for a config file path, or None if not recognized."""
    name = p.name
    if name in ("pyproject.toml", "Cargo.toml"):
        # Cargo.toml without [package] is a workspace root — still a config
        return "cargo" if name == "Cargo.toml" else "python-pyproject"
    if name == "pom.xml":
        return "maven"
    if name in ("settings.gradle", "settings.gradle.kts"):
        return "gradle-settings"
    if name in ("build.gradle", "build.gradle.kts"):
        return "gradle-build"
    if name == "package.json":
        return "npm"
    if name == "go.mod":
        return "go-mod"
    if name in ("setup.py", "setup.cfg"):
        return "setuptools"
    if name == "CMakeLists.txt":
        return "cmake"
    if name == "Makefile":
        return "make"
    for pat in _CONFIG_FILE_PATTERNS:
        if fnmatch.fnmatch(name, pat):
            return "python-requirements"
    return None


def _find_config_files(root: Path) -> List[Path]:
    """Walk *root* and return paths of recognized build config files."""
    results: List[Path] = []
    for dirpath, dirnames, filenames in root.walk() if hasattr(root, "walk") else _os_walk(root):
        dirnames[:] = [d for d in dirnames if d not in _CONFIG_SKIP_DIRS and not d.startswith(".")]
        for fname in filenames:
            if fname in _CONFIG_FILE_NAMES:
                results.append(Path(dirpath) / fname)
            else:
                for pat in _CONFIG_FILE_PATTERNS:
                    if fnmatch.fnmatch(fname, pat):
                        results.append(Path(dirpath) / fname)
                        break
    return sorted(results)


def _os_walk(root: Path):
    """os.walk wrapper returning (Path, list, list) tuples."""
    import os
    for dirpath, dirnames, filenames in os.walk(root):
        yield Path(dirpath), dirnames, filenames


def _safe_read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _parse_pyproject(p: Path):
    try:
        import tomllib  # Python 3.11+
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return None, None, []
    try:
        data = tomllib.loads(_safe_read(p))
    except Exception:
        return None, None, []
    proj = data.get("project", {})
    name = proj.get("name") or None
    version = proj.get("version") or None
    raw_deps = list(proj.get("dependencies", []))
    return name, version, raw_deps


def _parse_requirements(p: Path):
    deps: List[str] = []
    for line in _safe_read(p).splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        dep = re.split(r"[>=<!;\[\s@]", line)[0].strip()
        if dep:
            deps.append(dep)
    return deps


def _parse_pom(p: Path):
    import xml.etree.ElementTree as ET
    NS = "http://maven.apache.org/POM/4.0.0"

    def t(tag: str) -> str:
        return f"{{{NS}}}{tag}"

    def find_text(elem, tag: str) -> Optional[str]:
        child = elem.find(t(tag))
        return child.text.strip() if child is not None and child.text else None

    try:
        root = ET.fromstring(_safe_read(p))
    except ET.ParseError:
        return None, None, [], []

    name = find_text(root, "artifactId")
    version = find_text(root, "version")

    raw_deps: List[str] = []
    deps_elem = root.find(t("dependencies"))
    if deps_elem is not None:
        for dep in deps_elem.findall(t("dependency")):
            gid = find_text(dep, "groupId") or ""
            aid = find_text(dep, "artifactId") or ""
            if aid:
                raw_deps.append(f"{gid}:{aid}" if gid else aid)

    modules: List[str] = []
    mods_elem = root.find(t("modules"))
    if mods_elem is not None:
        for mod in mods_elem.findall(t("module")):
            if mod.text:
                modules.append(mod.text.strip())

    return name, version, raw_deps, modules


def _parse_gradle_settings(p: Path):
    text = _safe_read(p)
    m = re.search(r"""rootProject\.name\s*=\s*['"]([^'"]+)['"]""", text)
    name = m.group(1) if m else None
    # Handle both single-arg and multi-arg includes:
    #   include(':a')  include ':a', ':b'  include(":a", ":b")
    modules: List[str] = []
    for inc in re.finditer(r"""include\s*\(?([^);\n]+)""", text):
        for mod in re.finditer(r"""["':]+([^"',)\s]+)""", inc.group(1)):
            modules.append(mod.group(1).lstrip(":"))
    return name, modules


def _parse_gradle_build(p: Path):
    text = _safe_read(p)
    gm = re.search(r"""^group\s*[=\s]\s*['"]([^'"]+)['"]""", text, re.MULTILINE)
    vm = re.search(r"""^version\s*[=\s]\s*['"]([^'"]+)['"]""", text, re.MULTILINE)
    name = gm.group(1) if gm else None
    version = vm.group(1) if vm else None
    raw_deps = re.findall(
        r"""(?:implementation|api|compile|runtimeOnly|testImplementation)\s*\(?\s*['"]([^'"]+)['"]""",
        text,
    )
    return name, version, raw_deps


def _parse_package_json(p: Path):
    import json
    try:
        data = json.loads(_safe_read(p))
    except (json.JSONDecodeError, ValueError):
        return None, None, []
    name = data.get("name") or None
    version = data.get("version") or None
    deps = (
        list(data.get("dependencies", {}).keys())
        + list(data.get("devDependencies", {}).keys())
    )
    return name, version, deps


def _parse_cargo(p: Path):
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore
        except ImportError:
            return None, None, [], []
    try:
        data = tomllib.loads(_safe_read(p))
    except Exception:
        return None, None, [], []
    pkg = data.get("package", {})
    name = pkg.get("name") or None
    version = pkg.get("version") or None
    raw_deps = list(data.get("dependencies", {}).keys())
    ws = data.get("workspace", {})
    modules = list(ws.get("members", []))
    return name, version, raw_deps, modules


def _parse_go_mod(p: Path):
    text = _safe_read(p)
    m = re.search(r"^module\s+(\S+)", text, re.MULTILINE)
    name = m.group(1) if m else None
    # require blocks and single-line requires
    block_deps = re.findall(r"^\s+(\S+)\s+v[\d.+\-]", text, re.MULTILINE)
    single_deps = re.findall(r"^require\s+(\S+)\s+v", text, re.MULTILINE)
    seen: dict = {}
    raw_deps = [seen.setdefault(d, d) for d in block_deps + single_deps if d not in seen]
    return name, raw_deps


def _parse_config_file(abs_path: Path, sg_root: Path) -> Optional[ConfigEntry]:
    """Parse one build config file; returns None if unrecognized or unparseable."""
    kind = _config_kind(abs_path)
    if kind is None:
        return None

    try:
        rel = abs_path.relative_to(sg_root)
    except ValueError:
        rel = abs_path  # outside root; keep absolute

    root_dir = rel.parent.as_posix()
    if root_dir == ".":
        root_dir = ""

    name: Optional[str] = None
    version: Optional[str] = None
    raw_deps: List[str] = []
    modules: List[str] = []

    try:
        if kind == "python-pyproject":
            name, version, raw_deps = _parse_pyproject(abs_path)
        elif kind == "python-requirements":
            raw_deps = _parse_requirements(abs_path)
        elif kind == "maven":
            name, version, raw_deps, modules = _parse_pom(abs_path)
        elif kind == "gradle-settings":
            name, modules = _parse_gradle_settings(abs_path)
        elif kind == "gradle-build":
            name, version, raw_deps = _parse_gradle_build(abs_path)
        elif kind == "npm":
            name, version, raw_deps = _parse_package_json(abs_path)
        elif kind == "cargo":
            name, version, raw_deps, modules = _parse_cargo(abs_path)
        elif kind == "go-mod":
            name, raw_deps = _parse_go_mod(abs_path)
    except Exception:
        pass  # graceful: return what we have

    return ConfigEntry(
        id="",  # assigned by caller
        path=rel.as_posix(),
        kind=kind,
        root_path=root_dir,
        name=name,
        version=version,
        raw_deps=raw_deps,
        modules=modules,
    )


def _collect_configs(sg_root: Path) -> List[ConfigEntry]:
    """Find, parse, and assign IDs + parent_id for all build config files."""
    abs_paths = _find_config_files(sg_root)
    entries: List[ConfigEntry] = []
    for i, ap in enumerate(abs_paths):
        entry = _parse_config_file(ap, sg_root)
        if entry is not None:
            entry = entry.model_copy(update={"id": f"cfg{i}"})
            entries.append(entry)

    # Resolve parent_id: for each Maven pom.xml, find the nearest ancestor pom.xml
    # in the entries list. Same logic applied to other hierarchical configs.
    path_to_cfg: Dict[str, ConfigEntry] = {e.path: e for e in entries}

    def _find_parent(entry: ConfigEntry) -> Optional[str]:
        parts = Path(entry.path).parent.parts
        for depth in range(len(parts) - 1, -1, -1):
            ancestor_dir = Path(*parts[:depth]) if depth > 0 else Path(".")
            candidate_path = (ancestor_dir / Path(entry.path).name).as_posix()
            if candidate_path != entry.path and candidate_path in path_to_cfg:
                return path_to_cfg[candidate_path].id
        return None

    # Only resolve parent for kinds that form hierarchies
    _HIERARCHICAL = {"maven", "gradle-settings", "gradle-build"}
    updated: List[ConfigEntry] = []
    for e in entries:
        if e.kind in _HIERARCHICAL:
            pid = _find_parent(e)
            if pid is not None:
                e = e.model_copy(update={"parent_id": pid})
        updated.append(e)

    return updated


# Lazy import — only needed when detect_clones=True

def _treepeat_derived_ignores(root_path: Path, file_id_map: dict) -> tuple:
    """Return glob patterns for top-level subdirs that contain no blueprint files.

    Strategy: walk one level below root_path; any subdir whose files are entirely
    absent from file_id_map contributes nothing to clone analysis, so we can
    safely tell treepeat to skip it.  Files directly in root_path (no subdir) are
    left alone.

    Example: if the blueprint covers server/, modules/, libs/ but not docs/ or
    rest-api-spec/, this returns ('**/docs/**', '**/rest-api-spec/**').
    """
    # Collect top-level subdirs that own at least one blueprint file
    active: set = set()
    for abs_path in file_id_map:
        try:
            rel = Path(abs_path).relative_to(root_path)
            if len(rel.parts) >= 2:          # file is inside a subdir
                active.add(rel.parts[0])
        except ValueError:
            pass

    # Any top-level subdir not in active → treepeat can skip it
    globs = []
    try:
        for entry in root_path.iterdir():
            if entry.is_dir() and entry.name not in active:
                globs.append(f"**/{entry.name}/**")
    except OSError:
        pass

    return tuple(globs)


def _detect_clone_lang_groups(abs_file_id_map: Dict[str, str]) -> Dict[str, frozenset]:
    """Return {lang: exts} for languages with >= _PRIMARY_CLONE_THRESHOLD files.

    Used to decide whether to run treepeat once (single/small language mix) or
    once per primary language (multi-language repos like llama-cpp).
    """
    lang_counts: Dict[str, int] = {}
    for abs_path in abs_file_id_map:
        ext = Path(abs_path).suffix.lower()
        for lang, exts in _LANG_TO_EXTS.items():
            if ext in exts:
                lang_counts[lang] = lang_counts.get(lang, 0) + 1
                break
    return {
        lang: _LANG_TO_EXTS[lang]
        for lang, count in lang_counts.items()
        if count >= _PRIMARY_CLONE_THRESHOLD
    }


def _run_treepeat_lazy(root_path, ruleset, file_id_map, ignore_dirs=(),
                       exclude_exts=(), sarif_save_path=None,
                       show_progress=False):
    from clone_detection import run_treepeat
    # Java getters/setters are 3-5 lines with braces; raise the threshold so
    # they don't flood the clone report with trivial boilerplate.
    has_java = any(p.endswith(".java") for p in file_id_map)
    min_lines = 8 if has_java else 5
    # Explicit ignore_dirs (from --ignore-dirs arg) → glob patterns
    explicit = tuple(f"**/{d}/**" for d in ignore_dirs if d)
    # Auto-derived: top-level subdirs with no blueprint files
    derived = _treepeat_derived_ignores(Path(root_path), file_id_map)
    # Test directories: expected repetition, excluded for perf and signal quality
    test_globs = tuple(f"**/{d}/**" for d in sorted(_TEST_DIR_NAMES))
    # Per-language run: exclude other primary languages' file extensions
    ext_globs = tuple(f"**/*{e}" for e in sorted(exclude_exts))
    # Merge, preserving order; explicit first so they're easy to audit in logs
    seen: set = set()
    ignore_globs = []
    for g in explicit + derived + test_globs + ext_globs:
        if g not in seen:
            seen.add(g)
            ignore_globs.append(g)
    return run_treepeat(root_path, ruleset=ruleset, file_id_map=file_id_map,
                        min_lines=min_lines, ignore_patterns=tuple(ignore_globs),
                        sarif_save_path=sarif_save_path,
                        show_progress=show_progress)


def _extract_symbols(
    file_id: str,
    path: str,
    root: Optional[str],
    registry,
) -> List[SymbolEntry]:
    """Read *path* from disk and extract symbols; returns [] on any error.

    *path* may be relative; if so it is resolved against *root*.
    """
    abs_path = Path(path) if Path(path).is_absolute() else Path(root or ".") / path
    ext = abs_path.suffix.lower()
    extractor = registry.get(ext)
    if extractor is None:
        return []
    try:
        content = abs_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    # TypeScriptSymbolExtractor supports per-extension parsing
    if hasattr(extractor, "extract_with_ext"):
        return extractor.extract_with_ext(file_id, content, ext)
    return extractor.extract(file_id, content)


def sourcegraph_to_blueprint(
    sg: SourceGraph,
    extract_symbols: bool = True,
    detect_clones: bool = False,
    clone_ruleset: str = "loose",
    detect_modules: bool = True,
    ignore_dirs: tuple = (),
    clone_sarif_path: Optional[Path] = None,
    show_progress: bool = False,
) -> Blueprint:
    """Convert a SourceGraph to a Blueprint.

    Files are assigned stable IDs (f0, f1, ...) sorted by path.
    Imports that resolve to files in the graph become FileEntry references;
    all other import strings become ExternalEntry nodes.

    If a FileNode carries import_details metadata, the kind field
    (system / package / unknown) is derived from the stored ImportType value.

    Symbol extraction (requires tree-sitter grammars) is attempted for each
    file and stored as SymbolEntry objects with stable IDs ("s0", "s1", ...).
    Pass extract_symbols=False to skip this step (e.g. in tests that only
    exercise import wiring).

    If detect_clones=True, treepeat is invoked as a subprocess to detect
    duplicate code. clone_ruleset controls the normalisation level
    ("none"=exact, "default"=normalized, "loose"=approximate).
    Raises CloneDetectionUnavailable if treepeat is not installed.

    If detect_modules=True (default), L2/L3 module boundaries are detected
    from the filesystem. Requires sg.root_path to be set; silently skipped
    if root is unavailable.
    """
    # Lazy-import to avoid hard dependency when grammars aren't installed
    if extract_symbols:
        try:
            from ts_parsers import SymbolExtractorRegistry
            _registry: Optional[object] = SymbolExtractorRegistry.default()
        except ImportError:
            _registry = None
    else:
        _registry = None

    sorted_paths = [
        p for p in sorted(sg._files.keys())
        if Path(p).suffix.lower() in _CODE_EXTENSIONS
    ]
    path_to_id: Dict[str, str] = {p: f"f{i}" for i, p in enumerate(sorted_paths)}
    sg_root: Optional[str] = getattr(sg, "root_path", None)

    def _count_lines(path: str, root: Optional[str]) -> int:
        p = Path(path)
        if not p.is_absolute() and root:
            p = Path(root) / p
        try:
            return p.read_text(encoding="utf-8", errors="replace").count("\n")
        except OSError:
            return 0

    def _strip_comment_markers(text: str) -> str:
        """Strip comment syntax markers from raw tree-sitter node text."""
        text = text.strip()
        if text.startswith('"""') or text.startswith("'''"):
            marker = text[:3]
            inner = text[3:]
            if inner.endswith(marker):
                inner = inner[:-3]
            return inner.strip()
        if text.startswith("/*"):
            # Block comment: strip /* opener, */ closer, and leading * on each line
            inner = text[2:]
            if inner.endswith("*/"):
                inner = inner[:-2]
            lines = inner.split("\n")
            result = [ln.lstrip("* ").rstrip() for ln in lines]
            return "\n".join(ln for ln in result if ln)
        if text.startswith("//"):
            return text.lstrip("/").strip()
        if text.startswith("#"):
            return text.lstrip("#").strip()
        return text

    def _comment_desc_from_tree(root_node) -> Optional[str]:
        """Walk top-level CST nodes to extract leading comment/docstring block."""
        lines: list = []
        for child in root_node.children:
            t = child.type
            # Anonymous whitespace/newline tokens
            if not child.is_named:
                continue
            # Comment nodes (line_comment, block_comment, doc_comment, comment, …)
            if t.endswith("comment") or t == "comment":
                raw = child.text.decode("utf-8", errors="replace")
                stripped = _strip_comment_markers(raw)
                lines.extend(stripped.splitlines())
            elif t == "expression_statement":
                # Python module docstring: expression_statement → string
                string_child = next(
                    (c for c in child.children if c.type == "string"), None
                )
                if string_child and not lines:
                    raw = string_child.text.decode("utf-8", errors="replace")
                    lines.extend(_strip_comment_markers(raw).splitlines())
                break  # real code node either way — stop
            else:
                break  # real code node — stop
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines) if lines else None

    def _try_ts_parse(content: str, ext: str):
        """Return a tree-sitter Tree for *content*, or None if no grammar is installed."""
        try:
            if ext == ".py":
                from ts_parsers import PythonImportParser as _P
                return _P()._parser.parse(content.encode("utf-8", errors="replace"))
            if ext in (".js", ".jsx", ".mjs"):
                from ts_parsers import JavaScriptImportParserTS as _P
                return _P()._parser.parse(content.encode("utf-8", errors="replace"))
            if ext == ".ts":
                from ts_parsers import TypeScriptImportParserTS as _P
                return _P()._ts_parser.parse(content.encode("utf-8", errors="replace"))
            if ext == ".tsx":
                from ts_parsers import TypeScriptImportParserTS as _P
                return _P()._tsx_parser.parse(content.encode("utf-8", errors="replace"))
            if ext in (".c", ".cpp", ".cc", ".h", ".hpp"):
                from ts_parsers import CImportParserTS as _P
                return _P()._parser.parse(content.encode("utf-8", errors="replace"))
            if ext == ".java":
                from ts_parsers import JavaImportParserTS as _P
                return _P()._parser.parse(content.encode("utf-8", errors="replace"))
        except (ImportError, Exception):
            pass
        return None

    def _read_file_ts_info(path: str, root: Optional[str]) -> Tuple[Optional[str], Optional[bool]]:
        """Return (comment_desc, has_parse_errors) for *path*.

        comment_desc    — leading comment/docstring text, or None
        has_parse_errors — True/False if tree-sitter parsed the file;
                           None if no grammar is available for this extension.

        Tries tree-sitter first; falls back to regex for comment extraction
        only (has_parse_errors stays None in the regex path).
        """
        p = Path(path)
        if not p.is_absolute() and root:
            p = Path(root) / p
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return None, None

        ext = p.suffix.lower()
        tree = _try_ts_parse(raw, ext)
        if tree is not None:
            comment_desc = _comment_desc_from_tree(tree.root_node)
            has_parse_errors = tree.root_node.has_error
            return comment_desc, has_parse_errors

        # Regex fallback for files with no installed tree-sitter grammar.
        comment_lines: list = []
        in_block = False   # inside /* ... */
        in_triple = False  # inside """..."""

        for raw_line in raw.splitlines()[:40]:
            line = raw_line.strip()

            if not line:
                if comment_lines:
                    comment_lines.append("")
                continue

            if not in_block and not in_triple and (line.startswith('"""') or line.startswith("'''")):
                marker = line[:3]
                inner = line[3:]
                if inner.endswith(marker) and len(inner) > len(marker):
                    comment_lines.append(inner[:-3].strip())
                    break
                comment_lines.append(inner.strip())
                in_triple = True
                continue

            if in_triple:
                if '"""' in line or "'''" in line:
                    closing = '"""' if '"""' in line else "'''"
                    text = line[:line.index(closing)].strip()
                    if text:
                        comment_lines.append(text)
                    in_triple = False
                    break
                comment_lines.append(line)
                continue

            if not in_block and line.startswith("/*"):
                inner = line[2:].lstrip("* ").rstrip("*/").strip()
                if inner:
                    comment_lines.append(inner)
                in_block = True
                continue

            if in_block:
                if "*/" in line:
                    inner = line[:line.index("*/")].lstrip("* ").strip()
                    if inner:
                        comment_lines.append(inner)
                    in_block = False
                    break
                inner = line.lstrip("* ").strip()
                if inner:
                    comment_lines.append(inner)
                continue

            if line.startswith("#"):
                comment_lines.append(line.lstrip("#").strip())
                continue
            if line.startswith("//"):
                comment_lines.append(line.lstrip("/").strip())
                continue

            break

        while comment_lines and comment_lines[-1] == "":
            comment_lines.pop()

        # Regex path: no grammar → has_parse_errors is None (no signal)
        return "\n".join(comment_lines) if comment_lines else None, None

    def _kind_from_details(file_node, import_str: str) -> str:
        for d in file_node.metadata.get("import_details", []):
            if d.get("resolved_path") == import_str or d.get("imported_name") == import_str:
                t = d.get("import_type", "unknown")
                if t == "system":
                    return "system"
                if t == "external":
                    return "package"
        return "unknown"

    externals: Dict[str, ExternalEntry] = {}
    file_entries: List[FileEntry] = []

    for path in sorted_paths:
        node = sg._files[path]
        import_ids: List[str] = []

        for imp in sorted(node.imports):
            if imp in path_to_id:
                import_ids.append(path_to_id[imp])
            else:
                ext_id = f"ext_{imp}"
                if ext_id not in externals:
                    kind = _kind_from_details(node, imp)
                    externals[ext_id] = ExternalEntry(id=ext_id, name=imp, kind=kind)
                import_ids.append(ext_id)

        comment_desc, has_parse_errors = _read_file_ts_info(path, sg_root)
        file_entries.append(FileEntry(
            id=path_to_id[path],
            path=path,
            size_bytes=node.size_bytes,
            line_count=_count_lines(path, sg_root),
            ext=node.extension,
            imports=import_ids,
            comment_desc=comment_desc,
            has_parse_errors=has_parse_errors,
        ))

    # Symbol extraction — production files only.
    # Test and generated-code symbols are noise in dead-code and call-graph analysis.
    all_symbols: List[SymbolEntry] = []
    if _registry is not None:
        for path in sorted_paths:
            if _is_test_file(str(path)) or _is_generated_file(str(path)):
                continue
            fid = path_to_id[path]
            syms = _extract_symbols(fid, path, sg_root, _registry)
            all_symbols.extend(syms)
    # Assign stable IDs sorted by (file_id, start_line)
    all_symbols.sort(key=lambda s: (s.file_id, s.start_line))
    # file_id is like "f0", "f1" — sort lexically but numerically
    all_symbols.sort(key=lambda s: (
        int(s.file_id[1:]) if s.file_id.startswith("f") and s.file_id[1:].isdigit() else 0,
        s.start_line,
    ))
    numbered = [s.model_copy(update={"id": f"s{i}"}) for i, s in enumerate(all_symbols)]

    # Config file discovery — parse build manifests for module boundary hints.
    # Done first so cfg_entries can inform module detection below.
    cfg_entries: List[ConfigEntry] = []
    lockfile_entries: List[LockfileEntry] = []
    if sg_root is not None:
        try:
            cfg_entries = _collect_configs(Path(sg_root))
        except Exception:
            pass  # graceful degradation
        try:
            lockfile_entries = _collect_lockfiles(Path(sg_root))
        except Exception:
            pass  # graceful degradation

    # Module detection — L2/L3, requires root_path
    from pathlib import Path as _Path
    mods: List = []
    modularity_status = "stub"
    if detect_modules and sg_root is not None:
        try:
            from modularity import detect_modules as _detect_modules
            mods = _detect_modules(_Path(sg_root), file_entries, cfg_entries)
            modularity_status = "complete"
        except Exception:
            pass  # graceful degradation — modules stay empty

    # Clone detection — optional, requires treepeat
    clones: List = []
    clone_status = "stub"
    if detect_clones:
        sg_root_path = Path(getattr(sg, "root_path", ".")).resolve()
        # Build abs_path → file_id map for the translator
        abs_file_id_map: Dict[str, str] = {}
        for rel_path, fid in path_to_id.items():
            p = Path(rel_path)
            abs_key = str(p.resolve() if p.is_absolute() else (sg_root_path / p).resolve())
            abs_file_id_map[abs_key] = fid
        # Run treepeat once per primary language group to avoid cross-language
        # noise (e.g. Python clones mixed with C/C++ clones in llama-cpp).
        lang_groups = _detect_clone_lang_groups(abs_file_id_map)
        any_timeout = False
        if len(lang_groups) <= 1:
            clones, any_timeout = _run_treepeat_lazy(
                sg_root_path, clone_ruleset, abs_file_id_map, ignore_dirs,
                sarif_save_path=clone_sarif_path, show_progress=show_progress)
        else:
            all_primary_exts: frozenset = frozenset(
                e for exts in lang_groups.values() for e in exts
            )
            all_clones: List = []
            for _lang, lang_exts in sorted(lang_groups.items()):
                lang_file_id_map = {
                    p: fid for p, fid in abs_file_id_map.items()
                    if Path(p).suffix.lower() in lang_exts
                }
                # For multi-language repos, suffix the SARIF path per language
                lang_sarif = (
                    clone_sarif_path.with_suffix(f".{_lang}.sarif")
                    if clone_sarif_path is not None else None
                )
                lang_clones, lang_timeout = _run_treepeat_lazy(
                    sg_root_path, clone_ruleset, lang_file_id_map, ignore_dirs,
                    exclude_exts=all_primary_exts - lang_exts,
                    sarif_save_path=lang_sarif,
                    show_progress=show_progress,
                )
                all_clones.extend(lang_clones)
                any_timeout = any_timeout or lang_timeout
            clones = all_clones
        clone_status = "timeout" if any_timeout else "complete"

    return Blueprint(
        files=file_entries,
        externals=list(externals.values()),
        configs=cfg_entries,
        lockfiles=lockfile_entries,
        symbols=numbered,
        modules=mods,
        modularity_status=modularity_status,
        clone_blocks=clones,
        clone_status=clone_status,
    )


def blueprint_to_sourcegraph(bp: Blueprint) -> SourceGraph:
    """Convert a Blueprint back to a SourceGraph.

    Internal imports (file-to-file) are restored via add_import so that
    both imports and imported_by sets are populated correctly.
    External imports are stored as raw name strings in FileNode.imports,
    matching how the import analysers populate them before resolution.
    """
    sg = SourceGraph()

    id_to_file: Dict[str, FileEntry] = {f.id: f for f in bp.files}
    id_to_ext: Dict[str, ExternalEntry] = {e.id: e for e in bp.externals}

    for fe in bp.files:
        sg.add_file(fe.path, fe.size_bytes, fe.ext)

    for fe in bp.files:
        for imp_id in fe.imports:
            if imp_id in id_to_file:
                sg.add_import(fe.path, id_to_file[imp_id].path)
            elif imp_id in id_to_ext:
                sg._files[fe.path].imports.add(id_to_ext[imp_id].name)

    return sg


# ---------------------------------------------------------------------------
# LSP enrichment helpers
# ---------------------------------------------------------------------------

def _uri_to_path(uri: str) -> str:
    """Strip the ``file://`` prefix from a file URI, returning an OS path."""
    if uri.startswith("file://"):
        return uri[7:]  # "file://" is 7 chars; leaves "/abs/path" on POSIX
    return uri


def _read_file_text(uri: str) -> str:
    """Read file content for a ``file://`` URI, returning '' on error."""
    try:
        return Path(_uri_to_path(uri)).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _find_symbol_at(
    syms_by_fid: Dict[str, List[SymbolEntry]],
    file_id: Optional[str],
    line_1based: int,
) -> Optional[str]:
    """Return the id of the innermost symbol at *line_1based* in *file_id*.

    Considers only function and method symbols (the kinds for which we build
    ReferenceEdge entries). Returns ``None`` if nothing matches.
    """
    if file_id is None:
        return None
    best: Optional[SymbolEntry] = None
    for sym in syms_by_fid.get(file_id, []):
        if sym.kind not in ("function", "method"):
            continue
        if sym.start_line <= line_1based <= sym.end_line:
            # prefer the innermost (smallest span)
            if best is None or (sym.end_line - sym.start_line) < (best.end_line - best.start_line):
                best = sym
    return best.id if best is not None else None


def _is_test_file(path: str) -> bool:
    """Return True if *path* looks like a test file by naming convention."""
    p = Path(path)
    name = p.stem.lower()
    parts = [part.lower() for part in p.parts]
    return (
        name.startswith("test_")
        or name.endswith("_test")
        or name.endswith(".test")
        or name.endswith(".spec")
        or any(part in ("test", "tests") for part in parts[:-1])  # parent dir
    )


def _is_generated_file(path: str) -> bool:
    """Return True if *path* looks like auto-generated code by naming convention.

    Covers protobuf/gRPC stubs, codegen output directories, and explicit
    ``*.generated.*`` markers.  Generated files are kept in the file inventory
    but their symbols are excluded from symbol extraction and LSP queries —
    they inflate dead-code counts and call-graph noise without contributing
    meaningful architectural signal.
    """
    p = Path(path)
    stem = p.stem.lower()
    parts = [part.lower() for part in p.parts]
    return (
        # Protobuf / gRPC generated stubs
        stem.endswith("_pb2")          # foo_pb2.py
        or stem.endswith("_pb2_grpc")  # foo_pb2_grpc.py
        or stem.endswith(".pb")        # foo.pb.go, foo.pb.ts
        # Explicit generated marker in the stem
        or stem.endswith("_generated")       # foo_generated.py
        or stem.endswith(".generated")       # foo.generated.ts → stem = foo.generated
        # Codegen output directories
        or any(part in ("generated", "__generated__") for part in parts[:-1])
    )


_LSP_SEVERITY: Dict[int, str] = {1: "error", 2: "warning", 3: "information", 4: "hint"}

_CALLABLE_KINDS = frozenset(("function", "method"))


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enrich_blueprint_with_lsp(
    bp: Blueprint,
    client,
    file_id_to_uri: Dict[str, str],
    language_id: str,
    symbol_budget_s: float = 300.0,
    show_progress: bool = False,
) -> Blueprint:
    """Enrich a Blueprint with LSP-derived call graph, dead code, and diagnostics.

    Sends ``textDocument/didOpen`` for every file in *file_id_to_uri*, collects
    ``publishDiagnostics`` push notifications, then queries incoming calls (or
    references as a fallback) for each function/method symbol to produce
    :class:`ReferenceEdge` objects.  Dead code is derived from the resulting
    call counts without an additional LSP round-trip.

    Coordinate convention: LSP positions are 0-based; Blueprint uses 1-based.
    A column of 0 is used when querying symbol positions (start-of-name heuristic).

    Args:
        bp: A Blueprint with FileEntry + SymbolEntry already populated.
        client: A started :class:`~lsp_client.LspClient` ready for requests.
        file_id_to_uri: Mapping from file_id to LSP URI (``file:///abs/path``).
            Only files present here are opened and queried.
        language_id: LSP language identifier (``"python"``, ``"typescript"``…).

    Returns:
        A new Blueprint with ``reference_edges``, ``dead_symbols``, and
        ``diagnostics`` populated; ``semantic_status``, ``dead_code_status``,
        and ``diagnostic_status`` set to ``"complete"``.
    """
    if not file_id_to_uri:
        return bp

    uri_to_fid: Dict[str, str] = {v: k for k, v in file_id_to_uri.items()}
    fid_to_path: Dict[str, str] = {f.id: f.path for f in bp.files}

    # Index symbols by file_id for fast lookup
    syms_by_fid: Dict[str, List[SymbolEntry]] = defaultdict(list)
    for sym in bp.symbols:
        if sym.file_id in file_id_to_uri:
            syms_by_fid[sym.file_id].append(sym)

    # --- open files and collect push diagnostics ---
    # Build content cache here so we can look up symbol columns below without
    # re-reading files.  LSP positions are 0-based; sym.start_line is 1-based.
    fid_to_lines: Dict[str, List[str]] = {}
    files_to_open = []
    for _fid, _uri in sorted(file_id_to_uri.items()):
        _content = _read_file_text(_uri)
        fid_to_lines[_fid] = _content.splitlines()
        files_to_open.append((_uri, _content, language_id))
    _open_t0 = time.monotonic()
    push_diags = client.open_files(files_to_open)
    applog.info("  LSP %s: open_files %.1fs (%d files)", language_id, time.monotonic() - _open_t0, len(files_to_open))

    # --- convert raw LSP diagnostics → DiagnosticEntry ---
    diag_entries: List[DiagnosticEntry] = []
    for uri, raw_diags in push_diags.items():
        fid = uri_to_fid.get(uri)
        if fid is None:
            continue
        for d in raw_diags:
            r = d.get("range", {})
            start = r.get("start", {})
            end = r.get("end", {})
            line = start.get("line", 0) + 1
            col = start.get("character", 0) + 1
            end_line = end.get("line", 0) + 1
            end_col = end.get("character", 0) + 1
            if end_line < line:
                end_line, end_col = line, col
            severity = _LSP_SEVERITY.get(d.get("severity", 2), "warning")
            code_val = d.get("code")
            diag_entries.append(DiagnosticEntry(
                file_id=fid,
                line=line,
                col=col,
                end_line=end_line,
                end_col=end_col,
                severity=severity,
                code=str(code_val) if code_val is not None else None,
                message=d.get("message", ""),
                source=d.get("source", language_id),
            ))

    # --- query call graph for each callable symbol ---
    ref_edges: List[ReferenceEdge] = []
    incoming_count: Dict[str, int] = {}  # symbol_id → number of incoming edges
    _sym_deadline = time.monotonic() + symbol_budget_s
    _budget_hit = False

    _total_syms = sum(len(v) for v in syms_by_fid.values())
    applog.info("  LSP %s: %d symbols to query (budget %.0fs)", language_id, _total_syms, symbol_budget_s)
    _pbar = _tqdm(
        total=_total_syms,
        desc=f"LSP {language_id}",
        unit="sym",
        disable=not (show_progress and HAS_TQDM),
    ) if HAS_TQDM else None

    _syms_queried = 0
    _loop_t0 = time.monotonic()

    for fid in sorted(syms_by_fid.keys()):
        if _budget_hit:
            break
        # Skip test and generated-code files: not production dead code.
        fpath = fid_to_path.get(fid, "")
        if _is_test_file(fpath) or _is_generated_file(fpath):
            continue
        uri = file_id_to_uri[fid]
        for sym in syms_by_fid[fid]:
            try:
                if time.monotonic() >= _sym_deadline:
                    applog.warn(
                        "⚠️  LSP %s: symbol budget %.0fs exhausted after %d edges — stopping early",
                        language_id, symbol_budget_s, len(ref_edges),
                    )
                    _budget_hit = True
                    break
                if sym.kind not in _CALLABLE_KINDS:
                    continue
                # Skip private non-exported symbols: LSP references for _helpers add
                # many round-trips but are rarely the interesting cross-file calls.
                if sym.name.startswith("_") and not sym.is_exported:
                    continue
                lsp_line = sym.start_line - 1  # 1-based → 0-based
                # Find the column of the symbol name on its definition line.
                # Hardcoding col=0 points at `def`/`class` keywords, not the name,
                # causing all LSP servers to return empty results.
                _line_text = fid_to_lines.get(fid, [""])[lsp_line] if lsp_line < len(fid_to_lines.get(fid, [])) else ""
                lsp_col = _line_text.find(sym.name)
                if lsp_col < 0:
                    lsp_col = 0  # fallback

                # Use textDocument/references directly.  Call hierarchy (prepareCallHierarchy
                # + incomingCalls) is theoretically richer but in practice returns empty results
                # for Python/jedi-language-server, adding two round-trips per symbol for no gain.
                try:
                    _ref_t0 = time.monotonic()
                    locs = client.references(uri, lsp_line, lsp_col)
                    _ref_dt = time.monotonic() - _ref_t0
                    if _ref_dt > 5.0:
                        applog.info(
                            "  LSP %s: slow ref %.1fs  %s:%d  %s",
                            language_id, _ref_dt, fpath, sym.start_line, sym.name,
                        )
                except Exception:
                    locs = []
                _syms_queried += 1
                for loc in locs:
                    loc_uri = loc.get("uri", "")
                    loc_fid = uri_to_fid.get(loc_uri)
                    if loc_fid is None:
                        continue
                    site_line = loc.get("range", {}).get("start", {}).get("line", 0) + 1
                    from_sym_id = _find_symbol_at(syms_by_fid, loc_fid, site_line)
                    if from_sym_id is None:
                        continue
                    ref_edges.append(ReferenceEdge(
                        from_symbol_id=from_sym_id,
                        to_symbol_id=sym.id,
                        call_site_file_id=loc_fid,
                        call_site_line=site_line,
                    ))
                    incoming_count[sym.id] = incoming_count.get(sym.id, 0) + 1
            finally:
                if _pbar is not None:
                    _pbar.update(1)

    if _pbar is not None:
        _pbar.close()

    applog.info(
        "  LSP %s: refs loop %.1fs — %d queried, %d edges%s",
        language_id, time.monotonic() - _loop_t0,
        _syms_queried, len(ref_edges),
        " [budget hit]" if _budget_hit else "",
    )

    # --- derive dead symbols ---
    dead_symbols: List[DeadSymbol] = list(bp.dead_symbols)
    dead_idx = len(dead_symbols)
    for sym in bp.symbols:
        if sym.file_id not in file_id_to_uri:
            continue
        if sym.kind not in _CALLABLE_KINDS:
            continue
        callers = [e for e in ref_edges if e.to_symbol_id == sym.id]
        count = len(callers)
        if count == 0 and not sym.is_exported:
            # No callers and not part of the public API → unreferenced
            dead_symbols.append(DeadSymbol(
                id=f"dead_{dead_idx}",
                symbol_id=sym.id,
                confidence=0.9,
                reason="unreferenced",
            ))
            dead_idx += 1
        elif count > 0 and sym.is_exported and all(
            _is_test_file(fid_to_path.get(e.call_site_file_id, ""))
            for e in callers
        ):
            # Public symbol called only from test code → effectively dead in production
            dead_symbols.append(DeadSymbol(
                id=f"dead_{dead_idx}",
                symbol_id=sym.id,
                confidence=0.7,
                reason="test_only",
            ))
            dead_idx += 1

    return bp.model_copy(update={
        "reference_edges": ref_edges,
        "dead_symbols": dead_symbols,
        "diagnostics": diag_entries,
        "semantic_status": "complete",
        "dead_code_status": "complete",
        "diagnostic_status": "complete",
    })


# ---------------------------------------------------------------------------
# Multi-language LSP orchestration
# ---------------------------------------------------------------------------

# Maps file extension → LSP language identifier.
_EXT_TO_LANG: Dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".rs": "rust",
    ".java": "java",
}

# Maps language identifier → server command (first element checked via shutil.which).
_LANG_SERVERS: Dict[str, List[str]] = {
    # jedi-language-server: pure Python wheel, pip-installable, no Node/Rust dep.
    # Future: replace with `ty server` (astral-sh/ty) once it implements callHierarchy
    # (currently missing from ty's LSP feature set; tracked upstream).
    "python": ["jedi-language-server"],
    "javascript": ["npx", "--no-install", "typescript-language-server", "--stdio"],
    "typescript": ["npx", "--no-install", "typescript-language-server", "--stdio"],
    "go": ["gopls"],
    "rust": ["rust-analyzer"],
    # Java: jdtls requires a Java 21+ JVM to run (even to analyse Java 8/11/17 source).
    # The command is resolved at runtime by _resolve_lsp_cmd() using jvm_detect.
    "java": ["jdtls"],
}


def _resolve_lsp_cmd(
    lang_id: str,
) -> Tuple[Optional[List[str]], Optional[str]]:
    """Return ``(cmd, skip_reason)`` for the LSP server for *lang_id*.

    For most languages *cmd* is just ``_LANG_SERVERS[lang_id]`` after a PATH
    check.  Java is handled specially: jdtls requires a Java 21+ JVM, located
    via :mod:`jvm_detect`, and a persistent ``--data`` workspace directory.

    Returns ``(None, reason)`` when the server is unavailable; *reason* is a
    short human-readable string suitable for ``Blueprint.semantic_skip_reasons``.
    Returns ``(cmd, None)`` on success.
    """
    base_cmd = _LANG_SERVERS.get(lang_id)
    if not base_cmd:
        return None, f"{lang_id}: no LSP server configured"

    if lang_id == "java":
        if not shutil.which("jdtls"):
            applog.warn(
                "⚠️  jdtls not found on PATH; skipping semantic enrichment for Java. "
                "Install with: brew install jdtls"
            )
            return None, "java: jdtls not installed (brew install jdtls)"

        from config import load_config
        try:
            cfg, _, _ = load_config()
            config_java_home: Optional[str] = cfg.java.java_home
        except Exception:
            config_java_home = None

        from jvm_detect import find_java, describe_java_candidates, format_candidates_log
        result = find_java(min_version=21, extra_home=config_java_home)
        if result is None:
            candidates = describe_java_candidates(extra_home=config_java_home)
            applog.warn(
                "⚠️  jdtls requires Java 21+, but no suitable JVM was found. "
                "Skipping semantic enrichment for Java.\n"
                "  Detected JVMs: %s\n"
                "  To fix: set COMPREHENSITY_JAVA_HOME, JAVA_HOME, or add "
                "[java] java_home = \"/path/to/jdk21+\" to your config.toml.",
                format_candidates_log(candidates),
            )
            versions_str = format_candidates_log(candidates)
            return None, f"java: Java 21+ JVM not found (detected: {versions_str})"

        java_bin, java_version = result
        applog.info("  jdtls will use Java %d at %s", java_version, java_bin)

        # Use a persistent workspace dir so jdtls can reuse its index across runs.
        # This is ~10x faster than a fresh tmpdir on large codebases.
        workspace_dir = Path.home() / ".comprehensity" / "jdtls-workspace"
        workspace_dir.mkdir(parents=True, exist_ok=True)

        return ["jdtls", "--java-executable", java_bin, "--data", str(workspace_dir)], None

    # All other languages: just check the binary is on PATH.
    # For npx-based servers, we do a quick 'pre-flight' to ensure the binary is actually
    # reachable (not hanging on a download if no internet).
    if base_cmd[0] == "npx":
        try:
            # Check if npx itself exists first
            if not shutil.which("npx"):
                return None, f"{lang_id}: npx not installed"
            # Try to run with --version to see if the package is reachable/cached.
            # We MUST use --no-install to honor the 'no network' constraint in Phase 1.
            # 60s timeout is generous for a local cache but prevents long hangs.
            subprocess.run(["npx", "--no-install", base_cmd[2], "--version"], 
                         capture_output=True, timeout=60, check=False)
        except (subprocess.SubprocessError, Exception):
            return None, f"{lang_id}: {base_cmd[2]} (via npx) is not reachable or not cached locally"
    elif not shutil.which(base_cmd[0]):
        return None, f"{lang_id}: {base_cmd[0]} not installed"
    return base_cmd, None

# Per-language LSP initializationOptions.  Passed verbatim to the server's
# initialize request.  Keeping these explicit prevents servers from indexing
# large directories (e.g. venvs, build artifacts) that inflate startup time.
_LANG_SERVER_INIT_OPTIONS: Dict[str, Dict] = {
    "python": {
        # jedi-language-server workspace settings:
        # ignoreFolders suppresses workspace-symbol indexing for these dirs.
        # We extend the server default (.git/.tox/__pycache__/.venv/venv) with
        # common artifact/output dirs so jedi doesn't crawl them on startup.
        "workspace": {
            "symbols": {
                "ignoreFolders": [
                    ".git", ".tox", "__pycache__", ".venv", "venv",
                    "node_modules", "output", "dist", "build", "target",
                    ".pytest_cache", "coverage_html_report", ".mypy_cache",
                ]
            }
        }
    },
}


def enrich_blueprint_semantic(bp: Blueprint, root: Path, show_progress: bool = False) -> Blueprint:
    """Enrich *bp* with LSP-derived call graph, dead code, and diagnostics.

    Groups ``bp.files`` by language (using :data:`_EXT_TO_LANG`), starts one
    :class:`~lsp_client.LspClient` per detected language server, calls
    :func:`enrich_blueprint_with_lsp` for each group, and merges the results
    into a single Blueprint.

    Files whose extension is not in :data:`_EXT_TO_LANG` are silently skipped.
    If a language server binary is not found on ``PATH``, a warning is logged
    and that language is skipped (graceful degradation).

    Args:
        bp: Blueprint with files and symbols already populated.
        root: Absolute path to the project root; used to resolve relative file
            paths to ``file://`` URIs for the LSP server.

    Returns:
        A new Blueprint with ``reference_edges``, ``dead_symbols``,
        ``diagnostics``, ``semantic_status``, ``dead_code_status``, and
        ``diagnostic_status`` set.  If no servers were available the original
        blueprint is returned unchanged.
    """
    # Group file entries by language.
    lang_files: Dict[str, List[FileEntry]] = defaultdict(list)
    for fe in bp.files:
        lang_id = _EXT_TO_LANG.get(fe.ext.lower())
        if lang_id:
            lang_files[lang_id].append(fe)

    if not lang_files:
        return bp

    # JS/TS preflight: node_modules must exist for the language server to resolve types.
    # If absent, skip JS/TS and emit a structured AnalysisWarning with the fix command.
    new_warnings: List[AnalysisWarning] = list(bp.analysis_warnings)
    _js_langs = {"javascript", "typescript"}
    _js_ts_count = sum(len(lang_files[l]) for l in _js_langs if l in lang_files)
    if _js_ts_count >= 10 and not (root / "node_modules").exists():
        pm_info = detect_js_package_manager(root)
        if pm_info is None or pm_info["required"] == "npm":
            action = "run: npm install"
        elif pm_info["required"] == "yarn-berry":
            if pm_info.get("installed_version") is None:
                action = "run: npm install -g corepack && corepack enable && yarn install"
            else:
                action = "run: corepack enable && yarn install"
        elif pm_info["required"] == "yarn-classic":
            action = "run: yarn install"
        elif pm_info["required"] == "pnpm":
            action = "run: pnpm install"
        elif pm_info["required"] == "bun":
            action = "run: bun install"
        else:
            action = "run: npm install"
        new_warnings.append(AnalysisWarning(
            phase="semantic",
            code="no_node_modules",
            severity="skipped",
            message=(
                "node_modules not found at project root; "
                "JavaScript/TypeScript semantic analysis skipped."
            ),
            action=action,
        ))
        applog.warn(
            "⚠️  node_modules not found at %s; skipping JS/TS semantic enrichment (%s)",
            root,
            action,
        )
        for lang_id in list(_js_langs):
            lang_files.pop(lang_id, None)

    if not lang_files:
        return bp.model_copy(update={"analysis_warnings": new_warnings}) \
               if new_warnings != list(bp.analysis_warnings) else bp

    # Collect merged results across languages.
    all_ref_edges: List[ReferenceEdge] = []
    all_diagnostics: List[DiagnosticEntry] = []
    # dead_symbols: start from existing; track which symbol_ids are already dead.
    all_dead_symbols: List[DeadSymbol] = list(bp.dead_symbols)
    seen_dead: Set[str] = {d.symbol_id for d in all_dead_symbols}
    enriched_any = False
    skip_reasons: List[str] = []

    for lang_id, files in lang_files.items():
        cmd, skip_reason = _resolve_lsp_cmd(lang_id)
        if cmd is None:
            if skip_reason:
                skip_reasons.append(skip_reason)
            base_cmd = _LANG_SERVERS.get(lang_id)
            if lang_id != "java":  # java logs its own detailed warning
                applog.warn(
                    "⚠️  LSP server not found for %s (%s); skipping semantic enrichment",
                    lang_id,
                    base_cmd[0] if base_cmd else "no server configured",
                )
            continue

        file_id_to_uri: Dict[str, str] = {}
        for fe in files:
            p = Path(fe.path)
            abs_path = p if p.is_absolute() else root / p
            file_id_to_uri[fe.id] = abs_path.resolve().as_uri()

        applog.info("  LSP %s: %d files via %s", lang_id, len(files), cmd[0])

        init_opts = _LANG_SERVER_INIT_OPTIONS.get(lang_id)
        try:
            with LspClient(cmd, root_uri=root.resolve().as_uri(),
                           initialization_options=init_opts) as client:
                bp_lang = enrich_blueprint_with_lsp(bp, client, file_id_to_uri, lang_id,
                                                    show_progress=show_progress)
        except Exception as exc:
            applog.warn("⚠️  LSP %s failed: %s", lang_id, exc)
            continue

        all_ref_edges.extend(bp_lang.reference_edges)
        all_diagnostics.extend(bp_lang.diagnostics)
        for d in bp_lang.dead_symbols:
            if d.symbol_id not in seen_dead:
                all_dead_symbols.append(d)
                seen_dead.add(d.symbol_id)
        enriched_any = True

    if not enriched_any:
        update: dict = {}
        if skip_reasons:
            update["semantic_skip_reasons"] = skip_reasons
        if new_warnings != list(bp.analysis_warnings):
            update["analysis_warnings"] = new_warnings
        return bp.model_copy(update=update) if update else bp

    update = {
        "reference_edges": all_ref_edges,
        "dead_symbols": all_dead_symbols,
        "diagnostics": all_diagnostics,
        "semantic_status": "complete",
        "semantic_skip_reasons": skip_reasons,
        "dead_code_status": "complete",
        "diagnostic_status": "complete",
    }
    if new_warnings != list(bp.analysis_warnings):
        update["analysis_warnings"] = new_warnings
    return bp.model_copy(update=update)
