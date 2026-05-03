"""Experimental linguistic concept signals for blueprint modules.

This module deliberately produces raw evidence, not production judgments. Phase 2
can use the namespaced payload to evaluate whether module/cluster vocabulary is
coherent enough to act like an architectural concept.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

from blueprint import Blueprint, FileEntry, ModuleEntry, SymbolEntry


EXPERIMENT_KEY = "comprehensity.concepts.v0"

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_IDENT_PART_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|[0-9]|\b)|[A-Z]?[a-z]+|[0-9]+"
)
_STOPWORDS = {
    "a", "after", "all", "an", "and", "any", "api", "app", "as", "author", "base",
    "before", "by", "cmd", "common", "core", "copyright", "data", "def", "default", "distribut",
    "file", "for", "from", "get", "impl", "in", "init", "internal", "is", "licens",
    "license", "main", "manager", "model", "module", "new", "not", "object", "of",
    "on", "one", "or", "package", "perf", "pkg", "rust", "set", "software", "src",
    "test", "tests", "the", "to", "type", "types", "under", "use", "util", "utils",
    "value", "with", "without",
}
_STEM_EXCEPTIONS = {
    # -s endings that are not ordinary plurals.
    "analysis", "axis", "basis", "canvas", "status",
    # -es endings that should not be shaved.
    "series", "species",
    # -ed endings that are complete words.
    "embed", "feed", "red",
    # -ing endings that are complete words.
    "ping", "ring", "string",
}
_IRREGULAR_STEMS = {
    "indices": "index",
    "matrices": "matrix",
    "movies": "movie",
}
_ABBREVIATIONS = {
    "cfg": "config",
    "cli": "cli",
    "cpu": "cpu",
    "ctx": "context",
    "gpu": "gpu",
    "http": "http",
    "id": "id",
    "idx": "index",
    "msg": "message",
    "req": "request",
    "resp": "response",
    "rsp": "response",
    "svc": "service",
    "url": "url",
    "uuid": "uuid",
    "xml": "xml",
}
_COMPOUND_PARTS = tuple(
    sorted(
        {
            # Original set
            "admin", "app", "apps", "blueprint", "cli", "domain", "error",
            "frontend", "guide", "import", "inner", "module", "multi",
            "server", "subdomain", "test", "user",
            # Generic architectural / infra words (appear as prefixes in glued identifiers)
            # e.g. errorhandler, pluginregistry, querybuilder, cachestore, eventhandler
            "action", "annotation", "attention", "backend", "builder", "cache",
            "client", "cluster", "config", "connector", "dispatcher", "embedding",
            "engine", "event", "executor", "factory", "filter", "graph", "handler",
            "index", "integration", "listener", "locale", "logger", "message",
            "middleware", "migration", "pipeline", "plugin", "processor", "provider",
            "proxy", "query", "queue", "registry", "resolver", "router", "scheduler",
            "schema", "search", "security", "serializer", "service", "template",
            "token", "transform", "validator", "worker",
            *_ABBREVIATIONS.keys(),
        },
        key=len,
        reverse=True,
    )
)
_ACRONYM_KEYS = tuple(
    sorted(
        (k for k in _ABBREVIATIONS if k == _ABBREVIATIONS[k]),
        key=len,
        reverse=True,
    )
)


def _split_known_acronyms(part: str) -> list[str]:
    """Split adjacent all-caps known acronyms, e.g. IDUUIDXMLURL."""
    if not part.isupper() or len(part) <= 2:
        return [part]
    lower = part.lower()
    out: list[str] = []
    i = 0
    while i < len(lower):
        match = next((key for key in _ACRONYM_KEYS if lower.startswith(key, i)), None)
        if match is None:
            return [part]
        out.append(match)
        i += len(match)
    return out


def _split_known_compound(part: str) -> list[str]:
    """Split glued lowercase package words like subdomaintestmodule."""
    if not part.islower() or len(part) < 5:
        return [part]
    out: list[str] = []
    i = 0
    while i < len(part):
        match = next((key for key in _COMPOUND_PARTS if part.startswith(key, i)), None)
        if match is None:
            # Only keep a remainder that's long enough to be a real word fragment.
            # Short remainders (e.g. "onse" from "resp"+"onse" in "response") are
            # abbreviation-prefix artifacts, not genuine split words.
            if len(part[i:]) >= 5:
                out.append(part[i:])
            break
        out.append(match)
        i += len(match)
    return out if len(out) > 1 else [part]


def _simple_stem(word: str) -> str:
    """Poor-man's Porter-lite stemmer for plural/past/progressive suffixes."""
    if word in _ABBREVIATIONS:
        return _ABBREVIATIONS[word]
    if word in _STEM_EXCEPTIONS:
        return word
    if word in _IRREGULAR_STEMS:
        return _IRREGULAR_STEMS[word]
    if re.search(r"[^aeiou]ies$", word):
        return re.sub(r"ies$", "y", word)
    if re.search(r"(sses|xes|ches|shes)$", word):
        return re.sub(r"es$", "", word)
    if re.search(r"s$", word) and not re.search(r"(ss|sis|us)$", word):
        return re.sub(r"s$", "", word)
    if re.search(r"(ing|ed)$", word) and len(word) > 5:
        stem = re.sub(r"(ing|ed)$", "", word)
        if len(stem) >= 3 and stem[-1] == stem[-2] and stem[-1] not in "aeiou":
            stem = stem[:-1]
        return stem
    return word


