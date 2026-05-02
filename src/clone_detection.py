"""clone_detection.py — SARIF → CloneBlock translator and treepeat subprocess wrapper.

Bite 2: sarif_to_clone_blocks — translates treepeat SARIF output to Blueprint
CloneBlock/CloneInstance objects with stable ID assignment.

Bite 3: run_treepeat — subprocess wrapper that invokes the treepeat binary,
writes SARIF to a temp file, calls sarif_to_clone_blocks, and cleans up.
"""

import hashlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from blueprint import CloneBlock, CloneInstance


class CloneDetectionUnavailable(RuntimeError):
    """Raised when the treepeat binary cannot be found."""


def _find_treepeat_binary() -> Optional[str]:
    """Return the path to the treepeat binary, or None if not found.

    Checks the venv-local bin directory first (same dir as sys.executable),
    so this works whether or not the venv is activated.
    """
    venv_bin = Path(sys.executable).parent
    for name in ("treepeat", "treepeat.exe"):
        candidate = venv_bin / name
        if candidate.is_file():
            return str(candidate)
    return shutil.which("treepeat")


_USR_BIN_TIME = "/usr/bin/time"
_TIME_FLAG = "-l" if sys.platform == "darwin" else "-v"
# macOS -l: "   1234567  maximum resident set size" (bytes)
# Linux -v: "Maximum resident set size (kbytes): 12345"
_RSS_RE_MACOS = re.compile(r"^\s*(\d+)\s+maximum resident set size", re.MULTILINE)
_RSS_RE_LINUX = re.compile(r"Maximum resident set size \(kbytes\):\s*(\d+)", re.MULTILINE)


def _parse_peak_rss_mb(text: str) -> Optional[float]:
    """Return peak RSS in MiB from /usr/bin/time stderr output, or None."""
    if sys.platform == "darwin":
        m = _RSS_RE_MACOS.search(text)
        return int(m.group(1)) / (1024 * 1024) if m else None
    m = _RSS_RE_LINUX.search(text)
    return int(m.group(1)) / 1024 if m else None


# Treepeat ruleset → CloneBlock.kind
RULESET_TO_KIND = {
    "none": "exact",
    "default": "normalized",
    "loose": "approximate",
}

# Java method names that indicate boilerplate (getters/setters, Object methods,
# builder pattern, test lifecycle).  Matched against regions[].name from SARIF.
_JAVA_BOILERPLATE_RE = re.compile(
    r"^(get|set|is)[A-Z]"           # accessors
    r"|^(equals|hashCode|toString|canEqual|clone)$"  # Object methods
    r"|^(build|with[A-Z])"          # builder pattern
    r"|^setUp$|^tearDown$"          # test lifecycle
)


# ---------------------------------------------------------------------------
# CPHA severity classification — Seven Circles of Copy-Paste Hell
# ---------------------------------------------------------------------------

_CIRCLE_TEST_DIRS: frozenset = frozenset({
    "test", "tests", "spec", "specs", "__tests__", "__test__",
    "migration", "migrations", "bench", "benchmark", "benchmarks",
    "generated", "__generated__", "fixtures",
})

_CIRCLE_VENDOR_DIRS: frozenset = frozenset({
    "vendor", "_vendor", "third_party", "third-party", "extern", "internal",
})


