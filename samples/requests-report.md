# Comprehensity Report

Generated: 2026-04-27 18:13 UTC

## Architecture Summary

The codebase follows a layered architecture centered on core HTTP data structures and a client library, requiring agents to maintain visibility across protocol definitions and implementation modules for bounded changes. Responsibilities are partitioned into distinct domains such as testing and certificate management, yet the shared reliance on core types necessitates broader context for downstream-impacting edits. Duplication is above 30 per 100 files, meaning agents will encounter frequent duplicate sites when editing shared patterns, increasing the risk of divergent updates across the repository.

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
| cl8 | HTTP client testing | 6 | 0 | 21 | 1.000 | 0.000 | 0.000 |
| cl5 | HTTP client library | 13 | 3 | 39 | 0.929 | 0.170 | 0.099 |
| cl1 | HTTP client library | 8 | 3 | 14 | 0.824 | 0.000 | 0.176 |
| cl7 | HTTP core data structures | 5 | 3 | 12 | 0.800 | 0.118 | 0.082 |
| cl2 | make | 1 | 0 | 0 | — | 0.000 | — |
| cl3 | pyproject | 1 | 0 | 0 | — | 0.000 | — |
| cl9 | __init__ | 1 | 0 | 0 | — | 0.000 | — |

## Top Unstable Modules

High instability (I → 1) means a cluster depends on many others but few depend on it. Agents making changes here must understand a large dependency surface, and changes are harder to scope and contain.

- **flask_theme_support** (`cl0`) — I=1.000, 1 file
- **setup** (`cl4`) — I=1.000, 1 file
- **certs** (`cl6`) — I=1.000, 1 file
- **HTTP client testing** (`cl8`) — I=1.000, 6 files
- **HTTP client library** (`cl5`) — I=0.929, 13 files

## Clone ROI

ROI score = lines × dead_fraction. Higher scores mean more deduplication benefit — and higher risk that agents editing one instance will miss others, producing inconsistent changes across the codebase.

| Clone | Lines | Dead Fraction | ROI Score |
|-------|------:|--------------:|----------:|
| dup_4 | 9 | 1.00 | 9.00 |
| dup_1 | 8 | 1.00 | 8.00 |
| dup_0 | 7 | 1.00 | 7.00 |
| dup_2 | 7 | 1.00 | 7.00 |
| dup_3 | 7 | 1.00 | 7.00 |
| dup_5 | 6 | 0.00 | 0.00 |
| dup_6 | 6 | 0.00 | 0.00 |
| dup_7 | 15 | 0.00 | 0.00 |
| dup_8 | 6 | 0.00 | 0.00 |
| dup_9 | 5 | 0.00 | 0.00 |
