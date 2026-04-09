"""Tests for jvm_detect.py — JVM discovery and version parsing."""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from jvm_detect import (
    _parse_java_version,
    describe_java_candidates,
    find_java,
    format_candidates_log,
)


# ---------------------------------------------------------------------------
# _parse_java_version
# ---------------------------------------------------------------------------

class TestParseJavaVersion:
    def test_modern_version(self):
        out = 'openjdk version "21.0.2" 2024-01-16\n'
        assert _parse_java_version(out) == 21

    def test_java_25(self):
        out = 'openjdk version "25" 2025-09-16\n'
        assert _parse_java_version(out) == 25

    def test_legacy_java_8(self):
        out = 'java version "1.8.0_381"\nJava(TM) SE Runtime...'
        assert _parse_java_version(out) == 8

    def test_legacy_java_11(self):
        out = 'openjdk version "11.0.20" 2023-07-18\n'
        assert _parse_java_version(out) == 11

    def test_legacy_java_17(self):
        out = 'openjdk version "17.0.8" 2023-07-18\n'
        assert _parse_java_version(out) == 17

    def test_unparseable_returns_none(self):
        assert _parse_java_version("something with no version") is None

    def test_empty_string_returns_none(self):
        assert _parse_java_version("") is None


# ---------------------------------------------------------------------------
# find_java — version filtering
# ---------------------------------------------------------------------------

class TestFindJava:
    def _fake_run(self, version_str: str):
        """Return a subprocess.run side-effect that emits a fake java -version."""
        import subprocess
        result = type("R", (), {"stderr": version_str, "stdout": ""})()

        def _run(cmd, **kwargs):
            return result

        return _run

    def test_returns_none_when_no_candidates(self, tmp_path):
        # Patch _candidate_paths to return a non-existent path
        with patch("jvm_detect._candidate_paths", return_value=[]):
            assert find_java(min_version=21) is None

    def test_finds_java_21(self, tmp_path):
        fake_java = tmp_path / "bin" / "java"
        fake_java.parent.mkdir(parents=True)
        fake_java.touch()
        version_output = 'openjdk version "21.0.2" 2024-01-16\n'

        with patch("jvm_detect._candidate_paths", return_value=[str(fake_java)]), \
             patch("jvm_detect.subprocess.run", side_effect=self._fake_run(version_output)):
            result = find_java(min_version=21)

        assert result is not None
        path, version = result
        assert str(fake_java) == path
        assert version == 21

    def test_skips_java_17_for_min_21(self, tmp_path):
        fake_java = tmp_path / "bin" / "java"
        fake_java.parent.mkdir(parents=True)
        fake_java.touch()
        version_output = 'openjdk version "17.0.8" 2023-07-18\n'

        with patch("jvm_detect._candidate_paths", return_value=[str(fake_java)]), \
             patch("jvm_detect.subprocess.run", side_effect=self._fake_run(version_output)):
            assert find_java(min_version=21) is None

    def test_extra_home_inserted_first(self, tmp_path):
        extra = tmp_path / "extra_jdk"
        extra.mkdir()
        (extra / "bin").mkdir()
        (extra / "bin" / "java").touch()

        paths_seen = []

        original = __import__("jvm_detect")._candidate_paths

        def capturing_candidates(extra_home=None):
            result = original(extra_home=extra_home)
            paths_seen.extend(result)
            return result

        with patch("jvm_detect._candidate_paths", side_effect=capturing_candidates), \
             patch("jvm_detect.subprocess.run",
                   side_effect=self._fake_run('openjdk version "21.0.1"')):
            find_java(min_version=21, extra_home=str(extra))

        # The extra_home bin/java should appear before env-var candidates
        assert str(extra / "bin" / "java") in paths_seen
        assert paths_seen[0] == str(extra / "bin" / "java")


# ---------------------------------------------------------------------------
# describe_java_candidates
# ---------------------------------------------------------------------------

class TestDescribeJavaCandidates:
    def test_returns_list_of_tuples(self, tmp_path):
        fake_java = tmp_path / "bin" / "java"
        fake_java.parent.mkdir(parents=True)
        fake_java.touch()
        version_output = 'openjdk version "17.0.8" 2023-07-18\n'

        with patch("jvm_detect._candidate_paths", return_value=[str(fake_java)]), \
             patch("jvm_detect.subprocess.run",
                   side_effect=lambda cmd, **kw: type("R", (), {
                       "stderr": version_output, "stdout": ""
                   })()):
            candidates = describe_java_candidates()

        assert len(candidates) >= 1
        path, version = candidates[0]
        assert path == str(fake_java)
        assert version == 17

    def test_missing_file_excluded(self, tmp_path):
        ghost = str(tmp_path / "ghost" / "java")
        with patch("jvm_detect._candidate_paths", return_value=[ghost]):
            candidates = describe_java_candidates()
        assert all(str(tmp_path / "ghost" / "java") != p for p, _ in candidates)

    def test_no_duplicates(self, tmp_path):
        fake_java = tmp_path / "bin" / "java"
        fake_java.parent.mkdir(parents=True)
        fake_java.touch()

        with patch("jvm_detect._candidate_paths",
                   return_value=[str(fake_java), str(fake_java)]), \
             patch("jvm_detect.subprocess.run",
                   side_effect=lambda cmd, **kw: type("R", (), {
                       "stderr": 'openjdk version "21"', "stdout": ""
                   })()):
            candidates = describe_java_candidates()

        paths = [p for p, _ in candidates]
        assert len(paths) == len(set(paths))


# ---------------------------------------------------------------------------
# format_candidates_log
# ---------------------------------------------------------------------------

class TestFormatCandidatesLog:
    def test_empty_returns_none_found(self):
        assert format_candidates_log([]) == "none found"

    def test_with_version(self):
        result = format_candidates_log([("/usr/bin/java", 17)])
        assert "Java 17" in result
        assert "/usr/bin/java" in result

    def test_without_version(self):
        result = format_candidates_log([("/usr/bin/java", None)])
        assert "/usr/bin/java" in result

    def test_multiple_separated_by_semicolons(self):
        result = format_candidates_log([("/a/java", 17), ("/b/java", 21)])
        assert "; " in result