def _split_identifier(text: str) -> list[str]:
    parts: list[str] = []
    for raw in _TOKEN_RE.findall(text.replace("_", " ").replace("-", " ")):
        for part in _IDENT_PART_RE.findall(raw):
            for acronym_part in _split_known_acronyms(part):
                parts.extend(_split_known_compound(acronym_part.lower()))
    tokens: list[str] = []
    for part in parts:
        normalized = _normalize_token(part)
        if normalized:
            tokens.append(normalized)
    return tokens


def _normalize_token(token: str) -> str:
    token = token.lower()
    if token in _ABBREVIATIONS:
        return _ABBREVIATIONS[token]
    if len(token) <= 2 or token in _STOPWORDS:
        return ""
    token = _simple_stem(token)
    if len(token) <= 2:
        return ""
    return "" if token in _STOPWORDS else token


def _entropy(counter: Counter[str]) -> float:
    total = sum(counter.values())
    if total <= 0:
        return 0.0
    return -sum((n / total) * math.log2(n / total) for n in counter.values())


def _round(value: float) -> float:
    return round(value, 4)


def _symbols_for_files(symbols: Iterable[SymbolEntry], file_ids: set[str]) -> list[SymbolEntry]:
    return [sym for sym in symbols if sym.file_id in file_ids]


def _tokens_in_symbol(sym: SymbolEntry) -> set[str]:
    return set(_split_identifier(sym.name))


def _symbol_term_evidence(
    symbols: list[SymbolEntry],
    top_terms: list[dict],
) -> list[dict]:
    """Return compact per-symbol linguistic evidence for a cluster."""
    focus_terms = {t["term"] for t in top_terms[:8]}
    evidence: list[dict] = []
    for sym in symbols:
        tokens = sorted(_tokens_in_symbol(sym))
        matches = sorted(focus_terms & set(tokens))
        if not tokens:
            continue
        evidence.append({
            "symbol_id": sym.id,
            "file_id": sym.file_id,
            "name": sym.name,
            "kind": sym.kind,
            "start_line": sym.start_line,
            "end_line": sym.end_line,
            "is_exported": sym.is_exported,
            "visibility": "public" if sym.is_exported else "private",
            "terms": tokens,
            "term_count": len(tokens),
            "matched_top_terms": matches,
            "matched_top_term_count": len(matches),
        })
    evidence.sort(
        key=lambda item: (
            -len(item["matched_top_terms"]),
            not item["is_exported"],
            item["name"],
            item["symbol_id"],
        )
    )
    return evidence[:16]


