"""Tests for clone_detection.sarif_to_clone_blocks and run_treepeat.

All tests use hand-crafted SARIF dicts written to tmp_path — no subprocess.
Fixture files in tests/fixtures/clone/ provide real content for hash tests.
"""

import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import clone_detection

from clone_detection import (
    RULESET_TO_KIND,
    CloneDetectionUnavailable,
    run_treepeat,
    sarif_to_clone_blocks,
)

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "clone"
PATH_A = str(FIXTURE_DIR / "a.py")
PATH_B = str(FIXTURE_DIR / "b.py")
PATH_C = str(FIXTURE_DIR / "c.py")

FILE_ID_MAP = {
    PATH_A: "src/a.py",
    PATH_B: "src/b.py",
    PATH_C: "src/c.py",
}

# Lines 1-5 of each fixture file (identical content)
REGION_LINES = 5


def write_sarif(tmp_path: Path, results: list) -> Path:
    sarif = {"runs": [{"results": results}]}
    p = tmp_path / "out.sarif"
    p.write_text(json.dumps(sarif), encoding="utf-8")
    return p


def make_result(regions: list) -> dict:
    return {
        "rule_id": "similar-code",
        "properties": {
            "similarity": 1.0,
            "similarityPercent": 100.0,
            "groupSize": len(regions),
            "regions": regions,
        },
    }


def region(path: str, start: int = 1, end: int = 5, lines: int = 5, name: str = "compute_total") -> dict:
    return {
        "path": path,
        "startLine": start,
        "endLine": end,
        "lines": lines,
        "type": "function_definition",
        "name": name,
    }


# ---------------------------------------------------------------------------
# Basic construction
# ---------------------------------------------------------------------------

