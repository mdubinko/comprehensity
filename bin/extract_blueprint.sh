#!/bin/sh
# Extract a structural blueprint from a codebase (Phase 1).
#
# Requires: comprehensity and its dependencies installed (uv pip install -e .)
#
# Usage:
#   bin/extract_blueprint.sh [DIR] -o blueprint.json [options]
#   bin/extract_blueprint.sh . -o bp.json --detect-clones
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/../src/extract_blueprint.py" "$@"
