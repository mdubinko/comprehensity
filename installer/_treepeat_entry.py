"""
_treepeat_entry.py — PyInstaller entry point wrapper for treepeat.

This file is used ONLY during the PyInstaller build process.  It mirrors the
console_scripts entry point declared by treepeat:
  treepeat = treepeat.cli:main

The resulting EXE is named 'treepeat' and bundled alongside the comprehensity
tools so that clone_detection.run_treepeat() can find it via shutil.which()
without requiring a separate Python installation.
"""
import sys
from treepeat.cli import main

if __name__ == "__main__":
    sys.exit(main())
