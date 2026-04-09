"""
_jedi_entry.py — PyInstaller entry point wrapper for jedi-language-server.

This file is used ONLY during the PyInstaller build process.  It mirrors the
console_scripts entry point declared by jedi-language-server:
  jedi-language-server = jedi_language_server.cli:cli

The resulting EXE is named 'jedi-language-server' and bundled alongside the
comprehensity tools so that blueprint_io._LANG_SERVERS['python'] can find it
via shutil.which() without requiring a separate Python installation.
"""
import sys
from jedi_language_server.cli import cli

if __name__ == "__main__":
    sys.exit(cli())
