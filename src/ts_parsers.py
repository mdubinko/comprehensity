"""
ts_parsers.py — Tree-sitter-backed import parsers

Provides TreeSitterImportParser (base class) and language implementations.
These are intended to replace the regex parsers in import_analysis.py; the
legacy classes remain there for reference and testing.

Requires: tree-sitter>=0.21 and the relevant tree-sitter-<lang> grammar
packages.  Missing grammar packages raise ImportError at instantiation time
with a clear install hint, not at module import time.

Tree-sitter API note (0.21+):
  - Parser(language) constructor
  - Query(language, query_string) constructor
  - QueryCursor(query).captures(node) -> dict[str, list[Node]]
"""

from __future__ import annotations

import sys
from abc import abstractmethod
from pathlib import Path
from typing import List, Optional

from import_analysis import Import, ImportParser, ImportType
from blueprint import SymbolEntry, SymbolKind


# ---------------------------------------------------------------------------
# Stdlib detection
# ---------------------------------------------------------------------------

def _get_stdlib_modules() -> frozenset:
    """Return the set of top-level stdlib module names for the running Python."""
    if hasattr(sys, "stdlib_module_names"):          # Python 3.10+
        return frozenset(sys.stdlib_module_names)
    # Curated fallback for Python 3.8 / 3.9
    return frozenset({
        "__future__", "_thread", "abc", "ast", "asyncio", "atexit",
        "base64", "binascii", "builtins", "bz2",
        "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
        "codecs", "codeop", "colorsys", "compileall", "concurrent",
        "configparser", "contextlib", "contextvars", "copy", "copyreg",
        "csv", "ctypes", "curses",
        "dataclasses", "datetime", "dbm", "decimal", "difflib", "dis",
        "doctest",
        "email", "encodings", "enum", "errno",
        "faulthandler", "fcntl", "filecmp", "fileinput", "fnmatch",
        "fractions", "ftplib", "functools",
        "gc", "getopt", "getpass", "gettext", "glob", "grp", "gzip",
        "hashlib", "heapq", "hmac", "html", "http",
        "idlelib", "imaplib", "importlib", "inspect", "io", "ipaddress",
        "itertools",
        "json",
        "keyword",
        "lib2to3", "linecache", "locale", "logging", "lzma",
        "mailbox", "marshal", "math", "mimetypes", "mmap", "modulefinder",
        "multiprocessing",
        "netrc", "nis", "nntplib", "numbers",
        "operator", "optparse", "os",
        "pathlib", "pdb", "pickle", "pickletools", "pipes", "pkgutil",
        "platform", "plistlib", "poplib", "posix", "posixpath", "pprint",
        "profile", "pstats", "pty", "pwd", "py_compile", "pyclbr",
        "pydoc",
        "queue", "quopri",
        "random", "re", "readline", "reprlib", "resource", "rlcompleter",
        "runpy",
        "sched", "secrets", "select", "selectors", "shelve", "shlex",
        "shutil", "signal", "site", "smtpd", "smtplib", "sndhdr",
        "socket", "socketserver", "spwd", "sqlite3", "sre_compile",
        "sre_constants", "sre_parse", "ssl", "stat", "statistics",
        "string", "stringprep", "struct", "subprocess", "sunau", "symtable",
        "sys", "sysconfig", "syslog",
        "tabnanny", "tarfile", "telnetlib", "tempfile", "termios", "test",
        "textwrap", "threading", "time", "timeit", "tkinter", "token",
        "tokenize", "tomllib", "trace", "traceback", "tracemalloc", "tty",
        "turtle", "turtledemo", "types", "typing",
        "unicodedata", "unittest", "urllib", "uu", "uuid",
        "venv",
        "warnings", "wave", "weakref", "webbrowser",
        "wsgiref",
        "xdrlib", "xml", "xmlrpc",
        "zipapp", "zipfile", "zipimport", "zlib", "zoneinfo",
    })


_STDLIB_TOP_LEVEL: frozenset = _get_stdlib_modules()


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class TreeSitterImportParser(ImportParser):
    """Base class for tree-sitter-backed import parsers.

    Subclasses receive a tree-sitter Language object, own a Parser instance,
    and implement _parse_tree() to produce Import objects from the CST.
    """

    def __init__(self, language) -> None:
        from tree_sitter import Parser
        self._language = language
        self._parser = Parser(language)

    def parse_file(self, file_path: str, content: str) -> List[Import]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        return self._parse_tree(file_path, tree)

    @abstractmethod
    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        """Walk the CST and return all Import objects found."""


# ---------------------------------------------------------------------------
# Python
# ---------------------------------------------------------------------------

