"""
Tests for the extract_blueprint CLI entry point.
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from blueprint import Blueprint
import extract_blueprint as eb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(src))
    return p


def _run(args: list[str], monkeypatch) -> Blueprint:
    """Run extract_blueprint.main() with the given argv, return the Blueprint.
    Forces --format json so these tests are format-agnostic."""
    monkeypatch.setattr(sys, "argv", ["extract_blueprint"] + args + ["--format", "json"])
    eb.main()


# ---------------------------------------------------------------------------
# Basic invocation
# ---------------------------------------------------------------------------

class TestExtractBlueprintCLI:
    def test_default_output_filename(self, tmp_path, monkeypatch):
        """With no -o flag and --format json the output goes to blueprint.json in cwd."""
        _write(tmp_path, "main.py", "import os\n")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(sys, "argv", ["extract_blueprint", str(tmp_path), "--format", "json"])
        eb.main()

        out = tmp_path / "blueprint.json"
        assert out.exists()
        bp = Blueprint.from_json(out.read_text())
        assert len(bp.files) == 1

    def test_explicit_output_file(self, tmp_path, monkeypatch):
        _write(tmp_path, "app.py", "import sys\n")
        out = tmp_path / "out.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        assert len(bp.files) == 1
        assert bp.files[0].path == "app.py"

    def test_empty_directory(self, tmp_path, monkeypatch):
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        assert bp.files == []
        assert bp.externals == []
        assert bp.validate_refs() == []

    def test_output_is_valid_blueprint_json(self, tmp_path, monkeypatch):
        """Output contains format/version envelope and parses cleanly."""
        _write(tmp_path, "hello.py", "import os\nprint('hi')\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--extensions", ".py", "--format", "json"],
        )
        eb.main()

        raw = json.loads(out.read_text())
        assert raw["format"] == "comprehensity-blueprint"
        assert "version" in raw
        bp = Blueprint.from_json(out.read_text())
        assert bp.validate_refs() == []

    def test_extension_filter(self, tmp_path, monkeypatch):
        _write(tmp_path, "a.py", "x = 1\n")
        _write(tmp_path, "b.js", "const x = 1;\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--extensions", ".py", "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        assert len(bp.files) == 1
        assert bp.files[0].path == "a.py"

    def test_imports_resolved(self, tmp_path, monkeypatch):
        """C #include resolves to a local file entry in the blueprint."""
        _write(tmp_path, "main.c", '#include "utils.h"\nint main(){}\n')
        _write(tmp_path, "utils.h", "void helper();\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--extensions", ".c,.h", "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        by_path = {f.path: f for f in bp.files}
        assert "utils.h" in by_path
        assert by_path["utils.h"].id in by_path["main.c"].imports

    def test_symbols_present(self, tmp_path, monkeypatch):
        _write(tmp_path, "lib.py", "def foo(): pass\nclass Bar: pass\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--extensions", ".py", "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        names = {s.name for s in bp.symbols}
        assert "foo" in names
        assert "Bar" in names

    def test_invalid_directory_exits(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path / "nonexistent"), "-o", str(tmp_path / "bp.json")],
        )
        with pytest.raises(SystemExit) as exc:
            eb.main()
        assert exc.value.code != 0

    def test_modules_python_package(self, tmp_path, monkeypatch):
        """A Python package directory (has __init__.py) produces an L2 module."""
        _write(tmp_path, "mypkg/__init__.py", "")
        _write(tmp_path, "mypkg/core.py", "def run(): pass\n")
        _write(tmp_path, "mypkg/utils.py", "def helper(): pass\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            ["extract_blueprint", str(tmp_path), "-o", str(out), "--extensions", ".py", "--format", "json"],
        )
        eb.main()

        bp = Blueprint.from_json(out.read_text())
        assert len(bp.modules) >= 1
        pkg_module = next((m for m in bp.modules if m.level == "L2"), None)
        assert pkg_module is not None
        assert pkg_module.name == "mypkg"

    def test_experimental_concepts_flag_attaches_extension_payload(self, tmp_path, monkeypatch):
        _write(tmp_path, "auth/__init__.py", "")
        _write(tmp_path, "auth/session_store.py", "class SessionStore: pass\n")
        out = tmp_path / "bp.json"
        monkeypatch.setattr(
            sys, "argv",
            [
                "extract_blueprint",
                str(tmp_path),
                "-o",
                str(out),
                "--extensions",
                ".py",
                "--experimental-concepts",
                "--format",
                "json",
            ],
        )
        eb.main()

        raw = json.loads(out.read_text())
        assert "x-experimental" in raw
        payload = raw["x-experimental"]["comprehensity.concepts.v0"]
        assert payload["status"] == "complete"
        assert payload["cluster_count"] >= 1


# ---------------------------------------------------------------------------
# FileEntry.comment_desc — comment / docstring extraction
# ---------------------------------------------------------------------------