def _term_rows(
    counter: Counter[str],
    sources: dict[str, set[str]] | None = None,
    *,
    limit: int = 8,
) -> list[dict]:
    rows: list[dict] = []
    for term, weight in counter.most_common(limit):
        row = {"term": term, "weight": weight}
        if sources is not None:
            row["sources"] = sorted(sources[term])
        rows.append(row)
    return rows


def _kind_term_rows(
    counters: dict[str, Counter[str]],
    *,
    limit_kinds: int = 8,
    limit_terms: int = 8,
) -> list[dict]:
    rows: list[dict] = []
    for kind, counter in sorted(
        counters.items(),
        key=lambda item: (-sum(item[1].values()), item[0]),
    )[:limit_kinds]:
        rows.append({
            "kind": kind,
            "symbol_count": sum(counter.values()),
            "top_terms": _term_rows(counter, limit=limit_terms),
        })
    return rows


def _tokens_in_file(fe: FileEntry) -> set[str]:
    tokens = set(_split_identifier(Path(fe.path).stem))
    for part in Path(fe.path).parts[:-1]:
        tokens.update(_split_identifier(part))
    if fe.comment_desc:
        tokens.update(_split_identifier(fe.comment_desc))
    return tokens


_TEST_PATH_RE = re.compile(r"(?:^|/)(?:tests?|spec|__tests__)/")


def _is_test_file(fe: FileEntry) -> bool:
    stem = Path(fe.path).stem
    name = Path(fe.path).name
    return (
        bool(_TEST_PATH_RE.search(fe.path))
        or stem.startswith("test_")
        or stem.endswith("_test")
        or stem.endswith("_spec")
        or ".spec." in name   # foo.spec.ts, foo.spec.js
        or ".test." in name   # foo.test.ts, foo.test.js
    )


def _coherence_distribution(clusters: list[dict]) -> dict:
    """p25/p50/p75/mean of concept_strength_proxy across module-level clusters.

    Uses L2 (graph-detected) clusters when available; falls back to L3
    (directory-based) for repos where Louvain produces no communities.
    """
    l2 = [c["concept_strength_proxy"] for c in clusters if c["level"] == "L2"]
    if not l2:
        l2 = [c["concept_strength_proxy"] for c in clusters if c["level"] == "L3"]
    if not l2:
        return {"p25": 0.0, "p50": 0.0, "p75": 0.0, "mean": 0.0, "cluster_count": 0}
    if len(l2) == 1:
        v = _round(l2[0])
        return {"p25": v, "p50": v, "p75": v, "mean": v, "cluster_count": 1}
    qs = statistics.quantiles(l2, n=4)
    return {
        "p25": _round(qs[0]),
        "p50": _round(statistics.median(l2)),
        "p75": _round(qs[2]),
        "mean": _round(statistics.mean(l2)),
        "cluster_count": len(l2),
    }


def _boundary_violations(
    clusters: list[dict],
    file_by_id: dict[str, FileEntry],
    modules: list[ModuleEntry],
) -> list[dict]:
    """Files whose vocabulary aligns better with a foreign cluster than their own."""
    file_to_cluster: dict[str, str] = {}
    for mod in modules:
        for fid in mod.file_ids:
            file_to_cluster[fid] = mod.id

    cluster_terms: dict[str, set[str]] = {
        c["cluster_id"]: {row["term"] for row in c["top_terms"][:8]}
        for c in clusters
    }
    cluster_names: dict[str, str] = {c["cluster_id"]: c["name"] for c in clusters}

    violations: list[dict] = []
    for file_id, fe in file_by_id.items():
        home_cid = file_to_cluster.get(file_id)
        if not home_cid:
            continue
        file_vocab = _tokens_in_file(fe)
        if not file_vocab:
            continue

        home_terms = cluster_terms.get(home_cid, set())
        union = file_vocab | home_terms
        home_overlap = len(file_vocab & home_terms) / len(union) if union else 0.0

        best_foreign_cid: str | None = None
        best_foreign_overlap = 0.0
        for cid, terms in cluster_terms.items():
            if cid == home_cid or not terms:
                continue
            u = file_vocab | terms
            overlap = len(file_vocab & terms) / len(u) if u else 0.0
            if overlap > best_foreign_overlap:
                best_foreign_overlap = overlap
                best_foreign_cid = cid

        if best_foreign_cid and best_foreign_overlap > home_overlap + 0.1:
            violations.append({
                "file_id": file_id,
                "path": fe.path,
                "home_cluster_id": home_cid,
                "home_cluster_name": cluster_names.get(home_cid, ""),
                "foreign_cluster_id": best_foreign_cid,
                "foreign_cluster_name": cluster_names.get(best_foreign_cid, ""),
                "home_overlap": _round(home_overlap),
                "foreign_overlap": _round(best_foreign_overlap),
            })

    violations.sort(key=lambda v: -(v["foreign_overlap"] - v["home_overlap"]))
    return violations