class PythonImportParser(TreeSitterImportParser):
    """Tree-sitter parser for Python import statements.

    Handles:
      import os
      import os, sys
      import os as o
      from pathlib import Path
      from pathlib import Path, PurePath
      from . import utils          (relative → LOCAL)
      from ..sibling import foo    (relative → LOCAL)
      from collections import (   (multi-line → single Import for the module)
          OrderedDict,
          defaultdict,
      )
    """

    def __init__(self) -> None:
        try:
            import tree_sitter_python as _tspy
        except ImportError:
            raise ImportError(
                "tree-sitter-python is required for Python import parsing. "
                "Install it with: uv pip install tree-sitter-python"
            ) from None
        from tree_sitter import Language
        super().__init__(Language(_tspy.language()))

    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        imports: List[Import] = []
        for node in tree.root_node.named_children:
            if node.type == "import_statement":
                imports.extend(self._handle_import(node))
            elif node.type == "import_from_statement":
                imp = self._handle_from_import(node)
                if imp is not None:
                    imports.append(imp)
            elif node.type == "future_import_statement":
                imports.append(self._handle_future_import(node))
        return imports

    # -- statement handlers --------------------------------------------------

    def _handle_import(self, node) -> List[Import]:
        """import os  /  import os, sys  /  import os as x"""
        raw = node.text.decode("utf-8", errors="replace")
        line = node.start_point[0] + 1
        result: List[Import] = []

        for child in node.named_children:
            if child.type == "dotted_name":
                name = child.text.decode("utf-8", errors="replace")
            elif child.type == "aliased_import":
                # aliased_import → first named child is the dotted_name
                name_node = child.named_children[0]
                name = name_node.text.decode("utf-8", errors="replace")
            else:
                continue

            result.append(Import(
                raw_statement=raw,
                imported_name=name,
                import_type=self._classify(name),
                line_number=line,
            ))
        return result

    def _handle_from_import(self, node) -> Optional[Import]:
        """from pathlib import Path  /  from . import utils"""
        if not node.named_children:
            return None

        module_node = node.named_children[0]
        raw = node.text.decode("utf-8", errors="replace")
        line = node.start_point[0] + 1

        if module_node.type == "relative_import":
            name = module_node.text.decode("utf-8", errors="replace")
            return Import(
                raw_statement=raw,
                imported_name=name,
                import_type=ImportType.LOCAL,
                line_number=line,
            )

        if module_node.type == "dotted_name":
            name = module_node.text.decode("utf-8", errors="replace")
            return Import(
                raw_statement=raw,
                imported_name=name,
                import_type=self._classify(name),
                line_number=line,
            )

        return None

    def _handle_future_import(self, node) -> Import:
        """from __future__ import annotations  (always SYSTEM)"""
        return Import(
            raw_statement=node.text.decode("utf-8", errors="replace"),
            imported_name="__future__",
            import_type=ImportType.SYSTEM,
            line_number=node.start_point[0] + 1,
        )

    # -- classification ------------------------------------------------------

    def _classify(self, name: str) -> ImportType:
        top = name.split(".")[0]
        return ImportType.SYSTEM if top in _STDLIB_TOP_LEVEL else ImportType.EXTERNAL

    def get_supported_extensions(self) -> set:
        return {".py", ".pyw"}


# ---------------------------------------------------------------------------
# C / C++
# ---------------------------------------------------------------------------

class CImportParserTS(TreeSitterImportParser):
    """Tree-sitter parser for C and C++ #include directives.

    Uses tree-sitter-cpp (a superset of C) for all C/C++ extensions.

    Handles:
      #include <stdio.h>   -> SYSTEM
      #include "local.h"   -> LOCAL
      Includes inside #ifdef / #ifndef blocks are also captured.
    """

    def __init__(self) -> None:
        try:
            import tree_sitter_cpp as tscpp
        except ImportError:
            raise ImportError(
                "tree-sitter-cpp is required for C/C++ import parsing. "
                "Install it with: uv pip install tree-sitter-cpp"
            ) from None
        from tree_sitter import Language
        super().__init__(Language(tscpp.language()))

    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        imports: List[Import] = []
        self._walk(tree.root_node, imports)
        return imports

    def _walk(self, node, imports: List[Import]) -> None:
        if node.type == "preproc_include":
            self._handle_include(node, imports)
        for child in node.children:
            self._walk(child, imports)

    def _handle_include(self, node, imports: List[Import]) -> None:
        line = node.start_point[0] + 1
        raw = node.text.decode("utf-8", errors="replace").strip()
        for child in node.children:
            if child.type == "system_lib_string":
                name = child.text.decode("utf-8", errors="replace").strip("<>").strip()
                imports.append(Import(
                    raw_statement=raw,
                    imported_name=name,
                    import_type=ImportType.SYSTEM,
                    line_number=line,
                ))
                return
            if child.type == "string_literal":
                name = child.text.decode("utf-8", errors="replace").strip('"')
                imports.append(Import(
                    raw_statement=raw,
                    imported_name=name,
                    import_type=ImportType.LOCAL,
                    line_number=line,
                ))
                return

    def get_supported_extensions(self) -> set:
        return {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}


# ---------------------------------------------------------------------------
# JavaScript / TypeScript
# ---------------------------------------------------------------------------

_NODE_BUILTINS: frozenset = frozenset({
    "assert", "buffer", "child_process", "cluster", "console", "crypto",
    "dgram", "dns", "domain", "events", "fs", "http", "http2", "https",
    "inspector", "module", "net", "os", "path", "perf_hooks", "process",
    "punycode", "querystring", "readline", "repl", "stream",
    "string_decoder", "sys", "timers", "tls", "trace_events", "tty",
    "url", "util", "v8", "vm", "wasi", "worker_threads", "zlib",
})


