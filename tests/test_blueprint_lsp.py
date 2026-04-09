"""Tests for enrich_blueprint_with_lsp in blueprint_io.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from blueprint import Blueprint, FileEntry, SymbolEntry
from blueprint_io import (
    _find_symbol_at,
    _is_generated_file,
    _is_test_file,
    _uri_to_path,
    enrich_blueprint_with_lsp,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_file(fid: str, path: str, ext: str = ".py") -> FileEntry:
    return FileEntry(id=fid, path=path, size_bytes=100, ext=ext)


def _make_sym(sid: str, fid: str, name: str, kind: str = "function",
              start: int = 1, end: int = 5, exported: bool = False) -> SymbolEntry:
    return SymbolEntry(
        id=sid, file_id=fid, name=name, kind=kind,
        start_line=start, end_line=end, is_exported=exported,
    )


def _mock_client(
    open_files_return=None,
    incoming_calls_return=None,
    references_return=None,
) -> MagicMock:
    """Build a mock LspClient with sensible defaults."""
    client = MagicMock()
    client.open_files.return_value = open_files_return or {}
    client.get_incoming_calls.return_value = incoming_calls_return or []
    client.references.return_value = references_return or []
    return client


def _simple_bp(files=None, symbols=None) -> Blueprint:
    return Blueprint(
        files=files or [],
        symbols=symbols or [],
    )


# ---------------------------------------------------------------------------
# _uri_to_path
# ---------------------------------------------------------------------------

class TestUriToPath:
    def test_strips_file_prefix(self):
        assert _uri_to_path("file:///home/user/foo.py") == "/home/user/foo.py"

    def test_no_prefix_passthrough(self):
        assert _uri_to_path("/absolute/path.py") == "/absolute/path.py"

    def test_empty_string(self):
        assert _uri_to_path("") == ""


# ---------------------------------------------------------------------------
# _is_test_file
# ---------------------------------------------------------------------------

class TestIsTestFile:
    def test_test_prefix(self):
        assert _is_test_file("tests/test_foo.py")

    def test_test_suffix(self):
        assert _is_test_file("src/foo_test.go")

    def test_tests_directory(self):
        assert _is_test_file("tests/utils.py")

    def test_non_test(self):
        assert not _is_test_file("src/main.py")

    def test_non_test_with_test_in_name(self):
        # "contest.py" — "test" appears but not as prefix/suffix marker
        assert not _is_test_file("src/contest.py")


# ---------------------------------------------------------------------------
# _is_generated_file
# ---------------------------------------------------------------------------

class TestIsGeneratedFile:
    def test_proto_pb2(self):
        assert _is_generated_file("src/foo_pb2.py")

    def test_proto_pb2_grpc(self):
        assert _is_generated_file("src/foo_pb2_grpc.py")

    def test_pb_go(self):
        assert _is_generated_file("pkg/api/foo.pb.go")

    def test_pb_ts(self):
        assert _is_generated_file("src/proto/bar.pb.ts")

    def test_explicit_generated_suffix(self):
        assert _is_generated_file("src/schema_generated.py")

    def test_generated_ts_double_ext(self):
        # foo.generated.ts → stem is "foo.generated"
        assert _is_generated_file("src/api/types.generated.ts")

    def test_generated_directory(self):
        assert _is_generated_file("src/generated/client.py")

    def test_graphql_generated_directory(self):
        assert _is_generated_file("src/__generated__/gql.ts")

    def test_non_generated_normal_file(self):
        assert not _is_generated_file("src/main.py")

    def test_non_generated_generate_in_name(self):
        # "generate_report.py" — "generate" in name but not a generated artifact
        assert not _is_generated_file("src/generate_report.py")


# ---------------------------------------------------------------------------
# _find_symbol_at
# ---------------------------------------------------------------------------

class TestFindSymbolAt:
    def _syms(self, *entries):
        from collections import defaultdict
        d = defaultdict(list)
        for sym in entries:
            d[sym.file_id].append(sym)
        return d

    def test_exact_start_line(self):
        sym = _make_sym("s0", "f0", "foo", start=3, end=10)
        d = self._syms(sym)
        assert _find_symbol_at(d, "f0", 3) == "s0"

    def test_exact_end_line(self):
        sym = _make_sym("s0", "f0", "foo", start=3, end=10)
        d = self._syms(sym)
        assert _find_symbol_at(d, "f0", 10) == "s0"

    def test_middle_of_range(self):
        sym = _make_sym("s0", "f0", "foo", start=1, end=20)
        d = self._syms(sym)
        assert _find_symbol_at(d, "f0", 10) == "s0"

    def test_outside_range(self):
        sym = _make_sym("s0", "f0", "foo", start=5, end=10)
        d = self._syms(sym)
        assert _find_symbol_at(d, "f0", 12) is None

    def test_unknown_file_returns_none(self):
        sym = _make_sym("s0", "f0", "foo")
        d = self._syms(sym)
        assert _find_symbol_at(d, "f99", 3) is None

    def test_none_file_id_returns_none(self):
        sym = _make_sym("s0", "f0", "foo")
        d = self._syms(sym)
        assert _find_symbol_at(d, None, 3) is None

    def test_prefers_innermost_symbol(self):
        outer = _make_sym("s0", "f0", "outer", start=1, end=20)
        inner = _make_sym("s1", "f0", "inner", start=5, end=10)
        d = self._syms(outer, inner)
        # line 7 is in both; inner has smaller span → prefer inner
        assert _find_symbol_at(d, "f0", 7) == "s1"

    def test_skips_non_callable_kinds(self):
        cls = _make_sym("s0", "f0", "MyClass", kind="class", start=1, end=20)
        d = self._syms(cls)
        assert _find_symbol_at(d, "f0", 5) is None


# ---------------------------------------------------------------------------
# enrich_blueprint_with_lsp — basic
# ---------------------------------------------------------------------------

class TestEnrichEmpty:
    def test_empty_file_map_returns_original(self):
        bp = _simple_bp(files=[_make_file("f0", "main.py")])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(bp, client, {}, "python")
        assert result is bp
        client.open_files.assert_not_called()

    def test_status_fields_set_to_complete(self):
        f = _make_file("f0", "main.py")
        s = _make_sym("s0", "f0", "foo")
        bp = _simple_bp(files=[f], symbols=[s])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        assert result.semantic_status == "complete"
        assert result.dead_code_status == "complete"
        assert result.diagnostic_status == "complete"

    def test_no_symbols_no_edges(self):
        f = _make_file("f0", "main.py")
        bp = _simple_bp(files=[f])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        assert result.reference_edges == []


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

class TestDiagnostics:
    def _diag(self, sl, sc, el, ec, sev=2, msg="err", src="pyright", code=None):
        d = {
            "range": {
                "start": {"line": sl, "character": sc},
                "end": {"line": el, "character": ec},
            },
            "severity": sev,
            "message": msg,
            "source": src,
        }
        if code is not None:
            d["code"] = code
        return d

    def test_lsp_0based_converted_to_1based(self):
        f = _make_file("f0", "main.py")
        bp = _simple_bp(files=[f])
        uri = "file:///main.py"
        client = _mock_client(open_files_return={uri: [self._diag(0, 0, 0, 5)]})
        result = enrich_blueprint_with_lsp(bp, client, {"f0": uri}, "python")
        assert len(result.diagnostics) == 1
        d = result.diagnostics[0]
        assert d.line == 1
        assert d.col == 1
        assert d.end_line == 1
        assert d.end_col == 6

    def test_severity_mapping(self):
        f = _make_file("f0", "main.py")
        bp = _simple_bp(files=[f])
        uri = "file:///main.py"
        for lsp_sev, expected in [(1, "error"), (2, "warning"), (3, "information"), (4, "hint")]:
            client = _mock_client(open_files_return={uri: [self._diag(0, 0, 0, 1, sev=lsp_sev)]})
            result = enrich_blueprint_with_lsp(bp, client, {"f0": uri}, "python")
            assert result.diagnostics[0].severity == expected

    def test_code_stored_as_string(self):
        f = _make_file("f0", "main.py")
        bp = _simple_bp(files=[f])
        uri = "file:///main.py"
        client = _mock_client(open_files_return={uri: [self._diag(0, 0, 0, 1, code=42)]})
        result = enrich_blueprint_with_lsp(bp, client, {"f0": uri}, "python")
        assert result.diagnostics[0].code == "42"

    def test_unknown_uri_in_push_diags_skipped(self):
        f = _make_file("f0", "main.py")
        bp = _simple_bp(files=[f])
        uri = "file:///main.py"
        client = _mock_client(
            open_files_return={"file:///other.py": [self._diag(0, 0, 0, 1)]}
        )
        result = enrich_blueprint_with_lsp(bp, client, {"f0": uri}, "python")
        assert result.diagnostics == []

    def test_multiple_files_multiple_diagnostics(self):
        f0 = _make_file("f0", "a.py")
        f1 = _make_file("f1", "b.py")
        bp = _simple_bp(files=[f0, f1])
        u0, u1 = "file:///a.py", "file:///b.py"
        client = _mock_client(open_files_return={
            u0: [self._diag(0, 0, 0, 1, msg="e1")],
            u1: [self._diag(2, 0, 2, 5, msg="e2"), self._diag(4, 0, 4, 1, msg="e3")],
        })
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        assert len(result.diagnostics) == 3
        assert {d.file_id for d in result.diagnostics} == {"f0", "f1"}


# ---------------------------------------------------------------------------
# Call hierarchy → ReferenceEdge
# ---------------------------------------------------------------------------

def _call_hierarchy_incoming(from_uri, from_name, sel_line, from_ranges):
    """Build a mock CallHierarchyIncomingCall dict."""
    return {
        "from": {
            "uri": from_uri,
            "name": from_name,
            "selectionRange": {
                "start": {"line": sel_line, "character": 0},
                "end": {"line": sel_line, "character": len(from_name)},
            },
        },
        "fromRanges": [
            {"start": {"line": ln, "character": 0},
             "end":   {"line": ln, "character": 1}}
            for ln in from_ranges
        ],
    }


class TestReferencesToReferenceEdge:
    def test_creates_edge_from_reference_location(self):
        # f0: foo (callee, lines 1-5); f1: bar (caller, lines 1-8)
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bar = _make_sym("s1", "f1", "bar", start=1, end=8)
        bp = _simple_bp(
            files=[_make_file("f0", "a.py"), _make_file("f1", "b.py")],
            symbols=[foo, bar],
        )
        u0, u1 = "file:///a.py", "file:///b.py"
        # querying foo → one reference in b.py at 0-based line 3 → 1-based line 4
        client = _mock_client()
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 0},
                                       "end":   {"line": 3, "character": 3}}}
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        assert len(result.reference_edges) == 1
        e = result.reference_edges[0]
        assert e.from_symbol_id == "s1"   # bar (contains line 4)
        assert e.to_symbol_id == "s0"     # foo
        assert e.call_site_file_id == "f1"
        assert e.call_site_line == 4      # 0-based 3 → 1-based 4

    def test_multiple_reference_locations_produce_multiple_edges(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bar = _make_sym("s1", "f1", "bar", start=1, end=20)
        bp = _simple_bp(
            files=[_make_file("f0", "a.py"), _make_file("f1", "b.py")],
            symbols=[foo, bar],
        )
        u0, u1 = "file:///a.py", "file:///b.py"
        client = _mock_client()
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 0},
                                       "end":   {"line": 3, "character": 3}}},
                {"uri": u1, "range": {"start": {"line": 10, "character": 0},
                                       "end":   {"line": 10, "character": 3}}},
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        # Two reference locations → two ReferenceEdge entries
        assert len(result.reference_edges) == 2
        assert {e.call_site_line for e in result.reference_edges} == {4, 11}

    def test_caller_in_unknown_uri_skipped(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bp = _simple_bp(files=[_make_file("f0", "a.py")], symbols=[foo])
        u0 = "file:///a.py"
        client = _mock_client()
        client.references.return_value = [
            {"uri": "file:///unknown.py",
             "range": {"start": {"line": 2, "character": 0},
                        "end":   {"line": 2, "character": 3}}}
        ]
        result = enrich_blueprint_with_lsp(bp, client, {"f0": u0}, "python")
        # Caller URI not in file_id_to_uri → skip
        assert result.reference_edges == []

    def test_non_callable_symbols_not_queried(self):
        cls = _make_sym("s0", "f0", "MyClass", kind="class", start=1, end=10)
        var = _make_sym("s1", "f0", "MY_VAR", kind="variable", start=12, end=12)
        bp = _simple_bp(files=[_make_file("f0", "a.py")], symbols=[cls, var])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///a.py"}, "python"
        )
        client.references.assert_not_called()

    def test_lsp_exception_falls_through_to_empty(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bp = _simple_bp(files=[_make_file("f0", "a.py")], symbols=[foo])
        client = _mock_client()
        client.references.side_effect = RuntimeError("server crashed")
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///a.py"}, "python"
        )
        # No crash; reference_edges empty
        assert result.reference_edges == []


# ---------------------------------------------------------------------------
# References — edge cases
# ---------------------------------------------------------------------------

class TestReferencesEdgeCases:
    def test_cross_file_reference_produces_edge(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bar = _make_sym("s1", "f1", "bar", start=1, end=8)
        bp = _simple_bp(
            files=[_make_file("f0", "a.py"), _make_file("f1", "b.py")],
            symbols=[foo, bar],
        )
        u0, u1 = "file:///a.py", "file:///b.py"
        client = _mock_client()
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 4},
                                       "end":   {"line": 3, "character": 10}}}
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        assert len(result.reference_edges) == 1
        e = result.reference_edges[0]
        assert e.to_symbol_id == "s0"     # foo (callee)
        assert e.from_symbol_id == "s1"   # bar (caller, contains line 4)
        assert e.call_site_line == 4      # 0-based 3 → 1-based 4

    def test_reference_with_unknown_uri_skipped(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bp = _simple_bp(files=[_make_file("f0", "a.py")], symbols=[foo])
        u0 = "file:///a.py"
        client = _mock_client()
        client.references.return_value = [
            {"uri": "file:///external.py",
             "range": {"start": {"line": 0, "character": 0},
                        "end":   {"line": 0, "character": 3}}},
        ]
        result = enrich_blueprint_with_lsp(bp, client, {"f0": u0}, "python")
        assert result.reference_edges == []

    def test_references_exception_falls_through(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5)
        bp = _simple_bp(files=[_make_file("f0", "a.py")], symbols=[foo])
        client = _mock_client()
        client.references.side_effect = RuntimeError("timeout")
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///a.py"}, "python"
        )
        assert result.reference_edges == []


# ---------------------------------------------------------------------------
# Dead code derivation
# ---------------------------------------------------------------------------

class TestDeadCodeDerivation:
    def test_unreferenced_non_exported_becomes_dead(self):
        foo = _make_sym("s0", "f0", "foo", exported=False)
        bp = _simple_bp(files=[_make_file("f0", "main.py")], symbols=[foo])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        assert len(result.dead_symbols) == 1
        dead = result.dead_symbols[0]
        assert dead.symbol_id == "s0"
        assert dead.confidence == pytest.approx(0.9)
        assert dead.reason == "unreferenced"

    def test_referenced_symbol_not_dead(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5, exported=False)
        bar = _make_sym("s1", "f1", "bar", start=1, end=8)
        bp = _simple_bp(
            files=[_make_file("f0", "a.py"), _make_file("f1", "b.py")],
            symbols=[foo, bar],
        )
        u0, u1 = "file:///a.py", "file:///b.py"
        client = _mock_client()
        # references for foo → one location inside bar (b.py line 4)
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 0},
                                       "end":   {"line": 3, "character": 3}}}
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        dead_ids = {d.symbol_id for d in result.dead_symbols}
        assert "s0" not in dead_ids  # foo has a reference → not dead

    def test_unreferenced_exported_not_dead(self):
        foo = _make_sym("s0", "f0", "foo", exported=True)
        bp = _simple_bp(files=[_make_file("f0", "main.py")], symbols=[foo])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        # Exported with no callers → not reported (could be public API)
        assert result.dead_symbols == []

    def test_exported_called_only_from_test_file_is_test_only(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5, exported=True)
        test_fn = _make_sym("s1", "f1", "test_foo", start=1, end=8)
        bp = _simple_bp(
            files=[_make_file("f0", "src/main.py"), _make_file("f1", "tests/test_main.py")],
            symbols=[foo, test_fn],
        )
        u0, u1 = "file:///src/main.py", "file:///tests/test_main.py"
        client = _mock_client()
        # foo (in src/main.py) is queried; only reference is inside the test file
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 0},
                                       "end":   {"line": 3, "character": 3}}}
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1}, "python"
        )
        test_only = [d for d in result.dead_symbols if d.reason == "test_only"]
        assert len(test_only) == 1
        assert test_only[0].symbol_id == "s0"
        assert test_only[0].confidence == pytest.approx(0.7)

    def test_exported_called_from_prod_and_test_not_dead(self):
        foo = _make_sym("s0", "f0", "foo", start=1, end=5, exported=True)
        caller = _make_sym("s1", "f1", "prod_caller", start=1, end=8)
        test_fn = _make_sym("s2", "f2", "test_foo", start=1, end=5)
        bp = _simple_bp(
            files=[
                _make_file("f0", "src/main.py"),
                _make_file("f1", "src/other.py"),
                _make_file("f2", "tests/test_main.py"),
            ],
            symbols=[foo, caller, test_fn],
        )
        u0 = "file:///src/main.py"
        u1 = "file:///src/other.py"
        u2 = "file:///tests/test_main.py"
        client = _mock_client()
        # foo has references in both prod (u1 line 4) and test (u2 line 3)
        client.references.side_effect = (
            lambda uri, line, char: [
                {"uri": u1, "range": {"start": {"line": 3, "character": 0},
                                       "end":   {"line": 3, "character": 3}}},
                {"uri": u2, "range": {"start": {"line": 2, "character": 0},
                                       "end":   {"line": 2, "character": 3}}},
            ] if uri == u0 else []
        )
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": u0, "f1": u1, "f2": u2}, "python"
        )
        assert all(d.symbol_id != "s0" for d in result.dead_symbols)

    def test_dead_symbols_ids_are_stable(self):
        syms = [_make_sym(f"s{i}", "f0", f"fn{i}", start=i*5+1, end=i*5+4)
                for i in range(3)]
        bp = _simple_bp(files=[_make_file("f0", "main.py")], symbols=syms)
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        ids = [d.id for d in result.dead_symbols]
        assert ids == [f"dead_{i}" for i in range(len(ids))]

    def test_skips_non_callable_for_dead_code(self):
        cls = _make_sym("s0", "f0", "MyClass", kind="class", exported=False)
        bp = _simple_bp(files=[_make_file("f0", "main.py")], symbols=[cls])
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        # Non-callable (class) not included in dead code analysis
        assert result.dead_symbols == []

    def test_existing_dead_symbols_preserved(self):
        from blueprint import DeadSymbol
        foo = _make_sym("s0", "f0", "foo", exported=False)
        existing_dead = DeadSymbol(id="dead_0", symbol_id="s99", confidence=0.5,
                                   reason="unreferenced")
        bp = _simple_bp(files=[_make_file("f0", "main.py")], symbols=[foo])
        bp = bp.model_copy(update={"dead_symbols": [existing_dead]})
        client = _mock_client()
        result = enrich_blueprint_with_lsp(
            bp, client, {"f0": "file:///main.py"}, "python"
        )
        assert any(d.id == "dead_0" for d in result.dead_symbols)
        assert any(d.symbol_id == "s0" for d in result.dead_symbols)