def _test_oracle(
    clusters: list[dict],
    file_by_id: dict[str, FileEntry],
    modules: list[ModuleEntry],
) -> dict:
    """Compare test file vocabulary to source cluster vocabulary.

    Test file names were written to describe what they test — treat them as
    ground truth for concept presence. Vocabulary drift is expected over time;
    weight this as a weak signal.
    """
    file_to_cluster: dict[str, str] = {}
    for mod in modules:
        for fid in mod.file_ids:
            file_to_cluster[fid] = mod.id

    cluster_terms: dict[str, set[str]] = {
        c["cluster_id"]: {row["term"] for row in c["top_terms"][:8]}
        for c in clusters
    }
    cluster_names: dict[str, str] = {c["cluster_id"]: c["name"] for c in clusters}

    test_files = [fe for fe in file_by_id.values() if _is_test_file(fe)]
    if not test_files or not cluster_terms:
        return {"test_file_count": 0, "matched_count": 0, "unmatched_count": 0, "mismatches": []}

    matched = 0
    unmatched = 0
    mismatches: list[dict] = []

    for fe in test_files:
        file_vocab = _tokens_in_file(fe)
        if not file_vocab:
            unmatched += 1
            continue

        best_cid: str | None = None
        best_overlap = 0.0
        for cid, terms in cluster_terms.items():
            if not terms:
                continue
            u = file_vocab | terms
            overlap = len(file_vocab & terms) / len(u) if u else 0.0
            if overlap > best_overlap:
                best_overlap = overlap
                best_cid = cid

        if best_cid is None or best_overlap == 0.0:
            unmatched += 1
            continue

        home_cid = file_to_cluster.get(fe.id)
        if home_cid is None or home_cid == best_cid:
            matched += 1
        else:
            mismatches.append({
                "file_id": fe.id,
                "path": fe.path,
                "structural_cluster_id": home_cid,
                "structural_cluster_name": cluster_names.get(home_cid, ""),
                "vocabulary_cluster_id": best_cid,
                "vocabulary_cluster_name": cluster_names.get(best_cid, ""),
                "overlap": _round(best_overlap),
            })
            matched += 1

    mismatches.sort(key=lambda m: -m["overlap"])
    return {
        "test_file_count": len(test_files),
        "matched_count": matched,
        "unmatched_count": unmatched,
        "mismatches": mismatches,
    }


