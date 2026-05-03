"""Experimental linguistic concept signals for blueprint modules.

This module deliberately produces raw evidence, not production judgments. Phase 2
can use the namespaced payload to evaluate whether module/cluster vocabulary is
coherent enough to act like an architectural concept.
"""

from __future__ import annotations

import math
import re
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
    "a", "an", "and", "any", "api", "app", "as", "base", "by", "common", "core",
    "copyright", "data", "def", "default", "file", "for", "from", "get", "impl", "in",
    "init", "internal", "is", "main", "manager", "model", "module", "new",
    "object", "of", "on", "one", "or", "perf", "set", "src", "test", "tests",
    "the", "to", "type", "types", "use", "util", "utils", "value", "with",
    "without",
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
            "admin", "app", "apps", "blueprint", "cli", "domain", "error",
            "frontend", "guide", "import", "inner", "module", "multi",
            "server", "subdomain", "test", "user",
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
            return [part]
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


def _cluster_payload(
    module: ModuleEntry,
    file_by_id: dict[str, FileEntry],
    symbols: list[SymbolEntry],
) -> dict:
    file_ids = set(module.file_ids)
    cluster_files = [file_by_id[fid] for fid in module.file_ids if fid in file_by_id]
    cluster_symbols = _symbols_for_files(symbols, file_ids)

    counts: Counter[str] = Counter()
    symbol_counts: Counter[str] = Counter()
    public_symbol_counts: Counter[str] = Counter()
    private_symbol_counts: Counter[str] = Counter()
    symbol_kind_counts: Counter[str] = Counter()
    symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    public_symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    private_symbol_kind_term_counts: dict[str, Counter[str]] = defaultdict(Counter)
    sources: dict[str, set[str]] = defaultdict(set)

    for term in _split_identifier(module.name):
        counts[term] += 3
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
        for term in _split_identifier(sym.name):
            symbol_counts[term] += 1
            symbol_kind_term_counts[sym.kind][term] += 1
            if sym.is_exported:
                public_symbol_counts[term] += 1
                public_symbol_kind_term_counts[sym.kind][term] += 1
            else:
                private_symbol_counts[term] += 1
                private_symbol_kind_term_counts[sym.kind][term] += 1
            counts[term] += 3
            sources[term].add("symbol")

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

    exported_symbols = [sym for sym in cluster_symbols if sym.is_exported]
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

    return {
        "cluster_id": module.id,
        "level": module.level,
        "name": module.name,
        "root_path": module.root_path,
        "file_count": len(cluster_files),
        "symbol_count": len(cluster_symbols),
        "exported_symbol_count": len(exported_symbols),
        "private_symbol_count": len(cluster_symbols) - len(exported_symbols),
        "public_symbol_ratio": _round(public_symbol_ratio),
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
    return {
        "schema": EXPERIMENT_KEY,
        "status": "complete",
        "description": (
            "Raw linguistic evidence over detected module clusters. Scores are "
            "experimental proxies for downstream evaluation, not production ratings."
        ),
        "cluster_count": len(clusters),
        "clusters": clusters,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }


def attach_concept_experiment(bp: Blueprint) -> Blueprint:
    """Attach the concept experiment payload to bp.x_experimental in place."""
    bp.x_experimental[EXPERIMENT_KEY] = concept_experiment_payload(bp)
    return bp


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
        concentration = 1.0 / module_count if module_count else 0.0
        score = (0.55 * support) + (0.25 * exported_ratio) + (0.20 * concentration)
        candidates.append({
            "term": token,
            "file_count": file_count,
            "symbol_count": symbol_count,
            "exported_symbol_count": exported_count,
            "module_count": module_count,
            "module_ids": sorted(token_modules[token])[:8],
            "support": _round(support),
            "exported_ratio": _round(exported_ratio),
            "concentration": _round(concentration),
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
    return candidates[:50]