class _JSLikeImportParser(TreeSitterImportParser):
    """Shared import-parsing logic for JS-family languages (JS, TS, TSX).

    Captures:
      import foo from 'bar'            (ES6 static import)
      import { a } from 'bar'
      import * as x from 'bar'
      import 'side-effect'
      require('./local')               (CommonJS)
      import('./dynamic')              (dynamic import)
    """

    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        imports: List[Import] = []
        self._walk(tree.root_node, imports)
        return imports

    def _walk(self, node, imports: List[Import]) -> None:
        if node.type == "import_statement":
            self._handle_import_statement(node, imports)
        elif node.type == "export_statement":
            self._handle_export_statement(node, imports)
        elif node.type == "call_expression":
            self._handle_call_expression(node, imports)
        for child in node.children:
            self._walk(child, imports)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _string_fragment(string_node) -> Optional[str]:
        """Extract the text content of a tree-sitter string node."""
        for child in string_node.named_children:
            if child.type == "string_fragment":
                return child.text.decode("utf-8", errors="replace")
        return None

    def _classify_module(self, name: str) -> ImportType:
        if name.startswith("./") or name.startswith("../") or name.startswith("/"):
            return ImportType.LOCAL
        if name.startswith("node:"):
            return ImportType.SYSTEM
        # Handle sub-path exports like fs/promises, stream/promises, path/posix
        top = name.split("/")[0]
        if top in _NODE_BUILTINS:
            return ImportType.SYSTEM
        return ImportType.EXTERNAL

    def _make_import(self, node, name: str) -> Import:
        return Import(
            raw_statement=node.text.decode("utf-8", errors="replace").strip(),
            imported_name=name,
            import_type=self._classify_module(name),
            line_number=node.start_point[0] + 1,
        )

    # -- statement handlers --------------------------------------------------

    def _handle_import_statement(self, node, imports: List[Import]) -> None:
        # The module source is the last named child of type 'string'
        for child in reversed(node.named_children):
            if child.type == "string":
                name = self._string_fragment(child)
                if name:
                    imports.append(self._make_import(node, name))
                return

    def _handle_export_statement(self, node, imports: List[Import]) -> None:
        """Handle re-export forms: export * from, export { } from, export * as ns from.

        Only captures exports that have a 'from' source string — bare ``export { Foo }``
        (no source) creates no import dependency and is silently ignored.
        """
        for child in reversed(node.named_children):
            if child.type == "string":
                name = self._string_fragment(child)
                if name:
                    imports.append(self._make_import(node, name))
                return

    def _handle_call_expression(self, node, imports: List[Import]) -> None:
        """Handle require('...') and import('...')."""
        if not node.named_children:
            return
        fn = node.named_children[0]
        is_require = fn.type == "identifier" and fn.text == b"require"
        is_dynamic = fn.type == "import"
        if not (is_require or is_dynamic):
            return
        # Find the string in the arguments
        for child in node.named_children:
            if child.type == "arguments":
                for arg in child.named_children:
                    if arg.type == "string":
                        name = self._string_fragment(arg)
                        if name:
                            imports.append(self._make_import(node, name))
                        return
                return


class JavaScriptImportParserTS(_JSLikeImportParser):
    """Tree-sitter parser for JavaScript (ES6 + CommonJS)."""

    def __init__(self) -> None:
        try:
            import tree_sitter_javascript as tsjs
        except ImportError:
            raise ImportError(
                "tree-sitter-javascript is required for JavaScript import parsing. "
                "Install it with: uv pip install tree-sitter-javascript"
            ) from None
        from tree_sitter import Language
        super().__init__(Language(tsjs.language()))

    def get_supported_extensions(self) -> set:
        return {".js", ".jsx", ".mjs"}


class TypeScriptImportParserTS(_JSLikeImportParser):
    """Tree-sitter parser for TypeScript (.ts) and TSX (.tsx).

    Uses language_typescript() for .ts and language_tsx() for .tsx so the
    grammar understands JSX syntax in TSX files.
    """

    def __init__(self) -> None:
        try:
            import tree_sitter_typescript as tsts
        except ImportError:
            raise ImportError(
                "tree-sitter-typescript is required for TypeScript import parsing. "
                "Install it with: uv pip install tree-sitter-typescript"
            ) from None
        from tree_sitter import Language, Parser
        self._ts_parser = Parser(Language(tsts.language_typescript()))
        self._tsx_parser = Parser(Language(tsts.language_tsx()))
        # Initialise base with the TS language (self._parser unused after override)
        super().__init__(Language(tsts.language_typescript()))

    def parse_file(self, file_path: str, content: str) -> List[Import]:
        ext = Path(file_path).suffix.lower()
        parser = self._tsx_parser if ext == ".tsx" else self._ts_parser
        tree = parser.parse(content.encode("utf-8", errors="replace"))
        return self._parse_tree(file_path, tree)

    def get_supported_extensions(self) -> set:
        return {".ts", ".tsx"}


# ---------------------------------------------------------------------------
# Java
# ---------------------------------------------------------------------------

