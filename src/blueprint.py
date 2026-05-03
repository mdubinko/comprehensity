"""
blueprint.py — Comprehensity data exchange contract

Defines the Blueprint format: the output of extract_blueprint and the sole
input to analyze_blueprint. Contains no source code — only structural data
that the client can audit before sharing.

Format identifier : "comprehensity-blueprint"
Current version   : "20260502"

Version history: comprehensity-private/spec/blueprint-changelog.md

Version policy: analyze_blueprint warns on unknown versions but loads anyway.
Blueprints produced by newer tooling will usually load fine into older readers
because fields with defaults are backward-compatible. Hard rejection is reserved
for major structural breaks.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


FORMAT_ID = "comprehensity-blueprint"
CURRENT_VERSION = "20260502"
SUPPORTED_VERSIONS = {"20260502"}


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

# Symbol kinds — kept coarse; Phase 2 can sub-classify further.
SymbolKind = Literal[
    "function",   # top-level function or free function
    "method",     # method inside a class/interface
    "class",      # class or abstract class
    "interface",  # interface / protocol / trait
    "variable",   # module-level variable or constant
    "other",      # anything that doesn't fit the above
]


class SymbolEntry(BaseModel):
    """A named, locatable symbol in a source file.

    id         : stable string, e.g. "s0", "s1", sorted by (file_id, start_line)
    file_id    : references FileEntry.id
    name       : unqualified symbol name (no path prefix)
    kind       : coarse classification — function / method / class / …
    start_line : 1-based line where the symbol definition begins
    end_line   : 1-based line where the definition ends (>= start_line)
    is_exported: True if the symbol is visible outside its file/module
    """
    id: str
    file_id: str
    name: str
    kind: SymbolKind
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    is_exported: bool = False

    @model_validator(mode="after")
    def end_not_before_start(self) -> SymbolEntry:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
            )
        return self

class FileEntry(BaseModel):
    """A source file in the scanned codebase.

    id      : stable string identifier, e.g. "f0", "f1", sorted by path
    imports : adjacency list — IDs of FileEntry or ExternalEntry nodes that
              this file imports directly. Reverse edges (imported_by) are
              computed at analysis time, not stored.
    """
    id: str
    path: str
    size_bytes: int = Field(ge=0)
    line_count: int = Field(ge=0, default=0)
    ext: str                        # e.g. ".py", ".ts", "" for no extension
    imports: List[str] = []         # IDs of files or externals
    comment_desc: Optional[str] = None    # leading comment / module docstring (comment lines only)
    has_parse_errors: Optional[bool] = None
    # None  → no tree-sitter grammar available for this file type (no signal)
    # False → parsed cleanly
    # True  → parse tree contains ERROR node(s)


class ExternalEntry(BaseModel):
    """A dependency that lives outside the scanned tree (stdlib or package).

    id   : "ext_{name}", e.g. "ext_numpy", "ext_os" — derived from name,
           so unique within a blueprint without a separate lookup.
    kind : "system"  — standard library (os, stdio.h, java.lang)
           "package" — third-party dependency (numpy, lodash)
           "unknown" — could not be classified
    """
    id: str                         # "ext_numpy"
    name: str                       # "numpy"
    kind: Literal["system", "package", "unknown"] = "unknown"


class ConfigEntry(BaseModel):
    """A parsed build / project configuration file found in the scanned tree.

    These are identified by filename (pyproject.toml, pom.xml, go.mod, …),
    not by extension, and are stored separately from FileEntry nodes.

    id        : stable string "cfg0", "cfg1", … sorted by path
    path      : path relative to scan root, posix separators
    kind      : build system identifier — see _CONFIG_FILE_NAMES in blueprint_io.py
    root_path : directory this config owns (posix, relative to scan root, "" = root)
    name      : declared project / artifact / package name
    version   : declared version string
    raw_deps  : direct declared external dependencies (package names or group:artifact)
    modules   : child module paths declared in this file (Maven <modules>, Gradle
                includes, npm workspaces, Cargo workspace members) — relative posix
                paths from this config's directory
    parent_id : ConfigEntry.id of the nearest ancestor config of the same kind,
                if one exists (Maven parent POM, Gradle root settings, etc.)
    """
    id: str
    path: str
    kind: str
    root_path: str
    name: Optional[str] = None
    version: Optional[str] = None
    raw_deps: List[str] = []
    modules: List[str] = []
    parent_id: Optional[str] = None


class LockfileEntry(BaseModel):
    """A dependency lockfile found in the scanned tree.

    Presence indicates that someone ran the package manager and committed the
    result — a basic reproducibility signal.  Absence means installs may
    produce different dependency trees on different machines or at different
    times.

    path : path relative to scan root, posix separators
    kind : lock manager — "npm" | "yarn" | "pnpm" | "poetry" | "cargo" |
                          "go" | "bundler" | "composer" | "pipenv" | "bun"
    """
    path: str
    kind: str


# ---------------------------------------------------------------------------
# Semantic edges (stubs — populated only when --semantic is passed)
# ---------------------------------------------------------------------------

class DiagnosticEntry(BaseModel):
    """A diagnostic (error, warning, etc.) reported by a language server.

    Stub: populated by the semantic (LSP) pass; absent in basic extraction.

    file_id   : references FileEntry.id
    line      : 1-based line where the diagnostic starts
    col       : 1-based column where the diagnostic starts
    end_line  : 1-based line where the diagnostic ends (>= line)
    end_col   : 1-based column where the diagnostic ends
    severity  : "error" | "warning" | "information" | "hint"
    code      : server-specific diagnostic code, e.g. "reportMissingImports"
    message   : human-readable diagnostic message
    source    : language server that produced this, e.g. "pyright", "typescript"
    """
    file_id: str
    line: int = Field(ge=1)
    col: int = Field(ge=1)
    end_line: int = Field(ge=1)
    end_col: int = Field(ge=1)
    severity: Literal["error", "warning", "information", "hint"]
    code: Optional[str] = None
    message: str
    source: str

    @model_validator(mode="after")
    def end_not_before_start(self) -> DiagnosticEntry:
        if self.end_line < self.line:
            raise ValueError(
                f"end_line ({self.end_line}) must be >= line ({self.line})"
            )
        return self


class ReferenceEdge(BaseModel):
    """A call/reference from one symbol to another.

    Stub: populated by the semantic (LSP) pass; absent in basic extraction.

    from_symbol_id   : the symbol that calls or references the target
    to_symbol_id     : the symbol being called or referenced
    call_site_file_id: file where the call/reference occurs (derivable from
                       from_symbol_id → SymbolEntry.file_id, but explicit for
                       cross-file queries without a full symbol lookup)
    call_site_line   : 1-based line of the call/reference site
    """
    from_symbol_id: str
    to_symbol_id: str
    call_site_file_id: str
    call_site_line: int = Field(ge=1)


DeadReason = Literal[
    "unreferenced",    # no ReferenceEdge points to this symbol
    "test_only",       # only referenced from test files
    "unreachable",     # dominated by a dead branch (future)
    "interface_only",  # only referenced through an interface (future)
]


class DeadSymbol(BaseModel):
    """A symbol that appears to be unused or dead.

    Stub: populated by the semantic pass; absent in basic extraction.

    id         : "dead_0", "dead_1", …
    symbol_id  : references SymbolEntry.id
    confidence : 0.0 (guess) – 1.0 (certain)
    reason     : classification of why the symbol is considered dead
    """
    id: str
    symbol_id: str
    confidence: float = Field(ge=0.0, le=1.0)
    reason: DeadReason = "unreferenced"


# ---------------------------------------------------------------------------
# Modularity nodes
# ---------------------------------------------------------------------------

ModuleLevel = Literal["L2", "L3", "L4"]
# L1 (file) is always present and implied by FileEntry; not stored explicitly.


class ModuleEntry(BaseModel):
    """A detected module boundary in the source tree.

    Level semantics:
      L2 — language package: Python __init__.py directory, Java package
           declaration, Go directory package.
      L3 — build unit: directory containing a build manifest such as
           package.json, go.mod, Cargo.toml, pom.xml, pyproject.toml.
      L4 — graph cluster: community detected via Louvain on the import graph.

    id         : stable string "m0", "m1", ... (L2/L3) or "cl0", "cl1", ...
                 (L4) sorted by min file_id within the cluster
    level      : "L2", "L3", or "L4"
    name       : human-readable identifier (package dotted name, build dir,
                 or "cluster_N" / LLM label for L4)
    root_path  : directory path relative to scan root, posix separators, no
                 trailing slash; "" means the scan root itself (always "" for L4)
    file_ids   : FileEntry IDs that belong to this module
    build_kind : L3 only — the build system detected ("npm", "pyproject",
                 "go", "cargo", "maven", "gradle", "setuptools", "cmake",
                 "make", or "unknown")
    label      : L4 only — short LLM-generated concept label (set by Bite 5)
    """
    id: str
    level: ModuleLevel
    name: str
    root_path: str
    file_ids: List[str] = []
    build_kind: Optional[str] = None   # L3 only
    label: Optional[str] = None        # L4 only — set by Bite 5

    # Martin metrics — set by Bite 6 scoring pass (L4 only)
    ca: Optional[int] = None           # afferent coupling (others → this)
    ce: Optional[int] = None           # efferent coupling (this → others)
    instability: Optional[float] = None    # Ce / (Ca + Ce)
    abstractness: Optional[float] = None   # abstract symbols / total symbols
    distance: Optional[float] = None       # |A + I - 1|


# ---------------------------------------------------------------------------
# Clone / duplicate nodes
# ---------------------------------------------------------------------------

class CloneInstance(BaseModel):
    """One occurrence of a duplicated code region.

    hash : SHA-256 hex digest of the normalized content (whitespace-collapsed,
           comment-stripped). Instances in the same CloneBlock must share the
           same hash; analyze_blueprint warns if they do not.
    """
    file_id: str
    start_line: int = Field(ge=1)
    end_line: int = Field(ge=1)
    hash: str                       # 64-char SHA-256 hex string

    @model_validator(mode="after")
    def end_not_before_start(self) -> CloneInstance:
        if self.end_line < self.start_line:
            raise ValueError(
                f"end_line ({self.end_line}) must be >= start_line ({self.start_line})"
            )
        return self


class CloneBlock(BaseModel):
    """A set of code regions that are duplicates of each other.

    Minimum two instances (a clone is by definition a pair or larger group).
    lines / tokens are the size of one instance, not the total across all.

    kind:
      "exact"       — truly identical AST (treepeat ruleset: none)
      "normalized"  — whitespace, string literals, function names normalized
                      (treepeat ruleset: default)
      "approximate" — additionally anonymizes identifiers and constants
                      (treepeat ruleset: loose)
      "semantic"    — reserved for future semantic / embedding-based detection

    circle / dantes — CPHA severity classification (Seven Circles of Copy-Paste Hell).
      circle : 1 (Conjured/harmless) … 7 (Endemic/codebase-corrupting); default 1.
      dantes : weighted severity score for this block; sum across all blocks then
               divide by total_files to get the dantes_per_file headline metric.
    """
    id: str                         # "dup_0", "dup_1", ...
    kind: Literal["exact", "normalized", "approximate", "semantic", "boilerplate"] = "exact"
    instances: List[CloneInstance] = Field(min_length=2)
    lines: int = Field(ge=1)
    tokens: int = Field(ge=0)
    circle: Literal[1, 2, 3, 4, 5, 6, 7] = 1
    dantes: float = Field(ge=0.0, default=0.0)


# ---------------------------------------------------------------------------
# Top-level summary (human-readable index, stamped just before writing)
# ---------------------------------------------------------------------------

class BlueprintSummary(BaseModel):
    """Human-readable index of blueprint contents.

    Appears near the top of the serialized file so clients can audit scope
    and provenance before deciding whether to share the blueprint.

    Sections are listed in inspection priority order:
      1. config_path — provenance: what machine/config produced this
      2. Section counts — scope: how much data is present
      3. Status flags   — completeness: which passes ran

    # TODO(format): investigate more space-efficient, human-scannable formats.
    # JSON is verbose for large blueprints (158 files → ~2 MB). Options:
    #   - YAML: more readable for nested structures, widely supported
    #   - Custom per-section encoding, e.g. compact symboldef strings:
    #       "s1130 f157 test_export_function_declaration 606-609 public"
    #     (id, file_id, name, line-range, exported flag) — ~5x smaller than JSON
    #   - MessagePack / CBOR: binary, ~40% smaller, less human-scannable
    #   - Hybrid: human-readable header + binary data sections
    # Constraint: analyze_blueprint must be able to round-trip the format.
    """
    # Section 1: provenance
    config_path: Optional[str] = None

    # Section 2: counts
    files: int = 0
    externals: int = 0
    configs: int = 0
    symbols: int = 0
    reference_edges: int = 0
    dead_symbols: int = 0
    diagnostics: int = 0
    modules: int = 0
    clone_blocks: int = 0

    # Parse coverage: how many files were successfully parsed by tree-sitter.
    # files_parsed_ok + files_parse_errors + files_no_grammar == files (total).
    # Low parse coverage means metrics (dead code, clones, symbols) cover less
    # of the codebase than the file count suggests.
    files_parsed_ok: int = 0
    files_parse_errors: int = 0
    files_no_grammar: int = 0

    # Section 3: pass status
    modularity_status: str = "stub"
    clone_status: str = "stub"
    semantic_status: str = "stub"
    dead_code_status: str = "stub"
    diagnostic_status: str = "stub"
    llm_status: str = "stub"


class AnalysisWarning(BaseModel):
    """A structured warning about incomplete or degraded analysis.

    Appended by extract_blueprint whenever a phase was skipped or degraded
    (e.g. node_modules absent, LSP server missing, clone detection timed out).
    Phase 2 surfaces these prominently so users know what to fix before re-running.

    phase    : which analysis phase was affected ("semantic", "clone", "phase1", etc.)
    code     : machine-readable key ("no_node_modules", "lsp_skip", "clone_timeout", etc.)
    severity : "degraded" | "skipped" | "error"
    message  : human-readable description of what was skipped or degraded
    action   : concrete command or step the user should run to fix it (empty string if N/A)
    """
    phase: str
    code: str
    severity: Literal["degraded", "skipped", "error"]
    message: str
    action: str = ""


# ---------------------------------------------------------------------------
# VCS metadata
# ---------------------------------------------------------------------------

class VcsInfo(BaseModel):
    """Version control metadata for the scanned repository.

    Populated by read_git_info() in vcs.py when a .git directory is found.
    None on the Blueprint when no VCS root is detected.

    scm           : version control system — "git" or "unknown"
    vcs_ref       : full 40-char commit SHA, or None if unresolvable
    vcs_branch    : branch name, or None for detached HEAD (e.g. historical checkouts)
    vcs_timestamp : Unix committer timestamp from the commit object, or None
                    (None when the object is packed rather than loose)
    git_version   : installed git version, e.g. "2.44.0"; None if not on PATH
    """
    scm: Literal["git", "unknown"] = "unknown"
    vcs_ref: Optional[str] = None
    vcs_branch: Optional[str] = None
    vcs_timestamp: Optional[int] = None
    git_version: Optional[str] = None


# ---------------------------------------------------------------------------
# Top-level container
# ---------------------------------------------------------------------------

class Blueprint(BaseModel):
    """The complete exchange artifact produced by extract_blueprint.

    format / version are literal types so Pydantic rejects documents that
    claim to be a different format or an unsupported version at parse time.

    clone_status:
      "stub"     — clone detection was not run; clone_blocks is empty
      "complete" — clone_blocks reflects a real detection pass

    Field order is intentional: summary → config audit trail → data sections.
    This lets clients audit provenance and scope before reading large arrays.
    """
    model_config = ConfigDict(populate_by_name=True)

    format: Literal["comprehensity-blueprint"] = FORMAT_ID
    version: Literal["20260502"] = CURRENT_VERSION
    generated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # Runtime context (OS, Python version, etc.) — helpful for debugging
    # messy client environments.
    runtime_info: Optional[dict] = None

    # Human-readable index — stamped last, just before writing to disk
    summary: Optional[BlueprintSummary] = None

    # Config audit trail — who produced this and with what settings
    config_path: Optional[str] = None   # abs path of config file used
    config_raw: Optional[str] = None    # raw TOML contents (for audit)

    files: List[FileEntry] = []
    externals: List[ExternalEntry] = []
    configs: List[ConfigEntry] = []
    lockfiles: List[LockfileEntry] = []

    symbols: List[SymbolEntry] = []
    reference_edges: List[ReferenceEdge] = []
    dead_symbols: List[DeadSymbol] = []
    diagnostics: List[DiagnosticEntry] = []

    modules: List[ModuleEntry] = []
    modularity_status: Literal["stub", "complete"] = "stub"

    clone_blocks: List[CloneBlock] = []
    clone_status: Literal["stub", "complete", "timeout"] = "stub"
    semantic_status: Literal["stub", "complete"] = "stub"
    # One entry per language that was detected but skipped during semantic enrichment,
    # e.g. "java: Java 21+ JVM not found" or "go: gopls not installed".
    # Empty list when semantic_status is "complete" or no languages were skipped.
    semantic_skip_reasons: List[str] = []
    dead_code_status: Literal["stub", "complete"] = "stub"
    diagnostic_status: Literal["stub", "complete"] = "stub"
    llm_status: Literal["stub", "complete", "skipped"] = "stub"

    # Structured warnings about incomplete/degraded analysis — populated by
    # extract_blueprint when a phase was skipped or ran with reduced fidelity.
    analysis_warnings: List[AnalysisWarning] = []

    # VCS metadata — populated when the scanned directory is inside a git repo.
    # None when no .git directory is found (e.g. a plain directory checkout).
    vcs: Optional[VcsInfo] = None

    # Experimental, opt-in extension data. Keys should be namespaced and versioned,
    # e.g. "comprehensity.concepts.v0". Producers must only populate this when a
    # runtime flag explicitly asks for unstable research signals.
    x_experimental: Dict[str, Any] = Field(default_factory=dict, alias="x-experimental")

    # ------------------------------------------------------------------
    # Summary computation
    # ------------------------------------------------------------------

    def compute_summary(self) -> BlueprintSummary:
        """Build a BlueprintSummary snapshot of the current blueprint state.

        Call this just before writing to disk so the summary reflects the
        final state (after semantic enrichment, config stamping, etc.).
        """
        parsed_ok = sum(1 for f in self.files if f.has_parse_errors is False)
        parse_errors = sum(1 for f in self.files if f.has_parse_errors is True)
        no_grammar = sum(1 for f in self.files if f.has_parse_errors is None)
        return BlueprintSummary(
            config_path=self.config_path,
            files=len(self.files),
            externals=len(self.externals),
            configs=len(self.configs),
            symbols=len(self.symbols),
            reference_edges=len(self.reference_edges),
            dead_symbols=len(self.dead_symbols),
            diagnostics=len(self.diagnostics),
            modules=len(self.modules),
            clone_blocks=len(self.clone_blocks),
            modularity_status=self.modularity_status,
            clone_status=self.clone_status,
            semantic_status=self.semantic_status,
            dead_code_status=self.dead_code_status,
            diagnostic_status=self.diagnostic_status,
            llm_status=self.llm_status,
            files_parsed_ok=parsed_ok,
            files_parse_errors=parse_errors,
            files_no_grammar=no_grammar,
        )

    # ------------------------------------------------------------------
    # Reference validation (warnings, never raises)
    # ------------------------------------------------------------------

    def validate_refs(self) -> List[str]:
        """Check internal consistency. Returns a list of warning strings.

        Does not raise — callers decide whether warnings are fatal.
        """
        warnings: List[str] = []
        valid_ids = {f.id for f in self.files} | {e.id for e in self.externals}
        file_ids = {f.id for f in self.files}

        for f in self.files:
            for imp in f.imports:
                if imp not in valid_ids:
                    warnings.append(
                        f"File {f.id!r} imports unknown id {imp!r}"
                    )

        symbol_ids = {s.id for s in self.symbols}

        for sym in self.symbols:
            if sym.file_id not in file_ids:
                warnings.append(
                    f"SymbolEntry {sym.id!r} references unknown file {sym.file_id!r}"
                )

        for edge in self.reference_edges:
            for attr, val in [("from_symbol_id", edge.from_symbol_id),
                               ("to_symbol_id", edge.to_symbol_id)]:
                if val not in symbol_ids:
                    warnings.append(
                        f"ReferenceEdge {attr}={val!r} references unknown symbol"
                    )
            if edge.call_site_file_id not in file_ids:
                warnings.append(
                    f"ReferenceEdge call_site_file_id={edge.call_site_file_id!r} references unknown file"
                )

        for diag in self.diagnostics:
            if diag.file_id not in file_ids:
                warnings.append(
                    f"DiagnosticEntry references unknown file {diag.file_id!r}"
                )

        for dead in self.dead_symbols:
            if dead.symbol_id not in symbol_ids:
                warnings.append(
                    f"DeadSymbol {dead.id!r} references unknown symbol {dead.symbol_id!r}"
                )

        for mod in self.modules:
            for fid in mod.file_ids:
                if fid not in file_ids:
                    warnings.append(
                        f"ModuleEntry {mod.id!r} references unknown file {fid!r}"
                    )

        for block in self.clone_blocks:
            hashes = {inst.hash for inst in block.instances}
            if len(hashes) > 1:
                warnings.append(
                    f"CloneBlock {block.id!r} has instances with differing hashes: {hashes}"
                )
            for inst in block.instances:
                if inst.file_id not in file_ids:
                    warnings.append(
                        f"CloneBlock {block.id!r} references unknown file {inst.file_id!r}"
                    )

        return warnings

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_json(self, **kwargs) -> str:
        """Serialize to JSON string. Passes kwargs to model_dump_json."""
        kwargs.setdefault("by_alias", True)
        return self.model_dump_json(indent=2, **kwargs)

    @classmethod
    def from_json(cls, raw: str) -> Blueprint:
        """Deserialize from JSON string with version check.

        Unknown versions produce a warning but load anyway — fields with
        defaults are backward-compatible across minor schema additions.
        """
        import json
        import warnings
        data = json.loads(raw)
        version = data.get("version", "<missing>")
        if version not in SUPPORTED_VERSIONS:
            warnings.warn(
                f"Blueprint version {version!r} is not in the known set "
                f"{sorted(SUPPORTED_VERSIONS)}; loading anyway. "
                f"Some fields may be missing or ignored.",
                UserWarning,
                stacklevel=2,
            )
        return cls.model_validate(data)

    @classmethod
    def from_file(cls, path: str) -> Blueprint:
        """Load a blueprint from a JSON or YAML file (auto-detected by extension)."""
        p = path if hasattr(path, "suffix") else __import__("pathlib").Path(path)
        with open(path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        if str(path).endswith((".yaml", ".yml")):
            return cls.from_yaml(raw)
        return cls.from_json(raw)

    def to_file(self, path: str) -> None:
        """Write the blueprint to a JSON file."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_json())
            fh.write("\n")

    # ------------------------------------------------------------------
    # YAML serialization (human-inspectable format)
    # ------------------------------------------------------------------

    def to_yaml(self) -> str:
        """Serialize to human-inspectable YAML with compact TSV records."""
        from blueprint_yaml import blueprint_to_yaml
        return blueprint_to_yaml(self)

    @classmethod
    def from_yaml(cls, raw: str) -> Blueprint:
        """Deserialize from a YAML string produced by to_yaml()."""
        from blueprint_yaml import blueprint_from_yaml
        return blueprint_from_yaml(raw)

    @classmethod
    def from_yaml_file(cls, path: str) -> Blueprint:
        """Load a blueprint from a YAML file."""
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_yaml(fh.read())

    def to_yaml_file(self, path: str) -> None:
        """Write the blueprint to a YAML file."""
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.to_yaml())