def _levenshtein(a: str, b: str) -> int:
    """Levenshtein edit distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    dp = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, dp[0] = dp[0], i
        for j, cb in enumerate(b, 1):
            temp = dp[j]
            dp[j] = prev if ca == cb else 1 + min(prev, dp[j - 1], dp[j])
            prev = temp
    return dp[-1]


def _longest_common_dir_prefix(paths: List[str]) -> str:
    """Return the common directory prefix shared by all paths."""
    if not paths:
        return ""
    parts_list = [p.replace("\\", "/").split("/") for p in paths]
    common: List[str] = []
    for level in zip(*parts_list):
        if len(set(level)) == 1:
            common.append(level[0])
        else:
            break
    # Drop the last component if it looks like a filename (has a dot)
    while common and "." in common[-1]:
        common.pop()
    return "/".join(common)


def _path_parts(p: str) -> List[str]:
    return p.replace("\\", "/").split("/")


def _module_dir(p: str, common_prefix: str) -> str:
    """First path component after stripping the common prefix."""
    rel = p
    if common_prefix and p.startswith(common_prefix + "/"):
        rel = p[len(common_prefix) + 1:]
    return rel.replace("\\", "/").split("/")[0]


def classify_circle(rel_paths: List[str], span: int) -> Tuple[int, float]:
    """Return (circle, dantes) for a clone block.

    rel_paths : project-relative file paths for each instance (may have duplicates)
    span      : number of lines in one instance

    See docs/cpha-taxonomy.md in comprehensity-private for the full specification,
    score-weight formulas, calibration targets, and rationale for each rule.

    Classification priority (first match wins):
      1  test/spec/generated/bench dir → Circle I
      2  all same file + span < 5L     → Circle I
      3  vendor/internal dir           → Circle III
      4  all same file                 → Circle II
      5  2 sister subtrees, edit≤3, same filename, depth≥1  → Circle V
      6  all parent dirs pairwise edit≤2  → Circle IV
      7  span≥30 + count≥5 + cross-module → Circle VII
      8  cross-module + span≥15           → Circle VI
      9  default                          → Circle I
    """
    count = len(rel_paths)
    unique_files = set(rel_paths)

    # Rule 1: any instance in test/generated/bench dir → Circle I
    for p in rel_paths:
        parts = _path_parts(p)
        if any(part in _CIRCLE_TEST_DIRS for part in parts[:-1]):
            return 1, 0.0

    # Rule 2: all in same file + short → Circle I
    if len(unique_files) == 1 and span < 5:
        return 1, 0.0

    # Rule 3: any instance in vendor/internal dir → Circle III
    for p in rel_paths:
        parts = _path_parts(p)
        if any(part in _CIRCLE_VENDOR_DIRS for part in parts[:-1]):
            return 3, 0.15

    # Rule 4: all in same file → Circle II
    if len(unique_files) == 1:
        return 2, round(0.05 * count, 4)

    # Compute module dirs relative to the common prefix
    unique_list = list(unique_files)
    common_pfx = _longest_common_dir_prefix(unique_list)
    module_dirs = {_module_dir(p, common_pfx) for p in rel_paths}
    is_cross_module = len(module_dirs) > 1

    # Rule 5: exactly 2 sister subtrees with similar names → Circle V (fork)
    # Requires files to be *nested* inside the module dirs (depth ≥ 1), not
    # directly in them — this distinguishes a fork from simple sibling adapters.
    if is_cross_module and len(module_dirs) == 2:
        md = list(module_dirs)
        if _levenshtein(md[0], md[1]) <= 3:
            basenames = {_path_parts(p)[-1] for p in rel_paths}
            if len(basenames) == 1:
                pfx0 = (common_pfx + "/" if common_pfx else "") + md[0] + "/"
                max_depth = max(
                    len(p[len(pfx0):].replace("\\", "/").split("/")) - 1
                    if p.startswith(pfx0) else 0
                    for p in rel_paths
                )
                if max_depth >= 1:
                    return 5, 0.6

    # Rule 6: sibling dirs with all pairwise name similarity ≤ 2 → Circle IV
    parent_dirs = {"/".join(_path_parts(p)[:-1]) for p in rel_paths}
    if len(parent_dirs) >= 2:
        pd_names = [pd.split("/")[-1] for pd in parent_dirs]
        all_close = all(
            _levenshtein(pd_names[i], pd_names[j]) <= 2
            for i in range(len(pd_names))
            for j in range(i + 1, len(pd_names))
        )
        if all_close:
            pairs = count * (count - 1) / 2
            return 4, round(0.3 * pairs, 4)

    # Rule 7: endemic — many cross-module instances of large blocks → Circle VII
    if span >= 30 and count >= 5 and is_cross_module:
        return 7, round(1.0 * count * math.log2(max(span, 2)), 4)

    # Rule 8: scattered cross-module duplication → Circle VI
    if is_cross_module and span >= 15:
        return 6, round(0.7 * count, 4)

    # Rule 9: default conservative
    return 1, 0.0


# ---------------------------------------------------------------------------

def _hash_region(path: str, start_line: int, end_line: int) -> str:
    """SHA-256 of the normalized content of a file region.

    Normalization: strip leading/trailing whitespace from each line, join with
    newlines. This matches what "identical content" means across clones.

    Falls back to hashing the coordinates if the file cannot be read.
    """
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        region = lines[start_line - 1 : end_line]
        normalized = "\n".join(line.strip() for line in region)
        return hashlib.sha256(normalized.encode()).hexdigest()
    except OSError:
        return hashlib.sha256(
            f"{path}:{start_line}:{end_line}".encode()
        ).hexdigest()


def sarif_to_clone_blocks(
    sarif_path: "Path | str",
    file_id_map: Dict[str, str],
    ruleset: str,
) -> List[CloneBlock]:
    """Translate a treepeat SARIF file to a sorted list of CloneBlocks.

    Args:
        sarif_path:   Path to the SARIF JSON file produced by treepeat.
        file_id_map:  Maps absolute file paths → Blueprint file IDs.
                      Regions whose paths are not in this map are skipped.
        ruleset:      The treepeat ruleset used: "none", "default", or "loose".
                      Determines CloneBlock.kind.

    Returns:
        List of CloneBlock objects, IDs assigned as dup_0, dup_1, … sorted
        by (first_instance_file_id, first_instance_start_line).
    """
    base_kind = RULESET_TO_KIND.get(ruleset, "exact")
    sarif = json.loads(Path(sarif_path).read_text(encoding="utf-8"))

    # Accumulate (sort_key, instances, lines, kind) before stable-ID assignment
    pending: List[Tuple[Tuple[str, int], List[CloneInstance], int, str]] = []

    for run in sarif.get("runs", []):
        for result in run.get("results", []):
            regions = result.get("properties", {}).get("regions", [])
            if len(regions) < 2:
                continue

            # Resolve paths and filter unknown
            resolved: List[Tuple[str, dict]] = []
            for region in regions:
                file_id = file_id_map.get(region["path"])
                if file_id is not None:
                    resolved.append((file_id, region))

            if len(resolved) < 2:
                continue

            # Sort instances within the group for stable ordering
            resolved.sort(key=lambda x: (x[0], x[1]["startLine"]))

            # All instances share the hash of the first region's content
            first_file_id, first_region = resolved[0]
            block_hash = _hash_region(
                first_region["path"],
                first_region["startLine"],
                first_region["endLine"],
            )

            instances = [
                CloneInstance(
                    file_id=file_id,
                    start_line=region["startLine"],
                    end_line=region["endLine"],
                    hash=block_hash,
                )
                for file_id, region in resolved
            ]

            # Tag as boilerplate if every non-empty region name matches the pattern.
            # Requires at least one non-empty name to avoid false-positives on
            # regions where treepeat emitted no name at all.
            names = [r.get("name", "") for r in regions]
            non_empty_names = [n for n in names if n]
            block_kind = (
                "boilerplate"
                if non_empty_names
                and all(_JAVA_BOILERPLATE_RE.search(n) for n in non_empty_names)
                else base_kind
            )

            rel_paths = [fid for fid, _ in resolved]
            sort_key = (first_file_id, first_region["startLine"])
            pending.append((sort_key, instances, regions[0]["lines"], block_kind, rel_paths))

    pending.sort(key=lambda x: x[0])

    blocks = []
    for i, (_, instances, lines, block_kind, rel_paths) in enumerate(pending):
        if block_kind == "boilerplate":
            circle, dantes = 1, 0.0
        else:
            circle, dantes = classify_circle(rel_paths, lines)
        blocks.append(CloneBlock(
            id=f"dup_{i}",
            kind=block_kind,
            instances=instances,
            lines=lines,
            tokens=0,
            circle=circle,
            dantes=dantes,
        ))
    return blocks


def _kill_proc_group(proc: subprocess.Popen) -> None:
    """Send SIGTERM to proc's process group, then SIGKILL if it doesn't exit."""
    try:
        pgid = os.getpgid(proc.pid)
        os.killpg(pgid, signal.SIGTERM)
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait()
    except (ProcessLookupError, PermissionError):
        pass


def run_treepeat(
    root_path: "Path | str",
    ruleset: str = "loose",
    min_lines: int = 5,
    ignore_patterns: Sequence[str] = (),
    file_id_map: Optional[Dict[str, str]] = None,
    sarif_save_path: Optional["Path"] = None,
    show_progress: bool = False,
) -> Tuple[List[CloneBlock], bool]:
    """Invoke treepeat and return (CloneBlocks, timed_out).

    Args:
        root_path:       Directory to analyse.
        ruleset:         "none", "default", or "loose". Determines CloneBlock.kind.
        min_lines:       Minimum clone size in lines (treepeat --min-lines).
        ignore_patterns: Glob patterns forwarded as --ignore flags.
        file_id_map:     Maps absolute file paths → Blueprint file IDs. If None,
                         built automatically as abs_path → path_relative_to_root.
        sarif_save_path: If given, copy the SARIF output to this path instead of
                         deleting it. Useful for debugging and standalone delivery.
        show_progress:   If True, pass --progress to treepeat and let stderr
                         inherit the terminal so tqdm renders correctly.

    Returns:
        (blocks, timed_out): sorted CloneBlocks (empty on timeout/error) and a
        bool that is True when the run was cut short by the timeout.

    Raises:
        CloneDetectionUnavailable: treepeat binary not found on PATH.
    """
    import time as _time
    binary = _find_treepeat_binary()
    if binary is None:
        raise CloneDetectionUnavailable(
            "treepeat binary not found. "
            "Install it with: uv pip install treepeat"
        )

    root_path = Path(root_path).resolve()

    if file_id_map is None:
        file_id_map = {
            str(p.resolve()): str(p.relative_to(root_path))
            for p in root_path.rglob("*")
            if p.is_file()
        }

    cmd = [
        binary,
        "-l", "info",       # stage-level timing on stderr
        "-r", ruleset,
        "detect", str(root_path),
        "-f", "sarif",
        "--min-lines", str(min_lines),
        "--verbose",        # per-language timing, ignored nodes, node types
        "--ignore-files", "",   # don't load repo .gitignore/.dockerignore; comprehensity owns ignore logic
    ]
    if ignore_patterns:
        cmd += ["--ignore", ",".join(ignore_patterns)]
    if show_progress:
        cmd += ["--progress"]

    with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as tmp:
        sarif_path = Path(tmp.name)

    cmd += ["-o", str(sarif_path)]
    # Wrap with /usr/bin/time when available to capture peak RSS in stderr.
    # Skipped when show_progress=True because stderr is inherited by the terminal.
    _measure_rss = not show_progress and os.path.exists(_USR_BIN_TIME)
    if _measure_rss:
        cmd = [_USR_BIN_TIME, _TIME_FLAG] + cmd
    # Run treepeat in its own process group so we can kill the entire tree
    # (including any parallel workers treepeat spawns) on timeout or error.
    # When show_progress=True, inherit stderr so tqdm renders to the terminal.
    t0 = _time.monotonic()
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=None if show_progress else subprocess.PIPE,
        start_new_session=True,
    )
    try:
        # 20-minute timeout: chromadb (1497 files) completes in ~1000s with 176 clones.
        # Larger repos (django 3003, transformers 3797) hit memory pressure during shingling
        # and either crash or run >4500s with minimal/no output. Cut losses early.
        _, stderr_bytes = proc.communicate(timeout=1200)
        elapsed = _time.monotonic() - t0
        stderr_text = (stderr_bytes or b"").decode(errors="replace")
        if proc.returncode != 0:
            from applog import warn
            warn("⚠️  treepeat failed (exit %d) after %.0fs; skipping clone detection\n%s",
                 proc.returncode, elapsed, stderr_text)
            return [], True  # treat non-zero exit as a timeout/failure so clone_status != "complete"
        from applog import debug
        if _measure_rss:
            rss = _parse_peak_rss_mb(stderr_text)
            if rss is not None:
                debug("treepeat peak RSS: %.0f MiB (%.0fs)", rss, elapsed)
        if stderr_text.strip():
            debug("treepeat (%.0fs) stderr:\n%s", elapsed, stderr_text.rstrip())
        if sarif_save_path is not None:
            try:
                import shutil as _shutil
                _shutil.copy2(sarif_path, sarif_save_path)
            except OSError:
                pass
        return sarif_to_clone_blocks(sarif_path, file_id_map, ruleset), False
    except subprocess.TimeoutExpired:
        elapsed = _time.monotonic() - t0
        _kill_proc_group(proc)
        from applog import warn
        warn("⚠️  treepeat timed out after %.0fs; skipping clone detection", elapsed)
        return [], True
    except BaseException:
        # Covers SystemExit (from SIGTERM handler) and unexpected exceptions.
        # Kill the group so treepeat workers don't become orphaned.
        _kill_proc_group(proc)
        raise
    finally:
        sarif_path.unlink(missing_ok=True)