class JavaImportParserTS(TreeSitterImportParser):
    """Tree-sitter parser for Java import declarations.

    Handles:
      import java.util.List;
      import java.util.*;
      import static org.junit.Assert.assertEquals;
    """

    # Well-known system top-level packages
    _SYSTEM_TOP = frozenset({"java", "javax", "sun", "jdk"})
    # Well-known external library (org.*) second-level segments
    _EXT_ORG = frozenset({
        "springframework", "apache", "junit", "mockito", "slf4j",
        "hibernate", "eclipse", "jetbrains", "assertj", "testng", "json",
        "reactivestreams", "checkerframework", "bouncycastle",
    })
    # Well-known external library (com.*) second-level segments
    _EXT_COM = frozenset({
        "google", "fasterxml", "amazonaws", "oracle", "sun",
        "squareup", "typesafe", "zaxxer", "github", "vladmihalcea",
        "auth0", "stripe", "twilio", "sendgrid", "newrelic", "datadog",
    })
    # Well-known external library (io.*) second-level segments
    _EXT_IO = frozenset({
        "micrometer", "grpc", "netty", "vertx", "reactivex",
        "swagger", "springfox", "opentelemetry", "prometheus",
        "lettuce", "r2dbc", "projectreactor",
    })
    # Well-known external library (net.*) second-level segments
    _EXT_NET = frozenset({"sf", "bytebuddy"})

    def __init__(self) -> None:
        try:
            import tree_sitter_java as tsjava
        except ImportError:
            raise ImportError(
                "tree-sitter-java is required for Java import parsing. "
                "Install it with: uv pip install tree-sitter-java"
            ) from None
        from tree_sitter import Language
        super().__init__(Language(tsjava.language()))

    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        imports: List[Import] = []
        for node in tree.root_node.named_children:
            if node.type == "import_declaration":
                self._handle_import(node, imports)
            elif node.type in (
                "class_declaration", "interface_declaration",
                "enum_declaration", "annotation_type_declaration",
                "record_declaration",
            ):
                break  # imports must precede type declarations
        return imports

    def _handle_import(self, node, imports: List[Import]) -> None:
        line = node.start_point[0] + 1
        raw = node.text.decode("utf-8", errors="replace").strip()
        for child in node.named_children:
            if child.type in ("scoped_identifier", "identifier"):
                name = child.text.decode("utf-8", errors="replace")
                imports.append(Import(
                    raw_statement=raw,
                    imported_name=name,
                    import_type=self._classify_import(name),
                    line_number=line,
                ))
                return

    def _classify_import(self, name: str) -> ImportType:
        parts = name.split(".")
        top = parts[0]
        second = parts[1] if len(parts) > 1 else ""
        if top in self._SYSTEM_TOP:
            return ImportType.SYSTEM
        if top == "org" and second in self._EXT_ORG:
            return ImportType.EXTERNAL
        if top == "com" and second in self._EXT_COM:
            return ImportType.EXTERNAL
        if top == "io" and second in self._EXT_IO:
            return ImportType.EXTERNAL
        if top == "net" and second in self._EXT_NET:
            return ImportType.EXTERNAL
        return ImportType.LOCAL

    def get_supported_extensions(self) -> set:
        return {".java"}


# ===========================================================================
# Symbol extraction
# ===========================================================================
#
# SymbolExtractor: abstract base for per-language symbol extraction.
# Each subclass receives file content + file_id and returns SymbolEntry objects.
# IDs are assigned by the caller (blueprint_io) once all files are processed.


class SymbolExtractor:
    """Abstract base class for tree-sitter symbol extractors.

    extract() returns a list of partially-filled SymbolEntry objects.
    The `id` field is left as "" — callers assign stable IDs after collecting
    symbols from all files.
    """

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        raise NotImplementedError

    def get_supported_extensions(self) -> set:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Python symbol extractor
# ---------------------------------------------------------------------------

class PythonSymbolExtractor(SymbolExtractor):
    """Extracts functions, methods, and classes from Python source.

    Exported = not prefixed with underscore (public by convention).
    Methods are identified by their enclosing class; everything else is a
    top-level function.
    """

    def __init__(self) -> None:
        try:
            import tree_sitter_python as _tspy
        except ImportError:
            raise ImportError(
                "tree-sitter-python is required for Python symbol extraction. "
                "Install it with: uv pip install tree-sitter-python"
            ) from None
        from tree_sitter import Language, Parser
        self._parser = Parser(Language(_tspy.language()))

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        symbols: List[SymbolEntry] = []
        self._walk(tree.root_node, file_id, symbols, in_class=False)
        return symbols

    def _walk(self, node, file_id: str, symbols: List[SymbolEntry],
              in_class: bool) -> None:
        if node.type == "class_definition":
            name = self._child_text(node, "identifier")
            if name:
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=not name.startswith("_"),
                ))
            # Walk into class body with in_class=True
            for child in node.children:
                self._walk(child, file_id, symbols, in_class=True)
            return

        if node.type == "function_definition":
            name = self._child_text(node, "identifier")
            if name:
                kind: SymbolKind = "method" if in_class else "function"
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=not name.startswith("_"),
                ))
            # Do not recurse into nested functions/classes for now
            return

        for child in node.children:
            self._walk(child, file_id, symbols, in_class=in_class)

    @staticmethod
    def _child_text(node, child_type: str) -> Optional[str]:
        for child in node.children:
            if child.type == child_type:
                return child.text.decode("utf-8", errors="replace")
        return None

    def get_supported_extensions(self) -> set:
        return {".py", ".pyw"}


# ---------------------------------------------------------------------------
# JavaScript / TypeScript symbol extractor
# ---------------------------------------------------------------------------