def _cluster_payload(
    module: ModuleEntry,
    file_by_id: dict[str, FileEntry],
    symbols: list[SymbolEntry],
) -> dict:
    file_ids = set(module.file_ids)
    cluster_files = [file_by_id[fid] for fid in module.file_ids if fid in file_by_id]
    cluster_symbols = _symbols_for_files(symbols, file_ids)
    exported_symbols = [sym for sym in cluster_symbols if sym.is_exported]

    # counts drives concept detection (dominant term, entropy, concept_strength_proxy).
    # Reporting counters (symbol_counts etc.) preserve raw frequencies for evidence output.
    counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    public_symbol_counts: Counter[str] = Counter()
    private_symbol_counts: Counter[str] = Counter()
    symbol_kind_counts: Counter[str] = Counter()
    symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    public_symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    private_symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    sources: dict[str, set[str]] = defaultdict(set)
    # Set-based presence counters: how many symbols of each visibility mention each term.
    # Used for normalized concept detection — cluster size does not inflate term weight.
    public_term_presence: Counter[str] = Counter()
    private_term_presence: Counter[str] = Counter()

    # Module name: fixed budget spread evenly across unique tokens.
    module_tokens = set(_split_identifier(module.name))
    module_budget = 3.0 / len(module_tokens) if module_tokens else 0.0
    for term in module_tokens:
        counts[term] += module_budget
        sources[term].add("module")

    for fe in cluster_files:
        for term in _split_identifier(Path(fe.path).stem):
            counts[term] += 2
            sources[term].add("file")
        for part in Path(fe.path).parts[:-1]:
            for term in _split_identifier(part):
                counts[term] += 1
                sources[term].add("path")
        if fe.comment_desc:
            for term in _split_identifier(fe.comment_desc):
                counts[term] += 1
                sources[term].add("comment")

    for sym in cluster_symbols:
        symbol_kind_counts[sym.kind] += 1
        sym_terms_list = _split_identifier(sym.name)
        sym_terms_set = set(sym_terms_list)
        # Raw list-based counts for reporting evidence.
        for term in sym_terms_list:
            symbol_counts[term] += 1
            symbol_kind_term_counts[sym.kind][term] += 1
            if sym.is_exported:
                public_symbol_counts[term] += 1
                public_symbol_kind_term_counts[sym.kind][term] += 1
            else:
                private_symbol_counts[term] += 1
                private_symbol_kind_term_counts[sym.kind][term] += 1
        # Set-based presence for normalized concept detection.
        for term in sym_terms_set:
            if sym.is_exported:
                public_term_presence[term] += 1
            else:
                private_term_presence[term] += 1
            sources[term].add("symbol")

    # Normalize symbol contributions: fixed budgets per visibility class,
    # weighted by the fraction of symbols mentioning each term.
    # A 5-symbol and a 500-symbol cluster contribute equal total symbol weight.
    # Public symbols outweigh private: interface vocabulary defines the module's concept.
    _PUBLIC_BUDGET = 4.0
    _PRIVATE_BUDGET = 1.0
    n_public = len(exported_symbols)
    n_private = len(cluster_symbols) - n_public
    for term, cnt in public_term_presence.items():
        counts[term] += _PUBLIC_BUDGET * (cnt / n_public) if n_public else 0.0
    for term, cnt in private_term_presence.items():
        counts[term] += _PRIVATE_BUDGET * (cnt / n_private) if n_private else 0.0

    token_total = sum(counts.values())
    unique_tokens = len(counts)
    top_terms = _term_rows(counts, sources)
    top_symbol_terms = _term_rows(symbol_counts)
    top_public_symbol_terms = _term_rows(public_symbol_counts)
    top_private_symbol_terms = _term_rows(private_symbol_counts)
    dominant = top_terms[0]["term"] if top_terms else None
    dominance = (top_terms[0]["weight"] / token_total) if top_terms and token_total else 0.0
    max_entropy = math.log2(unique_tokens) if unique_tokens > 1 else 1.0
    normalized_entropy = _entropy(counts) / max_entropy if max_entropy else 0.0
    vocabulary_tightness = 1.0 - normalized_entropy

    public_symbol_ratio = (
        len(exported_symbols) / len(cluster_symbols) if cluster_symbols else 0.0
    )

    if dominant:
        naming_consistency = (
            sum(1 for sym in cluster_symbols if dominant in _tokens_in_symbol(sym))
            / len(cluster_symbols)
            if cluster_symbols else 0.0
        )
        public_naming_consistency = (
            sum(1 for sym in exported_symbols if dominant in _tokens_in_symbol(sym))
            / len(exported_symbols)
            if exported_symbols else 0.0
        )
        file_coverage = (
            sum(1 for fe in cluster_files if dominant in _tokens_in_file(fe))
            / len(cluster_files)
            if cluster_files else 0.0
        )
    else:
        naming_consistency = 0.0
        public_naming_consistency = 0.0
        file_coverage = 0.0

    concept_strength_proxy = (
        0.35 * vocabulary_tightness
        + 0.25 * dominance
        + 0.20 * naming_consistency
        + 0.20 * file_coverage
    )

    # Ousterhout depth: high ratio = narrow interface + rich internals = easier agent scoping.
    # 0.0 when no exported symbols (no declared interface; treat as maximally shallow).
    depth_ratio = _round(n_private / n_public) if n_public else 0.0

    # Alignment: does the module's name reflect its dominant vocabulary concept?
    concept_aligned = (dominant is None) or (dominant in module_tokens)
    alignment_gap = None if concept_aligned else dominant

    return {
        "cluster_id": module.id,
        "level": module.level,
        "name": module.name,
        "root_path": module.root_path,
        "file_count": len(cluster_files),
        "symbol_count": len(cluster_symbols),
        "exported_symbol_count": len(exported_symbols),
        "private_symbol_count": len(cluster_symbols) - len(exported_symbols),
        "depth_ratio": depth_ratio,
        "public_symbol_ratio": _round(public_symbol_ratio),
        "concept_aligned": concept_aligned,
        "alignment_gap": alignment_gap,
        "symbol_kind_counts": dict(sorted(symbol_kind_counts.items())),
        "token_count": token_total,
        "unique_token_count": unique_tokens,
        "normalized_entropy": _round(normalized_entropy),
        "vocabulary_tightness": _round(vocabulary_tightness),
        "dominant_term": dominant,
        "dominance": _round(dominance),
        "naming_consistency": _round(naming_consistency),
        "public_naming_consistency": _round(public_naming_consistency),
        "file_coverage": _round(file_coverage),
        "concept_strength_proxy": _round(concept_strength_proxy),
        "top_terms": top_terms,
        "top_symbol_terms": top_symbol_terms,
        "top_public_symbol_terms": top_public_symbol_terms,
        "top_private_symbol_terms": top_private_symbol_terms,
        "top_symbol_terms_by_kind": _kind_term_rows(symbol_kind_term_counts),
        "top_public_symbol_terms_by_kind": _kind_term_rows(public_symbol_kind_term_counts),
        "top_private_symbol_terms_by_kind": _kind_term_rows(private_symbol_kind_term_counts),
        "symbol_term_evidence": _symbol_term_evidence(cluster_symbols, top_terms),
    }


