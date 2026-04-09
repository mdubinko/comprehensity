import os
import sys
import time
import argparse
import fnmatch
from pathlib import Path
from typing import List
from srcgraph import SourceGraph
import applog

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


def should_ignore_path(
    path: Path, ignore_patterns: List[str], include_hidden: bool
) -> bool:
    """Check if a path should be ignored based on patterns and hidden file settings"""
    # Check if hidden and not including hidden files
    if not include_hidden and any(part.startswith(".") for part in path.parts):
        return True

    # Check against ignore patterns
    path_str = str(path).replace("\\", "/")
    for pattern in ignore_patterns:
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True

    return False


def should_ignore_file(
    path: Path,
    file_patterns: List[str],
    extensions: List[str],
    exclude_extensions: List[str],
    min_size: int,
    max_size: int,
) -> bool:
    """Check if a file should be ignored based on various criteria"""
    try:
        size = path.stat().st_size

        # Size checks
        if size < min_size or size > max_size:
            return True

        # File pattern checks
        for pattern in file_patterns:
            if fnmatch.fnmatch(path.name, pattern):
                return True

        # Extension checks
        ext = path.suffix.lower()
        if extensions and ext not in extensions:
            return True
        if exclude_extensions and ext in exclude_extensions:
            return True

    except (OSError, PermissionError):
        return True  # Skip files we can't access

    return False


def build_source_graph(root_path: str, args=None) -> SourceGraph:
    """Build complete in-memory source graph with filtering"""
    root = Path(root_path).resolve()

    if not root.exists():
        applog.error("❌ path not found → %s", root_path)
        sys.exit(1)

    if not root.is_dir():
        applog.error("❌ not a directory → %s", root_path)
        sys.exit(1)

    # Parse filtering options
    ignore_dirs = []
    ignore_files = []
    include_extensions = []
    exclude_extensions = []

    if args:
        ignore_dirs = [d.strip() for d in args.ignore_dirs.split(",") if d.strip()]
        ignore_files = [f.strip() for f in args.ignore_files.split(",") if f.strip()]
        if args.extensions:
            include_extensions = [
                e.strip() for e in args.extensions.split(",") if e.strip()
            ]
        if args.exclude_extensions:
            exclude_extensions = [
                e.strip() for e in args.exclude_extensions.split(",") if e.strip()
            ]

        max_depth = args.max_depth
        include_hidden = args.include_hidden
        min_file_size = args.min_file_size
        max_file_size = args.max_file_size
        follow_symlinks = args.follow_symlinks
    else:
        # Defaults for backwards compatibility
        max_depth = None
        include_hidden = False
        min_file_size = 0
        max_file_size = 100 * 1024 * 1024
        follow_symlinks = False

    graph = SourceGraph(root_path=str(root))

    # Walk through all files and directories
    def walk_directory(current_path: Path, current_depth: int = 0):
        if max_depth is not None and current_depth > max_depth:
            return

        try:
            items = list(current_path.iterdir())
        except (OSError, PermissionError) as e:
            applog.warn("⚠️  cannot access %s: %s", current_path, e)
            return

        # Use tqdm for progress if available and we have many items
        items_to_process = items
        if HAS_TQDM and len(items) > 10:
            items_to_process = tqdm(items, desc="Scanning files", unit="file")

        for item in items_to_process:
            try:
                # Skip symlinks unless following them
                if item.is_symlink() and not follow_symlinks:
                    continue

                # Get relative path from root
                relative_path = item.relative_to(root)
                filepath = str(relative_path).replace("\\", "/")

                if item.is_dir():
                    # Check if directory should be ignored
                    if should_ignore_path(relative_path, ignore_dirs, include_hidden):
                        continue

                    graph.add_directory(filepath)
                    walk_directory(item, current_depth + 1)
                else:
                    # Check if file should be ignored
                    if should_ignore_path(
                        relative_path, ignore_dirs + ignore_files, include_hidden
                    ):
                        continue
                    if should_ignore_file(
                        item,
                        ignore_files,
                        include_extensions,
                        exclude_extensions,
                        min_file_size,
                        max_file_size,
                    ):
                        continue

                    try:
                        size_bytes = item.stat().st_size
                    except (OSError, PermissionError):
                        size_bytes = 0

                    graph.add_file(filepath, size_bytes)

            except (OSError, PermissionError) as e:
                applog.warn("⚠️  skipping %s: %s", item, e)
                continue

                # Get relative path from root
                relative_path = item.relative_to(root)
                filepath = str(relative_path).replace("\\", "/")

                if item.is_dir():
                    # Check if directory should be ignored
                    if should_ignore_path(relative_path, ignore_dirs, include_hidden):
                        continue

                    graph.add_directory(filepath)
                    walk_directory(item, current_depth + 1)
                else:
                    # Check if file should be ignored
                    if should_ignore_path(
                        relative_path, ignore_dirs + ignore_files, include_hidden
                    ):
                        continue
                    if should_ignore_file(
                        item,
                        ignore_files,
                        include_extensions,
                        exclude_extensions,
                        min_file_size,
                        max_file_size,
                    ):
                        continue

                    try:
                        size_bytes = item.stat().st_size
                    except (OSError, PermissionError):
                        size_bytes = 0

                    graph.add_file(filepath, size_bytes)

            except (OSError, PermissionError) as e:
                applog.warn("⚠️  skipping %s: %s", item, e)
                continue

    walk_directory(root)
    return graph


