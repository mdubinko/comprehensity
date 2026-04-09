"""
Static import audit — no-network guarantee.

Two checks:

1. phase0.py imports only stdlib modules (plus first-party co-installed modules
   like applog). Phase 0 must not depend on grammar or LSP packages (tree-sitter,
   pydantic, etc.) that may not be installed on the customer's machine.

2. All client-side modules avoid networking primitives. Even if a third-party
   dep is present (pydantic, tree-sitter, propweaver), the modules themselves
   must not import socket, urllib, requests, httpx, or similar.

These checks complement the runtime socket-blocking fixture in conftest.py:
the fixture catches dynamic network attempts; these tests catch them statically
at the source level before execution.
"""
import ast
import sys
from pathlib import Path

import pytest

SRC_DIR = Path(__file__).parent.parent / "src"

# phase0.py runs before grammar/LSP installers — no third-party packages.
# Exception: applog is a first-party, no-network module co-installed with
# comprehensity, so it is always available when comprehensity-scan is invoked.
STDLIB_ONLY_FILES = ["phase0.py"]
PHASE0_FIRST_PARTY_ALLOWED = frozenset({"applog"})

# All modules that execute on the customer's machine (client-side).
CLIENT_SIDE_FILES = [
    "phase0.py",
    "applog.py",
    "blueprint.py",
    "blueprint_io.py",
    "clone_detection.py",   # uses subprocess (local binary), not networking
    "scan.py",
    "ts_parsers.py",
    "import_analysis.py",
    "srcgraph.py",
]

# Top-level module names that indicate network capability.
# Any direct import of these in client-side code is a violation.
NETWORKING_MODULES = frozenset({
    "socket",
    "urllib",
    "urllib3",
    "requests",
    "httpx",
    "aiohttp",
    "http",
    "ftplib",
    "smtplib",
    "poplib",
    "imaplib",
    "telnetlib",
    "xmlrpc",
    "nntplib",
    "ssl",        # included: client code has no reason to touch TLS directly
    "socketserver",
})


def _top_level_imports(source: str) -> list[str]:
    """Return the top-level module name for every import in *source*."""
    tree = ast.parse(source)
    names: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:   # skip relative imports
                names.append(node.module.split(".")[0])
    return names


def _stdlib_names() -> frozenset[str]:
    """Return the set of stdlib module names for the running interpreter."""
    if hasattr(sys, "stdlib_module_names"):          # Python 3.10+
        return frozenset(sys.stdlib_module_names)    # type: ignore[attr-defined]

    # Fallback for Python 3.8/3.9: a conservative hand-maintained list.
    # Err on the side of inclusion — false positives here just mean we miss
    # a third-party package slipping in, which the networking check covers.
    return frozenset({
        "__future__", "_thread", "abc", "aifc", "argparse", "array",
        "ast", "asynchat", "asyncio", "asyncore", "atexit", "audioop",
        "base64", "bdb", "binascii", "bisect", "builtins", "bz2",
        "calendar", "cgi", "cgitb", "chunk", "cmath", "cmd", "code",
        "codecs", "codeop", "collections", "colorsys", "compileall",
        "concurrent", "configparser", "contextlib", "contextvars",
        "copy", "copyreg", "csv", "ctypes", "curses", "dataclasses",
        "datetime", "dbm", "decimal", "difflib", "dis", "distutils",
        "doctest", "email", "encodings", "enum", "errno", "faulthandler",
        "fcntl", "filecmp", "fileinput", "fnmatch", "fractions",
        "functools", "gc", "getopt", "getpass", "gettext", "glob",
        "grp", "gzip", "hashlib", "heapq", "hmac", "html", "http",
        "idlelib", "imaplib", "imghdr", "importlib", "inspect", "io",
        "ipaddress", "itertools", "json", "keyword", "lib2to3",
        "linecache", "locale", "logging", "lzma", "mailbox", "marshal",
        "math", "mimetypes", "mmap", "modulefinder", "multiprocessing",
        "netrc", "numbers", "operator", "optparse", "os", "pathlib",
        "pdb", "pickle", "pickletools", "pipes", "pkgutil", "platform",
        "plistlib", "poplib", "posix", "posixpath", "pprint", "profile",
        "pstats", "pty", "pwd", "py_compile", "pyclbr", "pydoc",
        "queue", "quopri", "random", "re", "readline", "reprlib",
        "resource", "rlcompleter", "runpy", "sched", "secrets",
        "select", "selectors", "shelve", "shlex", "shutil", "signal",
        "site", "smtpd", "smtplib", "sndhdr", "socket", "socketserver",
        "sqlite3", "ssl", "stat", "statistics", "string", "stringprep",
        "struct", "subprocess", "sunau", "symtable", "sys", "sysconfig",
        "syslog", "tabnanny", "tarfile", "telnetlib", "tempfile",
        "termios", "test", "textwrap", "threading", "time", "timeit",
        "tkinter", "token", "tokenize", "trace", "traceback",
        "tracemalloc", "tty", "turtle", "types", "typing", "unicodedata",
        "unittest", "urllib", "uu", "uuid", "venv", "warnings", "wave",
        "weakref", "webbrowser", "wsgiref", "xdrlib", "xml", "xmlrpc",
        "zipapp", "zipfile", "zipimport", "zlib",
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("filename", STDLIB_ONLY_FILES)
def test_phase0_imports_stdlib_only(filename: str) -> None:
    """phase0.py must import nothing outside the standard library.

    It runs before the comprehensity installer, so only stdlib is guaranteed
    to be available on the customer's machine.
    """
    source = (SRC_DIR / filename).read_text(encoding="utf-8")
    stdlib = _stdlib_names()

    violations = [
        mod for mod in _top_level_imports(source)
        if mod not in stdlib and mod not in PHASE0_FIRST_PARTY_ALLOWED
    ]
    assert not violations, (
        f"{filename} must only import stdlib modules (or comprehensity first-party "
        f"modules), but found disallowed import(s): {violations}. "
        f"Phase 0 must not depend on grammar or LSP packages that may not yet be "
        f"installed on the customer's machine."
    )


@pytest.mark.parametrize("filename", CLIENT_SIDE_FILES)
def test_no_networking_imports(filename: str) -> None:
    """Client-side modules must not directly import networking primitives.

    Phase 0 and Phase 1 (basic) carry a contractual no-network guarantee.
    Importing socket, urllib, requests, etc. — even without calling them —
    is a code-review signal that something has gone wrong.
    """
    source = (SRC_DIR / filename).read_text(encoding="utf-8")

    violations = [
        mod for mod in _top_level_imports(source)
        if mod in NETWORKING_MODULES
    ]
    assert not violations, (
        f"{filename} imports networking module(s): {violations}. "
        f"Client-side code (Phase 0 and Phase 1) must never make outbound "
        f"network calls — this is a contractual guarantee."
    )