class TestSarifToCloneBlocksBasic:
    def test_single_pair_returns_one_block(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert len(blocks) == 1

    def test_empty_results_returns_empty(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks == []

    def test_no_runs_returns_empty(self, tmp_path):
        sarif_path = tmp_path / "empty.sarif"
        sarif_path.write_text(json.dumps({}), encoding="utf-8")
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks == []

    def test_single_region_skipped(self, tmp_path):
        """A result with only one region is not a clone — must be skipped."""
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks == []


# ---------------------------------------------------------------------------
# Absolute path → file_id conversion
# ---------------------------------------------------------------------------

class TestAbsolutePathConversion:
    def test_file_ids_set_correctly(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        ids = {inst.file_id for inst in blocks[0].instances}
        assert ids == {"src/a.py", "src/b.py"}

    def test_unknown_path_excluded(self, tmp_path):
        """Regions whose paths are not in file_id_map are silently dropped."""
        unknown = "/nonexistent/ghost.py"
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region(PATH_B), region(unknown)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert len(blocks) == 1
        file_ids = {inst.file_id for inst in blocks[0].instances}
        assert "ghost.py" not in str(file_ids)
        assert len(blocks[0].instances) == 2

    def test_all_unknown_paths_skipped(self, tmp_path):
        """If all regions resolve to unknown paths, block is dropped entirely."""
        sarif_path = write_sarif(tmp_path, [
            make_result([region("/x/a.py"), region("/x/b.py")])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks == []

    def test_one_of_two_unknown_skipped(self, tmp_path):
        """If only one region is resolvable, the result (< 2 instances) is skipped."""
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region("/x/ghost.py")])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks == []


# ---------------------------------------------------------------------------
# Multi-instance groups
# ---------------------------------------------------------------------------

class TestMultiInstanceGroups:
    def test_three_instances(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region(PATH_B), region(PATH_C)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert len(blocks[0].instances) == 3

    def test_two_results_two_blocks(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region(PATH_B)]),
            make_result([region(PATH_A, 1, 5), region(PATH_C, 1, 5)]),
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert len(blocks) == 2


# ---------------------------------------------------------------------------
# Hash computation
# ---------------------------------------------------------------------------

class TestHashComputation:
    def test_all_instances_share_hash(self, tmp_path):
        """All instances in a CloneBlock must have the same hash."""
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region(PATH_B)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        hashes = {inst.hash for inst in blocks[0].instances}
        assert len(hashes) == 1

    def test_hash_is_64_char_hex(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        h = blocks[0].instances[0].hash
        assert len(h) == 64
        assert all(c in "0123456789abcdef" for c in h)

    def test_hash_matches_normalized_content(self, tmp_path):
        """Hash equals SHA-256 of the stripped lines of the first region."""
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        lines = Path(PATH_A).read_text().splitlines()[0:5]
        expected = hashlib.sha256(
            "\n".join(l.strip() for l in lines).encode()
        ).hexdigest()
        assert blocks[0].instances[0].hash == expected

    def test_nonexistent_path_falls_back_to_coordinate_hash(self, tmp_path):
        """_hash_region falls back gracefully when the file doesn't exist."""
        ghost = "/nonexistent/ghost.py"
        ghost2 = "/nonexistent/ghost2.py"
        ghost_map = {ghost: "src/ghost.py", ghost2: "src/ghost2.py"}
        sarif_path = write_sarif(tmp_path, [
            make_result([region(ghost), region(ghost2)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, ghost_map, "none")
        assert len(blocks) == 1
        h = blocks[0].instances[0].hash
        assert len(h) == 64


# ---------------------------------------------------------------------------
# Stable ID assignment
# ---------------------------------------------------------------------------

class TestStableIdAssignment:
    def test_ids_are_dup_n(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A), region(PATH_B)]),
            make_result([region(PATH_A, 1, 5), region(PATH_C, 1, 5)]),
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert [b.id for b in blocks] == ["dup_0", "dup_1"]

    def test_ids_sorted_by_first_instance_file_id(self, tmp_path):
        """Blocks are sorted by (first_instance_file_id, start_line)."""
        # Result order in SARIF is C,B then A,B — output should be A first
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_C), region(PATH_B)]),
            make_result([region(PATH_A), region(PATH_B)]),
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        # src/a.py < src/b.py < src/c.py lexicographically
        assert blocks[0].instances[0].file_id == "src/a.py"
        assert blocks[0].id == "dup_0"

    def test_instances_within_block_sorted(self, tmp_path):
        """Instances within a block are sorted by (file_id, start_line)."""
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_C), region(PATH_A), region(PATH_B)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        file_ids = [inst.file_id for inst in blocks[0].instances]
        assert file_ids == sorted(file_ids)


# ---------------------------------------------------------------------------
# lines / tokens counts
# ---------------------------------------------------------------------------

class TestLinesCounts:
    def test_lines_from_region(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [
            make_result([region(PATH_A, end=10, lines=10), region(PATH_B, end=10, lines=10)])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks[0].lines == 10

    def test_tokens_is_zero(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks[0].tokens == 0


# ---------------------------------------------------------------------------
# Ruleset → kind mapping
# ---------------------------------------------------------------------------

class TestRulesetToKind:
    @pytest.mark.parametrize("ruleset,expected_kind", list(RULESET_TO_KIND.items()))
    def test_ruleset_kind_mapping(self, tmp_path, ruleset, expected_kind):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, ruleset)
        assert blocks[0].kind == expected_kind

    def test_unknown_ruleset_defaults_to_exact(self, tmp_path):
        sarif_path = write_sarif(tmp_path, [make_result([region(PATH_A), region(PATH_B)])])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "unknown_ruleset")
        assert blocks[0].kind == "exact"


# ---------------------------------------------------------------------------
# run_treepeat subprocess wrapper
# ---------------------------------------------------------------------------

FAKE_BINARY = "/usr/local/bin/treepeat"


def _make_fake_popen(tmp_path: Path, sarif_results: list):
    """Return a subprocess.Popen stub that writes a canned SARIF to the -o path."""
    def fake_popen(cmd, **kwargs):
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        def communicate(timeout=None):
            idx = cmd.index("-o")
            out_path = Path(cmd[idx + 1])
            sarif = {"runs": [{"results": sarif_results}]}
            out_path.write_text(json.dumps(sarif), encoding="utf-8")
            return b"", b""
        mock_proc.communicate.side_effect = communicate
        return mock_proc
    return fake_popen


class TestRunTreepeat:
    def test_raises_when_binary_missing(self, tmp_path):
        """CloneDetectionUnavailable is raised when treepeat is not on PATH."""
        with patch("clone_detection._find_treepeat_binary", return_value=None):
            with pytest.raises(CloneDetectionUnavailable, match="treepeat"):
                run_treepeat(tmp_path)

    def test_returns_empty_list_when_no_clones(self, tmp_path):
        fake_popen = _make_fake_popen(tmp_path, sarif_results=[])
        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=fake_popen):
            blocks, timed_out = run_treepeat(tmp_path, ruleset="none")
        assert blocks == []
        assert timed_out is False

    def test_returns_clone_blocks_from_sarif(self, tmp_path):
        """CloneBlocks are constructed from the SARIF written by treepeat."""
        # Create real files so _hash_region can read them
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        content = "\n".join(f"line{i}" for i in range(10))
        a.write_text(content)
        b.write_text(content)

        results = [make_result([
            region(str(a), 1, 5),
            region(str(b), 1, 5),
        ])]
        fake_popen = _make_fake_popen(tmp_path, sarif_results=results)

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=fake_popen):
            blocks, timed_out = run_treepeat(tmp_path, ruleset="none")

        assert len(blocks) == 1
        assert blocks[0].id == "dup_0"
        assert timed_out is False

    def test_ruleset_forwarded_to_cmd(self, tmp_path):
        """The ruleset arg appears in the subprocess command."""
        captured = []
        fake_popen = _make_fake_popen(tmp_path, sarif_results=[])

        def capturing_popen(cmd, **kwargs):
            captured.extend(cmd)
            return fake_popen(cmd, **kwargs)

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=capturing_popen):
            run_treepeat(tmp_path, ruleset="default")

        assert "-r" in captured
        assert "default" in captured

    def test_min_lines_forwarded_to_cmd(self, tmp_path):
        """--min-lines value is forwarded to treepeat."""
        captured = []
        fake_popen = _make_fake_popen(tmp_path, sarif_results=[])

        def capturing_popen(cmd, **kwargs):
            captured.extend(cmd)
            return fake_popen(cmd, **kwargs)

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=capturing_popen):
            run_treepeat(tmp_path, min_lines=15)

        assert "--min-lines" in captured
        assert "15" in captured

    def test_ignore_patterns_forwarded_to_cmd(self, tmp_path):
        """Each ignore pattern appears after --ignore in the command."""
        captured = []
        fake_popen = _make_fake_popen(tmp_path, sarif_results=[])

        def capturing_popen(cmd, **kwargs):
            captured.extend(cmd)
            return fake_popen(cmd, **kwargs)

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=capturing_popen):
            run_treepeat(tmp_path, ignore_patterns=["**/.venv/**", "**/node_modules/**"])

        assert captured.count("--ignore") == 1
        ignore_val = captured[captured.index("--ignore") + 1]
        assert "**/.venv/**" in ignore_val
        assert "**/node_modules/**" in ignore_val

    def test_sarif_tempfile_cleaned_up(self, tmp_path, monkeypatch):
        """The temporary SARIF file is deleted after translation."""
        created_paths: list[Path] = []
        original_ntf = tempfile.NamedTemporaryFile

        def tracking_ntf(**kwargs):
            ctx = original_ntf(**kwargs)
            created_paths.append(Path(ctx.name))
            return ctx

        fake_popen = _make_fake_popen(tmp_path, sarif_results=[])

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=fake_popen), \
             patch("clone_detection.tempfile.NamedTemporaryFile", side_effect=tracking_ntf):
            run_treepeat(tmp_path)

        assert created_paths, "Expected at least one temp file to be created"
        for p in created_paths:
            assert not p.exists(), f"Temp file not cleaned up: {p}"

    def test_custom_file_id_map_used(self, tmp_path):
        """If file_id_map is provided, it is used instead of the auto-built one."""
        a = tmp_path / "a.py"
        b = tmp_path / "b.py"
        a.write_text("x = 1\n" * 10)
        b.write_text("x = 1\n" * 10)

        custom_map = {str(a): "custom/a.py", str(b): "custom/b.py"}
        results = [make_result([region(str(a), 1, 5), region(str(b), 1, 5)])]
        fake_popen = _make_fake_popen(tmp_path, sarif_results=results)

        with patch("clone_detection.shutil.which", return_value=FAKE_BINARY), \
             patch("clone_detection.subprocess.Popen", side_effect=fake_popen):
            blocks, _ = run_treepeat(tmp_path, file_id_map=custom_map)

        file_ids = {inst.file_id for inst in blocks[0].instances}
        assert file_ids == {"custom/a.py", "custom/b.py"}