class _JSLikeSymbolExtractor(SymbolExtractor):
    """Shared symbol extraction logic for JS / TS / TSX.

    Captures:
      function foo() {}                         → function, exported if module.exports or export
      const foo = () => {}                      → function (arrow)
      const foo = function() {}                 → function (named function expression)
      class Foo {}                              → class
      method inside class                       → method
      export function / export class            → exported

    Export detection is best-effort without full scope analysis:
      - Top-level `export` keyword on the declaration → is_exported = True
      - Appears in module.exports = { foo } → is_exported = True (post-processing pass)
    """

    def __init__(self, parser) -> None:
        self._parser = parser

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        raw: List[SymbolEntry] = []
        self._walk(tree.root_node, file_id, raw, in_class=False, exported_by_keyword=False)
        # Collect names exported via module.exports = { name, ... }
        cjs_exports = self._collect_cjs_exports(tree.root_node)
        if cjs_exports:
            for sym in raw:
                if sym.name in cjs_exports:
                    # Replace with is_exported=True (Pydantic models are immutable, rebuild)
                    idx = raw.index(sym)
                    raw[idx] = sym.model_copy(update={"is_exported": True})
        return raw

    def _walk(self, node, file_id: str, symbols: List[SymbolEntry],
              in_class: bool, exported_by_keyword: bool) -> None:
        """Walk the CST collecting top-level declarations."""

        # export keyword wrapping — mark children as exported
        if node.type == "export_statement":
            for child in node.children:
                self._walk(child, file_id, symbols, in_class,
                           exported_by_keyword=True)
            return

        # function_declaration: function foo() {}
        if node.type == "function_declaration":
            name = self._identifier_text(node)
            if name:
                kind: SymbolKind = "method" if in_class else "function"
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported_by_keyword,
                ))
            return  # don't recurse into function body

        # class_declaration: class Foo {}
        if node.type == "class_declaration":
            name = self._identifier_text(node)
            if name:
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind="class",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported_by_keyword,
                ))
            # Walk into class body for methods, not further nested classes
            for child in node.children:
                self._walk(child, file_id, symbols, in_class=True,
                           exported_by_keyword=False)
            return

        # method_definition inside a class body
        if node.type == "method_definition":
            name = self._identifier_text(node)
            if name and name not in ("constructor",):
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=False,  # methods inherit class visibility
                ))
            return

        # lexical_declaration / variable_declaration: const foo = () => {} or function(){}
        if node.type in ("lexical_declaration", "variable_declaration"):
            if not in_class:
                self._handle_var_decl(node, file_id, symbols, exported_by_keyword)
            return

        # Recurse into top-level nodes only (program, module)
        if node.type in ("program", "module", "class_body"):
            for child in node.children:
                self._walk(child, file_id, symbols, in_class, exported_by_keyword)

    def _handle_var_decl(self, node, file_id: str, symbols: List[SymbolEntry],
                         exported_by_keyword: bool) -> None:
        """const foo = () => {}  or  const foo = function() {}"""
        for child in node.children:
            if child.type == "variable_declarator":
                name_node = child.child_by_field_name("name") if hasattr(child, "child_by_field_name") else None
                if name_node is None:
                    # fallback: first child with type "identifier"
                    for c in child.children:
                        if c.type == "identifier":
                            name_node = c
                            break
                if name_node is None:
                    continue
                name = name_node.text.decode("utf-8", errors="replace")

                # Check RHS is a function/arrow
                value_node = None
                for c in child.children:
                    if c.type in ("arrow_function", "function", "function_expression"):
                        value_node = c
                        break
                if value_node is None:
                    continue

                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind="function",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=exported_by_keyword,
                ))

    @staticmethod
    def _identifier_text(node) -> Optional[str]:
        """Return text of the first 'name' field child, or first identifier child."""
        # Try field-based access first (more reliable)
        if hasattr(node, "child_by_field_name"):
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                return name_node.text.decode("utf-8", errors="replace")
        # Fallback: first identifier child
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8", errors="replace")
        return None

    @staticmethod
    def _collect_cjs_exports(root) -> set:
        """Collect names from module.exports = { name, ... } patterns."""
        names: set = set()
        for node in root.children:
            # expression_statement → assignment_expression
            if node.type != "expression_statement":
                continue
            for child in node.children:
                if child.type != "assignment_expression":
                    continue
                # LHS must be module.exports
                lhs = child.children[0] if child.children else None
                if lhs is None or lhs.text not in (b"module.exports", b"exports"):
                    continue
                # RHS is the object
                rhs = child.children[-1] if len(child.children) >= 3 else None
                if rhs is None or rhs.type != "object":
                    continue
                for prop in rhs.children:
                    if prop.type in ("shorthand_property_identifier",
                                     "shorthand_property_identifier_pattern"):
                        names.add(prop.text.decode("utf-8", errors="replace"))
                    elif prop.type == "pair":
                        key = prop.children[0] if prop.children else None
                        if key and key.type in ("property_identifier", "identifier"):
                            names.add(key.text.decode("utf-8", errors="replace"))
        return names


class JavaScriptSymbolExtractor(_JSLikeSymbolExtractor):
    """Tree-sitter symbol extractor for JavaScript."""

    def __init__(self) -> None:
        try:
            import tree_sitter_javascript as tsjs
        except ImportError:
            raise ImportError(
                "tree-sitter-javascript is required for JavaScript symbol extraction. "
                "Install it with: uv pip install tree-sitter-javascript"
            ) from None
        from tree_sitter import Language, Parser
        super().__init__(Parser(Language(tsjs.language())))

    def get_supported_extensions(self) -> set:
        return {".js", ".jsx", ".mjs"}


