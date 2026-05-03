"""Tests for experimental linguistic concept signals."""

from blueprint import Blueprint, FileEntry, ModuleEntry, SymbolEntry
from concepts import (
    EXPERIMENT_KEY,
    _simple_stem,
    _split_identifier,
    attach_concept_experiment,
    concept_experiment_payload,
)


def test_simple_stem_porter_lite_cases():
    assert _simple_stem("libraries") == "library"
    assert _simple_stem("boxes") == "box"
    assert _simple_stem("classes") == "class"
    assert _simple_stem("vehicles") == "vehicle"
    assert _simple_stem("values") == "value"
    assert _simple_stem("rules") == "rule"
    assert _simple_stem("languages") == "language"
    assert _simple_stem("fixtures") == "fixture"
    assert _simple_stem("analysis") == "analysis"
    assert _simple_stem("basis") == "basis"
    assert _simple_stem("axis") == "axis"
    assert _simple_stem("status") == "status"
    assert _simple_stem("canvas") == "canvas"
    assert _simple_stem("indices") == "index"
    assert _simple_stem("matrices") == "matrix"
    assert _simple_stem("movies") == "movie"
    assert _simple_stem("series") == "series"
    assert _simple_stem("red") == "red"
    assert _simple_stem("embed") == "embed"
    assert _simple_stem("feed") == "feed"
    assert _simple_stem("string") == "string"
    assert _simple_stem("ping") == "ping"
    assert _simple_stem("ring") == "ring"
    assert _simple_stem("running") == "run"
    assert _simple_stem("loaded") == "load"


def test_identifier_splitting_handles_camel_acronyms_and_underscores():
    assert _split_identifier("HTTPResponseParser") == ["http", "response", "parser"]
    assert _split_identifier("parseHTTPResponse") == ["parse", "http", "response"]
    assert _split_identifier("parse_http_response") == ["parse", "http", "response"]
    assert _split_identifier("initialCamelCase") == ["initial", "camel", "case"]
    assert _split_identifier("InitialCamelCase") == ["initial", "camel", "case"]


def test_identifier_splitting_expands_common_code_abbreviations():
    assert _split_identifier("ctx_cfg_svc") == ["context", "config", "service"]
    assert _split_identifier("reqRespMsgIdx") == ["request", "response", "message", "index"]
    assert _split_identifier("userIDUUIDXMLURL") == ["user", "id", "uuid", "xml", "url"]


def test_identifier_splitting_handles_known_glued_package_words():
    assert _split_identifier("subdomaintestmodule") == ["subdomain"]
    assert _split_identifier("blueprintapp") == ["blueprint"]
    assert _split_identifier("cliapp") == ["cli"]
    assert _split_identifier("multiapp") == ["multi"]
    assert _split_identifier("appctx") == ["context"]
    assert _split_identifier("testserver") == ["server"]
    assert _split_identifier("importerrorapp") == ["import", "error"]
    assert _split_identifier("userguide") == ["user", "guide"]


def test_identifier_splitting_filters_generic_run_noise():
    assert _split_identifier("copyright") == []
    assert _split_identifier("use") == []
    assert _split_identifier("without") == []
    assert _split_identifier("perf") == []


def _bp() -> Blueprint:
    return Blueprint(
        files=[
            FileEntry(
                id="f0",
                path="auth/session_store.py",
                size_bytes=100,
                ext=".py",
                comment_desc="Session token persistence for authentication.",
            ),
            FileEntry(
                id="f1",
                path="auth/token_validator.py",
                size_bytes=120,
                ext=".py",
                comment_desc="Validate authentication tokens.",
            ),
            FileEntry(
                id="f2",
                path="billing/invoice.py",
                size_bytes=80,
                ext=".py",
                comment_desc="Invoice calculation.",
            ),
        ],
        symbols=[
            SymbolEntry(id="s0", file_id="f0", name="SessionStore", kind="class", start_line=1, end_line=10, is_exported=True),
            SymbolEntry(id="s1", file_id="f0", name="save_session_token", kind="function", start_line=12, end_line=14, is_exported=True),
            SymbolEntry(id="s2", file_id="f1", name="TokenValidator", kind="class", start_line=1, end_line=8, is_exported=True),
            SymbolEntry(id="s3", file_id="f1", name="validate_session_token", kind="function", start_line=10, end_line=12, is_exported=False),
            SymbolEntry(id="s5", file_id="f1", name="_refresh_secret_cache", kind="method", start_line=14, end_line=16, is_exported=False),
            SymbolEntry(id="s4", file_id="f2", name="InvoiceCalculator", kind="class", start_line=1, end_line=8, is_exported=True),
        ],
        modules=[
            ModuleEntry(id="m0", level="L2", name="auth", root_path="auth", file_ids=["f0", "f1"]),
            ModuleEntry(id="m1", level="L2", name="billing", root_path="billing", file_ids=["f2"]),
        ],
        modularity_status="complete",
    )


def test_concept_payload_reports_module_clusters():
    payload = concept_experiment_payload(_bp())
    assert payload["schema"] == EXPERIMENT_KEY
    assert payload["status"] == "complete"
    assert payload["cluster_count"] == 2

    auth = next(c for c in payload["clusters"] if c["name"] == "auth")
    assert auth["file_count"] == 2
    assert auth["symbol_count"] == 5
    assert auth["exported_symbol_count"] == 3
    assert auth["private_symbol_count"] == 2
    assert auth["symbol_kind_counts"] == {"class": 2, "function": 2, "method": 1}
    assert auth["dominant_term"] in {"session", "token", "auth", "authentication"}
    assert auth["concept_strength_proxy"] > 0
    assert auth["top_terms"]
    assert auth["symbol_term_evidence"]
    public_terms = {row["term"] for row in auth["top_public_symbol_terms"]}
    private_terms = {row["term"] for row in auth["top_private_symbol_terms"]}
    assert "session" in public_terms
    assert "secret" in private_terms
    assert "cache" in private_terms
    assert any(
        row["kind"] == "method"
        and {term["term"] for term in row["top_terms"]} >= {"refresh", "secret", "cache"}
        for row in auth["top_private_symbol_terms_by_kind"]
    )
    assert any(
        item["name"] == "save_session_token"
        and item["matched_top_terms"]
        and item["file_id"] == "f0"
        and item["visibility"] == "public"
        and item["term_count"] == 3
        for item in auth["symbol_term_evidence"]
    )
    assert payload["candidate_count"] > 0
    assert any(c["term"] == "token" for c in payload["candidates"])


def test_attach_concept_experiment_uses_namespaced_extension_key():
    bp = attach_concept_experiment(_bp())
    assert EXPERIMENT_KEY in bp.x_experimental
    assert bp.x_experimental[EXPERIMENT_KEY]["cluster_count"] == 2
