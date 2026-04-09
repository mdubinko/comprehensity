# comprehensity.spec — PyInstaller build spec for the comprehensity phase1 installer.
#
# Produces: dist/comprehensity/
#   comprehensity-scan          (phase 0 scanner / install guide)
#   extract-blueprint           (phase 1 extractor)
#   jedi-language-server        (Python LSP, bundled for --semantic)
#   treepeat                    (clone detection backend, bundled)
#   _internal/                  (shared bytecode + native libs)
#     tree_sitter_python/
#       _binding.abi3.so
#     tree_sitter_javascript/
#       _binding.abi3.so
#     ...                       (one dir per installed grammar)
#
# Phase 2 tools (analyze-blueprint, compare-models, check-llm) are NOT
# included here — they require LLM connectivity and ship separately.
#
# Build prerequisites:
#   uv pip install pyinstaller         # add pyinstaller to dev deps first
#   uv pip install -e ".[dev,lang-all]"
#
# Build command (run from repo root):
#   .venv/bin/pyinstaller installer/comprehensity.spec
#
# Output is in dist/comprehensity/.  Wrap with:
#   macOS:   productbuild + pkgbuild  → comprehensity-<ver>-macos.pkg
#   Windows: NSIS script              → comprehensity-<ver>-windows.exe
#   Linux:   appimagetool             → comprehensity-<ver>-linux.AppImage

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

block_cipher = None

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SPEC_DIR  = Path(SPECPATH)           # installer/ directory (where this .spec lives)
_REPO_DIR  = _SPEC_DIR.parent        # repo root
_SRC_DIR   = _REPO_DIR / 'src'
_INST_DIR  = _SPEC_DIR               # installer/ contains rthooks + entry wrappers

# ---------------------------------------------------------------------------
# Collect tree-sitter grammar packages
# ---------------------------------------------------------------------------
# Each grammar ships a _binding.abi3.so (stable ABI C extension).
# PyInstaller's static import analysis does NOT discover these because every
# parser __init__ method guards the import with:
#     try: import tree_sitter_python as _tspy
#     except ImportError: raise ImportError("install hint") from None
#
# collect_all() picks up the Python package, the .abi3.so binary, and any
# data files declared by the wheel.  Packages not installed in the build
# venv are silently skipped.

_GRAMMAR_PACKAGES = [
    'tree_sitter_python',
    'tree_sitter_javascript',
    'tree_sitter_typescript',
    'tree_sitter_java',
    'tree_sitter_c',
    'tree_sitter_cpp',
    'tree_sitter_rust',
    'tree_sitter_c_sharp',
    'tree_sitter_kotlin',
    'tree_sitter_ruby',
    'tree_sitter_swift',
    'tree_sitter_go',
]

grammar_datas     = []
grammar_binaries  = []
grammar_hiddenimports = []

for _pkg in _GRAMMAR_PACKAGES:
    try:
        _d, _b, _h = collect_all(_pkg)
        grammar_datas    += _d
        grammar_binaries += _b
        grammar_hiddenimports += _h
    except Exception:
        pass  # not installed in this build env — skip

# Native extensions that static analysis may miss:
#   igraph._igraph.abi3.so        — Python-igraph C binding
#   pydantic_core._pydantic_core  — Rust-backed pydantic v2 core
#   yaml._yaml                    — optional LibYAML C extension

for _pkg in ('igraph', 'pydantic_core', 'propweaver', 'yaml', 'datasketch'):
    try:
        _d, _b, _h = collect_all(_pkg)
        grammar_datas    += _d
        grammar_binaries += _b
        grammar_hiddenimports += _h
    except Exception:
        pass

# numpy 2.x: PyInstaller's built-in hook predates the _core subpackage.
# Bypass it — find every .so under the numpy package dir and preserve the
# relative path so `import numpy._core._multiarray_umath` resolves correctly.
import glob as _glob
import numpy as _np

_numpy_pkg  = os.path.dirname(_np.__file__)
_numpy_root = os.path.dirname(_numpy_pkg)   # site-packages/
for _so in _glob.glob(os.path.join(_numpy_pkg, '**', '*.so'), recursive=True):
    _dest = os.path.dirname(os.path.relpath(_so, _numpy_root))
    grammar_binaries.append((_so, _dest))

# ---------------------------------------------------------------------------
# Shared Analysis parameters
# ---------------------------------------------------------------------------

RUNTIME_HOOKS = [str(_INST_DIR / 'rthook_bundle_path.py')]

PATHEX = [str(_SRC_DIR)]