def generate_directory_listing(root_path, output_file=None, args=None):
    """
    Generate a directory listing with import analysis and metadata

    Args:
        root_path (str): Path to the directory to analyze
        output_file (str, optional): Output file path. If None, prints to stdout.
        args: Parsed command line arguments for filtering and formatting
    """
    start = time.perf_counter()
    # Build the in-memory graph with filtering
    graph = build_source_graph(root_path, args)

    # Always analyze imports for scan command (this is the new behavior)
    include_paths = []
    if args and args.include_paths:
        include_paths = [p.strip() for p in args.include_paths.split(",") if p.strip()]

    try:
        import import_analysis

        import_analysis.analyze_source_imports(graph, include_paths, applog.info)
    except ImportError as e:
        applog.error("❌ import_analysis unavailable: %s", e)
        sys.exit(1)

    # Add scan metadata to graph
    from pathlib import Path

    scan_metadata = {
        "scan_timestamp": time.time(),
        "scan_parameters": {
            "root_path": str(Path(root_path).resolve()),
            "ignore_dirs": args.ignore_dirs if args else "",
            "ignore_files": args.ignore_files if args else "",
            "extensions": args.extensions if args else None,
            "exclude_extensions": args.exclude_extensions if args else "",
            "max_depth": args.max_depth if args else None,
            "include_hidden": args.include_hidden if args else False,
            "min_file_size": args.min_file_size if args else 0,
            "max_file_size": args.max_file_size if args else 100 * 1024 * 1024,
            "follow_symlinks": args.follow_symlinks if args else False,
        },
    }
    graph.set_graph_metadata("scan_info", scan_metadata)

    # Handle path formatting
    if args and args.absolute:
        # Convert to absolute paths
        root_abs = Path(root_path).resolve()
        for file_node in graph.files.values():
            file_node.path = str(root_abs / file_node.path)
        for dir_node in graph.directories.values():
            dir_node.path = str(root_abs / dir_node.path)
    elif args and args.relative_to:
        # Convert to paths relative to specified base
        base = Path(args.relative_to).resolve()
        root_abs = Path(root_path).resolve()
        try:
            for file_node in graph.files.values():
                abs_path = root_abs / file_node.path
                file_node.path = str(abs_path.relative_to(base))
            for dir_node in graph.directories.values():
                abs_path = root_abs / dir_node.path
                dir_node.path = str(abs_path.relative_to(base))
        except ValueError as e:
            applog.error("❌ relative-to failed → %s: %s", args.relative_to, e)
            sys.exit(1)

    match args.format if args else None:
        case "csv":
            content = graph.to_csv_format()
        case "pipe":
            lines = graph.to_pipe_format()
            content = "\n".join(lines)
        case "blueprint":
            from blueprint_io import sourcegraph_to_blueprint

            detect_clones = getattr(args, "detect_clones", False)
            clone_ruleset = getattr(args, "clone_ruleset", "loose")
            bp = sourcegraph_to_blueprint(
                graph,
                detect_clones=detect_clones,
                clone_ruleset=clone_ruleset,
            )
            content = bp.to_json()
        case _:
            content = graph.to_json_format(include_metadata=True)

    # Output results - scan command always requires output file
    if not output_file:
        applog.error("❌ -o required for scan command")
        applog.info(
            "example: %s . -o project.json", sys.argv[0] if sys.argv else "scan"
        )
        sys.exit(1)

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(content)
            if not content.endswith("\n"):
                f.write("\n")
        elapsed = time.perf_counter() - start
        applog.summary(
            "✅ scan → %s | %d files · %.1fs", output_file, graph.file_count(), elapsed
        )
    except IOError as e:
        applog.error("❌ write failed → %s: %s", output_file, e)
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(
        description="Generate a recursive directory listing for code analysis",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scan.py /path/to/codebase
  python3 scan.py . -o listing.txt --format json
  python3 scan.py ~/project --ignore-dirs .git,node_modules --max-depth 5
  python3 scan.py . --exclude-extensions .pyc,.log --include-hidden
        """,
    )

    # Logging
    parser.add_argument(
        "--console",
        default=None,
        metavar="LEVEL",
        help="Console log level: TRACE/DEBUG/INFO/SUMMARY/WARN/ERROR/FATAL (default: SUMMARY)",
    )
    parser.add_argument(
        "--file",
        dest="file_level",
        default=None,
        metavar="LEVEL",
        help="File log level (NONE disables; default: NONE, or DEBUG when -o is given)",
    )

    # Positional argument
    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to analyze (default: current directory)",
    )

    # Core options
    parser.add_argument(
        "--ignore-dirs",
        default=".git,node_modules,target,build,dist,.gradle,.maven,.venv,venv,__pycache__,.pytest_cache,.tox,coverage_html_report",
        help="Comma-separated list of directories to skip entirely (default: .git,node_modules,target,build,dist,.gradle,.maven,.venv,venv,__pycache__,.pytest_cache,.tox,coverage_html_report)",
    )

    parser.add_argument(
        "--ignore-files",
        default=".DS_Store,Thumbs.db,*.tmp,*.log",
        help="Comma-separated list of file patterns to skip (default: .DS_Store,Thumbs.db,*.tmp,*.log)",
    )

    parser.add_argument(
        "--max-depth",
        type=int,
        help="Limit recursion depth (useful for very deep projects)",
    )

    parser.add_argument(
        "--max-file-size",
        type=int,
        default=100 * 1024 * 1024,  # 100MB
        help="Skip files larger than N bytes (default: 100MB)",
    )

    # Output control
    parser.add_argument(
        "-o", "--output", help="Output file path (default: stdout)", metavar="FILE"
    )

    parser.add_argument(
        "--format",
        choices=["pipe", "csv", "json", "full-json", "blueprint"],
        default="full-json",
        help="Output format: full-json (default), pipe, csv, json, blueprint",
    )

    parser.add_argument(
        "--relative-to",
        help="Show paths relative to different base (not just input dir)",
    )

    parser.add_argument(
        "--absolute",
        action="store_true",
        help="Show absolute paths instead of relative",
    )

    # Filtering
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files/dirs (default: skip)",
    )

    parser.add_argument(
        "--extensions",
        help="Comma-separated list of extensions to include (e.g. .py,.js)",
    )

    parser.add_argument(
        "--exclude-extensions",
        default=".class,.pyc,.o,.exe",
        help="Comma-separated list of extensions to skip (default: .class,.pyc,.o,.exe)",
    )

    parser.add_argument(
        "--min-file-size",
        type=int,
        default=0,
        help="Skip files smaller than N bytes (default: 0)",
    )

    # Performance
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links (default: false)",
    )

    parser.add_argument(
        "--progress", action="store_true", help="Show progress bar for large scans"
    )

    # Import analysis options
    parser.add_argument(
        "--analyze-imports",
        action="store_true",
        help="Analyze import/include relationships (experimental)",
    )

    parser.add_argument(
        "--detect-clones",
        action="store_true",
        help="Detect duplicate code blocks (requires treepeat; blueprint format only)",
    )

    parser.add_argument(
        "--clone-ruleset",
        choices=["none", "default", "loose"],
        default="loose",
        help="Clone normalisation level: none=exact, default=normalized, loose=approximate (default: loose)",
    )

    parser.add_argument(
        "--include-paths", help="Comma-separated list of additional include directories"
    )

    args = parser.parse_args()

    # --progress implies INFO if no explicit --console was given
    console_level = args.console
    if args.progress and console_level is None:
        console_level = "INFO"

    applog.configure(
        console_level=console_level,
        file_level=args.file_level,
        output_given=args.output is not None,
    )

    generate_directory_listing(args.directory, args.output, args)


if __name__ == "__main__":
    main()