def concept_experiment_payload(bp: Blueprint) -> dict:
    """Return namespaced experimental concept evidence for a blueprint."""
    file_by_id = {fe.id: fe for fe in bp.files}
    modules = [mod for mod in bp.modules if mod.file_ids]
    clusters = [
        _cluster_payload(mod, file_by_id, bp.symbols)
        for mod in modules
    ]
    clusters.sort(
        key=lambda c: (
            c["level"],
            -c["concept_strength_proxy"],
            c["name"],
            c["cluster_id"],
        )
    )
    candidates = _concept_candidates(bp, modules, file_by_id)
    godterm_count = sum(1 for c in candidates if c["godterm"])

    misaligned = [
        {"cluster_id": c["cluster_id"], "name": c["name"], "dominant_term": c["alignment_gap"]}
        for c in clusters if not c["concept_aligned"]
    ]
    shallow_module_rate = _round(
        sum(1 for c in clusters if c["depth_ratio"] < 1.0) / len(clusters)
        if clusters else 0.0
    )

    return {
        "schema": EXPERIMENT_KEY,
        "status": "complete",
        "description": (
            "Raw linguistic evidence over detected module clusters. Scores are "
            "experimental proxies for downstream evaluation, not production ratings."
        ),
        "cluster_count": len(clusters),
        "coherence_distribution": _coherence_distribution(clusters),
        "shallow_module_rate": shallow_module_rate,
        "misaligned_cluster_count": len(misaligned),
        "misaligned_clusters": misaligned,
        "clusters": clusters,
        "candidate_count": len(candidates),
        "godterm_count": godterm_count,
        "candidates": candidates,
        "boundary_violations": _boundary_violations(clusters, file_by_id, modules),
        "test_oracle": _test_oracle(clusters, file_by_id, modules),
    }


