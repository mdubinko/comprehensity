"""
Integration tests for Bite 4: full scan pipeline
  build_source_graph → analyze_source_imports → sourcegraph_to_blueprint
"""

import json
import sys
import textwrap
from pathlib import Path

import pytest

# Ensure src/ is on the path for all imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from blueprint import Blueprint, CURRENT_VERSION
from blueprint_io import sourcegraph_to_blueprint
from srcgraph import SourceGraph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write(tmp_path: Path, rel: str, src: str) -> Path:
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(textwrap.dedent(src))
    return p


def _build_and_analyze(root: Path, include_paths=None):
    """Run build_source_graph + analyze_source_imports on *root*."""
    import scan
    import import_analysis

    sg = scan.build_source_graph(str(root))
    import_analysis.analyze_source_imports(sg, include_paths or [])
    return sg


# ---------------------------------------------------------------------------
# Blueprint format tests
# ---------------------------------------------------------------------------

class TestScanToBlueprint:
    def test_empty_directory(self, tmp_path):
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)
        assert isinstance(bp, Blueprint)
        assert bp.files == []
        assert bp.externals == []
        assert bp.validate_refs() == []

    def test_single_python_file(self, tmp_path):
        _write(tmp_path, "main.py", """\
            import os
            print("hello")
        """)
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        assert len(bp.files) == 1
        fe = bp.files[0]
        assert fe.path == "main.py"
        assert fe.ext == ".py"
        assert fe.size_bytes > 0
        # os is external — should show up there, not as a file import
        assert all(imp.startswith("ext_") for imp in fe.imports)
        ext_names = {e.name for e in bp.externals}
        assert "os" in ext_names
        assert bp.validate_refs() == []

    def test_internal_import_edge(self, tmp_path):
        # C local includes are definitively LOCAL, so the resolver can find the file.
        _write(tmp_path, "utils.h", "int helper(void);\n")
        _write(tmp_path, "main.c", '#include "utils.h"\nint main(){return 0;}\n')
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        assert len(bp.files) == 2
        path_to_fe = {fe.path: fe for fe in bp.files}
        main_fe = path_to_fe["main.c"]
        utils_fe = path_to_fe["utils.h"]

        assert utils_fe.id in main_fe.imports
        assert bp.validate_refs() == []

    def test_blueprint_json_round_trip(self, tmp_path):
        _write(tmp_path, "a.py", "import b\n")
        _write(tmp_path, "b.py", "x = 1\n")
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        raw = bp.to_json()
        data = json.loads(raw)
        assert data["format"] == "comprehensity-blueprint"
        assert data["version"] == CURRENT_VERSION
        assert len(data["files"]) == 2

        restored = Blueprint.from_json(raw)
        assert {f.path for f in restored.files} == {"a.py", "b.py"}

    def test_java_package_resolution_codebase_root(self, tmp_path):
        # com.example.Foo should resolve to com/example/Foo.java at the codebase root
        _write(tmp_path, "com/example/Util.java", "package com.example;\npublic class Util {}\n")
        _write(tmp_path, "Main.java", "import com.example.Util;\npublic class Main {}\n")
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        path_to_fe = {fe.path: fe for fe in bp.files}
        main_fe = path_to_fe["Main.java"]
        util_fe = path_to_fe["com/example/Util.java"]

        assert util_fe.id in main_fe.imports
        assert bp.validate_refs() == []

    def test_java_package_resolution_maven_layout(self, tmp_path):
        # Maven standard layout: src/main/java/<package path>
        _write(tmp_path, "src/main/java/com/example/Service.java",
               "package com.example;\npublic class Service {}\n")
        _write(tmp_path, "src/main/java/com/example/Controller.java",
               "import com.example.Service;\npublic class Controller {}\n")
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        path_to_fe = {fe.path: fe for fe in bp.files}
        ctrl = path_to_fe["src/main/java/com/example/Controller.java"]
        svc = path_to_fe["src/main/java/com/example/Service.java"]

        assert svc.id in ctrl.imports
        assert bp.validate_refs() == []

    def test_blueprint_format_flag(self, tmp_path, capsys):
        """scan.generate_directory_listing with --format blueprint writes valid JSON."""
        _write(tmp_path, "hello.py", "import sys\n")
        out_file = tmp_path / "out.json"

        import argparse
        args = argparse.Namespace(
            ignore_dirs="",
            ignore_files="",
            extensions=".py",
            exclude_extensions="",
            max_depth=None,
            include_hidden=False,
            min_file_size=0,
            max_file_size=100 * 1024 * 1024,
            follow_symlinks=False,
            progress=False,
            analyze_imports=True,
            include_paths=None,
            format="blueprint",
            absolute=False,
            relative_to=None,
        )

        import scan
        scan.generate_directory_listing(str(tmp_path), str(out_file), args)

        raw = out_file.read_text()
        bp = Blueprint.from_json(raw)
        assert len(bp.files) == 1
        assert bp.files[0].path == "hello.py"
        assert bp.validate_refs() == []

    def test_python_relative_import_single_dot(self, tmp_path):
        """from .utils import helper → resolves to sibling file, not ext_."""
        _write(tmp_path, "mypkg/__init__.py", "")
        _write(tmp_path, "mypkg/utils.py", "def helper(): pass\n")
        _write(tmp_path, "mypkg/main.py", "from .utils import helper\n")
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        path_to_fe = {fe.path: fe for fe in bp.files}
        main_fe = path_to_fe["mypkg/main.py"]
        utils_fe = path_to_fe["mypkg/utils.py"]

        assert utils_fe.id in main_fe.imports, "relative import '.utils' must resolve to file ID, not ext_"
        assert not any(imp == "ext_.utils" for imp in main_fe.imports)
        assert bp.validate_refs() == []

    def test_python_relative_import_double_dot(self, tmp_path):
        """from ..config import Cfg → resolves to parent package file, not ext_."""
        _write(tmp_path, "pkg/__init__.py", "")
        _write(tmp_path, "pkg/config.py", "class Cfg: pass\n")
        _write(tmp_path, "pkg/sub/__init__.py", "")
        _write(tmp_path, "pkg/sub/service.py", "from ..config import Cfg\n")
        sg = _build_and_analyze(tmp_path)
        bp = sourcegraph_to_blueprint(sg)

        path_to_fe = {fe.path: fe for fe in bp.files}
        svc_fe = path_to_fe["pkg/sub/service.py"]
        cfg_fe = path_to_fe["pkg/config.py"]

        assert cfg_fe.id in svc_fe.imports, "relative import '..config' must resolve to file ID, not ext_"
        assert bp.validate_refs() == []