class TestFileEntryCommentDesc:
    """Tests for _read_comment_desc via the full extraction pipeline."""

    def _extract(self, tmp_path: Path, files: dict) -> Blueprint:
        """Write *files* (rel_path → content) and extract a blueprint."""
        out = tmp_path / "bp.json"
        for rel, src in files.items():
            _write(tmp_path, rel, src)
        import sys as _sys
        _sys.argv = ["extract_blueprint", str(tmp_path), "-o", str(out),
                     "--extensions", ".py,.js,.ts,.c,.h,.java", "--format", "json"]
        eb.main()
        return Blueprint.from_file(str(out))

    def _file(self, bp: Blueprint, name: str):
        return next(f for f in bp.files if f.path.endswith(name))

    def test_python_docstring_captured(self, tmp_path):
        bp = self._extract(tmp_path, {"mod.py": '"""HTTP routing module.\n\nDispatches requests."""\nimport os\n'})
        assert self._file(bp, "mod.py").comment_desc == "HTTP routing module.\n\nDispatches requests."

    def test_python_hash_comment_captured(self, tmp_path):
        bp = self._extract(tmp_path, {"util.py": "# Utility helpers\n# for file I/O\nimport os\n"})
        assert self._file(bp, "util.py").comment_desc == "Utility helpers\nfor file I/O"

    def test_js_line_comments_captured(self, tmp_path):
        bp = self._extract(tmp_path, {"index.js": "// Entry point\n// Sets up the server\nconst x = 1;\n"})
        assert self._file(bp, "index.js").comment_desc == "Entry point\nSets up the server"

    def test_c_block_comment_captured(self, tmp_path):
        bp = self._extract(tmp_path, {"main.c": "/* Main entry point.\n * Initialises everything.\n */\n#include <stdio.h>\n"})
        hdr = self._file(bp, "main.c").comment_desc
        assert "Main entry point" in hdr
        assert "Initialises everything" in hdr

    def test_no_comment_returns_none(self, tmp_path):
        bp = self._extract(tmp_path, {"bare.py": "import os\nx = 1\n"})
        assert self._file(bp, "bare.py").comment_desc is None

    def test_header_stops_at_first_code_line(self, tmp_path):
        bp = self._extract(tmp_path, {"mixed.py": "# Only this comment\nx = 1\n# Not this — code came first\n"})
        assert self._file(bp, "mixed.py").comment_desc == "Only this comment"

    def test_header_round_trips_through_json(self, tmp_path):
        bp = self._extract(tmp_path, {"doc.py": '"""Round-trip test."""\npass\n'})
        restored = Blueprint.from_json(bp.to_json())
        assert self._file(restored, "doc.py").comment_desc == "Round-trip test."


# ---------------------------------------------------------------------------
# _strip_phase2 unit tests
# ---------------------------------------------------------------------------

class TestStripPhase2:
    """_strip_phase2 must remove all LLM/Phase2 sections from raw TOML."""

    def _strip(self, toml: str):
        return eb._strip_phase2(textwrap.dedent(toml))

    def test_empty_returns_none(self):
        assert eb._strip_phase2("") is None

    def test_none_input_returns_none(self):
        # raw can be passed as empty string from load_config defaults
        assert eb._strip_phase2("") is None

    def test_scan_only_preserved(self):
        raw = "[scan]\nmax_depth = 10\n"
        assert self._strip(raw) == "[scan]\nmax_depth = 10"

    def test_strips_phase2_llm(self):
        raw = """\
            [scan]
            max_depth = 10

            [phase2.llm]
            backend = "ollama"
            api_key = "sk-secret"
        """
        result = self._strip(raw)
        assert "phase2" not in result
        assert "api_key" not in result
        assert "max_depth" in result

    def test_strips_phase2_token_budget(self):
        raw = """\
            [extract]
            foo = true

            [phase2.token_budget]
            max_tokens_per_run = 1000
        """
        result = self._strip(raw)
        assert "token_budget" not in result
        assert "max_tokens_per_run" not in result
        assert "foo" in result

    def test_strips_bare_llm_section(self):
        """Old flat [llm] section name must also be stripped (the bug)."""
        raw = """\
            [scan]
            max_depth = 5

            [llm]
            backend = "lmstudio"
            base_url = "http://127.0.0.1:1234"
            model = "phi-4"
            api_key = "sk-secret"
        """
        result = self._strip(raw)
        assert result is not None
        assert "[llm]" not in result
        assert "backend" not in result
        assert "api_key" not in result
        assert "max_depth" in result

    def test_strips_bare_token_budget_section(self):
        """Old flat [token_budget] section name must also be stripped."""
        raw = """\
            [extract]
            bar = 1

            [token_budget]
            max_tokens_per_run = 0
            report_usage = true
        """
        result = self._strip(raw)
        assert "[token_budget]" not in result
        assert "max_tokens_per_run" not in result
        assert "bar" in result

    def test_all_phase2_sections_stripped_leaves_none(self):
        """Config with only Phase 2 sections → None (nothing left to stamp)."""
        raw = """\
            [llm]
            backend = "ollama"

            [token_budget]
            max_tokens_per_run = 0
        """
        assert self._strip(raw) is None

    def test_sections_after_phase2_not_included(self):
        """A non-phase2 section appearing after a phase2 section is NOT restored."""
        # TOML sections are order-dependent; we strip once we see a phase2 header
        # and resume only when we see a non-phase2 header.
        raw = """\
            [scan]
            a = 1

            [phase2.llm]
            backend = "ollama"

            [extract]
            b = 2
        """
        result = self._strip(raw)
        assert "a" in result
        assert "backend" not in result
        assert "b" in result  # [extract] after [phase2.llm] should be restored
