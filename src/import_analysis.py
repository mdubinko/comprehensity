#!/usr/bin/env python3

"""
Import Analysis Module using Property Graph

This module analyzes import/include relationships in codebases using the PropGraph
property graph database library. It replaces the functionality from depgraph.py with a
more general graph-based approach.

Key changes from depgraph.py:
- Uses PropertyGraph to store import relationships as nodes and edges
- Maintains same language parsing functionality
- Stores import metadata in graph properties
- Provides same analyze_source_imports API for compatibility
"""

import re
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List, Dict, Set, Optional, Tuple

from propweaver import PropertyGraph

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


class ImportType(Enum):
    """Types of imports across different languages"""

    LOCAL = "local"  # Local project files (C: "file.h", Python: from .module)
    SYSTEM = "system"  # System/standard library (C: <stdio.h>, Python: import os)
    EXTERNAL = "external"  # External packages (Python: import numpy, JS: import lodash)
    UNKNOWN = "unknown"  # Cannot determine type


@dataclass
class Import:
    """Represents a single import/include statement"""

    raw_statement: str  # Original text: '#include "file.h"', 'import sys'
    imported_name: str  # What's being imported: 'file.h', 'sys'
    import_type: ImportType  # LOCAL, SYSTEM, EXTERNAL, UNKNOWN
    line_number: int  # Line number in source file
    resolved_path: Optional[str] = None  # Actual file path if resolved

    def __str__(self):
        return f"{self.import_type.value}: {self.imported_name}"


class ImportParser(ABC):
    """Abstract base class for language-specific import parsers"""

    @abstractmethod
    def parse_file(self, file_path: str, content: str) -> List[Import]:
        """
        Parse a file and extract all import statements

        Args:
            file_path: Path to the file being parsed (for context)
            content: File content as string

        Returns:
            List of Import objects found in the file
        """
        pass

    @abstractmethod
    def get_supported_extensions(self) -> Set[str]:
        """Return set of file extensions this parser supports"""
        pass


class JavaImportParserLegacy(ImportParser):
    """Legacy regex parser for Java import statements (kept for fallback/testing)."""

    def __init__(self):
        # Java import patterns
        self.import_pattern = re.compile(
            r"^\s*import\s+(static\s+)?([a-zA-Z_$][a-zA-Z0-9_$]*(?:\.[a-zA-Z_$*][a-zA-Z0-9_$*]*)*)\s*;\s*(?://.*)?$"
        )

        # Java system packages
        self.system_packages = {"java", "javax", "com.sun", "sun", "com.oracle", "jdk"}

        # Common external library prefixes
        self.common_external_prefixes = {
            "org.springframework",
            "org.apache",
            "org.junit",
            "org.mockito",
            "org.slf4j",
            "org.hibernate",
            "com.google",
            "com.fasterxml",
            "io.micrometer",
            "org.assertj",
            "org.testng",
            "com.amazonaws",
            "org.eclipse",
            "org.jetbrains",
            "net.sf",
            "org.json",
        }

    def parse_file(self, file_path: str, content: str) -> List[Import]:
        """Parse Java file for import statements"""
        imports = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            line = line.strip()
            if not line or line.startswith("//") or line.startswith("/*"):
                continue

            # Skip package declarations
            if line.startswith("package "):
                continue

            # Stop at class/interface/enum declarations (imports must come before)
            if (
                line.startswith("public class ")
                or line.startswith("class ")
                or line.startswith("public interface ")
                or line.startswith("interface ")
                or line.startswith("public enum ")
                or line.startswith("enum ")
                or line.startswith("@")
            ):
                break

            if match := self.import_pattern.match(line):
                is_static = match.group(1) is not None
                full_import = match.group(2)
                import_type = self._classify_import(full_import, is_static)

                imports.append(
                    Import(
                        raw_statement=line,
                        imported_name=full_import,
                        import_type=import_type,
                        line_number=line_num,
                    )
                )

        return imports

    def _classify_import(self, import_name: str, is_static: bool) -> ImportType:
        """Classify Java import as LOCAL, SYSTEM, or EXTERNAL"""
        # Handle wildcard imports
        base_package = import_name.rstrip(".*")

        # Check if it's a system package
        for system_pkg in self.system_packages:
            if import_name.startswith(system_pkg + "."):
                return ImportType.SYSTEM

        # Check common external libraries
        for external_prefix in self.common_external_prefixes:
            if import_name.startswith(external_prefix + "."):
                return ImportType.EXTERNAL

        parts = import_name.split(".")

        match len(parts):
            case 1:
                return ImportType.LOCAL  # Single word, likely local
            case n if n >= 2:
                first_part, second_part = parts[0], parts[1]

                match first_part:
                    case "org":
                        if second_part in [
                            "apache",
                            "springframework",
                            "junit",
                            "mockito",
                            "slf4j",
                            "hibernate",
                            "eclipse",
                            "jetbrains",
                            "assertj",
                            "testng",
                            "json",
                        ]:
                            return ImportType.EXTERNAL
                        return ImportType.LOCAL

                    case "com":
                        if second_part in [
                            "google",
                            "fasterxml",
                            "amazonaws",
                            "oracle",
                            "sun",
                        ]:
                            return ImportType.EXTERNAL
                        return ImportType.LOCAL

                    case "io":
                        if second_part in ["micrometer"]:
                            return ImportType.EXTERNAL
                        return ImportType.LOCAL

                    case "net":
                        if second_part in ["sf"]:
                            return ImportType.EXTERNAL
                        return ImportType.LOCAL

                    case _:
                        return ImportType.LOCAL

            case _:
                return ImportType.LOCAL

    def get_supported_extensions(self) -> Set[str]:
        return {".java"}


