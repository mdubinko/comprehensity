# Comprehensity — Client Guide

This document is written for engineering teams and security reviewers at client organizations.
It explains what comprehensity does, what runs on your machines, what leaves your environment,
and how every claim is enforced — not just promised.

---

## What it does

Comprehensity analyzes a codebase and produces structured insights about architectural health,
import complexity, and duplicate code — with a particular focus on patterns that indicate
AI-generated code needing human review.

The analysis produces a scorecard: which files are tightly coupled, which modules are fragile,
where code has been copy-pasted across the codebase, which dependencies are pulling in the most
complexity. This gives you a concrete picture of where AI codegen has left behind technical debt
and where human review should be focused.

Most "agent readiness" tools evaluate process hygiene: CI pipelines, linters, test coverage,
documentation. Comprehensity measures structural architecture — coupling, module boundaries,
import topology, and clone density. These are the factors that determine whether an AI agent
can reason about a change without overflowing its context window, producing incoherent edits
across files, or duplicating logic that already exists elsewhere. Process hygiene and
structural architecture are complementary; comprehensity covers the gap that hygiene tools
leave.

---

## How it works: three phases, two machines

Analysis is split into three phases (including a "phase 0") with a hard boundary between them.

```
Your machine                            Analysis server
────────────                            ───────────────
Phase 0: detect languages, identify
         build manifests, check for
         language servers and phase
         1 readiness.

Phase 1: parse source files locally
         build import graph
         detect duplicate code blocks
         collect metrics
  → produces blueprint.json
  → NO outbound network calls

You review blueprint.json
You upload blueprint.json  ──────────→ Phase 2: graph analysis, scoring,
                                                 module naming, insights report
                                        → report returned to you
```

**Phase 0 and Phase 1 run entirely on your machine.** They produce a `blueprint.json` file —
a compact, human-readable summary — that you review before sending anything anywhere.
Phase 2 reads only that file. Your source code never leaves your environment.

---

## Running Phase 0

Phase 0 is delivered as a plain source bundle.

Typical bundle contents:

```text
comprehensity-phase0-<version>/
  INSTRUCTIONS.md
  README.md
  VERSION
  phase0.py
  phase0.sh
  phase0.ps1
  phase0.cmd
  sample-output.json
```

### What you need

- Python 3.7 or newer on the machine running the scan
- Read access to the codebase you want to scan
- Write access to a directory where you want to save `scan.json` (optional)

Phase 0 itself has no third-party Python dependencies and does not install anything.

### macOS / Linux

1. Unzip the bundle.
2. Open a terminal.
3. Change into the unpacked bundle directory.
4. Run:

```bash
./phase0.sh /path/to/project
```

To save JSON to a file:

```bash
./phase0.sh /path/to/project -o scan.json
```

To print the install guidance derived from the scan:

```bash
./phase0.sh /path/to/project --install-guide
```

To write `scan.json` and print the install guide in one pass:

```bash
./phase0.sh /path/to/project -o scan.json --install-guide
```

If the shell script is not executable, run:

```bash
bash phase0.sh /path/to/project
```

### Windows PowerShell

1. Unzip the bundle.
2. Open PowerShell.
3. Change into the unpacked bundle directory.
4. Run:

```powershell
.\phase0.ps1 C:\path\to\project
```

To save JSON to a file:

```powershell
.\phase0.ps1 C:\path\to\project -o scan.json
```

To print the install guidance:

```powershell
.\phase0.ps1 C:\path\to\project --install-guide
```

If PowerShell script execution is restricted, run:

```powershell
py -3 .\phase0.py C:\path\to\project
```

or:

```powershell
python .\phase0.py C:\path\to\project
```

### If the machine Python is too old

If the machine default Python is older than 3.7, use any approved newer Python already present
on the machine and create a local virtual environment for the scan.

macOS / Linux:

```bash
python3.11 -m venv .phase0-venv
. .phase0-venv/bin/activate
python phase0.py /path/to/project -o scan.json --install-guide
```

Windows PowerShell:

```powershell
py -3.11 -m venv .phase0-venv
.\.phase0-venv\Scripts\Activate.ps1
python .\phase0.py C:\path\to\project -o scan.json --install-guide
```

If `uv` is already installed and approved in your environment, you may also use it to provision
an isolated Python. For Phase 0, built-in `venv` is preferred because it keeps the procedure
standard and transparent.

### Windows Command Prompt

