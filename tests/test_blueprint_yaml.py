"""
Tier 1 tests for blueprint_yaml.py — YAML serialization round-trip.

Coverage:
  - Empty blueprint round-trips
  - FileEntry: path, size, line_count, ext, imports (omitted when empty), comment_desc (block scalar)
  - ExternalEntry: name, kind
  - SymbolEntry: all fields including line-range and is_exported
  - ReferenceEdge: all fields (no id)
  - DeadSymbol: all fields
  - DiagnosticEntry: all fields including message with spaces/tabs
  - ModuleEntry: all fields; file_ids omitted when empty; None numeric → null
  - CloneBlock: kind/lines/tokens; instances; hash dropped on round-trip
  - Status fields preserved
  - config_path / config_raw preserved
  - summary present in YAML output with *_schema entries
  - readme key present
  - YAML is valid (parseable by yaml.safe_load)
  - from_file() auto-detects .yaml by extension
"""

from __future__ import annotations

import textwrap

import pytest
import yaml

from blueprint import (
    Blueprint, CloneBlock, CloneInstance,
    DeadSymbol, DiagnosticEntry,
    ExternalEntry, FileEntry,
    ModuleEntry, ReferenceEdge, SymbolEntry,
)
from blueprint_yaml import blueprint_to_yaml, blueprint_from_yaml


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fe(fid: str, path: str = "", imports=None, comment_desc=None) -> FileEntry:
    return FileEntry(
        id=fid, path=path or f"{fid}.py",
        size_bytes=100, line_count=10, ext=".py",
        imports=imports or [], comment_desc=comment_desc,
    )

def _rt(bp: Blueprint) -> Blueprint:
    """Round-trip: Blueprint → YAML → Blueprint."""
    return blueprint_from_yaml(blueprint_to_yaml(bp))


# ---------------------------------------------------------------------------
# Empty blueprint
# ---------------------------------------------------------------------------

class TestEmpty:
    def test_empty_round_trips(self):
        bp = Blueprint()
        rt = _rt(bp)
        assert rt.files == []
        assert rt.externals == []
        assert rt.symbols == []

    def test_yaml_is_valid(self):
        raw = blueprint_to_yaml(Blueprint())
        doc = yaml.safe_load(raw)
        assert doc["format"] == "comprehensity-blueprint"

    def test_readme_present(self):
        raw = blueprint_to_yaml(Blueprint())
        doc = yaml.safe_load(raw)
        assert "readme" in doc
        assert "TAB" in doc["readme"]

    def test_summary_present_with_schemas(self):
        raw = blueprint_to_yaml(Blueprint())
        doc = yaml.safe_load(raw)
        assert "summary" in doc
        assert "files_schema" in doc["summary"]
        assert "symbols_schema" in doc["summary"]
        assert "clone_blocks_schema" in doc["summary"]


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------

class TestFiles:
    def test_basic_fields(self):
        bp = Blueprint(files=[_fe("f0", path="src/foo.py")])
        rt = _rt(bp)
        assert len(rt.files) == 1
        f = rt.files[0]
        assert f.id == "f0"
        assert f.path == "src/foo.py"
        assert f.size_bytes == 100
        assert f.line_count == 10
        assert f.ext == ".py"

    def test_imports_omitted_when_empty(self):
        raw = blueprint_to_yaml(Blueprint(files=[_fe("f0")]))
        doc = yaml.safe_load(raw)
        assert "imports" not in doc["files"][0]

    def test_imports_preserved(self):
        bp = Blueprint(files=[_fe("f0", imports=["f1", "ext_os"])])
        rt = _rt(bp)
        assert rt.files[0].imports == ["f1", "ext_os"]

    def test_comment_desc_none_omitted(self):
        raw = blueprint_to_yaml(Blueprint(files=[_fe("f0")]))
        doc = yaml.safe_load(raw)
        assert "comment_desc" not in doc["files"][0]

    def test_comment_desc_single_line(self):
        bp = Blueprint(files=[_fe("f0", comment_desc="Module docstring.")])
        rt = _rt(bp)
        assert rt.files[0].comment_desc == "Module docstring."

    def test_comment_desc_multiline_block_scalar(self):
        comment_desc = "Line one.\nLine two.\nLine three."
        bp = Blueprint(files=[_fe("f0", comment_desc=comment_desc)])
        raw = blueprint_to_yaml(bp)
        # pyyaml should use a block scalar (| or |-) for multi-line strings
        assert "comment_desc: |" in raw
        rt = _rt(bp)
        assert rt.files[0].comment_desc == comment_desc

    def test_path_with_spaces(self):
        bp = Blueprint(files=[_fe("f0", path="src/my module/foo.py")])
        rt = _rt(bp)
        assert rt.files[0].path == "src/my module/foo.py"


# ---------------------------------------------------------------------------
# Externals
# ---------------------------------------------------------------------------

