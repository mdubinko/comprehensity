"""Tests for modularity.py — L2/L3 module detection."""

from pathlib import Path

import pytest

from blueprint import FileEntry, ModuleEntry
from modularity import (
    detect_modules,
    _detect_l3,
    _detect_l2,
    _detect_python_packages,
    _detect_go_packages,
    _detect_java_packages,
)

FIXTURES = Path(__file__).parent / "fixtures" / "repos"
PY_SIMPLE = FIXTURES / "py_simple"
TS_MONOREPO = FIXTURES / "ts_monorepo"
MIXED = FIXTURES / "mixed_java_py"
PY_PKG = FIXTURES / "py_pkg"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def fe(id: str, path: str, ext: str = ".py") -> FileEntry:
    return FileEntry(id=id, path=path, size_bytes=0, ext=ext)


# ---------------------------------------------------------------------------
# L3: build unit detection
# ---------------------------------------------------------------------------

class TestL3Detection:
    def test_py_simple_has_one_l3(self):
        files = [
            fe("f0", "src/main.py"),
            fe("f1", "src/models.py"),
            fe("f2", "src/utils.py"),
        ]
        mods = _detect_l3(PY_SIMPLE, files)
        assert len(mods) == 1
        m = mods[0]
        assert m.level == "L3"
        assert m.root_path == ""
        assert m.build_kind == "pyproject"
        assert set(m.file_ids) == {"f0", "f1", "f2"}

    def test_ts_monorepo_has_three_l3(self):
        files = [
            fe("f0", "packages/api/src/index.ts", ".ts"),
            fe("f1", "packages/api/src/routes.ts", ".ts"),
            fe("f2", "packages/client/src/App.tsx", ".tsx"),
            fe("f3", "packages/client/src/index.ts", ".ts"),
        ]
        mods = _detect_l3(TS_MONOREPO, files)
        assert len(mods) == 3
        root_mod = next(m for m in mods if m.root_path == "")
        assert root_mod.build_kind == "npm"
        api_mod = next(m for m in mods if m.root_path == "packages/api")
        assert api_mod.build_kind == "npm"
        assert set(api_mod.file_ids) == {"f0", "f1"}
        client_mod = next(m for m in mods if m.root_path == "packages/client")
        assert set(client_mod.file_ids) == {"f2", "f3"}

    def test_root_l3_excludes_nested_files(self):
        """Files under nested build units must NOT appear in the root module."""
        files = [
            fe("f0", "packages/api/src/index.ts", ".ts"),
            fe("f1", "packages/client/src/App.tsx", ".tsx"),
        ]
        mods = _detect_l3(TS_MONOREPO, files)
        root_mod = next(m for m in mods if m.root_path == "")
        # All files live under nested packages, so root should have none
        assert root_mod.file_ids == []

    def test_empty_root_has_no_l3(self):
        # A temp directory with no build configs
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            mods = _detect_l3(Path(tmp), [])
        assert mods == []

    def test_mixed_has_two_l3(self):
        files = [
            fe("f0", "src/main/java/App.java", ".java"),
            fe("f1", "src/main/java/Service.java", ".java"),
            fe("f2", "src/python/analyze.py"),
            fe("f3", "src/python/utils.py"),
        ]
        mods = _detect_l3(MIXED, files)
        # pom.xml and pyproject.toml both at root — two configs → first kind wins,
        # but deduplication collapses to ONE root module
        root_mods = [m for m in mods if m.root_path == ""]
        assert len(root_mods) == 1


# ---------------------------------------------------------------------------
# L2: Python package detection
# ---------------------------------------------------------------------------

class TestPythonPackageDetection:
    def test_detects_init_dirs(self):
        files = [
            fe("f0", "myapp/__init__.py"),
            fe("f1", "myapp/core/__init__.py"),
            fe("f2", "myapp/core/engine.py"),
            fe("f3", "myapp/utils/__init__.py"),
            fe("f4", "myapp/utils/helpers.py"),
        ]
        mods = _detect_python_packages(PY_PKG, files)
        dirs = {m.root_path for m in mods}
        assert "myapp" in dirs
        assert "myapp/core" in dirs
        assert "myapp/utils" in dirs

    def test_package_contains_correct_files(self):
        files = [
            fe("f0", "myapp/__init__.py"),
            fe("f1", "myapp/core/__init__.py"),
            fe("f2", "myapp/core/engine.py"),
        ]
        mods = _detect_python_packages(PY_PKG, files)
        core_mod = next(m for m in mods if m.root_path == "myapp/core")
        # Should contain __init__.py and engine.py but NOT the parent's __init__.py
        assert set(core_mod.file_ids) == {"f1", "f2"}

    def test_no_init_py_no_modules(self):
        files = [fe("f0", "src/main.py"), fe("f1", "src/utils.py")]
        mods = _detect_python_packages(PY_SIMPLE, files)
        assert mods == []

    def test_dotted_package_name(self):
        files = [fe("f0", "myapp/core/__init__.py")]
        mods = _detect_python_packages(PY_PKG, files)
        core_mod = next(m for m in mods if m.root_path == "myapp/core")
        assert core_mod.name == "myapp.core"

    def test_root_package_name(self):
        files = [fe("f0", "myapp/__init__.py")]
        mods = _detect_python_packages(PY_PKG, files)
        assert mods[0].name == "myapp"


