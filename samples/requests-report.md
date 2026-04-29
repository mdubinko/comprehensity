# Comprehensity Report

Generated: 2026-04-29 23:18 UTC

## Architecture Summary

The codebase follows a layered architecture, transitioning from high-level HTTP interfaces through client libraries to core primitives and a mock server. This separation of concerns allows agents to perform bounded changes within specific layers by isolating interface definitions from implementation details. Because duplication is above 15 per 100 files, agents will encounter duplicate sites when editing shared patterns, requiring coordinated updates across all instances.

## Overview

| Metric | Value |
|--------|------:|
| Files | 38 |
| Externals | 50 |
| Symbols | 278 |
| L3 Build Units | 2 |
| L2 Packages | 3 |
| L4 Clusters | 10 |
| Clone blocks | 7 (18.4 per 100 files) |
| Avg Instability | 0.936 |
| Avg Distance from Main Seq | 0.194 |
| Analysis completeness | ✅ Full |

## Build Units (L3)

Each entry is a directory containing a build manifest (package.json, Cargo.toml, pyproject.toml, pom.xml, etc.).

| Module | Path | Build System | Files |
|--------|------|:------------:|------:|
| m0 | `(root)` | make | 35 |
| m1 | `docs` | make | 3 |

## Parse Coverage

36/36 grammar-supported files parsed cleanly (100%). 0 had parse errors. 2 files have no grammar (not analysed) (`docs/make.bat`, `pyproject.toml`).

**By file type** (grammar-supported only):

| Extension | OK | Errors | Error % |
|-----------|---:|-------:|--------:|
| `.py` | 36 | 0 | 0% |

## Modules (L4 Clusters)

Sorted by instability descending. **I** = instability (1 → no dependents, 0 → no outgoing deps). **A** = abstractness. **D** = distance from main sequence |A+I−1|.

| Cluster | Label | Files | Ca | Ce | I | A | D |
|---------|-------|------:|---:|---:|--:|--:|--:|
| cl0 | flask_theme_support | 1 | 0 | 2 | 1.000 | 1.000 | 1.000 |
| cl4 | setup | 1 | 0 | 2 | 1.000 | 0.000 | 0.000 |
| cl6 | certs | 1 | 0 | 1 | 1.000 | 0.000 | 0.000 |
| cl8 | Mock HTTP Server | 6 | 0 | 21 | 1.000 | 0.000 | 0.000 |
| cl5 | High-level HTTP client interface | 13 | 3 | 39 | 0.929 | 0.170 | 0.099 |
| cl1 | HTTP client library | 8 | 3 | 14 | 0.824 | 0.000 | 0.176 |
| cl7 | Core HTTP primitives | 5 | 3 | 12 | 0.800 | 0.118 | 0.082 |
| … | _3 files with no detected dependencies omitted_ | | | | | | |

_3 files (8% of all files) have no detected import relationships to other files in this repo. This may reflect tool/config files, genuinely isolated utilities, or languages with incomplete import extraction._

## Module Instability

The codebase exhibits a leaf-heavy topology ($I_{avg} = 0.936$) typical of standalone libraries, meaning agents face low blast-radius from in-repo dependents but must trace outgoing dependencies—such as those in `High-level HTTP client interface`—to understand the full context of a change. Because no modules were identified with $I < 0.5$, there are no high-impact stable cores that would trigger widespread architectural ripples during an edit. Consequently, an agent can typically achieve highly predictable change scoping, often requiring only 1–2 modules in active context to execute a bounded task.

## Clone ROI

The codebase exhibits production logic duplication within the `src/requests/` module, specifically across `api.py`, `cookies.py`, and `auth.py`. The highest impact risks are found in multi-line blocks within `src/requests/api.py` and recurring patterns in `src/requests/cookies.py`. At a density of 18.4 per 100 files, agents will regularly produce divergent edits across duplicate sites.

**Top clone blocks by size** (test-only blocks excluded):

| Clone | Lines | Dead Fraction |
|-------|------:|--------------:|
| dup_5 | 12 | 0.00 |
| dup_6 | 10 | 0.00 |
| dup_4 | 9 | 1.00 |
| dup_1 | 8 | 1.00 |
| dup_0 | 7 | 1.00 |
| dup_2 | 7 | 1.00 |
| dup_3 | 7 | 1.00 |

> To see the actual duplicated source for each clone block, run:
> `comprehensity-clonereport --blueprint path/to/blueprint.json --repo /path/to/repo -o clones.md`