class TestExternals:
    def test_round_trip(self):
        bp = Blueprint(
            externals=[
                ExternalEntry(id="ext_numpy", name="numpy", kind="package"),
                ExternalEntry(id="ext_os", name="os", kind="system"),
            ]
        )
        rt = _rt(bp)
        assert len(rt.externals) == 2
        assert rt.externals[0].id == "ext_numpy"
        assert rt.externals[0].name == "numpy"
        assert rt.externals[0].kind == "package"
        assert rt.externals[1].kind == "system"


# ---------------------------------------------------------------------------
# Symbols
# ---------------------------------------------------------------------------

class TestSymbols:
    def test_all_fields(self):
        bp = Blueprint(
            files=[_fe("f0")],
            symbols=[
                SymbolEntry(id="s0", file_id="f0", name="my_func",
                            kind="function", start_line=10, end_line=20,
                            is_exported=True),
                SymbolEntry(id="s1", file_id="f0", name="_helper",
                            kind="method", start_line=25, end_line=25,
                            is_exported=False),
            ],
        )
        rt = _rt(bp)
        s0 = rt.symbols[0]
        assert s0.id == "s0"
        assert s0.file_id == "f0"
        assert s0.name == "my_func"
        assert s0.kind == "function"
        assert s0.start_line == 10
        assert s0.end_line == 20
        assert s0.is_exported is True

        s1 = rt.symbols[1]
        assert s1.is_exported is False

    def test_line_range_format_in_yaml(self):
        bp = Blueprint(
            files=[_fe("f0")],
            symbols=[SymbolEntry(id="s0", file_id="f0", name="foo",
                                  kind="function", start_line=5, end_line=15,
                                  is_exported=False)],
        )
        raw = blueprint_to_yaml(bp)
        assert "5-15" in raw


# ---------------------------------------------------------------------------
# ReferenceEdge
# ---------------------------------------------------------------------------

class TestReferenceEdges:
    def test_round_trip(self):
        bp = Blueprint(
            reference_edges=[
                ReferenceEdge(from_symbol_id="s0", to_symbol_id="s1",
                              call_site_file_id="f0", call_site_line=42),
            ]
        )
        rt = _rt(bp)
        assert len(rt.reference_edges) == 1
        e = rt.reference_edges[0]
        assert e.from_symbol_id == "s0"
        assert e.to_symbol_id == "s1"
        assert e.call_site_file_id == "f0"
        assert e.call_site_line == 42

    def test_no_id_key_in_yaml(self):
        bp = Blueprint(
            reference_edges=[
                ReferenceEdge(from_symbol_id="s0", to_symbol_id="s1",
                              call_site_file_id="f0", call_site_line=1),
            ]
        )
        doc = yaml.safe_load(blueprint_to_yaml(bp))
        assert "id" not in doc["reference_edges"][0]


# ---------------------------------------------------------------------------
# DeadSymbol
# ---------------------------------------------------------------------------

class TestDeadSymbols:
    def test_round_trip(self):
        bp = Blueprint(
            dead_symbols=[
                DeadSymbol(id="dead_0", symbol_id="s0",
                           confidence=0.9, reason="unreferenced"),
            ]
        )
        rt = _rt(bp)
        d = rt.dead_symbols[0]
        assert d.id == "dead_0"
        assert d.symbol_id == "s0"
        assert d.confidence == 0.9
        assert d.reason == "unreferenced"


# ---------------------------------------------------------------------------
# DiagnosticEntry
# ---------------------------------------------------------------------------

class TestDiagnostics:
    def test_round_trip(self):
        bp = Blueprint(
            diagnostics=[
                DiagnosticEntry(
                    file_id="f0", line=5, col=1, end_line=5, end_col=10,
                    severity="error", code="E001", source="pyright",
                    message="Unexpected token",
                ),
            ]
        )
        rt = _rt(bp)
        d = rt.diagnostics[0]
        assert d.file_id == "f0"
        assert d.line == 5
        assert d.end_line == 5
        assert d.severity == "error"
        assert d.code == "E001"
        assert d.source == "pyright"
        assert d.message == "Unexpected token"

    def test_message_with_spaces(self):
        bp = Blueprint(
            diagnostics=[
                DiagnosticEntry(
                    file_id="f0", line=1, col=1, end_line=1, end_col=1,
                    severity="warning", code=None, source="mypy",
                    message="Cannot assign to a method  (extra spaces here)",
                ),
            ]
        )
        rt = _rt(bp)
        assert rt.diagnostics[0].message == "Cannot assign to a method  (extra spaces here)"
        assert rt.diagnostics[0].code is None


# ---------------------------------------------------------------------------
# ModuleEntry (with scoring fields)
# ---------------------------------------------------------------------------

