# Comprehensity Report

Generated: 2026-04-29 02:55 UTC

## Architecture Summary

This layered architecture, separating core structures from client implementation and test suites, permits bounded changes if agents are provided with relevant core definitions. Responsibilities between transport logic and configuration are distinct, though overlapping module definitions suggest certain edits may require context across multiple directory levels to ensure consistency. Duplication is above 30 per 100 files, meaning agents will encounter frequent duplicate sites when editing shared patterns, increasing the risk of divergent updates.

## Overview

| Metric | Value |
|--------|------:|
| Files | 38 |
| Externals | 50 |
| Symbols | 278 |
| L3 Build Units | 2 |
| L2 Packages | 3 |
| L4 Clusters | 10 |
| Clone blocks | 12 (31.6 per 100 files) |
| Avg Instability | 0.936 |
| Avg Distance from Main Seq | 0.194 |
| Analysis completeness | ✅ Full |

## Build Units (L3)

Each entry is a directory containing a build manifest (package.json, Cargo.toml, pyproject.toml, pom.xml, etc.).

| Module | Path | Build System | Files |
|--------|------|:------------:|------:|
| m0 | `(root)` | make | 35 |
| m1 | `docs` | make | 3 |

## Modules (L4 Clusters)

Sorted by instability descending. **I** = instability (1 → no dependents, 0 → no outgoing deps). **A** = abstractness. **D** = distance from main sequence |A+I−1|.

| Cluster | Label | Files | Ca | Ce | I | A | D |
|---------|-------|------:|---:|---:|--:|--:|--:|
| cl0 | flask_theme_support | 1 | 0 | 2 | 1.000 | 1.000 | 1.000 |
| cl4 | setup | 1 | 0 | 2 | 1.000 | 0.000 | 0.000 |
| cl6 | certs | 1 | 0 | 1 | 1.000 | 0.000 | 0.000 |
| cl8 | HTTP client test suite | 6 | 0 | 21 | 1.000 | 0.000 | 0.000 |
| cl5 | HTTP client library (13 files) | 13 | 3 | 39 | 0.929 | 0.170 | 0.099 |
| cl1 | HTTP client library (8 files) | 8 | 3 | 14 | 0.824 | 0.000 | 0.176 |
| cl7 | HTTP client core structures | 5 | 3 | 12 | 0.800 | 0.118 | 0.082 |
| … | _3 isolated single-file clusters omitted (no import relationships)_ | | | | | | |

## Top Unstable Modules

High instability (I → 1) means the cluster imports heavily from others but few clusters depend on it — it sits at the leaf end of the dependency graph. Agents touching these clusters must hold a large incoming dependency surface in context: a change may require tracing through many imported modules to reason about correctness. Trivial single-file clusters with no inbound dependencies are excluded; only clusters that represent meaningful groupings or have real dependents appear here.

- **HTTP client test suite** (`cl8`) — I=1.000, 6 files
- **HTTP client library (13 files)** (`cl5`) — I=0.929, 13 files
- **HTTP client library (8 files)** (`cl1`) — I=0.824, 8 files
- **HTTP client core structures** (`cl7`) — I=0.800, 5 files

## Clone ROI

Sorted by size (lines) descending — larger clone blocks carry more risk that an agent editing one instance will miss the others, producing inconsistent changes across the codebase. Clone blocks where every instance is in a test or spec file are excluded. Dead fraction indicates what proportion of the clone's files contain unreferenced symbols; this is informational only and does not affect ranking.

| Clone | Lines | Dead Fraction |
|-------|------:|--------------:|
| dup_10 | 12 | 0.00 |
| dup_11 | 10 | 0.00 |
| dup_4 | 9 | 1.00 |
| dup_1 | 8 | 1.00 |
| dup_0 | 7 | 1.00 |
| dup_2 | 7 | 1.00 |
| dup_3 | 7 | 1.00 |

> To see the actual duplicated source for each clone block, run:
> `comprehensity-clonereport --blueprint path/to/blueprint.json --repo /path/to/repo -o clones.md`
