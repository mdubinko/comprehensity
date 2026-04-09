"""
rthook_bundle_path.py — PyInstaller runtime hook

Two responsibilities:
1. Prepend the bundle directory to PATH so shutil.which() finds bundled
   sibling binaries (jedi-language-server, treepeat).

2. Handle multiprocessing resource tracker / forkserver subprocesses.
   On macOS, Python's multiprocessing re-spawns the frozen executable with:
     [exe, *interpreter_flags, '-c', 'from multiprocessing.resource_tracker import main;main(...)']
   PyInstaller's built-in pyi_rth_multiprocessing hook catches this via an
   exact sys.flags set-comparison that fails on Python 3.12 in frozen mode.
   We intercept it first with a looser pattern check.

This hook runs before PyInstaller's built-in runtime hooks.
"""
import os
import sys

# ---------------------------------------------------------------------------
# 1. Multiprocessing subprocess interception (must come first)
# ---------------------------------------------------------------------------
# Pattern: last two argv entries are '-c' followed by a multiprocessing
# bootstrap string.  We don't check the flag set — just the -c + code shape.
_MP_PREFIXES = (
    'from multiprocessing.resource_tracker import main',
    'from multiprocessing.forkserver import main',
    'from multiprocessing.spawn import spawn_main',
)
if len(sys.argv) >= 2 and sys.argv[-2] == '-c' and sys.argv[-1].startswith(_MP_PREFIXES):
    exec(sys.argv[-1])  # noqa: S102
    sys.exit()

# ---------------------------------------------------------------------------
# 2. Bundle directory on PATH
# ---------------------------------------------------------------------------
_bundle_dir = os.path.dirname(os.path.abspath(sys.executable))
_path = os.environ.get("PATH", "")
if _bundle_dir not in _path.split(os.pathsep):
    os.environ["PATH"] = _bundle_dir + (os.pathsep + _path if _path else "")