class TypeScriptImportParserLegacy(ImportParser):
    """Legacy regex parser for TypeScript/JavaScript ES6 imports (kept for fallback/testing)."""

    def __init__(self):
        # ES6 import patterns
        self.import_patterns = [
            # import name from 'module'
            re.compile(r'^\s*import\s+(\w+)\s+from\s+[\'"]([^\'"]+)[\'"]'),
            # import { name1, name2 } from 'module'
            re.compile(r'^\s*import\s+\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]'),
            # import * as name from 'module'
            re.compile(r'^\s*import\s+\*\s+as\s+\w+\s+from\s+[\'"]([^\'"]+)[\'"]'),
            # import name, { other } from 'module'
            re.compile(
                r'^\s*import\s+\w+\s*,\s*\{[^}]*\}\s+from\s+[\'"]([^\'"]+)[\'"]'
            ),
            # import 'module' (side-effects only)
            re.compile(r'^\s*import\s+[\'"]([^\'"]+)[\'"]'),
        ]

        # Dynamic imports: import('module')
        self.dynamic_import_pattern = re.compile(
            r'import\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)'
        )

        # CommonJS: require('module') or const x = require('module')
        self.require_pattern = re.compile(r'require\s*\(\s*[\'"]([^\'"]+)[\'"]\s*\)')

    def parse_file(self, file_path: str, content: str) -> List[Import]:
        """Parse TypeScript/JavaScript file for import statements"""
        imports = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Remove comments for cleaner parsing (simple approach)
            line = line.strip()
            if not line or line.startswith("//"):
                continue

            # Remove inline comments
            if "//" in line:
                line = line.split("//")[0].strip()

            # Check ES6 import patterns
            for pattern in self.import_patterns:
                if match := pattern.search(line):
                    # Get the module name (last group for most patterns)
                    module_name = match.groups()[-1]
                    import_type = self._classify_import(module_name)

                    imports.append(
                        Import(
                            raw_statement=line,
                            imported_name=module_name,
                            import_type=import_type,
                            line_number=line_num,
                        )
                    )
                    break  # Only match first pattern per line

            # Check for dynamic imports in the line
            for match in self.dynamic_import_pattern.finditer(line):
                module_name = match.group(1)
                import_type = self._classify_import(module_name)

                imports.append(
                    Import(
                        raw_statement=line,
                        imported_name=module_name,
                        import_type=import_type,
                        line_number=line_num,
                    )
                )

            # Check for CommonJS requires
            for match in self.require_pattern.finditer(line):
                module_name = match.group(1)
                import_type = self._classify_import(module_name)

                imports.append(
                    Import(
                        raw_statement=line,
                        imported_name=module_name,
                        import_type=import_type,
                        line_number=line_num,
                    )
                )

        return imports

    def _classify_import(self, module_name: str) -> ImportType:
        """Classify import as LOCAL, SYSTEM, or EXTERNAL"""
        match module_name:
            case _ if module_name.startswith("./") or module_name.startswith("../"):
                return ImportType.LOCAL

            case (
                "fs"
                | "path"
                | "os"
                | "crypto"
                | "http"
                | "https"
                | "url"
                | "events"
                | "stream"
                | "util"
                | "child_process"
                | "cluster"
                | "dns"
                | "net"
                | "tls"
                | "readline"
                | "zlib"
                | "buffer"
                | "process"
                | "console"
                | "assert"
            ):
                return ImportType.SYSTEM

            case "window" | "document" | "navigator" | "location" | "history":
                return ImportType.SYSTEM

            case "typescript" | "zone.js":
                return ImportType.EXTERNAL

            case _ if (
                module_name.startswith("@angular/")
                or module_name.startswith("@types/")
                or module_name.startswith("rxjs")
            ):
                return ImportType.EXTERNAL

            case _ if module_name.startswith("@") and "/" in module_name:
                return ImportType.EXTERNAL

            case _ if not module_name.startswith("/") and "/" not in module_name:
                return ImportType.EXTERNAL

            case _:
                return ImportType.UNKNOWN

    def get_supported_extensions(self) -> Set[str]:
        return {".ts", ".tsx", ".js", ".jsx", ".mjs", ".vue"}


