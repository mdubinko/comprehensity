"""jvm_detect.py — Locate Java executables across platforms.

Searches multiple sources and filters by minimum JVM version.
Call ``find_java(min_version=21)`` to get the first acceptable executable.

Override precedence (highest to lowest):
  1. Caller-supplied *extra_home* (e.g. from config file ``[java] java_home``)
  2. ``COMPREHENSITY_JAVA_HOME`` env var
  3. ``JAVA_HOME`` env var
  4. Homebrew Cellar (macOS: /opt/homebrew, /usr/local — descending version)
  5. SDKMAN installs  (~/.sdkman/candidates/java/*)
  6. asdf installs    (~/.asdf/installs/java/*)
  7. System JVM dirs  (/usr/lib/jvm/* on Linux)
  8. Windows standard locations (Program Files/Eclipse Adoptium, Microsoft, Java)
  9. ``java`` on PATH — last resort

Use ``describe_java_candidates()`` to enumerate all candidates with their
detected versions — helpful for diagnostics and install-guide output.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


def _parse_java_version(output: str) -> Optional[int]:
    """Extract the major version integer from ``java -version`` stderr/stdout.

    Handles:
      - Modern: "21.0.1", "17.0.7"
      - Legacy: "1.8.0_372"
      - OpenJDK: "openjdk version \"21.0.1\""
      - Unquoted or varied: "java version 11.0.19"
    """
    # Look for a version-like string: "X.Y.Z" or "X.Y" or just "X"
    # We prefer the first one after 'version' if present.
    m = re.search(r'version\s+"?(\d+)(?:\.(\d+))?', output, re.IGNORECASE)
    if not m:
        # Fallback: just look for the first quoted number
        m = re.search(r'"(\d+)(?:\.(\d+))?', output)
    
    if not m:
        return None
    
    major = int(m.group(1))
    # Legacy format: "1.8" → major 8
    if major == 1 and m.group(2):
        return int(m.group(2))
    return major


def _java_version(java_bin: str) -> Optional[int]:
    """Return the major version of *java_bin*, or None on any failure."""
    try:
        result = subprocess.run(
            [java_bin, "-version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        # ``java -version`` writes to stderr on all known JVMs.
        output = result.stderr or result.stdout
        return _parse_java_version(output)
    except Exception:
        return None


def _sorted_subdirs(parent: Path) -> List[Path]:
    """Return immediate subdirectories of *parent* sorted descending by name.

    Returns an empty list if *parent* doesn't exist or can't be read.
    Descending sort puts higher version numbers first (e.g. ``21.0.2`` before ``17.0.5``).
    """
    try:
        return sorted((d for d in parent.iterdir() if d.is_dir()), reverse=True)
    except OSError:
        return []


def _candidate_paths(extra_home: Optional[str] = None) -> List[str]:
    """Return candidate ``java`` binary paths in priority order (may have duplicates).

    Args:
        extra_home: Optional JDK home directory supplied by the caller (e.g.
            from a config file).  Inserted at highest priority, before env vars.
    """
    candidates: List[str] = []

    def _add_home(home: Optional[str]) -> None:
        if home:
            # On Windows the binary is java.exe; Path handles the extension transparently
            candidates.append(str(Path(home) / "bin" / "java"))

    # 1. Caller-supplied override (e.g. [java] java_home from config file)
    _add_home(extra_home)

    # 2. COMPREHENSITY_JAVA_HOME env var
    _add_home(os.environ.get("COMPREHENSITY_JAVA_HOME"))

    # 3. JAVA_HOME env var
    _add_home(os.environ.get("JAVA_HOME"))

    # 4. Homebrew on macOS (Apple Silicon: /opt/homebrew; Intel: /usr/local)
    for brew_prefix in ("/opt/homebrew", "/usr/local"):
        cellar = Path(brew_prefix) / "Cellar" / "openjdk"
        for version_dir in _sorted_subdirs(cellar):
            # Homebrew macOS .jdk bundle layout
            macos_bin = (
                version_dir / "libexec" / "openjdk.jdk" / "Contents" / "Home" / "bin" / "java"
            )
            if macos_bin.exists():
                candidates.append(str(macos_bin))
            # Fallback: some formulae install a flat bin/java
            flat_bin = version_dir / "bin" / "java"
            if flat_bin.exists():
                candidates.append(str(flat_bin))

    # 5. SDKMAN installs (~/.sdkman/candidates/java/<version>/bin/java)
    sdkman_java = Path.home() / ".sdkman" / "candidates" / "java"
    for version_dir in _sorted_subdirs(sdkman_java):
        if version_dir.name == "current":
            continue  # skip the symlink — we'll evaluate the real dirs first
        bin_path = version_dir / "bin" / "java"
        if bin_path.exists():
            candidates.append(str(bin_path))
    # Add the "current" symlink last so it loses to explicit versions
    sdkman_current = sdkman_java / "current" / "bin" / "java"
    if sdkman_current.exists():
        candidates.append(str(sdkman_current))

    # 6. asdf installs (~/.asdf/installs/java/<version>/bin/java)
    asdf_java = Path.home() / ".asdf" / "installs" / "java"
    for version_dir in _sorted_subdirs(asdf_java):
        bin_path = version_dir / "bin" / "java"
        if bin_path.exists():
            candidates.append(str(bin_path))

    # 7. Common Linux JVM directories (/usr/lib/jvm/*)
    jvm_root = Path("/usr/lib/jvm")
    for jvm_dir in _sorted_subdirs(jvm_root):
        bin_path = jvm_dir / "bin" / "java"
        if bin_path.exists():
            candidates.append(str(bin_path))

    # 8. Windows standard installation directories
    for win_root in (
        r"C:\Program Files\Eclipse Adoptium",
        r"C:\Program Files\Microsoft",
        r"C:\Program Files\Java",
        r"C:\Program Files\BellSoft",      # Liberica JDK
        r"C:\Program Files\Amazon Corretto",
    ):
        win_path = Path(win_root)
        for jdk_dir in _sorted_subdirs(win_path):
            bin_path = jdk_dir / "bin" / "java.exe"
            if bin_path.exists():
                candidates.append(str(bin_path))

    # 9. java on PATH — last resort
    java_on_path = shutil.which("java")
    if java_on_path:
        candidates.append(java_on_path)

    return candidates


def find_java(
    min_version: int = 21,
    extra_home: Optional[str] = None,
) -> Optional[Tuple[str, int]]:
    """Return ``(path, version)`` for the first Java executable >= *min_version*.

    Returns ``None`` if no suitable JVM is found.

    Args:
        min_version: Minimum required major version (default 21).
        extra_home:  Optional JDK home directory to try first (e.g. from a
                     config file).  Equivalent to setting COMPREHENSITY_JAVA_HOME
                     but supplied programmatically.
    """
    seen: set = set()
    for candidate in _candidate_paths(extra_home=extra_home):
        if candidate in seen:
            continue
        seen.add(candidate)
        version = _java_version(candidate)
        if version is not None and version >= min_version:
            return candidate, version
    return None


def describe_java_candidates(
    extra_home: Optional[str] = None,
) -> List[Tuple[str, Optional[int]]]:
    """Return all reachable Java candidates with their detected major versions.

    Only candidates whose path exists on disk are included.
    Results are in search-priority order.

    Args:
        extra_home: Optional JDK home directory to include at highest priority.

    Returns:
        List of ``(path, version)`` tuples.  ``version`` is ``None`` if the
        binary could not be interrogated.
    """
    seen: set = set()
    results: List[Tuple[str, Optional[int]]] = []
    for candidate in _candidate_paths(extra_home=extra_home):
        if candidate in seen:
            continue
        seen.add(candidate)
        if Path(candidate).exists():
            results.append((candidate, _java_version(candidate)))
    return results


def format_candidates_log(candidates: List[Tuple[str, Optional[int]]]) -> str:
    """Format a candidate list as a compact human-readable string for log output."""
    if not candidates:
        return "none found"
    parts = []
    for path, version in candidates:
        parts.append(f"{path} (Java {version})" if version else path)
    return "; ".join(parts)
