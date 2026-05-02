"""Tests for blueprint_io.py — SourceGraph ↔ Blueprint conversions."""

import shutil
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
import clone_detection
from blueprint import Blueprint, CURRENT_VERSION, ExternalEntry, FileEntry
from blueprint_io import blueprint_to_sourcegraph, sourcegraph_to_blueprint
from srcgraph import SourceGraph
from scan import build_source_graph

CLONE_EXACT_FIXTURE = Path(__file__).parent / "fixtures" / "repos" / "clone_exact"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_sg(*files):
    """Build a SourceGraph from (path, size, ext) tuples."""
    sg = SourceGraph(root_path="/root")
    for path, size, ext in files:
        sg.add_file(path, size, ext)
    return sg


# ---------------------------------------------------------------------------
# sourcegraph_to_blueprint
# ---------------------------------------------------------------------------

class TestSourcegraphToBlueprint:
    def test_empty_graph(self):
        bp = sourcegraph_to_blueprint(SourceGraph())
        assert bp.files == []
        assert bp.externals == []

    def test_single_file_no_imports(self):
        sg = make_sg(("/src/main.py", 100, ".py"))
        bp = sourcegraph_to_blueprint(sg)
        assert len(bp.files) == 1
        fe = bp.files[0]
        assert fe.id == "f0"
        assert fe.path == "/src/main.py"
        assert fe.size_bytes == 100
        assert fe.ext == ".py"
        assert fe.imports == []
        assert bp.externals == []

    def test_ids_are_sorted_by_path(self):
        sg = make_sg(("/z.py", 1, ".py"), ("/a.py", 2, ".py"), ("/m.py", 3, ".py"))
        bp = sourcegraph_to_blueprint(sg)
        paths = [f.path for f in bp.files]
        assert paths == sorted(paths)
        assert bp.files[0].id == "f0"
        assert bp.files[1].id == "f1"
        assert bp.files[2].id == "f2"

    def test_internal_import(self):
        sg = make_sg(("/a.py", 10, ".py"), ("/b.py", 20, ".py"))
        sg.add_import("/a.py", "/b.py")
        bp = sourcegraph_to_blueprint(sg)
        a = next(f for f in bp.files if f.path == "/a.py")
        b = next(f for f in bp.files if f.path == "/b.py")
        assert b.id in a.imports
        assert a.imports == [b.id]
        assert bp.externals == []

    def test_external_import_unknown_kind(self):
        sg = make_sg(("/a.py", 10, ".py"))
        sg._files["/a.py"].imports.add("numpy")
        bp = sourcegraph_to_blueprint(sg)
        assert len(bp.externals) == 1
        ext = bp.externals[0]
        assert ext.id == "ext_numpy"
        assert ext.name == "numpy"
        assert ext.kind == "unknown"
        assert bp.files[0].imports == ["ext_numpy"]

    def test_external_kind_from_import_details_system(self):
        sg = make_sg(("/a.py", 10, ".py"))
        sg._files["/a.py"].imports.add("os")
        sg._files["/a.py"].metadata["import_details"] = [
            {"imported_name": "os", "import_type": "system",
             "raw_statement": "import os", "line_number": 1, "resolved_path": None}
        ]
        bp = sourcegraph_to_blueprint(sg)
        ext = bp.externals[0]
        assert ext.kind == "system"

    def test_external_kind_from_import_details_package(self):
        sg = make_sg(("/a.py", 10, ".py"))
        sg._files["/a.py"].imports.add("numpy")
        sg._files["/a.py"].metadata["import_details"] = [
            {"imported_name": "numpy", "import_type": "external",
             "raw_statement": "import numpy", "line_number": 1, "resolved_path": None}
        ]
        bp = sourcegraph_to_blueprint(sg)
        ext = bp.externals[0]
        assert ext.kind == "package"

    def test_external_kind_from_resolved_path(self):
        """import_details resolved_path matches the import string."""
        sg = make_sg(("/a.py", 10, ".py"))
        sg._files["/a.py"].imports.add("os")
        sg._files["/a.py"].metadata["import_details"] = [
            {"imported_name": "something_else", "import_type": "system",
             "raw_statement": "import os", "line_number": 1, "resolved_path": "os"}
        ]
        bp = sourcegraph_to_blueprint(sg)
        assert bp.externals[0].kind == "system"

    def test_shared_external_deduped(self):
        """Two files importing the same external produce one ExternalEntry."""
        sg = make_sg(("/a.py", 10, ".py"), ("/b.py", 20, ".py"))
        sg._files["/a.py"].imports.add("os")
        sg._files["/b.py"].imports.add("os")
        bp = sourcegraph_to_blueprint(sg)
        assert len(bp.externals) == 1
        assert bp.externals[0].id == "ext_os"

    def test_mixed_imports(self):
        sg = make_sg(("/a.py", 10, ".py"), ("/b.py", 20, ".py"))
        sg.add_import("/a.py", "/b.py")
        sg._files["/a.py"].imports.add("os")
        bp = sourcegraph_to_blueprint(sg)
        a = next(f for f in bp.files if f.path == "/a.py")
        b = next(f for f in bp.files if f.path == "/b.py")
        assert b.id in a.imports
        assert "ext_os" in a.imports
        assert len(bp.externals) == 1

    def test_blueprint_validates_clean(self):
        sg = make_sg(("/a.py", 10, ".py"), ("/b.py", 20, ".py"))
        sg.add_import("/a.py", "/b.py")
        bp = sourcegraph_to_blueprint(sg)
        assert bp.validate_refs() == []

    def test_format_and_version_fields(self):
        bp = sourcegraph_to_blueprint(SourceGraph())
        assert bp.format == "comprehensity-blueprint"
        assert bp.version == CURRENT_VERSION