class TypeScriptSymbolExtractor(_JSLikeSymbolExtractor):
    """Tree-sitter symbol extractor for TypeScript (.ts) and TSX (.tsx)."""

    def __init__(self) -> None:
        try:
            import tree_sitter_typescript as tsts
        except ImportError:
            raise ImportError(
                "tree-sitter-typescript is required for TypeScript symbol extraction. "
                "Install it with: uv pip install tree-sitter-typescript"
            ) from None
        from tree_sitter import Language, Parser
        self._ts_parser = Parser(Language(tsts.language_typescript()))
        self._tsx_parser = Parser(Language(tsts.language_tsx()))
        super().__init__(self._ts_parser)

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        # _JSLikeSymbolExtractor.extract uses self._parser; override to select by ext
        # We don't have the path here, so callers use extract_with_ext instead.
        return super().extract(file_id, content)

    def extract_with_ext(self, file_id: str, content: str, ext: str) -> List[SymbolEntry]:
        old = self._parser
        self._parser = self._tsx_parser if ext == ".tsx" else self._ts_parser
        try:
            return super().extract(file_id, content)
        finally:
            self._parser = old

    def get_supported_extensions(self) -> set:
        return {".ts", ".tsx"}


# ---------------------------------------------------------------------------
# Java symbol extractor
# ---------------------------------------------------------------------------

class JavaSymbolExtractor(SymbolExtractor):
    """Extracts classes, interfaces, enums, records, and methods from Java source.

    Exported = has a `public` modifier.
    Methods are only extracted when inside a type declaration body.
    """

    # Top-level and nested type declaration node types → SymbolKind
    _TYPE_NODES: dict = {
        "class_declaration": "class",
        "enum_declaration": "class",
        "record_declaration": "class",
        "interface_declaration": "interface",
        "annotation_type_declaration": "interface",
    }

    def __init__(self) -> None:
        try:
            import tree_sitter_java as tsjava
        except ImportError:
            raise ImportError(
                "tree-sitter-java is required for Java symbol extraction. "
                "Install it with: uv pip install tree-sitter-java"
            ) from None
        from tree_sitter import Language, Parser
        self._parser = Parser(Language(tsjava.language()))

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        symbols: List[SymbolEntry] = []
        self._walk(tree.root_node, file_id, symbols, in_class=False)
        return symbols

    def _walk(self, node, file_id: str, symbols: List[SymbolEntry],
              in_class: bool) -> None:
        if node.type in self._TYPE_NODES:
            name = self._identifier(node)
            if name:
                kind: SymbolKind = self._TYPE_NODES[node.type]  # type: ignore[assignment]
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind=kind,
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=self._has_public(node),
                ))
            # Recurse into the type body to find nested types and methods
            for child in node.children:
                self._walk(child, file_id, symbols, in_class=True)
            return

        if in_class and node.type in ("method_declaration", "constructor_declaration"):
            name = self._identifier(node)
            if name:
                symbols.append(SymbolEntry(
                    id="",
                    file_id=file_id,
                    name=name,
                    kind="method",
                    start_line=node.start_point[0] + 1,
                    end_line=node.end_point[0] + 1,
                    is_exported=self._has_public(node),
                ))
            return  # don't descend into method body

        for child in node.children:
            self._walk(child, file_id, symbols, in_class=in_class)

    @staticmethod
    def _identifier(node) -> Optional[str]:
        """Return text of the first `identifier` child, or None."""
        for child in node.children:
            if child.type == "identifier":
                return child.text.decode("utf-8", errors="replace")
        return None

    @staticmethod
    def _has_public(node) -> bool:
        """True if the node has a `modifiers` child containing `public`."""
        for child in node.children:
            if child.type == "modifiers":
                for mod in child.children:
                    if mod.type == "public":
                        return True
        return False

    def get_supported_extensions(self) -> set:
        return {".java"}


# ---------------------------------------------------------------------------
# SymbolExtractorRegistry — mirrors LanguageDetector pattern
# ---------------------------------------------------------------------------

class SymbolExtractorRegistry:
    """Maps file extensions to SymbolExtractor instances (lazy-loaded)."""

    def __init__(self) -> None:
        self._ext_map: dict = {}
        self._loaded: dict = {}

    def register(self, extractor_cls) -> None:
        """Register an extractor class; instance created on first use."""
        # Instantiate to discover extensions, but catch missing grammar gracefully
        try:
            inst = extractor_cls()
            for ext in inst.get_supported_extensions():
                self._ext_map[ext] = inst
        except ImportError:
            pass  # grammar not installed — skip silently

    def get(self, ext: str) -> Optional[SymbolExtractor]:
        return self._ext_map.get(ext.lower())

    @classmethod
    def default(cls) -> SymbolExtractorRegistry:
        registry = cls()
        registry.register(PythonSymbolExtractor)
        registry.register(JavaScriptSymbolExtractor)
        registry.register(TypeScriptSymbolExtractor)
        registry.register(JavaSymbolExtractor)
        registry.register(RustSymbolExtractor)
        registry.register(CSymbolExtractor)
        return registry