class TestModules:
    def test_basic_l2(self):
        bp = Blueprint(
            modules=[
                ModuleEntry(id="m0", level="L2", name="src.core",
                            root_path="src/core", file_ids=["f0", "f1"]),
            ]
        )
        rt = _rt(bp)
        m = rt.modules[0]
        assert m.id == "m0"
        assert m.level == "L2"
        assert m.name == "src.core"
        assert m.root_path == "src/core"
        assert m.file_ids == ["f0", "f1"]
        assert m.build_kind is None
        assert m.label is None

    def test_l4_with_scoring(self):
        mod = ModuleEntry(id="cl0", level="L4", name="cluster_0",
                          root_path="", file_ids=["f0"],
                          label="Auth & Config",
                          instability=0.75, abstractness=0.5,
                          distance=0.25, ca=2, ce=6)
        bp = Blueprint(modules=[mod])
        rt = _rt(bp)
        m = rt.modules[0]
        assert m.label == "Auth & Config"
        assert m.instability == 0.75
        assert m.abstractness == 0.5
        assert m.distance == 0.25
        assert m.ca == 2
        assert m.ce == 6

    def test_none_scoring_fields(self):
        mod = ModuleEntry(id="cl0", level="L4", name="cluster_0",
                          root_path="", file_ids=["f0"])
        bp = Blueprint(modules=[mod])
        rt = _rt(bp)
        m = rt.modules[0]
        assert m.instability is None
        assert m.abstractness is None
        assert m.distance is None
        assert m.ca is None
        assert m.ce is None

    def test_file_ids_omitted_when_empty(self):
        mod = ModuleEntry(id="m0", level="L2", name="pkg", root_path="")
        raw = blueprint_to_yaml(Blueprint(modules=[mod]))
        doc = yaml.safe_load(raw)
        assert "file_ids" not in doc["modules"][0]


# ---------------------------------------------------------------------------
# CloneBlock
# ---------------------------------------------------------------------------

class TestCloneBlocks:
    def test_round_trip(self):
        bp = Blueprint(
            files=[_fe("f0"), _fe("f1")],
            clone_blocks=[
                CloneBlock(
                    id="dup_0", kind="normalized", lines=15, tokens=75,
                    instances=[
                        CloneInstance(file_id="f0", start_line=1,
                                      end_line=15, hash="a" * 64),
                        CloneInstance(file_id="f1", start_line=5,
                                      end_line=19, hash="a" * 64),
                    ],
                )
            ],
        )
        rt = _rt(bp)
        b = rt.clone_blocks[0]
        assert b.id == "dup_0"
        assert b.kind == "normalized"
        assert b.lines == 15
        assert b.tokens == 75
        assert len(b.instances) == 2
        assert b.instances[0].file_id == "f0"
        assert b.instances[0].start_line == 1
        assert b.instances[0].end_line == 15
        assert b.instances[1].file_id == "f1"
        assert b.instances[1].start_line == 5

    def test_hash_dropped(self):
        """Hash is intentionally omitted in YAML; round-trip produces empty hash."""
        bp = Blueprint(
            files=[_fe("f0"), _fe("f1")],
            clone_blocks=[
                CloneBlock(
                    id="dup_0", kind="exact", lines=5, tokens=20,
                    instances=[
                        CloneInstance(file_id="f0", start_line=1,
                                      end_line=5, hash="b" * 64),
                        CloneInstance(file_id="f1", start_line=1,
                                      end_line=5, hash="b" * 64),
                    ],
                )
            ],
        )
        rt = _rt(bp)
        assert rt.clone_blocks[0].instances[0].hash == ""


# ---------------------------------------------------------------------------
# Status fields and metadata
# ---------------------------------------------------------------------------

class TestMetadata:
    def test_status_fields_preserved(self):
        bp = Blueprint(
            clone_status="complete",
            modularity_status="complete",
            semantic_status="stub",
        )
        rt = _rt(bp)
        assert rt.clone_status == "complete"
        assert rt.modularity_status == "complete"
        assert rt.semantic_status == "stub"

    def test_config_path_and_raw(self):
        bp = Blueprint(
            config_path="/home/user/.comprehensity/config.toml",
            config_raw="[llm]\nbackend = \"none\"\n",
        )
        rt = _rt(bp)
        assert rt.config_path == "/home/user/.comprehensity/config.toml"
        assert rt.config_raw == "[llm]\nbackend = \"none\"\n"

    def test_config_raw_block_scalar_in_yaml(self):
        """Multi-line config_raw at top level should use YAML block scalar."""
        bp = Blueprint(config_raw="[llm]\nbackend = \"none\"\n")
        raw = blueprint_to_yaml(bp)
        assert "config_raw: |" in raw   # block scalar at top level


# ---------------------------------------------------------------------------
# from_file auto-detection
# ---------------------------------------------------------------------------

class TestFromFile:
    def test_yaml_extension_detected(self, tmp_path):
        bp = Blueprint(files=[_fe("f0", path="foo.py")])
        out = tmp_path / "blueprint.yaml"
        out.write_text(blueprint_to_yaml(bp), encoding="utf-8")
        rt = Blueprint.from_file(str(out))
        assert rt.files[0].path == "foo.py"

    def test_json_extension_still_works(self, tmp_path):
        bp = Blueprint(files=[_fe("f0", path="bar.py")])
        out = tmp_path / "blueprint.json"
        out.write_text(bp.to_json() + "\n", encoding="utf-8")
        rt = Blueprint.from_file(str(out))
        assert rt.files[0].path == "bar.py"
