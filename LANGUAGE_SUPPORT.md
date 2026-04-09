# Language Support Matrix

## Support Levels

| Level | What you get |
|---|---|
| **scan** | File listing, extension histogram, phase0 signals (monorepo detection, generated-code markers). No grammar required. |
| **phase1-imports** | + Import graph: file-to-file dependency edges, external package identification. Requires tree-sitter grammar + import parser. |
| **phase1-symbols** | + Function, class, and method extraction into `SymbolEntry` objects. Requires grammar + symbol extractor. |
| **phase1+semantic** | + LSP-derived call graph (`ReferenceEdge`), dead code (`DeadSymbol`), and type diagnostics (`DiagnosticEntry`). Requires a language server on PATH. |
| **phase2** | Louvain clustering, concept labeling, cohesion/instability scoring, clone×dead-code ROI. Language-agnostic — reads `blueprint.json` only. Richer output when phase1-symbols and phase1+semantic data are present. |

Phase 2 is enabled by whatever Phase 1 data is available; it is not a per-language property.

---

## Current Status

| Language | Extensions | Phase 1 level | Semantic (LSP) | Grammar package | Notes |
|---|---|---|---|---|---|
| **Python** | `.py` `.pyw` | phase1-symbols | ✅ jedi-language-server | `tree-sitter-python` | Pure Python wheel, pip-installable, no Node/Rust dep. |
| **JavaScript** | `.js` `.jsx` `.mjs` | phase1-symbols | ✅ typescript-language-server (via npx) | `tree-sitter-javascript` | Node required; server launches via `npx` automatically. See [JS/TS discussion](#jsts). |
| **TypeScript** | `.ts` `.tsx` | phase1-symbols | ✅ typescript-language-server (via npx) | `tree-sitter-javascript` `tree-sitter-typescript` | Node required; server launches via `npx` automatically. See [JS/TS discussion](#jsts). |
| **Java** | `.java` | phase1-symbols | ⚠️ jdtls | `tree-sitter-java` | JavaSymbolExtractor: class, interface, method, record, enum. jdtls requires JVM 21+ + jdtls jar; see [Java discussion](#java). |
| **C** | `.c` `.h` | phase1-symbols | — | `tree-sitter-cpp` | `CImportParserTS` + `CSymbolExtractor` (functions, structs, enums). Uses CPP grammar (superset of C) for both. No LSP server planned — `#include` resolution requires a compilation database. |
| **C++** | `.cpp` `.hpp` `.cc` `.cxx` `.hxx` | phase1-symbols | — | `tree-sitter-cpp` | Same parser/extractor as C, plus classes and methods. No LSP server planned. |
| **Go** | `.go` | scan | ⚠️ gopls | `tree-sitter-go` | Grammar available; no import parser or symbol extractor yet. gopls: Go binary, `go install`. TBD. |
| **Rust** | `.rs` | phase1-symbols | ⚠️ rust-analyzer | `tree-sitter-rust` | `use` declarations + `extern crate`; functions, structs, enums, traits, impl methods. `--detect-clones` works. rust-analyzer: `rustup component add`. |
| **Ruby** | `.rb` | scan | — | `tree-sitter-ruby` | Grammar available; no parser, extractor, or LSP server. Planned. |
| **C#** | `.cs` | scan | — | `tree-sitter-c-sharp` | Grammar available; no parser, extractor, or LSP server. Planned. |
| **Kotlin** | `.kt` | scan | — | `tree-sitter-kotlin` | Grammar available; no parser, extractor, or LSP server. Planned. |
| **Swift** | `.swift` | scan | — | `tree-sitter-swift` | Grammar available; no parser, extractor, or LSP server. Planned. |

**Legend:** ✅ implemented and ready · ⚠️ configured but pending installer discussion or runtime dep · — not yet supported

---

## Installer Implications

The installer goal is a single-command, network-isolated-friendly setup. Language server
availability determines which features can be offered out of the box.

| Language | Grammar (pip wheel) | LSP server | Install method | Node required | Pip wheel? | Network-isolated |
|---|---|---|---|---|---|---|
| Python | ✅ | jedi-language-server | `pip install jedi-language-server` | No | ✅ pure Python wheel | ✅ via mirror |
| JavaScript | ✅ | typescript-language-server | `npx` (bundled with Node) | **Yes** | No | ⚠️ needs Node pre-installed |
| TypeScript | ✅ | typescript-language-server | `npx` (bundled with Node) | **Yes** | No | ⚠️ needs Node pre-installed |
| Java | ✅ | jdtls | manual jar download | No (JVM) | No | ⚠️ binary pre-install |
| C/C++ | ✅ | — | — | — | — | N/A |
| Go | ✅ | gopls | `go install golang.org/x/tools/gopls@latest` | No (Go) | No | ⚠️ binary pre-install |
| Rust | ✅ | rust-analyzer | `rustup component add rust-analyzer` | No (Rust) | No | ⚠️ binary pre-install |

Grammar packages are always pip wheels. For network-isolated environments, they need to
be available on an internal mirror — same requirement as `pydantic` or `tree-sitter`.

The `--semantic` flag degrades gracefully: if a language server is not found on PATH,
that language is skipped with a warning. Phase 1 basic always works without any LSP server.

---

## Per-Language Discussions

These sections record the reasoning behind each language server choice.
Fill in as each language is reviewed.

### Python

**Decision:** jedi-language-server (current) → ty (planned)

pyright was the original choice but requires Node.js at runtime (`pip install pyright`
installs a Node.js wrapper), which breaks network-isolated environments without Node.

pylyzer was evaluated as a Rust-wheel replacement but is ruled out:
- pip wheel does not bundle ERG stubs (`ERG_PATH/lib/pystd`, `ERG_PATH/lib/core.d`);
  requires a separate Erg toolchain install with no fix planned upstream.
- Project is in maintenance-only mode as of 2025.

**Current choice:** `jedi-language-server` — pure Python wheel, pip-installable, no
external runtime deps. Supports `textDocument/references`, `publishDiagnostics`, and
`textDocument/prepareCallHierarchy`, covering all LSP call types comprehensity uses.

**Planned replacement:** `ty` (astral-sh/ty) — extremely fast Rust-based type checker
and language server by the same team as uv/Ruff. Pip-installable, no external deps.
Blocked on: `callHierarchy/*` is not yet implemented in ty's LSP. Once it ships,
ty becomes the clear upgrade path (same installer ecosystem, 10–100× faster than jedi).

**Status:** jedi-language-server implemented and in use. Switch to ty pending upstream
callHierarchy support.

---

### JS/TS

**Decision:** typescript-language-server (no alternative)

There is no Node-free JS/TS language server that provides type-aware call hierarchy.
All alternatives (biome, oxc) are linters only — no `prepareCallHierarchy`, no type
inference, no `ReferenceEdge` data. Deno LSP has Deno-module assumptions that break
on standard Node/CommonJS/tsconfig codebases.

typescript-language-server wraps the TypeScript compiler directly and is the only
correct choice. Node is a required peer dependency for `--semantic` on JS/TS files.

In practice this is not a constraint: any client with a JS/TS codebase already has
Node installed. The server is launched via `npx --yes typescript-language-server --stdio`
so no separate global install step is needed. If Node is absent, phase0 `--install-guide`
directs the user to install it; once Node is present, npx handles the rest.

**Status:** Implemented. Server launches via npx; no global install required.

#### Known limitation: TypeScript path aliases

TypeScript projects frequently configure path aliases in `tsconfig.json` (e.g. `@app/`,
`~/`, `@env/`). These look syntactically identical to scoped npm packages (`@org/pkg`) and
are currently classified as `EXTERNAL` rather than `LOCAL` in the import graph.

Resolving them correctly requires parsing `tsconfig.json` `compilerOptions.paths` and
`compilerOptions.baseUrl` — which is out of scope for Phase 1. Affected imports:

- Show up in `externals` list as package references rather than file edges
- Do not contribute to the local import graph or fan-in/fan-out scores
- Are still visible in `--semantic` ReferenceEdge data (typescript-language-server
  resolves them correctly via the tsconfig it reads at startup)

Workaround for projects that rely heavily on path aliases: use `--semantic`, where
the LSP-derived call graph will capture the cross-module relationships accurately.

---

### Go

**Status:** TBD — discussion pending. Note: import parser and symbol extractor also needed before semantic adds value.

---

### Rust

**Status:** Phase 1 imports and symbols fully implemented. Semantic via rust-analyzer configured but not yet connected to the installer; `rustup component add rust-analyzer` is the install step once decided.

---

### Java

**Decision:** Eclipse JDT Language Server (jdtls)

jdtls is the reference Java language server — it is the backend powering the Java extension
in VS Code and Eclipse IDE. It provides `textDocument/references` and
`textDocument/prepareCallHierarchy`, covering both LSP call types comprehensity uses.

**JVM detection:** comprehensity searches for a JVM 21+ in the following priority order:
1. `[java] java_home` in `~/.comprehensity/config.toml`
2. `COMPREHENSITY_JAVA_HOME` env var
3. `JAVA_HOME` env var
4. Homebrew Cellar (macOS: `/opt/homebrew`, `/usr/local` — descending version)
5. SDKMAN (`~/.sdkman/candidates/java/*`)
6. asdf (`~/.asdf/installs/java/*`)
7. `/usr/lib/jvm/*` (Linux)
8. Windows: Eclipse Adoptium, Microsoft, BellSoft, Amazon Corretto registry paths
9. `java` on PATH

If no JVM 21+ is found, the semantic phase is skipped with a `semantic_skip_reasons` entry
in the blueprint. Phase 1 (import graph + symbols) always works without any JVM.

**jdtls launch:** comprehensity passes `--java-executable <path>` (the detected JVM) and
`--data ~/.comprehensity/jdtls-workspace` (a persistent workspace directory, which makes
repeated runs faster). jdtls must be on PATH or specified via `[java] jdtls_path` in config.

**Symbols extracted:** `class_declaration`, `interface_declaration`, `enum_declaration`,
`record_declaration`, `annotation_type_declaration`, `method_declaration`,
`constructor_declaration`. `is_exported=True` when the node has a `public` modifier.

**Boilerplate filter:** trivial methods (getters, setters, `hashCode`, `equals`, `toString`,
builder/test lifecycle) are tagged `kind="boilerplate"` in clone detection output and excluded
from dead-code counts. Clone detection uses `min_lines=8` for Java (vs. 5 for other languages)
to avoid flagging single-method accessors.

**Status:** Phase 1 imports and symbols fully implemented. Semantic via jdtls implemented;
installer/bundling strategy for shipping JDK 21+ with comprehensity is under discussion.

---

### C / C++

**Status:** Phase 1 imports and symbols fully implemented. `CImportParserTS` handles
`#include` directives for all C/C++ extensions (`.c`, `.h`, `.cpp`, `.cc`, `.cxx`,
`.hpp`, `.hxx`) using the `tree-sitter-cpp` grammar (a strict superset of C).
`CSymbolExtractor` extracts functions, named structs, enums, C++ classes, and methods.
`static` functions are marked `is_exported=False`.

No LSP server planned. `#include` resolution is path-dependent and requires a
compilation database (`compile_commands.json`). Out of scope for Phase 1.

---

## Adding a New Language

1. Install grammar: `uv pip install tree-sitter-<lang>`
2. Add grammar to `pyproject.toml` as a `lang-<name>` optional dep
3. Subclass `TreeSitterImportParser` in `src/import_analysis.py`; register in `LanguageDetector`
4. Add `tests/fixtures/lang/sample.<ext>` and parser tests in `tests/test_ts_parsers.py`
5. *(Optional)* Subclass `SymbolExtractor` in `src/ts_parsers.py`; register in `SymbolExtractorRegistry.default()`
6. *(Optional)* Add LSP server entry to `_EXT_TO_LANG` and `_LANG_SERVERS` in `src/blueprint_io.py`
7. Update this document