# ===========================================================================
# Rust
# ===========================================================================

class RustImportParser(TreeSitterImportParser):
    """Tree-sitter parser for Rust use declarations and extern crate.

    Handles:
      use std::collections::HashMap;
      use std::io::{self, Read};
      use crate::config::Settings;
      use super::utils::helper;
      use serde::{Deserialize, Serialize};
      use tokio::*;
      extern crate serde;

    Classification:
      std / core / alloc / proc_macro / test  → SYSTEM
      crate / super / self                    → LOCAL
      everything else                         → EXTERNAL
    """

    _SYSTEM_CRATES = frozenset({"std", "core", "alloc", "proc_macro", "test"})
    _LOCAL_ROOTS = frozenset({"crate", "super", "self"})

    def __init__(self) -> None:
        try:
            import tree_sitter_rust as tsrust
        except ImportError:
            raise ImportError(
                "tree-sitter-rust is required for Rust import parsing. "
                "Install it with: uv pip install tree-sitter-rust"
            ) from None
        from tree_sitter import Language
        super().__init__(Language(tsrust.language()))

    def _parse_tree(self, file_path: str, tree) -> List[Import]:
        imports: List[Import] = []
        for node in tree.root_node.named_children:
            if node.type == "use_declaration":
                self._handle_use(node, imports)
            elif node.type == "extern_crate_declaration":
                self._handle_extern_crate(node, imports)
        return imports

    def _handle_use(self, decl_node, imports: List[Import]) -> None:
        line = decl_node.start_point[0] + 1
        raw = decl_node.text.decode("utf-8", errors="replace").strip()
        # The argument field holds the use_tree
        arg = decl_node.child_by_field_name("argument")
        if arg is None:
            # Fallback: first named child that isn't a keyword
            for child in decl_node.named_children:
                if child.type not in ("use_declaration",):
                    arg = child
                    break
        if arg is not None:
            for root in self._collect_roots(arg):
                imports.append(Import(
                    raw_statement=raw,
                    imported_name=root,
                    import_type=self._classify(root),
                    line_number=line,
                ))

    def _collect_roots(self, node) -> List[str]:
        """Recursively collect root crate names from a use_tree node."""
        if node.type == "use_list":
            roots: List[str] = []
            for child in node.named_children:
                roots.extend(self._collect_roots(child))
            return roots
        # For all other use_tree variants, extract first path segment from text
        text = node.text.decode("utf-8", errors="replace").strip()
        # Strip "as alias" suffix (use_as_clause)
        text = text.split(" as ")[0].strip()
        # First "::" segment is the root crate
        root = text.split("::")[0].strip().lstrip("{").strip()
        return [root] if root and root != "*" else []

    def _handle_extern_crate(self, node, imports: List[Import]) -> None:
        line = node.start_point[0] + 1
        raw = node.text.decode("utf-8", errors="replace").strip()
        for child in node.named_children:
            if child.type == "identifier":
                name = child.text.decode("utf-8", errors="replace")
                imports.append(Import(
                    raw_statement=raw,
                    imported_name=name,
                    import_type=self._classify(name),
                    line_number=line,
                ))
                return

    def _classify(self, name: str) -> ImportType:
        if name in self._SYSTEM_CRATES:
            return ImportType.SYSTEM
        if name in self._LOCAL_ROOTS:
            return ImportType.LOCAL
        return ImportType.EXTERNAL

    def get_supported_extensions(self) -> set:
        return {".rs"}


class RustSymbolExtractor(SymbolExtractor):
    """Extracts functions, structs, enums, traits, and impl methods from Rust source.

    Exported = has a `pub` visibility modifier.
    Methods are only extracted from impl blocks (not from trait definitions).
    """

    _TOP_LEVEL: dict = {
        "function_item": "function",
        "struct_item": "class",
        "enum_item": "class",
        "trait_item": "interface",
        "type_item": "class",
    }

    def __init__(self) -> None:
        try:
            import tree_sitter_rust as tsrust
        except ImportError:
            raise ImportError(
                "tree-sitter-rust is required for Rust symbol extraction. "
                "Install it with: uv pip install tree-sitter-rust"
            ) from None
        from tree_sitter import Language, Parser
        self._parser = Parser(Language(tsrust.language()))

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        symbols: List[SymbolEntry] = []
        self._walk_top(tree.root_node, file_id, symbols)
        return symbols

    def _walk_top(self, node, file_id: str, symbols: List[SymbolEntry]) -> None:
        for child in node.children:
            if child.type in self._TOP_LEVEL:
                name = self._name(child)
                if name:
                    symbols.append(SymbolEntry(
                        id="",
                        file_id=file_id,
                        name=name,
                        kind=self._TOP_LEVEL[child.type],  # type: ignore[arg-type]
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        is_exported=self._is_pub(child),
                    ))
            elif child.type == "impl_item":
                self._walk_impl(child, file_id, symbols)
            elif child.type == "mod_item":
                # Recurse into inline modules
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk_top(body, file_id, symbols)

    def _walk_impl(self, impl_node, file_id: str, symbols: List[SymbolEntry]) -> None:
        body = impl_node.child_by_field_name("body")
        if body is None:
            return
        for child in body.children:
            if child.type == "function_item":
                name = self._name(child)
                if name:
                    symbols.append(SymbolEntry(
                        id="",
                        file_id=file_id,
                        name=name,
                        kind="method",
                        start_line=child.start_point[0] + 1,
                        end_line=child.end_point[0] + 1,
                        is_exported=self._is_pub(child),
                    ))

    @staticmethod
    def _name(node) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        if name_node is not None:
            return name_node.text.decode("utf-8", errors="replace")
        return None

    @staticmethod
    def _is_pub(node) -> bool:
        for child in node.children:
            if child.type == "visibility_modifier":
                return True
        return False

    def get_supported_extensions(self) -> set:
        return {".rs"}


