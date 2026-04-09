"""Tests for blueprint.py — schema construction, round-trip, and validate_refs."""

import json

import pytest
from pydantic import ValidationError

from blueprint import Blueprint, CloneBlock, CloneInstance, DiagnosticEntry, ReferenceEdge, SymbolEntry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

HASH_A = "a" * 64
HASH_B = "b" * 64


def make_instance(file_id: str = "src/foo.py", start: int = 1, end: int = 5, hash: str = HASH_A) -> CloneInstance:
    return CloneInstance(file_id=file_id, start_line=start, end_line=end, hash=hash)


def make_block(**kwargs) -> CloneBlock:
    defaults = dict(
        id="dup_0",
        instances=[make_instance("src/a.py"), make_instance("src/b.py")],
        lines=5,
        tokens=20,
    )
    defaults.update(kwargs)
    return CloneBlock(**defaults)


# ---------------------------------------------------------------------------
# CloneBlock.kind — construction
# ---------------------------------------------------------------------------

class TestCloneBlockKind:
    def test_default_kind_is_exact(self):
        block = make_block()
        assert block.kind == "exact"

    def test_kind_exact(self):
        assert make_block(kind="exact").kind == "exact"

    def test_kind_normalized(self):
        assert make_block(kind="normalized").kind == "normalized"

    def test_kind_approximate(self):
        assert make_block(kind="approximate").kind == "approximate"

    def test_kind_semantic(self):
        assert make_block(kind="semantic").kind == "semantic"

    def test_kind_invalid_rejected(self):
        with pytest.raises(ValidationError):
            make_block(kind="fuzzy")

    def test_kind_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            make_block(kind="")


# ---------------------------------------------------------------------------
# CloneBlock.kind — JSON round-trip
# ---------------------------------------------------------------------------

class TestCloneBlockKindRoundTrip:
    def test_round_trip_normalized(self):
        block = make_block(kind="normalized")
        data = block.model_dump()
        restored = CloneBlock.model_validate(data)
        assert restored.kind == "normalized"

    def test_json_round_trip_approximate(self):
        block = make_block(kind="approximate")
        json_str = block.model_dump_json()
        restored = CloneBlock.model_validate_json(json_str)
        assert restored.kind == "approximate"

    def test_kind_present_in_json(self):
        block = make_block(kind="exact")
        data = json.loads(block.model_dump_json())
        assert "kind" in data
        assert data["kind"] == "exact"


# ---------------------------------------------------------------------------
# validate_refs — CloneBlock with kind
# ---------------------------------------------------------------------------

class TestValidateRefsCloneBlock:
    def _bp_with_blocks(self, blocks):
        """Minimal Blueprint with two real files and provided clone_blocks."""
        from blueprint import Blueprint, FileEntry
        return Blueprint.model_validate({
            "files": [
                {"id": "src/a.py", "path": "src/a.py", "size_bytes": 100, "ext": ".py", "imports": []},
                {"id": "src/b.py", "path": "src/b.py", "size_bytes": 100, "ext": ".py", "imports": []},
            ],
            "clone_blocks": [b.model_dump() for b in blocks],
            "clone_status": "complete",
        })

    def test_valid_clone_block_no_warnings(self):
        block = make_block(kind="normalized")
        bp = self._bp_with_blocks([block])
        assert bp.validate_refs() == []

    def test_unknown_file_id_still_flagged(self):
        inst_bad = make_instance(file_id="src/ghost.py")
        block = CloneBlock(
            id="dup_0", kind="exact",
            instances=[make_instance("src/a.py"), inst_bad],
            lines=5, tokens=10,
        )
        bp = self._bp_with_blocks([block])
        warnings = bp.validate_refs()
        assert any("ghost.py" in w for w in warnings)

    def test_differing_hashes_still_flagged(self):
        inst_a = make_instance("src/a.py", hash=HASH_A)
        inst_b = make_instance("src/b.py", hash=HASH_B)
        block = CloneBlock(
            id="dup_0", kind="approximate",
            instances=[inst_a, inst_b],
            lines=5, tokens=10,
        )
        bp = self._bp_with_blocks([block])
        warnings = bp.validate_refs()
        assert any("differing hashes" in w for w in warnings)


# ---------------------------------------------------------------------------
# DiagnosticEntry — construction and validation
# ---------------------------------------------------------------------------

