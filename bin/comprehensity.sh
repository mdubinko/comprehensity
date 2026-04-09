#!/bin/bash

# Comprehensity - Code Analysis Tool
# Usage: ./bin/comprehensity.sh <command> [arguments...]
# Commands:
#   scan     - Scan codebase structure and generate file listings
#   analyze  - Analyze codebase for duplicate/similar code sections

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SRC_DIR="${SCRIPT_DIR}/../src"

# Function to check environment and provide diagnostics
check_environment() {
    local issues=0

    # Check if python3 is available
    if ! command -v python3 &> /dev/null; then
        echo "❌ ISSUE: python3 command not found" >&2
        echo "   SOLUTION: Install Python 3.6+ from https://python.org/downloads/" >&2
        echo "   Or on Ubuntu/Debian: sudo apt install python3" >&2
        echo "   Or on macOS with Homebrew: brew install python3" >&2
        issues=$((issues + 1))
    else
        # Check Python version
        python_version=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
        if [[ $? -ne 0 ]]; then
            echo "❌ ISSUE: Cannot determine Python version" >&2
            echo "   SOLUTION: Reinstall Python 3.6+ from https://python.org/downloads/" >&2
            issues=$((issues + 1))
        else
            major=$(echo "$python_version" | cut -d. -f1)
            minor=$(echo "$python_version" | cut -d. -f2)
            if [[ $major -lt 3 || ($major -eq 3 && $minor -lt 6) ]]; then
                echo "❌ ISSUE: Python version $python_version is too old" >&2
                echo "   SOLUTION: Install Python 3.6+ from https://python.org/downloads/" >&2
                issues=$((issues + 1))
            fi
        fi
    fi

    # Check if source files exist
    if [[ ! -f "$SRC_DIR/scan.py" ]]; then
        echo "❌ ISSUE: scan.py not found at $SRC_DIR/scan.py" >&2
        echo "   SOLUTION: Ensure you have the complete comprehensity source code" >&2
        issues=$((issues + 1))
    fi

    if [[ ! -f "$SRC_DIR/copypaste.py" ]]; then
        echo "❌ ISSUE: copypaste.py not found at $SRC_DIR/copypaste.py" >&2
        echo "   SOLUTION: Ensure you have the complete comprehensity source code" >&2
        issues=$((issues + 1))
    fi

    # Check directory permissions
    if [[ ! -r "." ]]; then
        echo "❌ ISSUE: No read permission for current directory" >&2
        echo "   SOLUTION: Run with appropriate permissions or from a readable directory" >&2
        issues=$((issues + 1))
    fi

    # Exit if critical issues found
    if [[ $issues -gt 0 ]]; then
        echo "" >&2
        echo "Found $issues critical issue(s). Please fix them and try again." >&2
        exit 1
    fi
}

# Show usage if no arguments provided
show_usage() {
    echo "Comprehensity - Code Analysis Tool"
    echo ""
    echo "Usage: $0 <command> [arguments...]"
    echo ""
    echo "Commands:"
    echo "  scan     Build source graph with import analysis (outputs JSON file)"
    echo "           Examples:"
    echo "             $0 scan /path/to/codebase -o project.json"
    echo "             $0 scan . -o analysis.json --extensions .py,.js"
    echo ""
    echo "  copypaste  Detect code duplicates using jscpd"
    echo "           Examples:"
    echo "             $0 copypaste project.json -o duplicates.json"
    echo "             $0 copypaste . --min-lines 3 --min-tokens 30"
    echo ""
    echo "  insights Generate comprehensive analysis (main entry point)"
    echo "           Examples:"
    echo "             $0 insights /path/to/codebase"
    echo "             $0 insights project.json --format json -o insights.json"
    echo ""
    echo "For detailed help on a specific command:"
    echo "  $0 scan --help"
    echo "  $0 copypaste --help"
    echo "  $0 insights --help"
}

# Check for command argument
if [[ $# -eq 0 ]]; then
    show_usage
    exit 1
fi

command="$1"
shift  # Remove command from arguments

# Run diagnostics
check_environment

# Set up environment
export PYTHONPATH="${SRC_DIR}:${PYTHONPATH}"

# Execute the appropriate command
case "$command" in
    scan)
        python3 "${SRC_DIR}/scan.py" "$@"
        ;;
    copypaste)
        # Check if jscpd is installed for copypaste command
        if ! command -v jscpd &> /dev/null; then
            echo "❌ ISSUE: jscpd command not found (required for copypaste command)" >&2
            echo "   SOLUTION: Install jscpd with: npm install -g jscpd" >&2
            echo "   Or check if Node.js is installed: npm --version" >&2
            echo "   Install Node.js from: https://nodejs.org/" >&2
            exit 1
        fi

        # Verify jscpd can run and get version
        if ! jscpd_version=$(jscpd --version 2>/dev/null); then
            echo "❌ ISSUE: jscpd installed but cannot run (may be corrupted)" >&2
            echo "   SOLUTION: Reinstall jscpd with: npm uninstall -g jscpd && npm install -g jscpd" >&2
            exit 1
        fi

        # jscpd is available, run the analysis
        python3 "${SRC_DIR}/copypaste.py" "$@"
        ;;
    insights)
        # Check if jscpd is installed for insights command (since it includes copypaste)
        if ! command -v jscpd &> /dev/null; then
            echo "❌ ISSUE: jscpd command not found (required for insights command)" >&2
            echo "   SOLUTION: Install jscpd with: npm install -g jscpd" >&2
            echo "   Or check if Node.js is installed: npm --version" >&2
            echo "   Install Node.js from: https://nodejs.org/" >&2
            exit 1
        fi

        # Verify jscpd can run and get version
        if ! jscpd_version=$(jscpd --version 2>/dev/null); then
            echo "❌ ISSUE: jscpd installed but cannot run (may be corrupted)" >&2
            echo "   SOLUTION: Reinstall jscpd with: npm uninstall -g jscpd && npm install -g jscpd" >&2
            exit 1
        fi

        # Comprehensive analysis with duplicate detection
        python3 "${SRC_DIR}/analyze.py" "$@"
        ;;
    --help|-h|help)
        show_usage
        ;;
    *)
        echo "❌ Unknown command: $command" >&2
        echo ""
        show_usage
        exit 1
        ;;
esac