# ---------------------------------------------------------------------------
# Boilerplate clone tagging
# ---------------------------------------------------------------------------

class TestBoilerplateFilter:
    """sarif_to_clone_blocks tags clones whose region names match Java boilerplate."""

    def _write_and_parse(self, tmp_path, name_a, name_b, ruleset="loose"):
        sarif_path = write_sarif(tmp_path, [
            make_result([
                region(PATH_A, name=name_a),
                region(PATH_B, name=name_b),
            ])
        ])
        return sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, ruleset)

    # --- should become "boilerplate" ---

    def test_getter_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "getName", "getName")
        assert blocks[0].kind == "boilerplate"

    def test_setter_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "setName", "setName")
        assert blocks[0].kind == "boilerplate"

    def test_boolean_accessor_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "isActive", "isActive")
        assert blocks[0].kind == "boilerplate"

    def test_equals_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "equals", "equals")
        assert blocks[0].kind == "boilerplate"

    def test_hashcode_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "hashCode", "hashCode")
        assert blocks[0].kind == "boilerplate"

    def test_tostring_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "toString", "toString")
        assert blocks[0].kind == "boilerplate"

    def test_builder_with_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "withName", "withName")
        assert blocks[0].kind == "boilerplate"

    def test_build_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "build", "build")
        assert blocks[0].kind == "boilerplate"

    def test_setup_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "setUp", "setUp")
        assert blocks[0].kind == "boilerplate"

    def test_teardown_tagged_boilerplate(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "tearDown", "tearDown")
        assert blocks[0].kind == "boilerplate"

    # --- should NOT become "boilerplate" ---

    def test_non_boilerplate_keeps_ruleset_kind(self, tmp_path):
        blocks = self._write_and_parse(tmp_path, "compute_total", "compute_total",
                                       ruleset="loose")
        assert blocks[0].kind == "approximate"

    def test_mixed_names_not_boilerplate(self, tmp_path):
        """If only some regions are boilerplate names, don't tag the whole group."""
        sarif_path = write_sarif(tmp_path, [
            make_result([
                region(PATH_A, name="getName"),
                region(PATH_B, name="processOrder"),
            ])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "loose")
        assert blocks[0].kind == "approximate"

    def test_empty_name_not_boilerplate(self, tmp_path):
        """Regions with no name field don't trigger boilerplate tagging."""
        sarif_path = write_sarif(tmp_path, [
            make_result([
                {**region(PATH_A), "name": ""},
                {**region(PATH_B), "name": ""},
            ])
        ])
        blocks = sarif_to_clone_blocks(sarif_path, FILE_ID_MAP, "none")
        assert blocks[0].kind == "exact"

    def test_boilerplate_overrides_ruleset_kind(self, tmp_path):
        """Boilerplate tag takes precedence over the ruleset-derived kind."""
        blocks = self._write_and_parse(tmp_path, "hashCode", "hashCode",
                                       ruleset="none")
        assert blocks[0].kind == "boilerplate"


# ---------------------------------------------------------------------------
# run_treepeat integration (skipped when treepeat not installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    clone_detection._find_treepeat_binary() is None,
    reason="treepeat not installed",
)
class TestRunTreepeatIntegration:
    def test_runs_against_clone_fixtures(self):
        """run_treepeat produces CloneBlocks on the real clone fixture directory."""
        fixture_root = FIXTURE_DIR
        blocks, timed_out = run_treepeat(fixture_root, ruleset="none", min_lines=3)
        # a.py, b.py, c.py all share identical content — at least one clone expected
        assert len(blocks) >= 1
        assert all(b.id.startswith("dup_") for b in blocks)
        assert timed_out is False