def attach_concept_experiment(bp: Blueprint) -> Blueprint:
    """Return a new Blueprint with the concept experiment payload in x_experimental."""
    payload = concept_experiment_payload(bp)
    return bp.model_copy(update={"x_experimental": {**bp.x_experimental, EXPERIMENT_KEY: payload}})


def _concept_candidates(
    bp: Blueprint,
    modules: list[ModuleEntry],
    file_by_id: dict[str, FileEntry],
) -> list[dict]:
    """Group recurring tokens across files/symbols as concept candidates."""
    file_tokens = {fe.id: _tokens_in_file(fe) for fe in bp.files}
    symbol_tokens = {sym.id: _tokens_in_symbol(sym) for sym in bp.symbols}

    token_files: dict[str, set[str]] = defaultdict(set)
    token_symbols: dict[str, set[str]] = defaultdict(set)
    token_modules: dict[str, set[str]] = defaultdict(set)
    token_exported_symbols: dict[str, set[str]] = defaultdict(set)

    for file_id, tokens in file_tokens.items():
        for token in tokens:
            token_files[token].add(file_id)

    for sym in bp.symbols:
        for token in symbol_tokens[sym.id]:
            token_symbols[token].add(sym.id)
            token_files[token].add(sym.file_id)
            if sym.is_exported:
                token_exported_symbols[token].add(sym.id)

    for mod in modules:
        module_tokens = set(_split_identifier(mod.name))
        for fid in mod.file_ids:
            module_tokens.update(file_tokens.get(fid, set()))
        for sym in _symbols_for_files(bp.symbols, set(mod.file_ids)):
            module_tokens.update(symbol_tokens.get(sym.id, set()))
        for token in module_tokens:
            token_modules[token].add(mod.id)

    N = len(modules)
    # BM25-style IDF ceiling: theoretical max when a term appears in no cluster (df=0).
    max_idf = math.log((N + 0.5) / 0.5 + 1) if N > 0 else 1.0

    candidates: list[dict] = []
    total_files = max(len(bp.files), 1)
    total_symbols = max(len(bp.symbols), 1)
    for token in sorted(set(token_files) | set(token_symbols)):
        file_count = len(token_files[token])
        symbol_count = len(token_symbols[token])
        if file_count < 2 and symbol_count < 2:
            continue
        exported_count = len(token_exported_symbols[token])
        support = (file_count / total_files) + (symbol_count / total_symbols)
        exported_ratio = exported_count / symbol_count if symbol_count else 0.0
        module_count = len(token_modules[token])
        # IDF: penalizes terms that appear in many clusters (godterms sort to bottom).
        df = module_count
        idf = math.log((N - df + 0.5) / (df + 0.5) + 1)
        idf_norm = _round(idf / max_idf) if max_idf > 0 else 0.0
        # weights uncalibrated; revisit after Flask/Requests validation experiment
        score = (0.30 * support) + (0.40 * exported_ratio) + (0.30 * idf_norm)
        # Omnipresent terms (appearing in >half of clusters) carry no discriminative signal.
        godterm = module_count > max(2, N // 2)
        candidates.append({
            "term": token,
            "file_count": file_count,
            "symbol_count": symbol_count,
            "exported_symbol_count": exported_count,
            "module_count": module_count,
            "module_ids": sorted(token_modules[token]),
            "support": _round(support),
            "exported_ratio": _round(exported_ratio),
            "idf": idf_norm,
            "godterm": godterm,
            "concept_candidate_score": _round(score),
        })

    candidates.sort(
        key=lambda c: (
            -c["concept_candidate_score"],
            -c["file_count"],
            -c["symbol_count"],
            c["term"],
        )
    )
    return candidates