```bat
phase0.cmd C:\path\to\project
phase0.cmd C:\path\to\project -o scan.json --install-guide
```

### What the output means

Phase 0 prints:
- a short status line to standard error
- a short install summary to standard error on every run
- JSON to standard output when `-o` is not supplied
- install guidance text to standard output when `--install-guide` is supplied

If you use `-o scan.json`, the JSON is written to that file instead of standard output.
The default short install summary is intended for human operators and does not change the JSON
format written to standard output or the output file.

### Common errors

**`Python 3 is required to run phase0.py`**
- Cause: neither `python3`, `py -3`, nor `python` resolved to a Python 3 interpreter.
- Fix: install Python 3 or run the script with the full path to your Python 3 executable.

**`phase0 requires Python 3.7+`**
- Cause: the launcher found Python, but it is too old.
- Fix: rerun with a newer interpreter, or create a local virtual environment from an approved
  Python 3.7+ install as shown above.

**`permission denied: ./phase0.sh`**
- Cause: the shell wrapper is not executable after unzip.
- Fix: run `bash phase0.sh /path/to/project` or `chmod +x phase0.sh`.

**`directory not found`**
- Cause: the target path is wrong, misspelled, or not mounted in the current environment.
- Fix: pass the full path to the source tree and confirm it exists before rerunning.

**`not a directory`**
- Cause: the target path points to a file instead of a source tree root.
- Fix: pass the project directory, not an individual file.

**PowerShell reports that script execution is disabled**
- Cause: local execution policy blocks `.ps1` files.
- Fix: run `py -3 .\phase0.py ...` directly, or use `phase0.cmd`.

**No JSON appears on screen**
- Cause: you used `-o`, so JSON was written to a file instead of standard output.
- Fix: open the named file, or rerun without `-o`.

**`--install-guide` prints only a small amount of output**
- Cause: the scanned codebase may only require a few grammars or no optional language servers.
- Fix: inspect `scan.json` to confirm which languages were detected.

### Recommended operating procedure

1. Unpack the bundle into a temporary working directory.
2. Run `phase0` against the codebase root with `-o scan.json --install-guide`.
3. Review `scan.json` and the printed install guidance.
4. Approve or reject the Phase 1 installation plan based on that output.
5. Keep the `scan.json` file with the engagement artifacts so the install decision is auditable.
6. Optionally compare the output shape to `sample-output.json` in the bundle if reviewers want
   a quick example of the JSON schema.

---

## Install report

After Phase 0 scans your codebase, running `phase0.py --install-guide` from the bundle
produces a plain-language report of exactly what will be installed and how.

Example output for a TypeScript project:

```
Grammar packages (uv pip install):
  tree-sitter-javascript
  tree-sitter-typescript

Language servers (manual steps):
  [javascript] npm install -g typescript-language-server typescript
```

For each detected language, the report shows:
- Which grammar package is needed and how to install it
- Which language server handles `--semantic` enrichment and how it is launched
- Whether any prerequisite runtime (Node, Go, Rust toolchain) needs to be installed first

### Phase 1 Network-restricted environments

If your machine cannot reach the public internet, ensure the following are available before running:

| Component | How it is fetched normally | What to pre-install |
|---|---|---|
| Python grammar wheels (`tree-sitter-python`, etc.) | `pip install` from PyPI | Mirror packages on internal PyPI or pre-install from wheel files |
| `jedi-language-server` | `pip install` from PyPI | Same — mirror or pre-install |
| `typescript-language-server` | `npx` fetches from npm registry on first use | Run `npm install -g typescript-language-server typescript` before running comprehensity, or ensure npm registry is mirrored |
| Node.js / npm / npx | Your standard package manager | Pre-install Node.js from your approved source |
| JDK 21+ (Java `--semantic`) | Your standard package manager or adoptium.net | Pre-install any JDK 21+ distribution; set `JAVA_HOME` or `[java] java_home` in config |
| jdtls (Java `--semantic`) | Eclipse JDT LS releases page | Download the `jdt-language-server-*.tar.gz`, extract, and ensure the launcher jar is on PATH or configure `[java] jdtls_path` |

The grammar packages are small precompiled wheels (a few hundred KB each). Once installed,
**no network access is ever required to run Phase 0 or Phase 1.** The language servers
perform local analysis only — they do not make outbound calls.

---

## The tools doing the work

