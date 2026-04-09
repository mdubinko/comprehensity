# comprehensity

Tools for evaluating AI codegen quality by analyzing code structure, dependencies, and duplicates.

Analysis runs in two phases: `extract_blueprint` runs client-side (no network calls, no LLMs)
and produces a compact `blueprint.json`; Phase 2 analysis reads only that file and produces
the full insights report.

**Security and privacy:** see [CLIENT_README.md](CLIENT_README.md) for a full explanation
of what runs on your machines, what leaves your environment, and how the no-network guarantee
is enforced.

**Why this matters:** see [WHITEPAPER.md](WHITEPAPER.md) for the empirical case for
structural code quality in AI-assisted development.

## Installation

### Phase0 Source Bundle

`phase0` can be shipped as a plain source bundle for client-side pre-scan use.

Bundle source-of-truth lives under:

```text
installers/
  phase0/
    BUILD.md
    BUILD_COMMIT
    INSTRUCTIONS.md
    README.md
    bundle.sh
    manifest.txt
    launchers/
      phase0.sh
      phase0.ps1
      phase0.cmd
```

Built artifacts are written to:

```text
dist/
  phase0/
    comprehensity-phase0-<version>.zip
    comprehensity-phase0-<version>.zip.sha256
```

Build the bundle locally with:

```bash
bash installers/phase0/bundle.sh
```

The bundle contains:
- `BUILD_COMMIT`
- `INSTRUCTIONS.md`
- `phase0.py`
- `phase0.sh`
- `phase0.ps1`
- `phase0.cmd`
- `README.md`
- `sample-output.json`
- `VERSION`

The GitHub Actions workflow at [`.github/workflows/build-phase0.yml`](.github/workflows/build-phase0.yml)
runs the same script in CI so local and CI builds stay aligned.

### Repo Setup

### Prerequisites

- Python 3.8+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Setup

```bash
git clone https://github.com/mdubinko/comprehensity.git
cd comprehensity

python3 -m venv .venv
source .venv/bin/activate     # Windows: .venv\Scripts\activate

uv pip install -e .

# Optional: include clone detection (adds treepeat)
uv pip install -e ".[clone]"
```

No Node.js or external runtimes are required for basic use.

## Usage

### Phase 0 — Inventory the codebase (optional pre-scan)

For client delivery, `phase0` can be run from the plain source bundle without a repo checkout.
See [CLIENT_README.md](CLIENT_README.md) for operating instructions and troubleshooting.

```bash
# Quick scan: what languages, build configs, and runtimes are present?
comprehensity-scan /path/to/project

# Write scan JSON for later use by the installer
comprehensity-scan /path/to/project -o scan.json

# Show grammar + language server install steps derived from the scan
comprehensity-scan /path/to/project --install-guide

# Write scan JSON and print install guide
comprehensity-scan /path/to/project -o scan.json --install-guide

# Show progress for large scans
comprehensity-scan /path/to/project --progress
```

`comprehensity-scan` is stdlib-only and runs before any grammar packages are installed.
By default it also prints a short install summary to `stderr`; use `--install-guide` for the
full detailed install guide on `stdout`.
It drives installer grammar selection and generates targeted language server guidance.

### Phase 1 — Extract a blueprint (client-side)

```bash
# Scan a project and produce a blueprint
extract_blueprint /path/to/project -o blueprint.json

# With clone detection — also writes blueprint.clones.sarif alongside the blueprint
extract_blueprint /path/to/project --detect-clones -o blueprint.json

# Custom SARIF output path, or suppress with 'none'
extract_blueprint /path/to/project --detect-clones -o blueprint.json --clones-output report.sarif

# With LSP-based call graph and diagnostics (requires a language server on PATH)
extract_blueprint /path/to/project --semantic -o blueprint.json

# Show progress for large projects
extract_blueprint /path/to/project --progress -o blueprint.json

# Disable LSP entirely for air-gapped / CI environments (config.toml)
# [extract]
# semantic_enrichment = false

# Inspect the blueprint before sharing — it contains no source code
cat blueprint.json
```

#### Production-code focus

The blueprint is built on a **need-to-know** basis. File paths are used to classify code
before analysis:

- **Test files** (`tests/`, `test_*.py`, `*_test.go`, `*.spec.ts`, etc.) are included in
  the file inventory and import graph but their symbols are **excluded from symbol extraction,
  dead-code analysis, and LSP queries**. Test helper functions are not production dead code.
- **Generated code** (`*_pb2.py`, `*.pb.go`, `*.generated.ts`, `generated/`,
  `__generated__/`, etc.) is handled the same way — present in the file inventory but
  excluded from symbol analysis. Protobuf stubs and codegen output inflate dead-code counts
  and add call-graph noise without contributing architectural signal.
- **Build artifacts and caches** (`.venv/`, `node_modules/`, `__pycache__/`, etc.) are
  excluded from the scan entirely via `--ignore-dirs`.

Path patterns are the mechanism: by checking whether a file's path looks like a test file,
comprehensity avoids bloating the blueprint with test scaffolding and avoids false dead-code
positives from uncalled test helpers.

## Development

```bash
uv pip install -e ".[dev]"
```

### Running tests

**Tier 1 — unit + fixture tests** (fast, run per-commit):
```bash
.venv/bin/python -m pytest tests/ -q --tb=short
```

**Tier 2 — real codebase scans** (slower, run manually or overnight):
```bash
# All enabled projects
.venv/bin/python tests/tier2/run.py

# Single project by name
.venv/bin/python tests/tier2/run.py --project cogno

# Filter by language
.venv/bin/python tests/tier2/run.py --language python

# Run projects blocked on a language (e.g. after adding Go support)
.venv/bin/python tests/tier2/run.py --pending go
```

Tier 2 outputs land in `output/tier2/<name>/` with timestamps. The run log
is at `output/tier2/run_<timestamp>.log`. Project list and configuration are
in `tests/tier2/projects.toml`.

### Adding a language parser

1. Subclass `TreeSitterImportParser` in `src/import_analysis.py`
2. Provide the tree-sitter language object and an s-expression query
3. Implement `get_supported_extensions()` and `_classify_import()`
4. Register in `LanguageDetector._register_default_parsers()` in `src/import_analysis.py`
5. Add a fixture file in `tests/fixtures/lang/` and tests in `tests/test_ts_parsers.py`

See [LANGUAGE_SUPPORT.md](LANGUAGE_SUPPORT.md) for the full language matrix and per-language
LSP server decisions.

See [SECURITY.md](SECURITY.md) for the no-network guarantee and OS-level isolation options.
