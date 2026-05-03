"""Tests for experimental linguistic concept signals."""

from blueprint import Blueprint, FileEntry, ModuleEntry, SymbolEntry
from concepts import (
    EXPERIMENT_KEY,
    _boundary_violations,
    _coherence_distribution,
    _is_test_file,
    _simple_stem,
    _split_identifier,
    _test_oracle,
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


# --- depth_ratio ---

def test_concept_payload_depth_ratio():
    # auth (m0): 3 exported, 2 private  → depth_ratio = round(2/3, 2) = 0.67
    # billing (m1): 1 exported, 0 private → depth_ratio = 0.0
    payload = concept_experiment_payload(_bp())
    auth = next(c for c in payload["clusters"] if c["name"] == "auth")
    billing = next(c for c in payload["clusters"] if c["name"] == "billing")
    assert auth["depth_ratio"] == round(2 / 3, 4)
    assert billing["depth_ratio"] == 0.0


# --- coherence_distribution ---

def test_concept_payload_coherence_distribution_is_well_formed():
    payload = concept_experiment_payload(_bp())
    dist = payload["coherence_distribution"]
    assert dist["cluster_count"] == 2
    assert 0.0 <= dist["p25"] <= dist["p50"] <= dist["p75"] <= 1.0
    assert 0.0 <= dist["mean"] <= 1.0


def test_coherence_distribution_single_cluster():
    dist = _coherence_distribution([{"level": "L2", "concept_strength_proxy": 0.6}])
    assert dist == {"p25": 0.6, "p50": 0.6, "p75": 0.6, "mean": 0.6, "cluster_count": 1}


def test_coherence_distribution_ignores_non_l2_clusters():
    clusters = [
        {"level": "L2", "concept_strength_proxy": 0.8},
        {"level": "L3", "concept_strength_proxy": 0.1},  # should be ignored
    ]
    dist = _coherence_distribution(clusters)
    assert dist["cluster_count"] == 1
    assert dist["p50"] == 0.8


# --- concept_aligned / alignment_gap ---

def test_concept_payload_alignment_fields_present():
    payload = concept_experiment_payload(_bp())
    for cluster in payload["clusters"]:
        assert "concept_aligned" in cluster
        assert "alignment_gap" in cluster
        if cluster["concept_aligned"]:
            assert cluster["alignment_gap"] is None
        else:
            assert cluster["alignment_gap"] == cluster["dominant_term"]


# --- _is_test_file ---

def _fe(path: str, ext: str = ".py") -> FileEntry:
    return FileEntry(id="x", path=path, size_bytes=0, ext=ext)


def test_is_test_file_detects_jest_and_dotspec_patterns():
    # __tests__ directory (Jest)
    assert _is_test_file(_fe("src/__tests__/auth.ts", ".ts"))
    assert _is_test_file(_fe("__tests__/auth.ts", ".ts"))
    # .spec. double-extension (Jasmine / Angular / Vitest)
    assert _is_test_file(_fe("src/auth.spec.ts", ".ts"))
    assert _is_test_file(_fe("src/auth.spec.js", ".js"))
    assert _is_test_file(_fe("src/auth.spec.tsx", ".tsx"))
    # .test. double-extension (Jest / Vitest)
    assert _is_test_file(_fe("src/auth.test.ts", ".ts"))
    assert _is_test_file(_fe("src/auth.test.jsx", ".jsx"))
    # existing patterns still work
    assert _is_test_file(_fe("tests/auth.py"))
    assert _is_test_file(_fe("test/auth.py"))
    assert _is_test_file(_fe("spec/auth.rb", ".rb"))
    assert _is_test_file(_fe("test_auth.py"))
    assert _is_test_file(_fe("auth_test.py"))
    # non-test files are not flagged
    assert not _is_test_file(_fe("src/auth.ts", ".ts"))
    assert not _is_test_file(_fe("src/auth_service.ts", ".ts"))
    assert not _is_test_file(_fe("latest.ts", ".ts"))


# --- _boundary_violations ---

def _two_cluster_setup():
    """Auth + billing clusters with a misplaced billing file in auth."""
    auth_file = FileEntry(
        id="f0", path="auth/session.py", size_bytes=100, ext=".py",
        comment_desc="Session token authentication.",
    )
    misplaced = FileEntry(
        id="f1", path="auth/invoice_handler.py", size_bytes=100, ext=".py",
        comment_desc="Invoice payment billing calculation.",
    )
    billing_file = FileEntry(
        id="f2", path="billing/invoice.py", size_bytes=100, ext=".py",
        comment_desc="Invoice payment billing.",
    )
    clusters = [
        {"cluster_id": "m0", "name": "auth",
         "top_terms": [{"term": "session"}, {"term": "token"}, {"term": "authentication"}]},
        {"cluster_id": "m1", "name": "billing",
         "top_terms": [{"term": "invoice"}, {"term": "payment"}, {"term": "billing"}]},
    ]
    modules = [
        ModuleEntry(id="m0", level="L2", name="auth", root_path="auth", file_ids=["f0", "f1"]),
        ModuleEntry(id="m1", level="L2", name="billing", root_path="billing", file_ids=["f2"]),
    ]
    file_by_id = {"f0": auth_file, "f1": misplaced, "f2": billing_file}
    return clusters, file_by_id, modules


def test_boundary_violations_flags_misplaced_file():
    clusters, file_by_id, modules = _two_cluster_setup()
    violations = _boundary_violations(clusters, file_by_id, modules)
    violation_paths = {v["path"] for v in violations}
    assert "auth/invoice_handler.py" in violation_paths


def test_boundary_violations_result_structure():
    clusters, file_by_id, modules = _two_cluster_setup()
    violations = _boundary_violations(clusters, file_by_id, modules)
    for v in violations:
        assert {"file_id", "path", "home_cluster_id", "home_cluster_name",
                "foreign_cluster_id", "foreign_cluster_name",
                "home_overlap", "foreign_overlap"} <= v.keys()
        assert v["foreign_overlap"] > v["home_overlap"]


# --- _test_oracle ---

def test_test_oracle_detects_vocabulary_drift():
    test_file = FileEntry(
        id="t0", path="tests/test_billing.py", size_bytes=100, ext=".py",
        comment_desc="Invoice payment tests.",
    )
    auth_file = FileEntry(id="f0", path="auth/session.py", size_bytes=100, ext=".py")
    clusters = [
        {"cluster_id": "m0", "name": "auth",
         "top_terms": [{"term": "session"}, {"term": "token"}, {"term": "authentication"}]},
        {"cluster_id": "m1", "name": "billing",
         "top_terms": [{"term": "invoice"}, {"term": "payment"}, {"term": "billing"}]},
    ]
    modules = [
        ModuleEntry(id="m0", level="L2", name="auth", root_path="auth", file_ids=["f0", "t0"]),
        ModuleEntry(id="m1", level="L2", name="billing", root_path="billing", file_ids=[]),
    ]
    file_by_id = {"f0": auth_file, "t0": test_file}

    result = _test_oracle(clusters, file_by_id, modules)
    assert result["test_file_count"] == 1
    mismatch_paths = {m["path"] for m in result["mismatches"]}
    assert "tests/test_billing.py" in mismatch_paths


def test_test_oracle_returns_empty_when_no_test_files():
    clusters = [
        {"cluster_id": "m0", "name": "auth",
         "top_terms": [{"term": "session"}, {"term": "token"}]},
    ]
    modules = [ModuleEntry(id="m0", level="L2", name="auth", root_path="auth", file_ids=["f0"])]
    src_file = FileEntry(id="f0", path="auth/session.py", size_bytes=100, ext=".py")
    result = _test_oracle(clusters, {"f0": src_file}, modules)
    assert result["test_file_count"] == 0
    assert result["mismatches"] == []
