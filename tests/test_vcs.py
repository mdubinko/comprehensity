"""
Tests for vcs.py — static git metadata reader.
"""
from __future__ import annotations

import zlib
from pathlib import Path

import pytest

from blueprint import VcsInfo
from vcs import (
    _read_git_dir,
    _resolve_ref,
    _read_commit_timestamp,
    read_git_info,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_loose_ref(git_dir: Path, ref: str, commit_hash: str) -> None:
    """Write a loose ref file under git_dir."""
    ref_path = git_dir / ref
    ref_path.parent.mkdir(parents=True, exist_ok=True)
    ref_path.write_text(commit_hash + "\n", encoding="utf-8")


def _make_commit_object(git_dir: Path, commit_hash: str, timestamp: int) -> None:
    """Write a minimal zlib-compressed commit object for the given hash."""
    content = (
        f"tree deadbeefdeadbeefdeadbeefdeadbeefdeadbeef\n"
        f"author A U Thor <a@example.com> {timestamp} +0000\n"
        f"committer C O Mitter <c@example.com> {timestamp} +0000\n"
        f"\nInitial commit\n"
    ).encode()
    header = f"commit {len(content)}\x00".encode()
    raw = zlib.compress(header + content)
    obj_path = git_dir / "objects" / commit_hash[:2] / commit_hash[2:]
    obj_path.parent.mkdir(parents=True, exist_ok=True)
    obj_path.write_bytes(raw)


# ---------------------------------------------------------------------------
# _read_git_dir
# ---------------------------------------------------------------------------

class TestReadGitDir:
    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        assert _read_git_dir(tmp_path) is None

    def test_returns_git_dir_when_dir(self, tmp_path: Path) -> None:
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        assert _read_git_dir(tmp_path) == git_dir

    def test_resolves_gitdir_file(self, tmp_path: Path) -> None:
        real_git = tmp_path / "actual_git"
        real_git.mkdir()
        git_file = tmp_path / ".git"
        git_file.write_text(f"gitdir: {real_git}\n", encoding="utf-8")
        assert _read_git_dir(tmp_path) == real_git

    def test_returns_none_for_broken_gitdir_file(self, tmp_path: Path) -> None:
        git_file = tmp_path / ".git"
        git_file.write_text("gitdir: /nonexistent/path\n", encoding="utf-8")
        assert _read_git_dir(tmp_path) is None


# ---------------------------------------------------------------------------
# _resolve_ref
# ---------------------------------------------------------------------------

class TestResolveRef:
    HASH = "a" * 40

    def test_loose_ref(self, tmp_path: Path) -> None:
        _make_loose_ref(tmp_path, "refs/heads/main", self.HASH)
        assert _resolve_ref(tmp_path, "refs/heads/main") == self.HASH

    def test_packed_refs_fallback(self, tmp_path: Path) -> None:
        packed = tmp_path / "packed-refs"
        packed.write_text(
            f"# pack-refs with: peeled fully-peeled sorted\n"
            f"{self.HASH} refs/heads/main\n",
            encoding="utf-8",
        )
        assert _resolve_ref(tmp_path, "refs/heads/main") == self.HASH

    def test_missing_ref_returns_none(self, tmp_path: Path) -> None:
        assert _resolve_ref(tmp_path, "refs/heads/nonexistent") is None

    def test_loose_ref_takes_precedence_over_packed(self, tmp_path: Path) -> None:
        loose_hash = "b" * 40
        packed_hash = "c" * 40
        _make_loose_ref(tmp_path, "refs/heads/main", loose_hash)
        packed = tmp_path / "packed-refs"
        packed.write_text(f"{packed_hash} refs/heads/main\n", encoding="utf-8")
        assert _resolve_ref(tmp_path, "refs/heads/main") == loose_hash

    def test_skips_peeled_lines_in_packed_refs(self, tmp_path: Path) -> None:
        packed = tmp_path / "packed-refs"
        packed.write_text(
            f"{self.HASH} refs/heads/main\n"
            f"^{'d' * 40}\n",
            encoding="utf-8",
        )
        assert _resolve_ref(tmp_path, "refs/heads/main") == self.HASH


# ---------------------------------------------------------------------------
# _read_commit_timestamp
# ---------------------------------------------------------------------------

class TestReadCommitTimestamp:
    HASH = "1234567890abcdef1234567890abcdef12345678"
    TS = 1712345678

    def test_reads_timestamp_from_loose_object(self, tmp_path: Path) -> None:
        _make_commit_object(tmp_path, self.HASH, self.TS)
        assert _read_commit_timestamp(tmp_path, self.HASH) == self.TS

    def test_returns_none_when_object_missing(self, tmp_path: Path) -> None:
        assert _read_commit_timestamp(tmp_path, self.HASH) is None

    def test_returns_none_for_short_hash(self, tmp_path: Path) -> None:
        assert _read_commit_timestamp(tmp_path, "abc") is None


# ---------------------------------------------------------------------------
# read_git_info
# ---------------------------------------------------------------------------

class TestReadGitInfo:
    HASH = "fedcba9876543210fedcba9876543210fedcba98"
    TS = 1700000000

    def _make_repo(self, root: Path, *, branch: str = "main", detached: bool = False) -> Path:
        git_dir = root / ".git"
        git_dir.mkdir()
        (git_dir / "objects").mkdir()
        _make_loose_ref(git_dir, f"refs/heads/{branch}", self.HASH)
        _make_commit_object(git_dir, self.HASH, self.TS)
        head = git_dir / "HEAD"
        if detached:
            head.write_text(self.HASH + "\n", encoding="utf-8")
        else:
            head.write_text(f"ref: refs/heads/{branch}\n", encoding="utf-8")
        return git_dir

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        assert read_git_info(tmp_path) is None

    def test_normal_branch(self, tmp_path: Path) -> None:
        self._make_repo(tmp_path, branch="main")
        info = read_git_info(tmp_path)
        assert info is not None
        assert info.scm == "git"
        assert info.vcs_ref == self.HASH
        assert info.vcs_branch == "main"
        assert info.vcs_timestamp == self.TS

    def test_detached_head(self, tmp_path: Path) -> None:
        self._make_repo(tmp_path, detached=True)
        info = read_git_info(tmp_path)
        assert info is not None
        assert info.scm == "git"
        assert info.vcs_ref == self.HASH
        assert info.vcs_branch is None  # detached HEAD has no branch

    def test_feature_branch_name(self, tmp_path: Path) -> None:
        self._make_repo(tmp_path, branch="feature/my-feature")
        info = read_git_info(tmp_path)
        assert info is not None
        assert info.vcs_branch == "feature/my-feature"

    def test_returns_vcs_info_type(self, tmp_path: Path) -> None:
        self._make_repo(tmp_path)
        info = read_git_info(tmp_path)
        assert isinstance(info, VcsInfo)

    def test_live_repo(self) -> None:
        """Smoke test against this repository's own .git."""
        repo_root = Path(__file__).parent.parent
        info = read_git_info(repo_root)
        # This repo has a .git dir; should return valid VcsInfo
        assert info is not None
        assert info.scm == "git"
        assert info.vcs_ref is None or len(info.vcs_ref) == 40
        # Branch may be None if in detached HEAD state (e.g. CI), that's fine


# ---------------------------------------------------------------------------
# Blueprint round-trip with vcs field
# ---------------------------------------------------------------------------

class TestBlueprintVcsRoundTrip:
    def test_json_round_trip(self) -> None:
        from blueprint import Blueprint
        vcs = VcsInfo(
            scm="git",
            vcs_ref="a" * 40,
            vcs_branch="main",
            vcs_timestamp=1712345678,
            git_version="2.44.0",
        )
        bp = Blueprint(vcs=vcs)
        restored = Blueprint.from_json(bp.to_json())
        assert restored.vcs is not None
        assert restored.vcs.scm == "git"
        assert restored.vcs.vcs_ref == "a" * 40
        assert restored.vcs.vcs_branch == "main"
        assert restored.vcs.vcs_timestamp == 1712345678
        assert restored.vcs.git_version == "2.44.0"

    def test_json_round_trip_none_vcs(self) -> None:
        from blueprint import Blueprint
        bp = Blueprint()
        restored = Blueprint.from_json(bp.to_json())
        assert restored.vcs is None

    def test_yaml_round_trip(self) -> None:
        from blueprint import Blueprint
        vcs = VcsInfo(
            scm="git",
            vcs_ref="b" * 40,
            vcs_branch="develop",
            vcs_timestamp=1700000000,
            git_version="2.39.0",
        )
        bp = Blueprint(vcs=vcs)
        bp.summary = bp.compute_summary()
        restored = Blueprint.from_yaml(bp.to_yaml())
        assert restored.vcs is not None
        assert restored.vcs.scm == "git"
        assert restored.vcs.vcs_branch == "develop"
        assert restored.vcs.vcs_timestamp == 1700000000

    def test_yaml_round_trip_none_vcs(self) -> None:
        from blueprint import Blueprint
        bp = Blueprint()
        bp.summary = bp.compute_summary()
        restored = Blueprint.from_yaml(bp.to_yaml())
        assert restored.vcs is None