class CImportParserLegacy(ImportParser):
    """Legacy regex parser for C and C++ #include statements (kept for fallback/testing)."""

    def __init__(self):
        # Regex patterns for C/C++ includes
        self.local_include_pattern = re.compile(
            r'^\s*#include\s+"([^"]+)"\s*(?://.*)?$'
        )
        self.system_include_pattern = re.compile(
            r"^\s*#include\s+<([^>]+)>\s*(?://.*)?$"
        )

    def parse_file(self, file_path: str, content: str) -> List[Import]:
        """Parse C/C++ file for #include statements"""
        imports = []
        lines = content.split("\n")

        for line_num, line in enumerate(lines, 1):
            # Skip lines inside multi-line comments (simple heuristic)
            line = line.strip()
            if not line or line.startswith("//"):
                continue

            # Check for local includes: #include "file.h"
            if match := self.local_include_pattern.match(line):
                imported_name = match.group(1)
                imports.append(
                    Import(
                        raw_statement=line,
                        imported_name=imported_name,
                        import_type=ImportType.LOCAL,
                        line_number=line_num,
                    )
                )
                continue

            # Check for system includes: #include <file.h>
            if match := self.system_include_pattern.match(line):
                imported_name = match.group(1)
                imports.append(
                    Import(
                        raw_statement=line,
                        imported_name=imported_name,
                        import_type=ImportType.SYSTEM,
                        line_number=line_num,
                    )
                )

        return imports

    def get_supported_extensions(self) -> Set[str]:
        return {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}