# ---------------------------------------------------------------------------
# _CODE_EXTENSIONS allowlist filter
# ---------------------------------------------------------------------------

class TestCodeExtensionsFilter:
    def test_non_code_file_excluded_from_files(self):
        """PNG in SourceGraph must not appear in blueprint.files."""
        sg = make_sg(("/src/main.py", 100, ".py"), ("/assets/logo.png", 200, ".png"))
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        paths = [f.path for f in bp.files]
        assert "/src/main.py" in paths
        assert "/assets/logo.png" not in paths

    def test_non_code_file_excluded_leaves_ids_stable(self):
        """File IDs are re-numbered from the filtered list only."""
        sg = make_sg(("/a.py", 10, ".py"), ("/b.png", 20, ".png"), ("/c.py", 30, ".py"))
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        assert len(bp.files) == 2
        assert bp.files[0].id == "f0"
        assert bp.files[1].id == "f1"

    def test_non_code_file_imported_becomes_external(self):
        """A .png imported by a .py becomes an ExternalEntry, not a FileEntry."""
        sg = make_sg(("/src/main.py", 100, ".py"), ("/assets/logo.png", 200, ".png"))
        sg.add_import("/src/main.py", "/assets/logo.png")
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        paths = [f.path for f in bp.files]
        assert "/assets/logo.png" not in paths
        ext_names = [e.name for e in bp.externals]
        assert "/assets/logo.png" in ext_names

    def test_validate_refs_clean_after_filter(self):
        """Blueprint with mixed code/non-code imports passes ref validation."""
        sg = make_sg(("/a.py", 10, ".py"), ("/b.py", 20, ".py"), ("/img.svg", 5, ".svg"))
        sg.add_import("/a.py", "/b.py")
        sg.add_import("/a.py", "/img.svg")
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        assert bp.validate_refs() == []


# ---------------------------------------------------------------------------
# blueprint_to_sourcegraph
# ---------------------------------------------------------------------------

