"""
phase0.py — Pre-analysis scanner (stdlib only, runs before installer).

Walks a source tree and produces a JSON summary that drives:
  - Installer tree-sitter grammar selection
  - Language server README generation

Output schema
-------------
{
  "format":       "phase0",
  "version":      "0.1",
  "root":         "<absolute path>",
  "extensions":   {".py": 12, ".ts": 5, ...},   # all extensions, sorted
  "languages":    {"python": 12, "typescript": 5, ...},  # known langs only
  "build_configs": [
    {"path": "pyproject.toml", "kind": "pyproject", "depth": 0},
    ...
  ],
  "monorepo":      true | false,   # build configs found at depth > 0
  "generated_dirs": ["dist", ...], # subdirs excluded as generated code
  "runtimes": {
    "node": "20.11.0",   # or null if not found
    "npm":  "10.2.4",
    "go":   "1.22.0",
    "java": null,
    "rust": null
  }
}

Paths in build_configs and generated_dirs always use forward slashes.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Minimal phase0 logging
# ---------------------------------------------------------------------------

# Phase 0 is packaged as a lightweight bootstrap scanner, so we intentionally
# do not import applog here. Keeping this file self-contained simplifies client
# installation and review.
def phase0_error(msg: str, *args: object) -> None:
    text = msg % args if args else msg
    print(text, file=sys.stderr)


def phase0_summary(msg: str, *args: object) -> None:
    text = msg % args if args else msg
    print(text, file=sys.stderr)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Directories skipped entirely — never traversed, never counted.
_SKIP_DIRS: frozenset = frozenset({
    # VCS
    ".git", ".hg", ".svn",

    # JS / Node
    "node_modules",
    "bower_components",         # Bower (legacy)
    ".nyc_output",              # Istanbul/NYC coverage raw data

    # Python
    "venv", ".venv", "env", ".env", "virtualenv",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".tox", ".nox", ".eggs",

    # IDE / editor metadata
    ".idea", ".vscode", ".settings",   # JetBrains, VS Code, Eclipse
    "nbproject",                        # NetBeans
    "xcuserdata",                       # Xcode per-user settings

    # Package manager / vendored dependency trees
    # (contain third-party code, not the project under analysis)
    "vendor",           # Go mod vendor, PHP Composer, Ruby Bundler
    "third_party",      # C/C++ and many others
    "third-party",      # hyphenated variant
    "external",         # C/C++ embedded deps
    "extern",           # variant
    "_deps",            # CMake FetchContent downloads
    "deps",             # Elixir/Erlang mix deps
    "Pods",             # iOS CocoaPods
    "Carthage",         # iOS Carthage
    ".pio",             # PlatformIO (embedded C/C++)

    # Build system internals (not source, not worth reporting)
    "CMakeFiles",       # CMake internal generated files
    ".gradle",          # Gradle daemon/cache files
    ".terraform",       # Terraform provider binaries

    # Language-specific caches / tool state
    ".kotlin",          # Kotlin compiler cache
    ".dart_tool",       # Dart build tool cache
    ".stack-work",      # Haskell Stack build cache
    "elm-stuff",        # Elm package cache
    "dist-newstyle",    # Haskell Cabal build
    ".elixir_ls",       # ElixirLS language server cache
})

# Directories treated as generated / build output.
# Files inside are excluded from counts; the dir itself is reported.
_GENERATED_DIR_NAMES: frozenset = frozenset({
    "dist", "build", "target", "out",
    "generated", "gen", "auto",
    "proto",          # compiled protobuf outputs
    "_build",         # Elixir mix build; CMake out-of-source builds
    "bazel-bin", "bazel-out", "bazel-testlogs",  # Bazel build system
    ".next", ".nuxt", ".svelte-kit",             # JS framework build caches
    "coverage", "htmlcov",
})

# Build manifest filename → kind label.
_BUILD_CONFIGS: Dict[str, str] = {
    "package.json":        "npm",
    "go.mod":              "go",
    "Cargo.toml":          "cargo",
    "pom.xml":             "maven",
    "build.gradle":        "gradle",
    "build.gradle.kts":    "gradle",
    "settings.gradle":     "gradle-settings",
    "settings.gradle.kts": "gradle-settings",
    "pyproject.toml":      "pyproject",
    "setup.py":            "setuptools",
    "setup.cfg":           "setuptools",
    "CMakeLists.txt":      "cmake",
    "Makefile":            "make",
    "build.sbt":           "sbt",
}

# Maps build-config kind → languages that config implies are primary.
# Omits ambiguous kinds (make, gradle-settings) that don't imply a specific language.
_BUILD_KIND_TO_LANGS: Dict[str, List[str]] = {
    "npm":        ["javascript", "typescript"],
    "go":         ["go"],
    "cargo":      ["rust"],
    "maven":      ["java"],
    "gradle":     ["java", "kotlin"],
    "pyproject":  ["python"],
    "setuptools": ["python"],
    "cmake":      ["c", "cpp"],
    "sbt":        ["scala"],
}

# Minimum file count for a language to be considered primary when no build config implies it.
_PRIMARY_FILE_THRESHOLD = 10

# File extension → language name (lowercase, matching tree-sitter grammar names).
_EXT_TO_LANG: Dict[str, str] = {
    ".py":   "python",  ".pyw":  "python",
    ".js":   "javascript", ".jsx": "javascript",
    ".mjs":  "javascript", ".cjs": "javascript",
    ".ts":   "typescript", ".tsx": "typescript",
    ".java": "java",
    ".c":    "c",   ".h":   "c",
    ".cpp":  "cpp", ".cxx": "cpp", ".cc": "cpp",
    ".hpp":  "cpp", ".hxx": "cpp",
    ".go":   "go",
    ".rs":   "rust",
    ".rb":   "ruby",
    ".cs":   "csharp",
    ".kt":   "kotlin", ".kts": "kotlin",
    ".swift": "swift",
}


# ---------------------------------------------------------------------------
# Runtime detection
# ---------------------------------------------------------------------------

# (output_key, binary, cmd, use_stderr, version_regex)
_RUNTIME_SPECS: List[Tuple[str, str, List[str], bool, str]] = [
    ("node", "node",  ["node",  "--version"], False, r"v?(\d+\.\d+\.\d+)"),
    ("npm",  "npm",   ["npm",   "--version"], False, r"(\d+\.\d+\.\d+)"),
    ("yarn", "yarn",  ["yarn",  "--version"], False, r"(\d+\.\d+\.\d+)"),
    ("pnpm", "pnpm",  ["pnpm",  "--version"], False, r"(\d+\.\d+\.\d+)"),
    ("bun",  "bun",   ["bun",   "--version"], False, r"(\d+\.\d+\.\d+)"),
    ("go",   "go",    ["go",    "version"],   False, r"go(\d+\.\d+(?:\.\d+)?)"),
    ("java", "java",  ["java",  "-version"],  True,  r"(\d+(?:\.\d+)+)"),
    ("rust", "rustc", ["rustc", "--version"], False, r"rustc\s+(\d+\.\d+\.\d+)"),
]


def detect_runtimes() -> Dict[str, Optional[str]]:
    """Probe installed runtimes; returns version string or None. Never raises."""
    result: Dict[str, Optional[str]] = {}
    for key, binary, cmd, use_stderr, pattern in _RUNTIME_SPECS:
        if not shutil.which(binary):
            result[key] = None
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            text = (proc.stderr if use_stderr else proc.stdout).strip()
            m = re.search(pattern, text)
            result[key] = m.group(1) if m else None
        except Exception:
            result[key] = None
    return result


def detect_js_package_manager(root: Path) -> Optional[Dict[str, Any]]:
    """Detect which JS package manager the project at *root* requires.

    Detection priority:
      1. ``packageManager`` field in root ``package.json`` (authoritative)
      2. Lock-file heuristics: pnpm-lock.yaml → pnpm; yarn.lock+.yarnrc.yml → yarn-berry;
         yarn.lock alone → yarn-classic; bun.lockb → bun; package-lock.json → npm
      3. Fallback: npm (package.json exists, no lockfile)

    Returns a dict::

        {
          "required":          "npm" | "yarn-classic" | "yarn-berry" | "pnpm" | "bun",
          "version_required":  "4.4.1" | None,       # from packageManager field
          "detection_source":  "packageManager-field" | "lockfile" | "fallback",
          "installed":         True | False,          # is the required tool present?
          "installed_version": "1.22.19" | None,      # what is actually installed
        }

    Returns ``None`` when *root* has no ``package.json`` (not a JS/TS project).
    Never raises.
    """
    pkg_json = root / "package.json"
    if not pkg_json.exists():
        return None

    required = "npm"
    version_required: Optional[str] = None
    detection_source = "fallback"

    # --- 1. packageManager field (authoritative) ---
    try:
        data = json.loads(pkg_json.read_text(encoding="utf-8"))
        pm_field = data.get("packageManager", "")
        if pm_field and "@" in pm_field:
            tool, _, ver = pm_field.partition("@")
            tool = tool.strip()
            ver = ver.strip() or None
            if tool == "yarn":
                try:
                    major = int(ver.split(".")[0]) if ver else 0
                except (ValueError, AttributeError):
                    major = 0
                required = "yarn-berry" if major >= 2 else "yarn-classic"
            elif tool in ("pnpm", "bun", "npm"):
                required = tool
            else:
                required = tool
            version_required = ver
            detection_source = "packageManager-field"
    except Exception:
        pass

    # --- 2. Lock-file heuristics ---
    if detection_source == "fallback":
        if (root / "pnpm-lock.yaml").exists():
            required, detection_source = "pnpm", "lockfile"
        elif (root / ".yarnrc.yml").exists() and (root / "yarn.lock").exists():
            required, detection_source = "yarn-berry", "lockfile"
        elif (root / "yarn.lock").exists():
            required, detection_source = "yarn-classic", "lockfile"
        elif (root / "bun.lockb").exists():
            required, detection_source = "bun", "lockfile"
        elif (root / "package-lock.json").exists():
            required, detection_source = "npm", "lockfile"

    # --- 3. Check what's installed ---
    def _probe(binary: str, cmd: List[str], pat: str) -> Optional[str]:
        if not shutil.which(binary):
            return None
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            m = re.search(pat, proc.stdout.strip())
            return m.group(1) if m else None
        except Exception:
            return None

    installed_version: Optional[str] = None
    installed = False

    if required == "npm":
        v = _probe("npm", ["npm", "--version"], r"(\d+\.\d+\.\d+)")
        installed, installed_version = v is not None, v
    elif required in ("yarn-berry", "yarn-classic"):
        v = _probe("yarn", ["yarn", "--version"], r"(\d+\.\d+\.\d+)")
        installed_version = v
        if v is not None:
            try:
                major = int(v.split(".")[0])
            except (ValueError, IndexError):
                major = 0
            installed = (major >= 2) if required == "yarn-berry" else (major == 1)
    elif required == "pnpm":
        v = _probe("pnpm", ["pnpm", "--version"], r"(\d+\.\d+\.\d+)")
        installed, installed_version = v is not None, v
    elif required == "bun":
        v = _probe("bun", ["bun", "--version"], r"(\d+\.\d+\.\d+)")
        installed, installed_version = v is not None, v

    return {
        "required":          required,
        "version_required":  version_required,
        "detection_source":  detection_source,
        "installed":         installed,
        "installed_version": installed_version,
    }


# ---------------------------------------------------------------------------
# Core scanner
# ---------------------------------------------------------------------------

def scan(root: str) -> Dict[str, Any]:
    """Walk *root* and return the Phase 0 summary dict."""
    root_path = Path(root).resolve()

    ext_counts: Dict[str, int] = {}
    build_configs: List[Dict[str, Any]] = []
    generated_dirs: List[str] = []

    for dirpath, dirnames, filenames in os.walk(root_path):
        rel = Path(dirpath).relative_to(root_path)
        depth = len(rel.parts)

        # Partition dirnames into keep / skip / generated in one pass.
        keep: List[str] = []
        for d in dirnames:
            if d in _SKIP_DIRS:
                pass  # silently prune
            elif d in _GENERATED_DIR_NAMES:
                gen_rel = (rel / d).as_posix() if depth > 0 else d
                generated_dirs.append(gen_rel)
                # do not keep → os.walk won't descend
            else:
                keep.append(d)
        dirnames[:] = keep

        # Detect build config files.
        for fname in filenames:
            if fname in _BUILD_CONFIGS:
                frel = (rel / fname).as_posix() if depth > 0 else fname
                build_configs.append({
                    "path":  frel,
                    "kind":  _BUILD_CONFIGS[fname],
                    "depth": depth,
                })

        # Accumulate extension counts.
        for fname in filenames:
            ext = Path(fname).suffix.lower()
            if ext:
                ext_counts[ext] = ext_counts.get(ext, 0) + 1

    # Aggregate language totals from extension counts.
    lang_counts: Dict[str, int] = {}
    for ext, count in ext_counts.items():
        lang = _EXT_TO_LANG.get(ext)
        if lang:
            lang_counts[lang] = lang_counts.get(lang, 0) + count

    monorepo = any(bc["depth"] > 0 for bc in build_configs)

    # Derive primary languages: build-config-implied (depth 0) + file-count fallback.
    primary_langs: set = set()
    for bc in build_configs:
        if bc["depth"] == 0:
            for lang in _BUILD_KIND_TO_LANGS.get(bc["kind"], []):
                if lang in lang_counts:
                    primary_langs.add(lang)
    for lang, count in lang_counts.items():
        if count >= _PRIMARY_FILE_THRESHOLD:
            primary_langs.add(lang)

    out: Dict[str, Any] = {
        "format":            "phase0",
        "version":           "0.1",
        "root":              str(root_path),
        "extensions":        dict(sorted(ext_counts.items())),
        "languages":         dict(sorted(lang_counts.items())),
        "primary_languages": sorted(primary_langs),
        "build_configs":     sorted(build_configs, key=lambda x: x["path"]),
        "monorepo":          monorepo,
        "generated_dirs":    sorted(generated_dirs),
        "runtimes":          detect_runtimes(),
    }
    _JS_LANGS = {"javascript", "typescript"}
    if _JS_LANGS & set(lang_counts):
        pm_info = detect_js_package_manager(root_path)
        if pm_info is not None:
            out["js_package_manager"] = pm_info
    return out


# ---------------------------------------------------------------------------
# Install recommendations
# ---------------------------------------------------------------------------

# Language → tree-sitter grammar PyPI package(s).
_LANG_TO_GRAMMARS: Dict[str, List[str]] = {
    "python":     ["tree-sitter-python"],
    "javascript": ["tree-sitter-javascript"],
    "typescript": ["tree-sitter-javascript", "tree-sitter-typescript"],
    "java":       ["tree-sitter-java"],
    "c":          ["tree-sitter-c"],
    "cpp":        ["tree-sitter-c", "tree-sitter-cpp"],
    "go":         ["tree-sitter-go"],
    "rust":       ["tree-sitter-rust"],
    "ruby":       ["tree-sitter-ruby"],
    "csharp":     ["tree-sitter-c-sharp"],
    "kotlin":     ["tree-sitter-kotlin"],
    "swift":      ["tree-sitter-swift"],
}

# Language server entries: (lang, runtime_key, ready_cmd, missing_prereq_msg, pip_auto)
#   lang            — language name (matches _EXT_TO_LANG values)
#   runtime_key     — key in runtimes dict (None = no external runtime needed)
#   ready_cmd       — command to emit when runtime IS present (or runtime_key is None)
#   missing_prereq  — message to emit when runtime is absent
#   pip_auto        — True if this can be installed automatically via pip
_LSP_SPECS: List[Tuple[str, Optional[str], str, str, bool]] = [
    (
        "python", None,
        # jedi-language-server: pure Python wheel, pip-installable, no external runtime.
        # Future: replace with `ty server` (astral-sh/ty) once it supports callHierarchy.
        "pip install jedi-language-server",
        "",
        True,
    ),
    (
        "javascript", "node",
        "npm install -g typescript-language-server typescript",
        "install Node.js (https://nodejs.org), then: npm install -g typescript-language-server typescript",
        False,
    ),
    (
        "typescript", "node",
        "npm install -g typescript-language-server typescript",
        "install Node.js (https://nodejs.org), then: npm install -g typescript-language-server typescript",
        False,
    ),
    (
        "go", "go",
        "go install golang.org/x/tools/gopls@latest",
        "install Go (https://go.dev), then: go install golang.org/x/tools/gopls@latest",
        False,
    ),
    (
        "rust", "rust",
        "rustup component add rust-analyzer",
        "install Rust toolchain (https://rustup.rs), then: rustup component add rust-analyzer",
        False,
    ),
    (
        "java", "java",
        "see https://github.com/eclipse-jdtls/eclipse.jdt.ls for jdtls setup",
        "install a JDK (https://adoptium.net), then see https://github.com/eclipse-jdtls/eclipse.jdt.ls",
        False,
    ),
]


def recommend_installs(scan_result: Dict[str, Any]) -> Dict[str, Any]:
    """Return actionable install recommendations derived from a scan() result.

    Output schema::

        {
          "grammar_packages": ["tree-sitter-python", ...],  # uv pip install these
          "pip_auto":         ["pylyzer"],                   # installed automatically
          "manual_steps": [
            {
              "lang":    "javascript",
              "command": "npm install -g typescript-language-server typescript",
              "ready":   true,   # False if runtime prerequisite is missing
              "note":    "...",  # human-readable guidance (set when ready=False)
            },
            ...
          ]
        }
    """
    langs: Dict[str, int] = scan_result.get("languages", {})
    runtimes: Dict[str, Optional[str]] = scan_result.get("runtimes", {})

    # Collect grammar packages (deduped, sorted).
    grammar_set: List[str] = []
    seen_grammars: set = set()
    for lang in sorted(langs):
        for pkg in _LANG_TO_GRAMMARS.get(lang, []):
            if pkg not in seen_grammars:
                seen_grammars.add(pkg)
                grammar_set.append(pkg)

    pip_auto: List[str] = []
    manual_steps: List[Dict[str, Any]] = []
    seen_lsp_langs: set = set()

    for lang, runtime_key, ready_cmd, missing_prereq, is_pip_auto in _LSP_SPECS:
        if lang not in langs:
            continue
        # Deduplicate: JS and TS share the same server.
        dedup_key = ready_cmd
        if dedup_key in seen_lsp_langs:
            continue
        seen_lsp_langs.add(dedup_key)

        if is_pip_auto:
            pip_auto.append(ready_cmd.split()[-1])  # package name is last token
            continue

        runtime_present = runtime_key is None or bool(runtimes.get(runtime_key))
        step: Dict[str, Any] = {"lang": lang, "command": ready_cmd, "ready": runtime_present}
        if not runtime_present:
            step["note"] = missing_prereq
        manual_steps.append(step)

    # Package manager install guidance (only for managers that aren't installed).
    pkg_manager_steps: List[Dict[str, Any]] = []
    js_pm = scan_result.get("js_package_manager")
    if js_pm and not js_pm.get("installed", True):
        req = js_pm.get("required", "npm")
        installed_ver = js_pm.get("installed_version")  # e.g. "1.22.19" if classic installed
        if req == "yarn-berry":
            if installed_ver is None:
                pkg_manager_steps.append({
                    "tool":    "yarn-berry",
                    "setup":   "npm install -g corepack && corepack enable",
                    "install": "yarn install",
                    "note":    "Project requires Yarn Berry but no Yarn is installed.",
                })
            else:
                pkg_manager_steps.append({
                    "tool":    "yarn-berry",
                    "setup":   "corepack enable",
                    "install": "yarn install",
                    "note":    (
                        f"Project requires Yarn Berry; Yarn Classic ({installed_ver}) is installed"
                        " — enable corepack first."
                    ),
                })
        elif req == "pnpm":
            pkg_manager_steps.append({
                "tool":    "pnpm",
                "setup":   "npm install -g pnpm",
                "install": "pnpm install",
                "note":    "Project requires pnpm but it is not installed.",
            })
        elif req == "bun":
            pkg_manager_steps.append({
                "tool":    "bun",
                "setup":   "npm install -g bun",
                "install": "bun install",
                "note":    "Project requires bun but it is not installed.",
            })

    return {
        "python_requirement": {
            "phase1_min": "3.8+",
            "current": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            "ready": sys.version_info >= (3, 8),
        },
        "grammar_packages":   grammar_set,
        "pip_auto":           pip_auto,
        "manual_steps":       manual_steps,
        "pkg_manager_steps":  pkg_manager_steps,
    }


def render_install_summary(recs: Dict[str, Any]) -> List[str]:
    """Return a short stderr-friendly install summary."""
    lines: List[str] = []
    py_req = recs.get("python_requirement")
    if py_req:
        lines.append(
            "Phase 1 Python runtime: requires Python %s (current: %s)%s"
            % (
                py_req["phase1_min"],
                py_req["current"],
                "" if py_req["ready"] else " -- upgrade interpreter before installing Phase 1",
            )
        )

    grammar_count = len(recs.get("grammar_packages", []))
    pip_auto_count = len(recs.get("pip_auto", []))
    manual_count = len(recs.get("manual_steps", []))
    lines.append(
        "Install summary: %d grammar package(s), %d pip auto-install server(s), %d manual step(s)"
        % (grammar_count, pip_auto_count, manual_count)
    )

    if manual_count:
        lines.append("Run with --install-guide for detailed installation steps.")
    return lines


def render_install_guide(recs: Dict[str, Any]) -> List[str]:
    """Return the full stdout install guide."""
    lines: List[str] = []
    py_req = recs.get("python_requirement")
    if py_req:
        lines.append(
            "Phase 1 Python runtime: requires Python %s (current: %s)%s"
            % (
                py_req["phase1_min"],
                py_req["current"],
                "" if py_req["ready"] else " -- upgrade interpreter before installing Phase 1",
            )
        )
    if recs["grammar_packages"]:
        lines.append("Grammar packages (uv pip install):")
        for pkg in recs["grammar_packages"]:
            lines.append(f"  {pkg}")
    if recs["pip_auto"]:
        lines.append("Language servers (pip, auto-installed):")
        for pkg in recs["pip_auto"]:
            lines.append(f"  {pkg}")
    if recs["manual_steps"]:
        lines.append("Language servers (manual steps):")
        for step in recs["manual_steps"]:
            if step["ready"]:
                lines.append(f"  [{step['lang']}] {step['command']}")
            else:
                lines.append(f"  [{step['lang']}] {step.get('note', step['command'])}")
    if recs.get("pkg_manager_steps"):
        lines.append("Package manager setup (run before semantic analysis):")
        for step in recs["pkg_manager_steps"]:
            lines.append(f"  [{step['tool']}] {step['note']}")
            lines.append(f"    1. {step['setup']}")
            lines.append(f"    2. {step['install']}")
    return lines


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    import argparse

    if sys.version_info < (3, 7):
        phase0_error(
            "❌ phase0 requires Python 3.7+ (found %d.%d.%d)",
            sys.version_info.major,
            sys.version_info.minor,
            sys.version_info.micro,
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(
        description="Phase 0: pre-analysis scanner — codebase inventory + runtime detection.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "root", nargs="?", default=".",
        help="Directory to scan (default: current directory)",
    )
    parser.add_argument(
        "-o", "--output",
        help="Write scan JSON to this file (stdout when omitted)",
    )
    parser.add_argument(
        "--install-guide", action="store_true",
        help="Print actionable install steps derived from the scan",
    )
    args = parser.parse_args()
    # Phase 0 keeps logging behavior intentionally hard-coded so the shipped
    # bootstrap script stays self-contained and easy to inspect.

    root_path = Path(args.root)
    if not root_path.exists():
        phase0_error("❌ directory not found → %s", args.root)
        sys.exit(1)
    if not root_path.is_dir():
        phase0_error("❌ not a directory → %s", args.root)
        sys.exit(1)

    import time
    t0 = time.monotonic()
    result = scan(args.root)
    elapsed = time.monotonic() - t0

    lang_count = len(result["languages"])
    file_exts = sum(result["extensions"].values())
    phase0_summary(
        "✅ scan → %s | %d extensions · %d languages · %d build configs · %.1fs",
        result["root"], file_exts, lang_count, len(result["build_configs"]), elapsed,
    )

    out = json.dumps(result, indent=2)
    if args.output:
        try:
            Path(args.output).write_text(out, encoding="utf-8")
        except OSError as e:
            phase0_error("❌ write failed → %s: %s", args.output, e)
            sys.exit(1)
    elif not args.install_guide:
        print(out)

    recs = recommend_installs(result)
    for line in render_install_summary(recs):
        phase0_summary(line)

    if args.install_guide:
        print("\n".join(render_install_guide(recs)))


if __name__ == "__main__":
    main()