HIDDENIMPORTS = grammar_hiddenimports + [
    # Grammar packages — belt-and-suspenders alongside collect_all
    *_GRAMMAR_PACKAGES,
    # Core tree-sitter runtime
    'tree_sitter',
    # propweaver — explicit submodule list in case collect_all fails silently
    'propweaver',
    'propweaver.api',
    'propweaver.core',
    'propweaver.exceptions',
    'propweaver.logger',
    'propweaver.logging_utils',
    'propweaver.query',
    'propweaver.storage',
    # igraph
    'igraph',
    # pydantic v2
    'pydantic',
    'pydantic.v1',
    'pydantic_core',
    # yaml
    'yaml',
    # numpy (treepeat → datasketch dependency)
    # numpy 2.x moved internals to _core; list explicitly for PyInstaller
    'numpy',
    'numpy._core',
    'numpy._core._multiarray_umath',
    'numpy._core._multiarray_tests',
    'numpy._core.multiarray',
    'numpy._core.umath',
    # tqdm
    'tqdm',
    'tqdm.auto',
    # treepeat (bundled separately as EXE, but its Python package may be
    # imported transitively — list to be safe)
    'treepeat',
    # jedi_language_server — bundled as EXE; package listed so any
    # import-time side effects are captured during analysis
    'jedi_language_server',
    # tomli for Python < 3.11 (TOML config parsing)
    'tomli',
    # pkg_resources / importlib.metadata used by some deps at import time
    'pkg_resources',
    'importlib.metadata',
]

DATAS    = grammar_datas
BINARIES = grammar_binaries

EXCLUDES = ['tkinter', '_tkinter']   # GUI toolkit — genuinely never needed

# ---------------------------------------------------------------------------
# Analysis for each entry point
# ---------------------------------------------------------------------------

def _analysis(script, extra_hiddenimports=None):
    """Convenience wrapper for Analysis with shared settings."""
    return Analysis(
        [str(script)],
        pathex=PATHEX,
        binaries=BINARIES,
        datas=DATAS,
        hiddenimports=HIDDENIMPORTS + (extra_hiddenimports or []),
        hookspath=[],
        hooksconfig={},
        runtime_hooks=RUNTIME_HOOKS,
        excludes=EXCLUDES,
        cipher=block_cipher,
        noarchive=False,
    )


a_scan    = _analysis(_SRC_DIR / 'phase0.py')
a_extract = _analysis(_SRC_DIR / 'extract_blueprint.py')

# jedi-language-server: Python LSP for --semantic on Python projects.
# Bundled so shutil.which('jedi-language-server') finds it via rthook PATH.
a_jedi = _analysis(
    _INST_DIR / '_jedi_entry.py',
    extra_hiddenimports=['jedi_language_server.cli', 'jedi_language_server.server'],
)

# treepeat: clone detection backend.
# Bundled so shutil.which('treepeat') finds it via rthook PATH.
a_treepeat = _analysis(
    _INST_DIR / '_treepeat_entry.py',
    extra_hiddenimports=['treepeat.cli'],
)

# ---------------------------------------------------------------------------
# PYZ archives (bytecode)
# ---------------------------------------------------------------------------

pyz_scan     = PYZ(a_scan.pure,     cipher=block_cipher)
pyz_extract  = PYZ(a_extract.pure,  cipher=block_cipher)
pyz_jedi     = PYZ(a_jedi.pure,     cipher=block_cipher)
pyz_treepeat = PYZ(a_treepeat.pure, cipher=block_cipher)

# ---------------------------------------------------------------------------
# EXE objects
# ---------------------------------------------------------------------------

_EXE_KWARGS = dict(
    console=True,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,      # True saves ~15% size but makes crash traces unreadable
    upx=False,        # UPX compression is unreliable with abi3.so files
    # macOS notarization: set CODESIGN_IDENTITY env var in CI before build
    codesign_identity=os.environ.get('CODESIGN_IDENTITY'),
    entitlements_file=None,
)

# exclude_binaries=True is required for one-dir mode with COLLECT.
# Without it each EXE embeds its own copy of the Python library (one-file
# behaviour), causing the bootloader to extract to a temp _MEI* dir instead
# of finding _internal/ next to the executable.
exe_scan     = EXE(pyz_scan,     a_scan.scripts,     [], exclude_binaries=True, name='comprehensity-scan',   **_EXE_KWARGS)
exe_extract  = EXE(pyz_extract,  a_extract.scripts,  [], exclude_binaries=True, name='extract-blueprint',    **_EXE_KWARGS)
exe_jedi     = EXE(pyz_jedi,     a_jedi.scripts,     [], exclude_binaries=True, name='jedi-language-server', **_EXE_KWARGS)
exe_treepeat = EXE(pyz_treepeat, a_treepeat.scripts, [], exclude_binaries=True, name='treepeat',             **_EXE_KWARGS)

# ---------------------------------------------------------------------------
# COLLECT — single output directory: dist/comprehensity/
# ---------------------------------------------------------------------------

coll = COLLECT(
    exe_scan,     a_scan.binaries,     a_scan.zipfiles,     a_scan.datas,
    exe_extract,  a_extract.binaries,  a_extract.zipfiles,  a_extract.datas,
    exe_jedi,     a_jedi.binaries,     a_jedi.zipfiles,     a_jedi.datas,
    exe_treepeat, a_treepeat.binaries, a_treepeat.zipfiles, a_treepeat.datas,
    strip=False,
    upx=False,
    name='comprehensity',
)
