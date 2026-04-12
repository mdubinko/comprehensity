"""
vcs.py — Static VCS metadata reader (stdlib only for commit data).

Reads git repository metadata directly from .git/ without invoking git for
commit info. Version detection uses a best-effort subprocess call to git.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import zlib
from pathlib import Path
from typing import Optional

from blueprint import VcsInfo


def _read_git_dir(root: Path) -> Optional[Path]:
    """Return the resolved .git directory, handling gitdir: file references.

    Covers regular repos, worktrees, and submodules where .git is a file
    pointing to the real git dir.
    """
    git_path = root / ".git"
    if not git_path.exists():
        return None
    if git_path.is_dir():
        return git_path
    # .git is a file — worktree or submodule
    try:
        content = git_path.read_text(encoding="utf-8").strip()
        if content.startswith("gitdir:"):
            target = Path(content[len("gitdir:"):].strip())
            if not target.is_absolute():
                target = root / target
            target = target.resolve()
            return target if target.is_dir() else None
    except OSError:
        pass
    return None


def _resolve_ref(git_dir: Path, ref: str) -> Optional[str]:
    """Resolve a git ref (e.g. 'refs/heads/main') to a 40-char commit hash.

    Checks loose ref file first, then falls back to packed-refs.
    """
    # Loose ref
    ref_path = git_dir / ref
    if ref_path.exists():
        try:
            return ref_path.read_text(encoding="utf-8").strip()
        except OSError:
            pass
    # Packed-refs fallback
    packed = git_dir / "packed-refs"
    if packed.exists():
        try:
            for line in packed.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("#") or line.startswith("^"):
                    continue
                parts = line.split()
                if len(parts) >= 2 and parts[1] == ref:
                    return parts[0]
        except OSError:
            pass
    return None


def _read_commit_timestamp(git_dir: Path, commit_hash: str) -> Optional[int]:
    """Read committer Unix timestamp from a loose git commit object.

    Returns None if the object file doesn't exist (e.g. packed objects) or
    cannot be parsed. Never raises.
    """
    if len(commit_hash) < 4:
        return None
    obj_path = git_dir / "objects" / commit_hash[:2] / commit_hash[2:]
    if not obj_path.exists():
        return None
    try:
        raw = zlib.decompress(obj_path.read_bytes())
        # Format: b"commit <size>\x00tree ...\nauthor ...\ncommitter Name <email> <ts> <tz>\n..."
        null_idx = raw.index(b"\x00")
        content = raw[null_idx + 1:].decode("utf-8", errors="replace")
        for line in content.splitlines():
            if line.startswith("committer "):
                # "committer Name <email> 1712345678 +0000"
                parts = line.rsplit(" ", 2)
                if len(parts) == 3:
                    return int(parts[1])
    except (OSError, zlib.error, ValueError, UnicodeDecodeError):
        pass
    return None


def _detect_git_version() -> Optional[str]:
    """Return the installed git version string (e.g. '2.44.0'), or None.

    Best-effort: returns None if git is not on PATH or the version cannot
    be parsed.
    """
    if not shutil.which("git"):
        return None
    try:
        proc = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        m = re.search(r"(\d+\.\d+\.\d+)", proc.stdout)
        return m.group(1) if m else None
    except Exception:
        return None


def read_git_info(root: Path) -> Optional[VcsInfo]:
    """Read VCS metadata from .git/ without invoking git for commit data.

    Returns a VcsInfo with scm='git', or None if no .git directory is found.

    vcs_branch is None for detached HEAD (typical for historical checkouts).
    vcs_timestamp reads the committer timestamp from the loose commit object;
    None when the object is packed (shallow clones, etc.).
    git_version is detected via a best-effort subprocess call to git --version.
    """
    git_dir = _read_git_dir(root)
    if git_dir is None:
        return None

    head_path = git_dir / "HEAD"
    if not head_path.exists():
        return None

    try:
        head_content = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    commit_hash: Optional[str] = None
    branch: Optional[str] = None

    if head_content.startswith("ref: "):
        ref = head_content[len("ref: "):]
        if ref.startswith("refs/heads/"):
            branch = ref[len("refs/heads/"):]
        commit_hash = _resolve_ref(git_dir, ref)
    elif len(head_content) == 40 and all(c in "0123456789abcdef" for c in head_content):
        # Detached HEAD — common for historical checkouts
        commit_hash = head_content

    timestamp = _read_commit_timestamp(git_dir, commit_hash) if commit_hash else None

    return VcsInfo(
        scm="git",
        vcs_ref=commit_hash,
        vcs_branch=branch,
        vcs_timestamp=timestamp,
        git_version=_detect_git_version(),
    )