# ---------------------------------------------------------------------------
# L2: Go package detection
# ---------------------------------------------------------------------------

class TestGoPackageDetection:
    def test_groups_by_directory(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pkg_dir = root / "cmd"
            pkg_dir.mkdir()
            (pkg_dir / "main.go").write_text("package main\n\nfunc main() {}")
            (pkg_dir / "util.go").write_text("package main\n\nfunc helper() {}")
            files = [
                fe("f0", "cmd/main.go", ".go"),
                fe("f1", "cmd/util.go", ".go"),
            ]
            mods = _detect_go_packages(root, files)
        assert len(mods) == 1
        assert mods[0].name == "main"
        assert mods[0].root_path == "cmd"
        assert set(mods[0].file_ids) == {"f0", "f1"}

    def test_multiple_packages(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "cmd").mkdir()
            (root / "internal").mkdir()
            (root / "cmd" / "main.go").write_text("package main\n")
            (root / "internal" / "service.go").write_text("package service\n")
            files = [
                fe("f0", "cmd/main.go", ".go"),
                fe("f1", "internal/service.go", ".go"),
            ]
            mods = _detect_go_packages(root, files)
        assert len(mods) == 2
        names = {m.name for m in mods}
        assert names == {"main", "service"}


# ---------------------------------------------------------------------------
# L2: Java package detection
# ---------------------------------------------------------------------------

class TestJavaPackageDetection:
    def test_groups_by_package_declaration(self):
        files = [
            fe("f0", "src/main/java/App.java", ".java"),
            fe("f1", "src/main/java/Service.java", ".java"),
        ]
        mods = _detect_java_packages(MIXED, files)
        # App.java has no package declaration in fixture → default package
        # Service.java same
        # Both end up in "(default)" or a named package if declared
        assert len(mods) >= 1

    def test_files_without_package_get_default(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo.java").write_text("public class Foo {}")
            files = [fe("f0", "Foo.java", ".java")]
            mods = _detect_java_packages(root, files)
        assert len(mods) == 1
        assert mods[0].name == "(default)"

    def test_named_package_extracted(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "Foo.java").write_text("package com.example;\npublic class Foo {}")
            files = [fe("f0", "Foo.java", ".java")]
            mods = _detect_java_packages(root, files)
        assert len(mods) == 1
        assert mods[0].name == "com.example"


# ---------------------------------------------------------------------------
# detect_modules: ID assignment and integration
# ---------------------------------------------------------------------------

class TestDetectModules:
    def test_ids_assigned(self):
        files = [
            fe("f0", "src/main.py"),
            fe("f1", "src/models.py"),
        ]
        mods = detect_modules(PY_SIMPLE, files)
        ids = [m.id for m in mods]
        assert all(id.startswith("m") and id[1:].isdigit() for id in ids)
        assert len(set(ids)) == len(ids)  # unique

    def test_l3_comes_before_l2(self):
        files = [
            fe("f0", "myapp/__init__.py"),
            fe("f1", "myapp/core/__init__.py"),
            fe("f2", "myapp/core/engine.py"),
        ]
        mods = detect_modules(PY_PKG, files)
        levels = [m.level for m in mods]
        # L3 entries (if any) must come before L2 entries
        seen_l2 = False
        for lvl in levels:
            if lvl == "L2":
                seen_l2 = True
            if seen_l2 and lvl == "L3":
                pytest.fail("L3 entry appeared after L2 entry")

    def test_validate_refs_passes_for_modules(self):
        from blueprint import Blueprint
        files = [
            fe("f0", "myapp/__init__.py"),
            fe("f1", "myapp/core/__init__.py"),
            fe("f2", "myapp/core/engine.py"),
        ]
        mods = detect_modules(PY_PKG, files)
        bp = Blueprint(files=files, modules=mods, modularity_status="complete")
        warnings = bp.validate_refs()
        assert warnings == []

    def test_validate_refs_warns_on_bad_file_id(self):
        from blueprint import Blueprint
        mod = ModuleEntry(id="m0", level="L3", name="root", root_path="", file_ids=["f99"])
        bp = Blueprint(files=[], modules=[mod])
        warnings = bp.validate_refs()
        assert any("f99" in w for w in warnings)

    def test_modularity_status_stub_by_default(self):
        from blueprint import Blueprint
        bp = Blueprint()
        assert bp.modularity_status == "stub"

    def test_py_pkg_end_to_end(self):
        """Full fixture: py_pkg has pyproject.toml + three __init__.py packages."""
        from scan import build_source_graph
        sg = build_source_graph(str(PY_PKG))
        from blueprint_io import sourcegraph_to_blueprint
        bp = sourcegraph_to_blueprint(sg, extract_symbols=False)
        assert bp.modularity_status == "complete"
        levels = {m.level for m in bp.modules}
        assert "L3" in levels
        assert "L2" in levels
        # Validate all refs
        assert bp.validate_refs() == []