class TestBlueprintToSourcegraph:
    def test_empty_blueprint(self):
        sg = blueprint_to_sourcegraph(Blueprint())
        assert sg.file_count() == 0

    def test_single_file(self):
        bp = Blueprint(files=[FileEntry(id="f0", path="/a.py", size_bytes=42, ext=".py")])
        sg = blueprint_to_sourcegraph(bp)
        assert sg.file_count() == 1
        node = sg.get_file("/a.py")
        assert node is not None
        assert node.size_bytes == 42
        assert node.extension == ".py"

    def test_internal_import_restored(self):
        bp = Blueprint(files=[
            FileEntry(id="f0", path="/a.py", size_bytes=10, ext=".py", imports=["f1"]),
            FileEntry(id="f1", path="/b.py", size_bytes=20, ext=".py"),
        ])
        sg = blueprint_to_sourcegraph(bp)
        a = sg.get_file("/a.py")
        b = sg.get_file("/b.py")
        assert "/b.py" in a.imports
        assert "/a.py" in b.imported_by

    def test_external_import_stored_as_name(self):
        bp = Blueprint(
            files=[FileEntry(id="f0", path="/a.py", size_bytes=10, ext=".py",
                             imports=["ext_numpy"])],
            externals=[ExternalEntry(id="ext_numpy", name="numpy", kind="package")],
        )
        sg = blueprint_to_sourcegraph(bp)
        a = sg.get_file("/a.py")
        assert "numpy" in a.imports

    def test_unknown_import_id_ignored(self):
        """An import ID that matches neither a file nor an external is silently dropped."""
        bp = Blueprint(files=[
            FileEntry(id="f0", path="/a.py", size_bytes=10, ext=".py",
                      imports=["nonexistent_id"]),
        ])
        sg = blueprint_to_sourcegraph(bp)
        a = sg.get_file("/a.py")
        assert a.imports == set()

    def test_imported_by_not_populated_for_externals(self):
        """Externals don't live in the graph, so no imported_by side-effect."""
        bp = Blueprint(
            files=[FileEntry(id="f0", path="/a.py", size_bytes=10, ext=".py",
                             imports=["ext_os"])],
            externals=[ExternalEntry(id="ext_os", name="os", kind="system")],
        )
        sg = blueprint_to_sourcegraph(bp)
        # No crash, and "os" is in imports as a raw name
        assert "os" in sg.get_file("/a.py").imports


# ---------------------------------------------------------------------------
# Round-trip
# ---------------------------------------------------------------------------

class TestRoundTrip:
    def _base_sg(self):
        sg = SourceGraph(root_path="/repo")
        sg.add_file("/repo/a.py", 100, ".py")
        sg.add_file("/repo/b.py", 200, ".py")
        sg.add_file("/repo/c.py", 300, ".py")
        sg.add_import("/repo/a.py", "/repo/b.py")
        sg.add_import("/repo/b.py", "/repo/c.py")
        sg._files["/repo/a.py"].imports.add("os")
        sg._files["/repo/a.py"].metadata["import_details"] = [
            {"imported_name": "os", "import_type": "system",
             "raw_statement": "import os", "line_number": 1, "resolved_path": None}
        ]
        return sg

    def test_file_count_preserved(self):
        sg = self._base_sg()
        sg2 = blueprint_to_sourcegraph(sourcegraph_to_blueprint(sg))
        assert sg2.file_count() == sg.file_count()

    def test_paths_preserved(self):
        sg = self._base_sg()
        sg2 = blueprint_to_sourcegraph(sourcegraph_to_blueprint(sg))
        assert {f.path for f in sg2.get_all_files()} == {f.path for f in sg.get_all_files()}

    def test_internal_imports_preserved(self):
        sg = self._base_sg()
        sg2 = blueprint_to_sourcegraph(sourcegraph_to_blueprint(sg))
        assert "/repo/b.py" in sg2.get_file("/repo/a.py").imports
        assert "/repo/c.py" in sg2.get_file("/repo/b.py").imports

    def test_imported_by_preserved(self):
        sg = self._base_sg()
        sg2 = blueprint_to_sourcegraph(sourcegraph_to_blueprint(sg))
        assert "/repo/a.py" in sg2.get_file("/repo/b.py").imported_by

    def test_external_imports_preserved_as_names(self):
        sg = self._base_sg()
        sg2 = blueprint_to_sourcegraph(sourcegraph_to_blueprint(sg))
        assert "os" in sg2.get_file("/repo/a.py").imports

    def test_json_round_trip(self):
        """Blueprint survives JSON serialisation and deserialisation."""
        sg = self._base_sg()
        bp = sourcegraph_to_blueprint(sg)
        bp2 = Blueprint.from_json(bp.to_json())
        sg2 = blueprint_to_sourcegraph(bp2)
        assert sg2.file_count() == sg.file_count()
        assert "/repo/b.py" in sg2.get_file("/repo/a.py").imports


