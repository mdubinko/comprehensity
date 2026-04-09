#!/bin/sh
# Phase 0 pre-analysis scanner.
#
# Stdlib only — no install required. Requires Python 3.6+.
#
# Usage:
#   bin/phase0.sh [DIR]         # scan DIR (default: current directory)
#   bin/phase0.sh [DIR] -o out.json
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/../src/phase0.py" "$@"
