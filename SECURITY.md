# Security: No-Network Guarantee

Comprehensity's client-side phases (Phase 0 and Phase 1 basic) carry an
explicit contractual guarantee: **they make zero outbound network calls**.

This document describes what that guarantee covers, how it is enforced, and
what the customer's data-flow looks like.

---

## Scope

| Phase | Runs where | Network calls |
|---|---|---|
| Phase 0 (`phase0.py`) | Customer's machine | **None** |
| Phase 1 basic (`extract_blueprint`) | Customer's machine | **None** |
| Phase 1 semantic (`extract_blueprint --semantic`) | Customer's machine | Local socket to language server subprocess only |
| Phase 2 (`analyze_blueprint`) | Analysis server | Yes — reads `blueprint.json` that the customer explicitly uploads |

Phases 0 and 1 basic produce a `blueprint.json` file. **All outbound
communication is initiated explicitly by the customer** when they choose to
share that file with the Phase 2 server.

---

## What the client-side code imports

**Phase 0** — stdlib only (Python 3.6+):
`json`, `os`, `pathlib`, `sys`, `typing`. No third-party packages.

**Phase 1 basic** — stdlib plus:
- `pydantic` — data validation; no network calls at runtime.
- `tree-sitter` and grammar wheels (`tree-sitter-python`, `tree-sitter-typescript`,
  etc.) — pure C parsers compiled into platform wheels at publish time; they
  do not open any socket at runtime.
- `propweaver` — local graph database; no network calls.

None of these packages import `socket`, `urllib`, `requests`, `httpx`, or
any other networking primitive during their normal operation.

---

## Enforcement layers

### 1. Static import audit (CI gate)

`tests/test_no_network.py` runs on every `pytest` invocation and:

- Verifies that `phase0.py` imports **only stdlib modules** (AST-level check).
- Verifies that every client-side module (`phase0.py`, `blueprint.py`,
  `blueprint_io.py`, `clone_detection.py`, `scan.py`, `ts_parsers.py`,
  `import_analysis.py`, `srcgraph.py`) does **not** directly import any
  networking primitive (`socket`, `urllib`, `requests`, `httpx`, `http`,
  `ssl`, etc.).

This is a code-level check — it catches violations before any code runs.

### 2. Runtime socket-blocking fixture (pytest)

`tests/conftest.py` installs a session-scoped autouse fixture that replaces
`socket.socket` with a function that raises `RuntimeError` immediately.

Any attempt to open a network connection during the test suite — including
import-time side effects from any dependency — fails loudly rather than
timing out or silently succeeding.

### 3. OS-level network isolation (for formal audits)

For customers who require hardware-level assurance, the client-side phases can
be run inside a network-isolated process:

**Linux:**
```bash
unshare --net python3 src/phase0.py .
unshare --net python3 -m pytest tests/
```

**macOS (Docker):**
```bash
docker run --network none -v "$(pwd)":/app -w /app python:3.11-slim \
    python src/phase0.py .
```

**Windows:**
Run inside Windows Sandbox or a Hyper-V container with outbound networking
disabled.

These are belt-and-suspenders options for security auditors. The software-level
guarantees (layers 1 and 2 above) apply in all standard deployments.

---

## Data flow summary

```
Customer's machine                      Analysis server
─────────────────                       ───────────────
Phase 0 (stdlib only)
  → extension histogram, build configs
  → drives installer (no outbound I/O)

Phase 1 basic (tree-sitter, pydantic)
  → reads source files locally
  → produces blueprint.json
  → NO outbound network calls

Customer reviews blueprint.json
Customer uploads blueprint.json  ──────→ Phase 2 (analyze_blueprint)
                                          → graph analysis, scoring
                                          → report returned to customer
```

Source code never leaves the customer's machine. Only the structural blueprint
(file paths, import edges, symbol names, clone hashes) is shared, and only
when the customer explicitly initiates the upload.

---

## Repository security posture

This repository has automated **CodeQL analysis** enabled for static security
scanning, as well as **Dependabot** vulnerability and malware alerts for all
dependencies.
