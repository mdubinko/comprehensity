"""clone_detection.py — SARIF → CloneBlock translator and treepeat subprocess wrapper.

Bite 2: sarif_to_clone_blocks — translates treepeat SARIF output to Blueprint
CloneBlock/CloneInstance objects with stable ID assignment.

Bite 3: run_treepeat — subprocess wrapper that invokes the treepeat binary,
writes SARIF to a temp file, calls sarif_to_clone_blocks, and cleans up.
"""

import hashlib
import json
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

            sort_key = (first_file_id, first_region["startLine"])
            pending.append((sort_key, instances, regions[0]["lines"], block_kind))

    pending.sort(key=lambda x: x[0])

    return [
        CloneBlock(
            id=f"dup_{i}",
            kind=block_kind,
            instances=instances,
            lines=lines,
            tokens=0,
        )
        for i, (_, instances, lines, block_kind) in enumerate(pending)
    ]


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
    ]
    if ignore_patterns:
        cmd += ["--ignore", ",".join(ignore_patterns)]
    if show_progress:
        cmd += ["--progress"]

    with tempfile.NamedTemporaryFile(suffix=".sarif", delete=False) as tmp:
        sarif_path = Path(tmp.name)

    cmd += ["-o", str(sarif_path)]
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