class CSymbolExtractor(SymbolExtractor):
    """Extracts functions, structs, enums, and classes from C and C++ source.

    Uses tree-sitter-cpp (a superset of C) for all C/C++ extensions.

    Exported = not declared static (C/C++). Methods inside class bodies
    inherit the exported status of the class (access specifiers are ignored).
    """

    def __init__(self) -> None:
        try:
            import tree_sitter_cpp as tscpp
        except ImportError:
            raise ImportError(
                "tree-sitter-cpp is required for C/C++ symbol extraction. "
                "Install it with: uv pip install tree-sitter-cpp"
            ) from None
        from tree_sitter import Language, Parser
        self._parser = Parser(Language(tscpp.language()))

    def extract(self, file_id: str, content: str) -> List[SymbolEntry]:
        tree = self._parser.parse(content.encode("utf-8", errors="replace"))
        symbols: List[SymbolEntry] = []
        self._walk_top(tree.root_node, file_id, symbols)
        return symbols

    def _walk_top(self, node, file_id: str, symbols: List[SymbolEntry]) -> None:
        for child in node.children:
            t = child.type
            if t == "function_definition":
                self._handle_function(child, file_id, symbols, kind="function")
            elif t in ("struct_specifier", "union_specifier"):
                self._handle_record(child, file_id, symbols)
            elif t == "class_specifier":
                self._handle_class(child, file_id, symbols)
            elif t == "enum_specifier":
                self._handle_enum(child, file_id, symbols)
            elif t == "namespace_definition":
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk_top(body, file_id, symbols)
            elif t == "template_declaration":
                self._walk_top(child, file_id, symbols)
            elif t == "declaration":
                # struct/class/enum with no variable declarator: specifier is the 'type' field
                type_node = child.child_by_field_name("type")
                if type_node is not None:
                    nt = type_node.type
                    if nt in ("struct_specifier", "union_specifier"):
                        self._handle_record(type_node, file_id, symbols)
                    elif nt == "class_specifier":
                        self._handle_class(type_node, file_id, symbols)
                    elif nt == "enum_specifier":
                        self._handle_enum(type_node, file_id, symbols)

    def _handle_function(self, node, file_id: str, symbols: List[SymbolEntry],
                         kind: str = "function") -> None:
        name = self._function_name(node)
        if not name:
            return
        symbols.append(SymbolEntry(
            id="",
            file_id=file_id,
            name=name,
            kind=kind,  # type: ignore[arg-type]
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=not self._is_static(node),
        ))

    def _handle_record(self, node, file_id: str, symbols: List[SymbolEntry]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = name_node.text.decode("utf-8", errors="replace")
        symbols.append(SymbolEntry(
            id="",
            file_id=file_id,
            name=name,
            kind="class",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=True,
        ))

    def _handle_class(self, node, file_id: str, symbols: List[SymbolEntry]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = name_node.text.decode("utf-8", errors="replace")
        symbols.append(SymbolEntry(
            id="",
            file_id=file_id,
            name=name,
            kind="class",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=True,
        ))
        body = node.child_by_field_name("body")
        if body is not None:
            for child in body.children:
                if child.type == "function_definition":
                    self._handle_function(child, file_id, symbols, kind="method")

    def _handle_enum(self, node, file_id: str, symbols: List[SymbolEntry]) -> None:
        name_node = node.child_by_field_name("name")
        if name_node is None:
            return
        name = name_node.text.decode("utf-8", errors="replace")
        symbols.append(SymbolEntry(
            id="",
            file_id=file_id,
            name=name,
            kind="class",
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            is_exported=True,
        ))

    @staticmethod
    def _function_name(node) -> Optional[str]:
        """Unwrap declarator layers to find the function's bare name."""
        declarator = node.child_by_field_name("declarator")
        # Unwrap pointer/reference wrappers before the function_declarator
        while declarator is not None and declarator.type in (
            "pointer_declarator", "reference_declarator",
        ):
            declarator = declarator.child_by_field_name("declarator")
        if declarator is None or declarator.type != "function_declarator":
            return None
        inner = declarator.child_by_field_name("declarator")
        # Unwrap further pointer layers (e.g. `int (*fp)()` style)
        while inner is not None and inner.type in (
            "pointer_declarator", "reference_declarator", "parenthesized_declarator",
        ):
            inner = inner.child_by_field_name("declarator")
        if inner is None:
            return None
        return inner.text.decode("utf-8", errors="replace")

    @staticmethod
    def _is_static(node) -> bool:
        """True if the function has a `static` storage-class specifier."""
        for child in node.children:
            if child.type == "storage_class_specifier" and child.text == b"static":
                return True
        return False

    def get_supported_extensions(self) -> set:
        return {".c", ".cpp", ".cxx", ".cc", ".h", ".hpp", ".hxx"}
