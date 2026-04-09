"""
extract_blueprint — Phase 1 blueprint extraction CLI.

Walks a codebase, builds the import graph, optionally detects duplicate code
blocks, and writes a blueprint.json — structural data only, no source.

Usage:
  extract_blueprint <directory> -o blueprint.json
  extract_blueprint . -o bp.json --detect-clones --clone-ruleset loose
  extract_blueprint ~/project -o out.json --ignore-dirs .git,node_modules
"""

import sys
import time
import argparse
from pathlib import Path
from typing import Optional

import applog

try:
    from tqdm import tqdm

    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False


def _strip_phase2(raw: str) -> str | None:
    """Remove Phase 2 sections from raw TOML before stamping into blueprint.

    Strips [phase2.llm], [phase2.token_budget] (current segmented names) and
    bare [llm], [token_budget] (old flat names) — both contain LLM credentials
    and network settings that must never appear in blueprint.yaml.
    """
    if not raw:
        return None
    _PHASE2_PREFIXES = ("[phase2", "[llm]", "[token_budget]")
    lines = raw.splitlines(keepends=True)
    result = []
    in_phase2 = False
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("["):
            in_phase2 = any(stripped.startswith(p) for p in _PHASE2_PREFIXES)
        if not in_phase2:
            result.append(line)
    cleaned = "".join(result).strip()
    return cleaned if cleaned else None