# ---------------------------------------------------------------------------
# Symbol extraction pipeline tests (requires grammars on disk)
# ---------------------------------------------------------------------------

class TestSymbolPipeline:
    def test_py_simple_has_symbols(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        assert len(bp.symbols) > 0

    def test_py_simple_symbol_ids_stable(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        ids = [s.id for s in bp.symbols]
        assert ids == [f"s{i}" for i in range(len(ids))]

    def test_py_simple_symbol_file_ids_valid(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        file_ids = {f.id for f in bp.files}
        for sym in bp.symbols:
            assert sym.file_id in file_ids

    def test_py_simple_validate_refs_clean(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        assert bp.validate_refs() == []

    def test_py_simple_contains_run_function(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        names = {s.name for s in bp.symbols}
        assert "run" in names

    def test_py_simple_contains_user_class(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        classes = [s for s in bp.symbols if s.kind == "class"]
        assert any(s.name == "User" for s in classes)

    def test_flat_js_has_greet_symbol(self):
        sg = build_source_graph("tests/fixtures/repos/flat_js")
        bp = sourcegraph_to_blueprint(sg)
        names = {s.name for s in bp.symbols}
        assert "greet" in names

    def test_flat_js_greet_is_exported(self):
        sg = build_source_graph("tests/fixtures/repos/flat_js")
        bp = sourcegraph_to_blueprint(sg)
        greet = next(s for s in bp.symbols if s.name == "greet")
        assert greet.is_exported is True

    def test_extract_symbols_false_yields_no_symbols(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        assert bp.symbols == []

    def test_symbols_sorted_by_file_then_line(self):
        sg = build_source_graph("tests/fixtures/repos/py_simple")
        bp = sourcegraph_to_blueprint(sg)
        # file_id integers must be non-decreasing; within same file, start_line non-decreasing
        prev_fnum = -1
        prev_line = -1
        for sym in bp.symbols:
            fnum = int(sym.file_id[1:])
            if fnum == prev_fnum:
                assert sym.start_line >= prev_line
            else:
                assert fnum >= prev_fnum
            prev_fnum = fnum
            prev_line = sym.start_line


# ---------------------------------------------------------------------------
# Clone detection integration
# ---------------------------------------------------------------------------
# _treepeat_derived_ignores
# ---------------------------------------------------------------------------

class TestTreepeatDerivedIgnores:
    def test_empty_map_ignores_all_subdirs(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        globs = _treepeat_derived_ignores(tmp_path, {})
        assert "**/src/**" in globs
        assert "**/docs/**" in globs

    def test_active_subdir_not_ignored(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        (tmp_path / "src").mkdir()
        (tmp_path / "docs").mkdir()
        file_id_map = {str(tmp_path / "src" / "main.py"): "f0"}
        globs = _treepeat_derived_ignores(tmp_path, file_id_map)
        assert "**/src/**" not in globs
        assert "**/docs/**" in globs

    def test_files_in_root_dont_block_subdir_ignore(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        (tmp_path / "docs").mkdir()
        # Only a root-level file — no subdir files at all
        file_id_map = {str(tmp_path / "README.md"): "f0"}
        globs = _treepeat_derived_ignores(tmp_path, file_id_map)
        assert "**/docs/**" in globs

    def test_nested_active_file_marks_top_level_dir(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        src = tmp_path / "src" / "subpkg"
        src.mkdir(parents=True)
        (tmp_path / "docs").mkdir()
        file_id_map = {str(src / "foo.py"): "f0"}
        globs = _treepeat_derived_ignores(tmp_path, file_id_map)
        assert "**/src/**" not in globs
        assert "**/docs/**" in globs

    def test_returns_glob_pattern_format(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        (tmp_path / "dist").mkdir()
        globs = _treepeat_derived_ignores(tmp_path, {})
        assert all(g.startswith("**/") and g.endswith("/**") for g in globs)

    def test_no_subdirs_returns_empty(self, tmp_path):
        from blueprint_io import _treepeat_derived_ignores
        # Only a file in root, no subdirs
        (tmp_path / "main.py").write_text("")
        globs = _treepeat_derived_ignores(tmp_path, {})
        assert globs == ()


# ---------------------------------------------------------------------------

class TestSourcegraphToBlueprintClones:
    def test_clone_status_stub_by_default(self):
        """detect_clones defaults to False; clone_status stays 'stub'."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        assert bp.clone_status == "stub"
        assert bp.clone_blocks == []

    def test_detect_clones_false_does_not_call_treepeat(self):
        """When detect_clones=False, run_treepeat is never invoked."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        with patch("blueprint_io._run_treepeat_lazy") as mock_rt:
            sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=False)
        mock_rt.assert_not_called()

    def test_detect_clones_true_calls_treepeat_and_sets_status(self):
        """With detect_clones=True, run_treepeat is called and clone_status='complete'."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        with patch("blueprint_io._run_treepeat_lazy", return_value=([], False)) as mock_rt:
            bp = sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=True)
        mock_rt.assert_called_once()
        assert bp.clone_status == "complete"

    def test_detect_clones_passes_correct_ruleset(self):
        """clone_ruleset is forwarded to run_treepeat."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        with patch("blueprint_io._run_treepeat_lazy", return_value=([], False)) as mock_rt:
            sourcegraph_to_blueprint(
                sg, extract_symbols=False, detect_clones=True, clone_ruleset="none"
            )
        _, kwargs = mock_rt.call_args
        assert kwargs.get("ruleset", mock_rt.call_args[0][1] if mock_rt.call_args[0] else None) in (
            "none", mock_rt.call_args[0][1] if len(mock_rt.call_args[0]) > 1 else None
        )
        # Positional: _run_treepeat_lazy(root_path, ruleset, file_id_map)
        assert mock_rt.call_args[0][1] == "none"

    def test_returned_clones_stored_in_blueprint(self):
        """CloneBlocks returned by run_treepeat appear in bp.clone_blocks."""
        from blueprint import CloneBlock, CloneInstance
        fake_block = CloneBlock(
            id="dup_0",
            kind="exact",
            instances=[
                CloneInstance(file_id="f0", start_line=7, end_line=11, hash="a" * 64),
                CloneInstance(file_id="f1", start_line=1, end_line=5, hash="a" * 64),
            ],
            lines=5,
            tokens=0,
        )
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        with patch("blueprint_io._run_treepeat_lazy", return_value=([fake_block], False)):
            bp = sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=True)
        assert len(bp.clone_blocks) == 1
        assert bp.clone_blocks[0].id == "dup_0"

    def test_file_id_map_passed_to_treepeat(self):
        """abs_file_id_map keys are absolute paths; values are Blueprint file IDs."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        captured = {}

        def capture(root_path, ruleset, file_id_map, ignore_dirs=(), **kwargs):
            captured.update(file_id_map)
            return [], False

        with patch("blueprint_io._run_treepeat_lazy", side_effect=capture):
            bp = sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=True)

        assert captured, "file_id_map should be non-empty"
        for abs_path, fid in captured.items():
            assert Path(abs_path).is_absolute(), f"Expected absolute path, got {abs_path!r}"
            assert fid.startswith("f"), f"Expected file ID like 'f0', got {fid!r}"
        # All blueprint file IDs should be in the map values
        bp_ids = {f.id for f in bp.files}
        assert bp_ids == set(captured.values())


@pytest.mark.skipif(
    clone_detection._find_treepeat_binary() is None,
    reason="treepeat not installed",
)
class TestCloneDetectionIntegration:
    def test_clone_exact_fixture_finds_duplicate(self):
        """Running treepeat on clone_exact finds the duplicated compute_total function."""
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=True, clone_ruleset="none")
        assert bp.clone_status == "complete"
        assert len(bp.clone_blocks) >= 1
        assert all(b.id.startswith("dup_") for b in bp.clone_blocks)

    def test_clone_exact_blueprint_json_round_trips(self):
        """Blueprint with clones serialises and deserialises cleanly."""
        from blueprint import Blueprint as BP
        sg = build_source_graph(str(CLONE_EXACT_FIXTURE))
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False, detect_clones=True, clone_ruleset="none")
        restored = BP.model_validate_json(bp.to_json())
        assert restored.clone_status == "complete"
        assert len(restored.clone_blocks) == len(bp.clone_blocks)
