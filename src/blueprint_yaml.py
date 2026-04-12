"""
blueprint_yaml.py — Human-inspectable YAML serialization for Blueprint.

Each data section uses compact tab-separated *_info strings so bulk data
is dense but still parseable.  Field order per section is documented in
summary.*_schema entries and in the _*_SCHEMA constants below.

Round-trip: blueprint_to_yaml() → blueprint_from_yaml() produces an
equivalent Blueprint.  One exception: CloneInstance.hash is omitted from
the YAML (use JSON if you need hash-integrity checks).

Intended use: clients inspect this file before deciding whether to share
the blueprint.  The canonical interchange format remains JSON.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

import yaml

from blueprint import (
    Blueprint, BlueprintSummary,
    CloneBlock, CloneInstance,
    ConfigEntry,
    DeadSymbol, DiagnosticEntry,
    ExternalEntry, FileEntry,
    ModuleEntry, ReferenceEdge,
    SymbolEntry,
    VcsInfo,
)

# ---------------------------------------------------------------------------
# Schema strings — documents field order within each *_info value
# ---------------------------------------------------------------------------

_FILES_SCHEMA = (
    "path\tsize_bytes\tline_count\text"
    "\t(comment_desc: separate key when present; imports: space-joined IDs)"
)
_EXTERNALS_SCHEMA   = "name\tkind"
_SYMBOLS_SCHEMA     = "file_id\tname\tkind\tlines\tis_exported"
_EDGES_SCHEMA       = "from_symbol_id\tto_symbol_id\tcall_site_file_id\tcall_site_line"
_DEAD_SCHEMA        = "symbol_id\tconfidence\treason"
_DIAGNOSTICS_SCHEMA = "file_id\tline\tcol\tend_line\tend_col\tseverity\tcode\tsource\tmessage"
_MODULES_SCHEMA     = (
    "level\tname\troot_path\tbuild_kind\tlabel"
    "\tinstability\tabstractness\tdistance\tca\tce"
    "\t(file_ids: space-joined IDs)"
)
_CLONES_SCHEMA     = "kind\tlines\ttokens\t(instances: space-joined file_id:start-end)"
_CONFIGS_SCHEMA    = (
    "path\tkind\troot_path\tname\tversion"
    "\t(raw_deps: space-joined; modules: space-joined; parent_id: separate key)"
)

_README = """\
comprehensity blueprint — structural analysis output (Phase 1)
This file contains structural metadata only: file paths, import graph, symbol names,
and clone regions. No source code is included.
Phase 1 (extract-blueprint, which produced this file) makes no network calls and no
LLM calls. LLM-based analysis (Phase 2, analyze-blueprint) runs only on the analyst's
machine, after you choose to share this file.
Fields within *_info strings are TAB-separated, written as \\t (visible in any editor).
Schemas are listed in summary.*_schema entries.
Caution: do not hand-edit — \\t sequences must remain exact.\
"""

# ---------------------------------------------------------------------------
# YAML dumper — controls string representation styles
# ---------------------------------------------------------------------------

class _Dumper(yaml.SafeDumper):
    pass


def _str_representer(dumper: yaml.SafeDumper, data: str) -> yaml.ScalarNode:
    """Literal block scalar for multi-line; double-quoted for tab-containing."""
    if "\n" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    if "\t" in data:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')
    return yaml.SafeDumper.represent_str(dumper, data)


_Dumper.add_representer(str, _str_representer)

# ---------------------------------------------------------------------------
# TSV field helpers
# ---------------------------------------------------------------------------

def _n(v: Any) -> str:
    """Render an optional string field: None → empty string."""
    return "" if v is None else str(v)


def _num(v: Any) -> str:
    """Render an optional numeric field: None → 'null'."""
    return "null" if v is None else str(v)


def _opt_str(s: str) -> Optional[str]:
    return None if s == "" else s


def _opt_float(s: str) -> Optional[float]:
    return None if s == "null" else float(s)


def _opt_int(s: str) -> Optional[int]:
    return None if s == "null" else int(s)


# ---------------------------------------------------------------------------
# Section encoders  (Blueprint → plain dicts for YAML)
# ---------------------------------------------------------------------------

def _enc_files(files: List[FileEntry]) -> List[Dict]:
    result = []
    for f in files:
        entry: Dict = {
            "id": f.id,
            "file_info": f"{f.path}\t{f.size_bytes}\t{f.line_count}\t{f.ext}",
        }
        if f.imports:
            entry["imports"] = " ".join(f.imports)
        if f.comment_desc:
            entry["comment_desc"] = f.comment_desc
        result.append(entry)
    return result


def _enc_externals(externals: List[ExternalEntry]) -> List[Dict]:
    return [
        {"id": e.id, "ext_info": f"{e.name}\t{e.kind}"}
        for e in externals
    ]


def _enc_symbols(symbols: List[SymbolEntry]) -> List[Dict]:
    return [
        {
            "id": s.id,
            "symbol_info": (
                f"{s.file_id}\t{s.name}\t{s.kind}\t"
                f"{s.start_line}-{s.end_line}\t"
                f"{'true' if s.is_exported else 'false'}"
            ),
        }
        for s in symbols
    ]


def _enc_edges(edges: List[ReferenceEdge]) -> List[Dict]:
    # ReferenceEdge has no id field; list items have only edge_info.
    return [
        {
            "edge_info": (
                f"{e.from_symbol_id}\t{e.to_symbol_id}\t"
                f"{e.call_site_file_id}\t{e.call_site_line}"
            )
        }
        for e in edges
    ]


def _enc_dead(dead: List[DeadSymbol]) -> List[Dict]:
    return [
        {"id": d.id, "dead_info": f"{d.symbol_id}\t{d.confidence}\t{d.reason}"}
        for d in dead
    ]


def _enc_diagnostics(diags: List[DiagnosticEntry]) -> List[Dict]:
    # message is last so it may contain tabs without ambiguity (split on first 8)
    return [
        {
            "diag_info": (
                f"{d.file_id}\t{d.line}\t{d.col}\t{d.end_line}\t{d.end_col}\t"
                f"{d.severity}\t{_n(d.code)}\t{d.source}\t{d.message}"
            )
        }
        for d in diags
    ]


def _enc_modules(modules: List[ModuleEntry]) -> List[Dict]:
    result = []
    for m in modules:
        entry: Dict = {
            "id": m.id,
            "module_info": (
                f"{m.level}\t{m.name}\t{m.root_path}\t{_n(m.build_kind)}\t{_n(m.label)}\t"
                f"{_num(m.instability)}\t{_num(m.abstractness)}\t{_num(m.distance)}\t"
                f"{_num(m.ca)}\t{_num(m.ce)}"
            ),
        }
        if m.file_ids:
            entry["file_ids"] = " ".join(m.file_ids)
        result.append(entry)
    return result


def _enc_clones(blocks: List[CloneBlock]) -> List[Dict]:
    result = []
    for b in blocks:
        entry: Dict = {
            "id": b.id,
            "clone_info": f"{b.kind}\t{b.lines}\t{b.tokens}",
        }
        if b.instances:
            entry["instances"] = " ".join(
                f"{inst.file_id}:{inst.start_line}-{inst.end_line}"
                for inst in b.instances
            )
        result.append(entry)
    return result


def _enc_configs(configs: List[ConfigEntry]) -> List[Dict]:
    result = []
    for c in configs:
        entry: Dict = {
            "id": c.id,
            "config_info": f"{c.path}\t{c.kind}\t{c.root_path}\t{_n(c.name)}\t{_n(c.version)}",
        }
        if c.raw_deps:
            entry["raw_deps"] = " ".join(c.raw_deps)
        if c.modules:
            entry["modules"] = " ".join(c.modules)
        if c.parent_id:
            entry["parent_id"] = c.parent_id
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Section decoders  (plain dicts from YAML → Blueprint objects)
# ---------------------------------------------------------------------------

def _dec_configs(raw: List[Dict]) -> List[ConfigEntry]:
    result = []
    for entry in raw:
        path, kind, root_path, name_s, version_s = entry["config_info"].split("\t")
        raw_deps_str = entry.get("raw_deps", "")
        modules_str = entry.get("modules", "")
        result.append(ConfigEntry(
            id=entry["id"],
            path=path,
            kind=kind,
            root_path=root_path,
            name=_opt_str(name_s),
            version=_opt_str(version_s),
            raw_deps=raw_deps_str.split() if raw_deps_str else [],
            modules=modules_str.split() if modules_str else [],
            parent_id=entry.get("parent_id") or None,
        ))
    return result


def _dec_files(raw: List[Dict]) -> List[FileEntry]:
    result = []
    for entry in raw:
        path, size_bytes, line_count, ext = entry["file_info"].split("\t")
        imports_str = entry.get("imports", "")
        imports = imports_str.split() if imports_str else []
        comment_desc = entry.get("comment_desc")
        if comment_desc:
            comment_desc = comment_desc.rstrip("\n")  # pyyaml block scalars add trailing \n
        result.append(FileEntry(
            id=entry["id"],
            path=path,
            size_bytes=int(size_bytes),
            line_count=int(line_count),
            ext=ext,
            imports=imports,
            comment_desc=comment_desc or None,
        ))
    return result


def _dec_externals(raw: List[Dict]) -> List[ExternalEntry]:
    result = []
    for entry in raw:
        name, kind = entry["ext_info"].split("\t")
        result.append(ExternalEntry(id=entry["id"], name=name, kind=kind))
    return result


def _dec_symbols(raw: List[Dict]) -> List[SymbolEntry]:
    result = []
    for entry in raw:
        file_id, name, kind, lines, exported = entry["symbol_info"].split("\t")
        start_s, end_s = lines.split("-", 1)
        result.append(SymbolEntry(
            id=entry["id"],
            file_id=file_id,
            name=name,
            kind=kind,
            start_line=int(start_s),
            end_line=int(end_s),
            is_exported=(exported == "true"),
        ))
    return result


def _dec_edges(raw: List[Dict]) -> List[ReferenceEdge]:
    result = []
    for entry in raw:
        from_sym, to_sym, file_id, line = entry["edge_info"].split("\t")
        result.append(ReferenceEdge(
            from_symbol_id=from_sym,
            to_symbol_id=to_sym,
            call_site_file_id=file_id,
            call_site_line=int(line),
        ))
    return result


def _dec_dead(raw: List[Dict]) -> List[DeadSymbol]:
    result = []
    for entry in raw:
        symbol_id, confidence, reason = entry["dead_info"].split("\t")
        result.append(DeadSymbol(
            id=entry["id"],
            symbol_id=symbol_id,
            confidence=float(confidence),
            reason=reason,
        ))
    return result


def _dec_diagnostics(raw: List[Dict]) -> List[DiagnosticEntry]:
    result = []
    for entry in raw:
        # Split on first 8 tabs — message (last field) may contain tabs
        parts = entry["diag_info"].split("\t", 8)
        file_id, line, col, end_line, end_col, severity, code, source, message = parts
        result.append(DiagnosticEntry(
            file_id=file_id,
            line=int(line),
            col=int(col),
            end_line=int(end_line),
            end_col=int(end_col),
            severity=severity,
            code=_opt_str(code),
            source=source,
            message=message,
        ))
    return result


def _dec_modules(raw: List[Dict]) -> List[ModuleEntry]:
    result = []
    for entry in raw:
        parts = entry["module_info"].split("\t")
        (level, name, root_path, build_kind_s, label_s,
         instability_s, abstractness_s, distance_s, ca_s, ce_s) = parts
        file_ids_str = entry.get("file_ids", "")
        file_ids = file_ids_str.split() if file_ids_str else []
        result.append(ModuleEntry(
            id=entry["id"],
            level=level,
            name=name,
            root_path=root_path,
            file_ids=file_ids,
            build_kind=_opt_str(build_kind_s),
            label=_opt_str(label_s),
            instability=_opt_float(instability_s),
            abstractness=_opt_float(abstractness_s),
            distance=_opt_float(distance_s),
            ca=_opt_int(ca_s),
            ce=_opt_int(ce_s),
        ))
    return result


def _dec_clones(raw: List[Dict]) -> List[CloneBlock]:
    result = []
    for entry in raw:
        kind, lines_s, tokens_s = entry["clone_info"].split("\t")
        instances_str = entry.get("instances", "")
        instances: List[CloneInstance] = []
        if instances_str:
            for token in instances_str.split():
                # format: file_id:start-end
                file_part, range_part = token.rsplit(":", 1)
                start_s, end_s = range_part.split("-", 1)
                instances.append(CloneInstance(
                    file_id=file_part,
                    start_line=int(start_s),
                    end_line=int(end_s),
                    hash="",  # omitted in YAML; use JSON for hash integrity
                ))
        result.append(CloneBlock(
            id=entry["id"],
            kind=kind,
            lines=int(lines_s),
            tokens=int(tokens_s),
            instances=instances,
        ))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def blueprint_to_yaml(bp: Blueprint) -> str:
    """Serialize *bp* to a human-inspectable YAML string."""
    # Build summary dict with interleaved *_schema entries
    s = bp.summary or bp.compute_summary()
    summary_dict: Dict = {
        "config_path": _n(s.config_path),
        "files": s.files,
        "files_schema": _FILES_SCHEMA,
        "externals": s.externals,
        "externals_schema": _EXTERNALS_SCHEMA,
        "configs": s.configs,
        "configs_schema": _CONFIGS_SCHEMA,
        "symbols": s.symbols,
        "symbols_schema": _SYMBOLS_SCHEMA,
        "reference_edges": s.reference_edges,
        "reference_edges_schema": _EDGES_SCHEMA,
        "dead_symbols": s.dead_symbols,
        "dead_symbols_schema": _DEAD_SCHEMA,
        "diagnostics": s.diagnostics,
        "diagnostics_schema": _DIAGNOSTICS_SCHEMA,
        "modules": s.modules,
        "modules_schema": _MODULES_SCHEMA,
        "clone_blocks": s.clone_blocks,
        "clone_blocks_schema": _CLONES_SCHEMA,
        "modularity_status": s.modularity_status,
        "clone_status": s.clone_status,
        "semantic_status": s.semantic_status,
        "dead_code_status": s.dead_code_status,
        "diagnostic_status": s.diagnostic_status,
        "llm_status": s.llm_status,
    }

    doc: Dict = {
        "readme": _README,
        "format": bp.format,
        "version": bp.version,
        "generated_at": bp.generated_at.isoformat(),
        "summary": summary_dict,
        "config_path": _n(bp.config_path),
        "config_raw": bp.config_raw or "",
        "files": _enc_files(bp.files),
        "externals": _enc_externals(bp.externals),
        "configs": _enc_configs(bp.configs),
        "symbols": _enc_symbols(bp.symbols),
        "reference_edges": _enc_edges(bp.reference_edges),
        "dead_symbols": _enc_dead(bp.dead_symbols),
        "diagnostics": _enc_diagnostics(bp.diagnostics),
        "modules": _enc_modules(bp.modules),
        "clone_blocks": _enc_clones(bp.clone_blocks),
        "modularity_status": bp.modularity_status,
        "clone_status": bp.clone_status,
        "semantic_status": bp.semantic_status,
        "dead_code_status": bp.dead_code_status,
        "diagnostic_status": bp.diagnostic_status,
        "llm_status": bp.llm_status,
        "vcs": bp.vcs.model_dump() if bp.vcs is not None else None,
    }

    return yaml.dump(doc, Dumper=_Dumper, sort_keys=False,
                     allow_unicode=True, width=120)


def blueprint_from_yaml(raw: str) -> Blueprint:
    """Deserialize a Blueprint from a YAML string produced by blueprint_to_yaml()."""
    from datetime import datetime, timezone
    from blueprint import SUPPORTED_VERSIONS

    doc = yaml.safe_load(raw)

    version = doc.get("version", "<missing>")
    if str(version) not in SUPPORTED_VERSIONS:
        raise ValueError(
            f"Blueprint version {version!r} is not supported "
            f"(supported: {sorted(SUPPORTED_VERSIONS)}). "
            "Update comprehensity and try again."
        )

    generated_at_raw = doc.get("generated_at", "")
    try:
        generated_at = datetime.fromisoformat(str(generated_at_raw))
    except ValueError:
        generated_at = datetime.now(timezone.utc)

    return Blueprint(
        version=str(version),
        generated_at=generated_at,
        config_path=_opt_str(doc.get("config_path", "")) ,
        config_raw=_opt_str(doc.get("config_raw", "")),
        files=_dec_files(doc.get("files", [])),
        externals=_dec_externals(doc.get("externals", [])),
        configs=_dec_configs(doc.get("configs", [])),
        symbols=_dec_symbols(doc.get("symbols", [])),
        reference_edges=_dec_edges(doc.get("reference_edges", [])),
        dead_symbols=_dec_dead(doc.get("dead_symbols", [])),
        diagnostics=_dec_diagnostics(doc.get("diagnostics", [])),
        modules=_dec_modules(doc.get("modules", [])),
        clone_blocks=_dec_clones(doc.get("clone_blocks", [])),
        modularity_status=doc.get("modularity_status", "stub"),
        clone_status=doc.get("clone_status", "stub"),
        semantic_status=doc.get("semantic_status", "stub"),
        dead_code_status=doc.get("dead_code_status", "stub"),
        diagnostic_status=doc.get("diagnostic_status", "stub"),
        llm_status=doc.get("llm_status", "stub"),
        vcs=VcsInfo(**doc["vcs"]) if doc.get("vcs") else None,
    )