def _get_runtime_info(args: argparse.Namespace) -> dict:
    """Return a dictionary of execution context for the blueprint."""
    import platform
    import os

    return {
        "platform": platform.platform(),
        "python_version": sys.version,
        "argv": sys.argv,
        "cwd": os.getcwd(),
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main():
    import signal

    def handle_sigterm(signum, frame):
        # Raising SystemExit ensures that finally blocks and with-statement
        # __exit__ methods are called as the process unwinds.
        sys.exit(1)

    try:
        signal.signal(signal.SIGTERM, handle_sigterm)
    except (ValueError, RuntimeError):
        # signal only works in main thread; ignore if called elsewhere
        pass

    start = time.perf_counter()
    parser = argparse.ArgumentParser(
        description="Extract a structural blueprint from a codebase (Phase 1).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  extract_blueprint .
  extract_blueprint /path/to/project -o blueprint.json
  extract_blueprint . -o bp.json --detect-clones
  extract_blueprint ~/project -o out.json --ignore-dirs .git,node_modules,build
        """,
    )

    # --- Logging ---
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

    parser.add_argument(
        "directory",
        nargs="?",
        default=".",
        help="Directory to analyze (default: current directory)",
    )
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        metavar="FILE",
        help="Output file path (default: blueprint.yaml or blueprint.json)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format: yaml (default, human-inspectable) or json (machine-readable)",
    )

    # --- Filtering ---
    parser.add_argument(
        "--ignore-dirs",
        default=".git,node_modules,target,build,dist,.gradle,.maven,.venv,venv,__pycache__,.pytest_cache,.tox,coverage_html_report",
        help="Comma-separated directories to skip (default includes common build/cache dirs)",
    )
    parser.add_argument(
        "--ignore-files",
        default=".DS_Store,Thumbs.db,*.tmp,*.log",
        help="Comma-separated file patterns to skip",
    )
    parser.add_argument(
        "--extensions",
        help="Comma-separated extensions to include, e.g. .py,.ts (default: all)",
    )
    parser.add_argument(
        "--exclude-extensions",
        default=".class,.pyc,.o,.exe",
        help="Comma-separated extensions to skip (default: .class,.pyc,.o,.exe)",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        help="Limit recursion depth",
    )
    parser.add_argument(
        "--include-hidden",
        action="store_true",
        help="Include hidden files/dirs (default: skip)",
    )
    parser.add_argument(
        "--min-file-size",
        type=int,
        default=0,
        help="Skip files smaller than N bytes (default: 0)",
    )
    parser.add_argument(
        "--max-file-size",
        type=int,
        default=100 * 1024 * 1024,
        help="Skip files larger than N bytes (default: 100 MB)",
    )

    # --- Performance ---
    parser.add_argument(
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links (default: false)",
    )
    parser.add_argument(
        "--progress",
        action="store_true",
        help="Show progress during scan (sets console level to INFO if not overridden)",
    )

    # --- Import analysis ---
    parser.add_argument(
        "--include-paths",
        help="Comma-separated additional include/search directories for import resolution",
    )

    # --- Semantic (LSP) enrichment ---
    parser.add_argument(
        "--semantic",
        action="store_true",
        help=(
            "Enrich blueprint with LSP-derived call graph, dead code, and diagnostics. "
            "Requires a language server on PATH for each detected language "
            "(e.g. pyright for Python, typescript-language-server for JS/TS)."
        ),
    )
    parser.add_argument(
        "--input",
        metavar="FILE",
        default=None,
        help=(
            "Load an existing phase-1 blueprint JSON instead of scanning from scratch. "
            "Skips all scanning, import analysis, and clone detection. "
            "Requires --semantic. The directory argument still specifies the source root "
            "used by the language server."
        ),
    )

    # --- Clone detection ---
    parser.add_argument(
        "--detect-clones",
        action="store_true",
        help="Detect duplicate code blocks (requires treepeat extra: pip install comprehensity[clone])",
    )
    parser.add_argument(
        "--clone-ruleset",
        choices=["none", "default", "loose"],
        default="loose",
        help="Clone normalisation level: none=exact, default=normalized, loose=approximate (default: loose)",
    )
    parser.add_argument(
        "--clones-output",
        metavar="PATH",
        default=None,
        help=(
            "Path for the raw SARIF clone report produced by treepeat. "
            "Defaults to <blueprint-output>.clones.sarif when --detect-clones is used. "
            "Pass an explicit path to override, or '--clones-output none' to suppress saving."
        ),
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

    # Resolve root
    root = Path(args.directory).resolve()
    if not root.exists():
        applog.error("❌ directory not found → %s", args.directory)
        sys.exit(1)
    if not root.is_dir():
        applog.error("❌ not a directory → %s", args.directory)
        sys.exit(1)

    default_name = (
        "blueprint.yaml" if args.output_format == "yaml" else "blueprint.json"
    )
    output_path = Path(args.output or default_name)

    from config import load_config

    cfg, cfg_path, cfg_raw = load_config()
    if cfg_path:
        applog.info("  config → %s (backend: %s)", cfg_path, cfg.phase2.llm.backend)
    else:
        applog.info("  config → built-in defaults (backend: none)")

    if args.input:
        # Fast path: load existing phase-1 blueprint, skip all scanning.
        if not args.semantic:
            applog.error("❌ --input requires --semantic")
            sys.exit(1)
        input_path = Path(args.input)
        if not input_path.exists():
            applog.error("❌ --input file not found → %s", args.input)
            sys.exit(1)
        from blueprint import Blueprint
        applog.info("🔍 loading blueprint → %s", input_path)
        with open(input_path, encoding="utf-8") as f:
            bp = Blueprint.model_validate_json(f.read())
        applog.info("  loaded: %d files · %d symbols", len(bp.files), len(bp.symbols))
        bp.runtime_info = _get_runtime_info(args)
        bp.config_path = cfg_path
        bp.config_raw = _strip_phase2(cfg_raw)
    else:
        applog.info("🔍 scanning → %s", root)

        # Build source graph (reuse scan.py infrastructure)
        import scan
        import import_analysis
        from blueprint_io import sourcegraph_to_blueprint

        # scan.build_source_graph expects an args namespace with these fields
        _t0 = time.perf_counter()
        sg = scan.build_source_graph(str(root), args)
        _t_scan = time.perf_counter() - _t0

        applog.info("  graph built: %d files (%.1fs)", sg.file_count(), _t_scan)

        include_paths = []
        if args.include_paths:
            include_paths = [p.strip() for p in args.include_paths.split(",") if p.strip()]

        _t0 = time.perf_counter()
        import_analysis.analyze_source_imports(sg, include_paths)
        _t_imports = time.perf_counter() - _t0

        applog.info("  imports resolved (%.1fs)", _t_imports)

        _ignore_dirs = tuple(d.strip() for d in args.ignore_dirs.split(",") if d.strip())

        # Resolve SARIF output path for clone report.
        # Default: alongside the blueprint, with .clones.sarif extension.
        # Suppressed by: '--clones-output none' or when --detect-clones is not set.
        clone_sarif_path: Optional[Path] = None
        if args.detect_clones:
            raw = args.clones_output
            if raw is None:
                clone_sarif_path = output_path.with_suffix("").with_suffix(".clones.sarif")
            elif raw.lower() != "none":
                clone_sarif_path = Path(raw)

        _t0 = time.perf_counter()
        bp = sourcegraph_to_blueprint(
            sg,
            detect_clones=args.detect_clones,
            clone_ruleset=args.clone_ruleset,
            ignore_dirs=_ignore_dirs,
            clone_sarif_path=clone_sarif_path,
        )
        _t_blueprint = time.perf_counter() - _t0

        applog.info("  blueprint built (%.1fs): %d symbols · %d clones [%s]",
                    _t_blueprint, len(bp.symbols), len(bp.clone_blocks), bp.clone_status)

        bp.runtime_info = {
            **_get_runtime_info(args),
            "elapsed_scan_s": round(_t_scan, 1),
            "elapsed_imports_s": round(_t_imports, 1),
            "elapsed_blueprint_s": round(_t_blueprint, 1),
        }
        bp.config_path = cfg_path
        bp.config_raw = _strip_phase2(cfg_raw)

    if args.semantic:
        if not cfg.extract.semantic_enrichment:
            applog.summary(
                "⚠️  semantic enrichment disabled via config (semantic_enrichment = false) — skipping LSP"
            )
        else:
            from blueprint_io import enrich_blueprint_semantic

            applog.info("  running LSP semantic enrichment…")
            _t0 = time.perf_counter()
            bp = enrich_blueprint_semantic(bp, root, show_progress=args.progress and HAS_TQDM)
            _t_semantic = time.perf_counter() - _t0
            bp.runtime_info = {**bp.runtime_info, "elapsed_semantic_s": round(_t_semantic, 1)}
            applog.info(
                "  semantic done (%.1fs): %d edges · %d dead · %d diagnostics",
                _t_semantic, len(bp.reference_edges), len(bp.dead_symbols), len(bp.diagnostics),
            )

    bp.summary = bp.compute_summary()

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            if args.output_format == "yaml":
                f.write(bp.to_yaml())
            else:
                content = bp.to_json()
                f.write(content)
                if not content.endswith("\n"):
                    f.write("\n")
    except IOError as e:
        applog.error("❌ write failed → %s: %s", output_path, e)
        sys.exit(1)

    elapsed = time.perf_counter() - start
    if args.semantic:
        applog.summary(
            "✅ blueprint → %s | %d files · %d externals · %d symbols · %d edges · %d dead · %d diags · %.1fs",
            output_path,
            len(bp.files),
            len(bp.externals),
            len(bp.symbols),
            len(bp.reference_edges),
            len(bp.dead_symbols),
            len(bp.diagnostics),
            elapsed,
        )
    else:
        applog.summary(
            "✅ blueprint → %s | %d files · %d externals · %d symbols · %d clones · %.1fs",
            output_path,
            len(bp.files),
            len(bp.externals),
            len(bp.symbols),
            len(bp.clone_blocks),
            elapsed,
        )
        if clone_sarif_path is not None and args.detect_clones:
            # Per-language runs write <base>.clones.<lang>.sarif instead of <base>.clones.sarif
            sarif_stem = clone_sarif_path.with_suffix("").with_suffix("")  # strip .clones.sarif
            per_lang = sorted(sarif_stem.parent.glob(f"{sarif_stem.name}.clones.*.sarif"))
            if clone_sarif_path.exists():
                applog.summary("✅ clones   → %s", clone_sarif_path)
            elif per_lang:
                for p in per_lang:
                    applog.summary("✅ clones   → %s", p)
            else:
                applog.summary("⚠️  clones SARIF not written (treepeat may have timed out)")


if __name__ == "__main__":
    main()