def _diag(**kwargs) -> DiagnosticEntry:
    defaults = dict(
        file_id="f0",
        line=3, col=1, end_line=3, end_col=20,
        severity="error",
        message="Name 'foo' is not defined",
        source="pyright",
    )
    defaults.update(kwargs)
    return DiagnosticEntry(**defaults)


class TestDiagnosticEntry:
    def test_minimal_construction(self):
        d = _diag()
        assert d.severity == "error"
        assert d.code is None

    def test_all_severities_accepted(self):
        for sev in ("error", "warning", "information", "hint"):
            assert _diag(severity=sev).severity == sev

    def test_invalid_severity_rejected(self):
        with pytest.raises(ValidationError):
            _diag(severity="critical")

    def test_code_stored(self):
        d = _diag(code="reportMissingImports")
        assert d.code == "reportMissingImports"

    def test_end_line_before_line_rejected(self):
        with pytest.raises(ValidationError):
            _diag(line=5, end_line=3)

    def test_same_line_accepted(self):
        d = _diag(line=5, end_line=5)
        assert d.end_line == 5

    def test_json_round_trip(self):
        d = _diag(severity="warning", code="W0611", message="unused import")
        restored = DiagnosticEntry.model_validate_json(d.model_dump_json())
        assert restored.severity == "warning"
        assert restored.code == "W0611"


# ---------------------------------------------------------------------------
# ReferenceEdge — call_site_file_id field
# ---------------------------------------------------------------------------

class TestReferenceEdge:
    def test_call_site_file_id_stored(self):
        edge = ReferenceEdge(
            from_symbol_id="s0",
            to_symbol_id="s1",
            call_site_file_id="f0",
            call_site_line=10,
        )
        assert edge.call_site_file_id == "f0"

    def test_missing_call_site_file_id_rejected(self):
        with pytest.raises(ValidationError):
            ReferenceEdge(
                from_symbol_id="s0",
                to_symbol_id="s1",
                call_site_line=10,
            )


# ---------------------------------------------------------------------------
# validate_refs — DiagnosticEntry and ReferenceEdge.call_site_file_id
# ---------------------------------------------------------------------------

def _minimal_bp(**overrides):
    """Two-file blueprint; accepts field overrides."""
    data = {
        "files": [
            {"id": "f0", "path": "src/a.py", "size_bytes": 10, "ext": ".py"},
            {"id": "f1", "path": "src/b.py", "size_bytes": 10, "ext": ".py"},
        ],
    }
    data.update(overrides)
    return Blueprint.model_validate(data)


def _sym(sym_id, file_id, start=1, end=5):
    return {"id": sym_id, "file_id": file_id, "name": "fn", "kind": "function",
            "start_line": start, "end_line": end}


class TestValidateRefsDiagnostics:
    def test_valid_diagnostic_no_warning(self):
        bp = _minimal_bp(diagnostics=[_diag(file_id="f0").model_dump()])
        assert bp.validate_refs() == []

    def test_unknown_file_id_flagged(self):
        bp = _minimal_bp(diagnostics=[_diag(file_id="ghost").model_dump()])
        warns = bp.validate_refs()
        assert any("ghost" in w for w in warns)

    def test_multiple_diagnostics_multiple_unknown(self):
        diags = [
            _diag(file_id="f0").model_dump(),
            _diag(file_id="bad1").model_dump(),
            _diag(file_id="bad2").model_dump(),
        ]
        bp = _minimal_bp(diagnostics=diags)
        warns = bp.validate_refs()
        assert any("bad1" in w for w in warns)
        assert any("bad2" in w for w in warns)


class TestValidateRefsReferenceEdge:
    def test_valid_edge_no_warning(self):
        bp = _minimal_bp(
            symbols=[_sym("s0", "f0"), _sym("s1", "f1")],
            reference_edges=[{
                "from_symbol_id": "s0", "to_symbol_id": "s1",
                "call_site_file_id": "f0", "call_site_line": 3,
            }],
        )
        assert bp.validate_refs() == []

    def test_unknown_call_site_file_id_flagged(self):
        bp = _minimal_bp(
            symbols=[_sym("s0", "f0"), _sym("s1", "f1")],
            reference_edges=[{
                "from_symbol_id": "s0", "to_symbol_id": "s1",
                "call_site_file_id": "ghost", "call_site_line": 3,
            }],
        )
        warns = bp.validate_refs()
        assert any("call_site_file_id" in w and "ghost" in w for w in warns)