Phase 0 and Phase 1 use tools your developers almost certainly already run every day.

### tree-sitter

[tree-sitter](https://tree-sitter.github.io/tree-sitter/) is a widely-used open-source
parser library, originally developed at GitHub and now maintained as an independent project.
It powers syntax highlighting and code navigation in VS Code, Neovim, Emacs, and most modern
editors. Comprehensity uses it to parse source files into syntax trees — the same way your
editor parses them to underline errors.

The tree-sitter grammars are small, precompiled Python wheels (one per language). They make
no network calls and have no runtime dependencies beyond Python.

### Language servers (optional, `--semantic` mode)

Language servers are the protocol behind IDE features like "Go to Definition" and "Find All
References." The [Language Server Protocol (LSP)](https://microsoft.github.io/language-server-protocol/)
was created by Microsoft and is now an open standard implemented by most editors and IDEs.

When the `--semantic` flag is used, comprehensity starts a language server, asks it to analyze
your code the same way your IDE would, and after analysis, shuts down the language server.
The language server makes no network calls during this process — it is doing local type-checking
and reference resolution only.

For **Python**, the server (`jedi-language-server`) is installed as a Python wheel alongside
comprehensity — no additional setup. For **JavaScript/TypeScript**, the server
(`typescript-language-server`) is launched via `npx`, which is bundled with Node.js. If Node is
already installed on the machine (which it will be for any JS/TS project), no separate install
step is required. `npx` fetches the server package on first use and caches it locally.
For **Java**, the server (`jdtls` — Eclipse JDT Language Server) requires a JVM 21+ and the
jdtls jar on PATH. Comprehensity searches common JVM locations automatically (JAVA_HOME, Homebrew,
SDKMAN, asdf, system paths); if found, it passes the JVM path to jdtls at launch. If no JVM 21+
is found, the Java semantic phase is skipped with an explanatory message — Phase 1 import and
symbol analysis always works without it.

The tool issues a fixed, auditable set of LSP requests: open file (`textDocument/didOpen`),
find references (`textDocument/references`), and get diagnostics (`textDocument/publishDiagnostics`).
Only production source files are opened — test files are identified by path pattern and excluded
from LSP queries.

If no language server is found, `--semantic` is skipped with a warning. Basic Phase 1
analysis benefits from but does not require it.

**Disabling LSP entirely (air-gapped / CI environments).** If language servers are not
installed and you want to suppress the warning, add this to your `config.toml`:

```toml
[extract]
semantic_enrichment = false
```

With this setting, `--semantic` is a no-op regardless of what is on PATH. This is the
recommended configuration for fully air-gapped environments or CI pipelines that only
need import graph, clone, and modularity output.

### treepeat (clone detection)

Duplicate code detection uses [treepeat](https://github.com/your-org/treepeat), a pure-Python
library that compares syntax trees across files to find matching blocks. It runs three passes:

> **Industry context**: GitClear (2025, n=211M changed lines) measured 12.3% of changed lines
> as duplicated code in AI-assisted repositories, up from 8.3% before widespread AI adoption —
> a 4x increase. The comprehensity clone report shows where your codebase stands relative to
> that baseline.

| Pass | What it finds | Example |
|---|---|---|
| **exact** | Identical code, token-for-token | Copy-paste with no changes |
| **normalized** | Same structure, different names or literals | Same logic, renamed variables |
| **approximate** | Similar structure with minor variations | Near-duplicate functions |

treepeat runs as a subprocess, touches only the files you point it at, and makes no network
calls. It exits when analysis is complete.

**Clone report output.** When `--detect-clones` is used, comprehensity automatically saves
the raw treepeat SARIF file alongside the blueprint:

```
blueprint.json           ← structural blueprint (import graph, symbols, modules)
blueprint.clones.sarif   ← raw clone detection report (SARIF format)
```

The SARIF file is a standalone deliverable. It can be viewed directly, imported into any
SARIF-aware tool (VS Code, GitHub Code Scanning, etc.), or inspected with a text editor —
each clone group lists the exact file paths and line ranges involved. You do not need to
run Phase 2 analysis to use it.

To save the SARIF to a custom path:
```bash
extract_blueprint /path/to/project --detect-clones -o blueprint.json \
  --clones-output /path/to/clones.sarif
```

To suppress the SARIF file entirely (embed clones in blueprint only):
```bash
extract_blueprint /path/to/project --detect-clones -o blueprint.json \
  --clones-output none
```

---

## What leaves your environment

**Nothing in Phase 0 or Phase 1 makes any outbound network call.** This is enforced, not
just a policy.

The test suite includes a socket-blocking fixture that intercepts any attempt to open a network
connection and fails the test immediately. If comprehensity accidentally tried to phone home,
the tests would catch it before the code shipped.

The output of Phase 1 is `blueprint.json`. Here is what it contains:

- **File paths** — relative paths within the project (e.g., `src/main.py`). No absolute
  paths from your machine.
- **File sizes** — in bytes.
- **Import relationships** — which files import which other files, by short opaque ID
  (`f0`, `f1`, …). No source code.
- **External dependencies** — names of packages imported (e.g., `numpy`, `os`). No version
  pinning data.
- **Build config metadata** — parsed summaries of project configuration files found in the
  tree (`pyproject.toml`, `pom.xml`, `Cargo.toml`, `go.mod`, `package.json`,
  `settings.gradle`, and similar). For each file: the declared project name, version,
  direct dependency names, and declared sub-module paths. This data tells the analysis
  server *how the authors intended the project to be decomposed* — Maven `<modules>`,
  Gradle `include` declarations, Cargo workspace members, and npm workspaces all express
  explicit module boundaries. Using declared boundaries rather than inferred ones produces
  more accurate instability and coupling metrics, and gives the LLM labeling step
  ground-truth module names to work with. No source code is included; only the structured
  fields from the config files (name, version, dependency package names).
- **Clone block records** — for each duplicate code region: the file IDs, start/end line
  numbers, and a SHA-256 hash of the block. **No source code is included.** The hash lets
  the analysis server confirm that two instances are identical without ever seeing the text.
- **Symbol metadata** (if `--semantic` was used) — function and class names, call edges,
  diagnostic counts. No function bodies.

Everything in the blueprint is things you would not hesitate to write on a whiteboard.

### Production-code focus

The blueprint is built on a **need-to-know** basis. File paths drive filtering decisions:

- **Test files** are identified by path pattern (`tests/`, `test_*.py`, `*_test.go`,
  `*.spec.ts`, and similar conventions). They appear in the file inventory but their
  symbols are **not included** in the blueprint. Test helpers are not production dead code
  and should not appear in architectural analysis.
- **Generated code** is identified by path pattern (`*_pb2.py`, `*.pb.go`,
  `*.generated.ts`, `generated/`, `__generated__/`, and similar conventions). Same
  treatment as test files: present in the file inventory, symbols excluded. Protobuf stubs
  and codegen output are not architecturally interesting and would inflate dead-code counts.
- **Build artifacts and caches** (`.venv/`, `node_modules/`, `__pycache__/`, etc.) are
  excluded from the scan entirely before any data is collected.

The path-based approach is intentional and auditable: you can verify by inspection which
files are classified as test files and which are treated as production code.

### Example blueprint (abbreviated)

```json
{
  "format": "comprehensity-blueprint",
  "version": "1",
  "generated_at": "2026-03-21T12:00:00Z",
  "files": [
    { "id": "f0", "path": "src/main.py", "size_bytes": 2048, "ext": ".py",
      "imports": ["f3", "ext_os", "ext_numpy"] }
  ],
  "externals": [
    { "id": "ext_numpy", "name": "numpy", "kind": "package" }
  ],
  "clone_blocks": [
    {
      "id": "dup_0",
      "kind": "exact",
      "lines": 23,
      "instances": [
        { "file_id": "f0", "start_line": 45, "end_line": 67, "hash": "a3f...1c" },
        { "file_id": "f3", "start_line": 12, "end_line": 34, "hash": "a3f...1c" }
      ]
    }
  ]
}
```

You can open this file in any text editor and read it yourself before uploading it.
Nothing is sent automatically.

The complete field-by-field specification is in [`spec/blueprint-schema.json`](spec/blueprint-schema.json)
— a standard JSON Schema document that also serves as the machine-verifiable contract
between Phase 1 (extraction) and Phase 2 (analysis).

---

## Zero LLM exposure in Phase 0/1

Phase 0 and Phase 1 contain **no LLM calls and no AI inference of any kind.** They are
deterministic analysis tools: parse the files, walk the import graph, hash the clone blocks,
write the blueprint. There is no mechanism by which your code could reach an LLM during
these phases — because no network calls are made at all.

LLM inference is used only in Phase 2, which runs on the analysis server and receives only
the blueprint. The blueprint contains no source code. The LLM sees file paths, import
relationships, and function names — the same information it would see if you described your
architecture in a document.

---

## Inspecting the code yourself

Phase 0 and Phase 1 are in the following source files, which you are welcome to audit:

| File | What it does |
|---|---|
| `src/phase0.py` | Language detection, build manifest scanning, runtime detection, install guidance (`comprehensity-scan`) |
| `src/scan.py` | Directory traversal, orchestration |
| `src/import_analysis.py` | Tree-sitter import parsers, import resolution |
| `src/ts_parsers.py` | Symbol extractors (function/class names) |
| `src/blueprint_io.py` | LSP client, blueprint assembly |
| `src/blueprint.py` | Blueprint data model (Pydantic) |

If you were sent the Phase 0 source bundle, the Phase 0 file in that bundle is the exact file
to inspect and run. It is a standalone copy of `src/phase0.py` packaged for client use, so a
repo checkout is not required to audit the pre-scan step.

The `--semantic` LSP client is in `blueprint_io.py`. You can verify that it starts the
language server, makes a fixed set of LSP calls (open file, get references, get call
hierarchy, get diagnostics), and then closes the connection. All socket communication is
to `localhost` only — the language server process is a child process on your own machine.

The test suite is in `tests/`. The no-network enforcement fixture is in `tests/conftest.py`.

---

## What Phase 2 produces

Phase 2 runs on the analysis server and reads only `blueprint.json`. It produces:

| Metric | Source |
|---|---|
| Fan-in / fan-out per file | Import adjacency list |
| Circular dependency cycles | Import graph (DFS) |
| Orphan files (no edges) | Import graph |
| Hub / god-object candidates | High fan-in + fan-out |
| External dependency inventory | `externals` list |
| Clone density per file | `clone_blocks` |
| Clone clusters (files sharing multiple clones) | `clone_blocks` |
| File size distribution, large files | `size_bytes` |
| Directory depth and crowding | `path` |
| Module cohesion and instability | Louvain clustering on import graph |
| Domain concept labels | LLM inference on file paths + import structure |

---

## Modularity analysis

Every codebase has module boundaries — the question is whether they match what the code
actually does. Comprehensity detects those boundaries automatically, measures how well
each module holds together, and labels what each one represents.

Detection works at multiple levels:

| Level | What it finds | When |
|---|---|---|
| **L1 — File** | Individual source files | Always |
| **L2 — Language package** | Python packages, Java package declarations, Go package names | Phase 1 |
| **L3 — Build unit** | `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `pyproject.toml` | Phase 0 |
| **L4 — Logical cluster** | Dense import subgraphs that move together | Phase 2 |
| **L5 — Domain concept** | What each cluster *is*: "auth", "payments", "data pipeline" | Phase 2 (LLM) |

L1–L3 run on your machine. L4–L5 run on the analysis server.

Engineering teams can also provide their own module descriptions — for example, the output
of asking a tech lead "list your modules and what each one does." Human labels take precedence
over synthesized ones.

---

## Supported languages

| Language | Import graph | Symbols | Semantic (LSP) |
|---|---|---|---|
| Python | ✅ | ✅ | ✅ jedi-language-server (pip wheel) |
| JavaScript | ✅ | ✅ | ✅ typescript-language-server (via npx; requires Node) |
| TypeScript | ✅ | ✅ | ✅ typescript-language-server (via npx; requires Node) |
| Java | ✅ | ✅ | ⚠️ requires JVM 21+ + jdtls |
| C / C++ | ✅ (best-effort) | — | — |
| Go | — | — | ⚠️ requires Go + gopls |
| Rust | ✅ clone detection | — | ⚠️ requires Rust toolchain + rust-analyzer |

Semantic analysis (`--semantic`) is optional. Phase 1 basic import and clone analysis
works for Python, JavaScript, TypeScript, Java, and C/C++ without any language server.
Rust clone detection via `--detect-clones` works at Phase 1 even without a language server.
If a language server is not found, that language is skipped with a warning.

For the full language support matrix including grammar packages and installer implications,
see [LANGUAGE_SUPPORT.md](LANGUAGE_SUPPORT.md).

---

## Questions

If you have questions about the blueprint format, the no-network guarantee, or anything
else in this document, please reach out before running the tool. We are happy to walk
through any part of the code or the data flow in detail.