class ImportResolver:
    """Resolves import statements to actual file paths"""

    def __init__(self, codebase_root: Path, include_paths: List[Path] = None):
        """
        Initialize resolver

        Args:
            codebase_root: Root directory of the codebase
            include_paths: Additional directories to search for includes
        """
        self.codebase_root = codebase_root
        self.include_paths = include_paths or []

        # Cache for resolved paths to avoid repeated filesystem operations
        self.resolution_cache: Dict[Tuple[str, str], Optional[str]] = {}

    def resolve_import(
        self, import_obj: Import, source_file_path: str
    ) -> Optional[str]:
        """
        Resolve an import to an actual file path

        Args:
            import_obj: The Import object to resolve
            source_file_path: Path of the file containing the import

        Returns:
            Resolved file path relative to codebase root, or None if not found
        """
        cache_key = (import_obj.imported_name, source_file_path)
        if cache_key in self.resolution_cache:
            return self.resolution_cache[cache_key]

        resolved_path = None

        if import_obj.import_type == ImportType.LOCAL:
            resolved_path = self._resolve_local_import(import_obj, source_file_path)
        elif import_obj.import_type == ImportType.SYSTEM:
            resolved_path = self._resolve_system_import(import_obj)
        elif import_obj.import_type == ImportType.EXTERNAL:
            # Python bare-name imports (e.g. `from streaming import X`) are classified
            # EXTERNAL by the parser (it can't see the filesystem), but may actually be
            # local modules in a src/ layout.  Try to find the file; if not found, leave
            # resolved_path as None so the import becomes an ExternalEntry as usual.
            if Path(source_file_path).suffix in {".py", ".pyw"}:
                resolved_path = self._resolve_python_module(
                    import_obj.imported_name, source_file_path
                )

        self.resolution_cache[cache_key] = resolved_path
        return resolved_path

    def _resolve_local_import(
        self, import_obj: Import, source_file_path: str
    ) -> Optional[str]:
        """Resolve local imports (e.g., #include "file.h", import './module')"""
        imported_name = import_obj.imported_name
        source_dir = Path(source_file_path).parent

        # Python relative imports: leading dots without a slash (e.g. ".app", "..sansio.app", ".")
        # 1 dot = current package (source_dir), 2 dots = parent, etc.
        if (
            imported_name.startswith(".")
            and not imported_name.startswith("./")
            and not imported_name.startswith("../")
        ):
            dots = len(imported_name) - len(imported_name.lstrip("."))
            module_part = imported_name[dots:]  # "" for bare ".", "app" for ".app"
            anchor = source_dir
            for _ in range(dots - 1):
                anchor = anchor.parent
            if module_part:
                rel = module_part.replace(".", "/")
                for suffix in (".py", ".pyw"):
                    candidate = self.codebase_root / anchor / (rel + suffix)
                    if candidate.exists() and candidate.is_file():
                        return self._get_relative_path(candidate)
                # package: module/__init__.py
                init = self.codebase_root / anchor / rel / "__init__.py"
                if init.exists() and init.is_file():
                    return self._get_relative_path(init)
            else:
                # bare "." or ".." → the package __init__.py
                init = self.codebase_root / anchor / "__init__.py"
                if init.exists() and init.is_file():
                    return self._get_relative_path(init)
            return None

        # Handle relative imports properly
        if imported_name.startswith("./") or imported_name.startswith("../"):
            # For relative imports, resolve relative to the source file's directory
            candidate_path = source_dir / imported_name
            # Normalize the path (handles .. and . components)
            candidate_path = Path(os.path.normpath(str(candidate_path)))
            resolved = self._try_resolve_path(
                self.codebase_root / candidate_path, import_obj
            )
            if resolved:
                return resolved

        # Fallback to original search paths
        search_paths = [
            self.codebase_root
            / source_dir
            / imported_name,  # Relative to codebase root
        ]

        # Add include paths
        for include_path in self.include_paths:
            search_paths.append(include_path / imported_name)

        # Search for the file
        for candidate_path in search_paths:
            resolved = self._try_resolve_path(candidate_path, import_obj)
            if resolved:
                return resolved

        # Java package-to-file resolution: com.example.Foo → com/example/Foo.java
        if self._looks_like_java_package(imported_name):
            resolved = self._resolve_java_package(imported_name)
            if resolved:
                return resolved

        return None

    def _resolve_python_module(
        self, module_name: str, source_file_path: str
    ) -> Optional[str]:
        """Resolve a Python bare/dotted module name against src-layout source roots.

        Handles ``from streaming import X`` → ``src/streaming.py`` and
        ``from layers.foo import Bar`` → ``src/layers/foo.py``.
        """
        # Dotted module path → filesystem path segments
        rel = module_name.replace(".", "/")
        source_dir = Path(source_file_path).parent

        search_roots = [
            self.codebase_root / source_dir,  # same dir as importing file
            self.codebase_root,  # project root
            self.codebase_root / "src",  # common src layout
        ]

        for root in search_roots:
            for suffix in (".py", ".pyw"):
                candidate = root / (rel + suffix)
                if candidate.exists() and candidate.is_file():
                    return self._get_relative_path(candidate)
            # Package: module/__init__.py
            init = root / rel / "__init__.py"
            if init.exists() and init.is_file():
                return self._get_relative_path(init)

        return None

    @staticmethod
    def _looks_like_java_package(name: str) -> bool:
        """True for dotted Java package names; false for C/JS file paths."""
        return (
            "." in name
            and not name.startswith(".")
            and not name.startswith("/")
            and not any(
                name.endswith(ext) for ext in (".h", ".c", ".cpp", ".hpp", ".js", ".ts")
            )
        )

    def _resolve_java_package(self, package_name: str) -> Optional[str]:
        """Convert com.example.Foo to com/example/Foo.java and search source roots."""
        java_rel = package_name.replace(".", "/") + ".java"
        candidates = [
            self.codebase_root / java_rel,
            self.codebase_root / "src" / "main" / "java" / java_rel,
            self.codebase_root / "src" / "test" / "java" / java_rel,
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return self._get_relative_path(candidate)
        return None

    def _try_resolve_path(
        self, candidate_path: Path, import_obj: Optional[Import] = None
    ) -> Optional[str]:
        """Try to resolve a path, handling TypeScript/JavaScript extension resolution"""
        try:
            # First try exact path
            if candidate_path.exists() and candidate_path.is_file():
                return self._get_relative_path(candidate_path)

            # TypeScript/JavaScript module resolution
            return self._try_resolve_ts_js_path(candidate_path, import_obj)

        except (OSError, PermissionError):
            pass

        return None

    def _try_resolve_ts_js_path(
        self, candidate_path: Path, import_obj: Optional[Import] = None
    ) -> Optional[str]:
        """Handle TypeScript/JavaScript specific resolution rules"""
        # Standard extension resolution - try appending extensions for extensionless imports
        if not candidate_path.suffix:
            # Standard TS/JS extensions
            for ext in [".ts", ".tsx", ".js", ".jsx", ".mjs"]:
                path_with_ext = candidate_path.with_suffix(ext)
                if path_with_ext.exists() and path_with_ext.is_file():
                    return self._get_relative_path(path_with_ext)

            # Try index files (common Node.js pattern)
            for index_file in ["index.ts", "index.tsx", "index.js", "index.jsx"]:
                index_path = candidate_path / index_file
                if index_path.exists() and index_path.is_file():
                    return self._get_relative_path(index_path)

        return None

    def _get_relative_path(self, resolved_path: Path) -> str:
        """Get path relative to codebase root"""
        try:
            relative_path = resolved_path.relative_to(self.codebase_root)
            return str(relative_path).replace("\\", "/")
        except ValueError:
            # Path is outside codebase root, return as-is
            return str(resolved_path)

    def _resolve_system_import(self, import_obj: Import) -> Optional[str]:
        """Resolve system imports (e.g., #include <stdio.h>)"""
        # For system includes, we generally don't resolve to actual files
        # as they're part of the system/compiler installation
        # But we could potentially look in standard system paths if needed
        return None


class LanguageDetector:
    """Detects programming language from file extensions"""

    def __init__(self):
        self.parsers: Dict[str, ImportParser] = {}
        self._register_default_parsers()

    def _register_default_parsers(self):
        """Register parsers: tree-sitter implementations preferred, legacy regex as fallback."""
        # Python
        try:
            from ts_parsers import PythonImportParser as _Py

            self.register_parser(_Py())
        except ImportError:
            pass  # No legacy Python regex parser; skip silently

        # C / C++
        try:
            from ts_parsers import CImportParserTS as _C

            self.register_parser(_C())
        except ImportError:
            self.register_parser(CImportParserLegacy())

        # TypeScript (.ts, .tsx) + JavaScript (.js, .jsx, .mjs)
        # Import both together: if either grammar package is missing, fall back
        # to the legacy parser which covers the full JS-family + .vue.
        try:
            from ts_parsers import (
                TypeScriptImportParserTS as _TS,
                JavaScriptImportParserTS as _JS,
            )

            self.register_parser(_TS())
            self.register_parser(_JS())
        except ImportError:
            self.register_parser(TypeScriptImportParserLegacy())

        # Java
        try:
            from ts_parsers import JavaImportParserTS as _Java

            self.register_parser(_Java())
        except ImportError:
            self.register_parser(JavaImportParserLegacy())

        # Rust
        try:
            from ts_parsers import RustImportParser as _Rust

            self.register_parser(_Rust())
        except ImportError:
            pass  # grammar not installed — skip silently

    def register_parser(self, parser: ImportParser):
        """Register a new language parser"""
        for ext in parser.get_supported_extensions():
            self.parsers[ext] = parser

    def get_parser(self, file_path: str) -> Optional[ImportParser]:
        """Get appropriate parser for a file"""
        ext = Path(file_path).suffix.lower()
        return self.parsers.get(ext)

    def get_supported_extensions(self) -> Set[str]:
        """Get all supported file extensions"""
        return set(self.parsers.keys())


def analyze_imports_for_file(
    file_path: str, content: str, detector: LanguageDetector, resolver: ImportResolver
) -> List[Import]:
    """
    Analyze imports for a single file

    Args:
        file_path: Path to the file
        content: File content
        detector: Language detector
        resolver: Import resolver

    Returns:
        List of Import objects with resolved paths
    """
    parser = detector.get_parser(file_path)
    if not parser:
        return []

    # Parse imports
    imports = parser.parse_file(file_path, content)

    # Resolve each import to actual file paths
    for import_obj in imports:
        resolved_path = resolver.resolve_import(import_obj, file_path)
        import_obj.resolved_path = resolved_path

    return imports


def analyze_source_imports(
    source_graph, include_paths: List[str] = None, progress_callback=None
):
    """
    Analyze imports for all files in a source graph using PropertyGraph to store relationships

    This function maintains API compatibility with the original depgraph.py version
    but uses PropertyGraph internally to store import relationships.

    Args:
        source_graph: SourceGraph object to populate with import data
        include_paths: Additional directories to search for includes
        progress_callback: Optional callback function for progress updates
    """
    # Setup
    root_path = Path(source_graph.root_path)
    include_paths_resolved = [Path(p).resolve() for p in (include_paths or [])]

    detector = LanguageDetector()
    resolver = ImportResolver(root_path, include_paths_resolved)

    # Create property graph to store import relationships
    import_graph = PropertyGraph()

    # Get all supported files
    supported_extensions = detector.get_supported_extensions()
    supported_files = [
        (file_path, file_node)
        for file_node in source_graph.get_all_files()
        for file_path in [file_node.path]
        if file_node.extension in supported_extensions
    ]

    if progress_callback:
        progress_callback(f"Analyzing imports for {len(supported_files)} files...")

    # First pass: Add all files as nodes in the property graph
    file_nodes = {}
    for file_path, file_node in supported_files:
        node = import_graph.add_node(
            "file",
            path=file_path,
            extension=file_node.extension,
            size=file_node.size_bytes,
        )
        file_nodes[file_path] = node

    # Second pass: Process each file and create import relationships
    for i, (file_path, file_node) in enumerate(supported_files):
        if progress_callback and i % 10 == 0:
            progress_callback(f"Processing {i + 1}/{len(supported_files)}: {file_path}")

        try:
            # Read file content
            full_path = root_path / file_path
            with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()

            # Analyze imports
            imports = analyze_imports_for_file(file_path, content, detector, resolver)

            # Store import data in the original SourceGraph (for backward compatibility)
            for import_obj in imports:
                # Add to this file's imports set - use resolved path if available, otherwise raw name
                import_target = (
                    import_obj.resolved_path
                    if import_obj.resolved_path
                    else import_obj.imported_name
                )
                file_node.imports.add(import_target)

                # If we resolved the import to an actual file, update the imported_by relationship
                if import_obj.resolved_path and source_graph.has_file(
                    import_obj.resolved_path
                ):
                    target_file = source_graph.get_file(import_obj.resolved_path)
                    target_file.imported_by.add(file_path)

                # Store detailed import info in metadata
                if "import_details" not in file_node.metadata:
                    file_node.metadata["import_details"] = []

                file_node.metadata["import_details"].append(
                    {
                        "raw_statement": import_obj.raw_statement,
                        "imported_name": import_obj.imported_name,
                        "import_type": import_obj.import_type.value,
                        "line_number": import_obj.line_number,
                        "resolved_path": import_obj.resolved_path,
                    }
                )

                # Also store relationships in the PropertyGraph
                if import_obj.resolved_path and import_obj.resolved_path in file_nodes:
                    # Create import edge between files
                    source_node = file_nodes[file_path]
                    target_node = file_nodes[import_obj.resolved_path]

                    import_graph.add_edge(
                        source_node,
                        "imports",
                        target_node,
                        raw_statement=import_obj.raw_statement,
                        imported_name=import_obj.imported_name,
                        import_type=import_obj.import_type.value,
                        line_number=import_obj.line_number,
                    )
                else:
                    # Create import edge to external/system import
                    # Add external import as a node if it doesn't exist
                    external_key = f"external:{import_obj.imported_name}"
                    if external_key not in file_nodes:
                        external_node = import_graph.add_node(
                            "external_import",
                            name=import_obj.imported_name,
                            import_type=import_obj.import_type.value,
                        )
                        file_nodes[external_key] = external_node

                    source_node = file_nodes[file_path]
                    external_node = file_nodes[external_key]

                    import_graph.add_edge(
                        source_node,
                        "imports",
                        external_node,
                        raw_statement=import_obj.raw_statement,
                        imported_name=import_obj.imported_name,
                        import_type=import_obj.import_type.value,
                        line_number=import_obj.line_number,
                    )

        except (OSError, PermissionError, UnicodeDecodeError) as e:
            if progress_callback:
                progress_callback(f"Warning: Could not analyze {file_path}: {e}")
            continue

    # Don't store the property graph object as it's not JSON serializable
    # Just use it for the analysis and let it be garbage collected

    if progress_callback:
        progress_callback(
            f"Import analysis complete. Processed {len(supported_files)} files."
        )

    return source_graph
