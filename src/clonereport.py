"""clonereport.py — supplemental clone source report.

Reads a blueprint.json/yaml produced by extract-blueprint and emits a
markdown file showing the actual duplicated source for each clone block,
sorted by size (lines) descending.

File paths in the blueprint are relative to the scan root, so the
repository root must be supplied via --repo. This lets the report be
read on any machine (e.g. shared with a reviewer) and re-run with the
correct local path.

Usable immediately after extract-blueprint — no phase 2 analysis needed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a supplemental markdown report showing source for each clone block.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  comprehensity-clonereport --blueprint blueprint.json --repo . -o clones.md
  comprehensity-clonereport --blueprint output/bp.yaml --repo /path/to/repo -o clones.md
        """,
    )
    parser.add_argument("--blueprint", required=True, metavar="FILE",
                        help="Path to blueprint.json or blueprint.yaml")
    parser.add_argument("--repo", required=True, metavar="DIR",
                        help="Path to the scanned repository root")
    parser.add_argument("-o", "--output", default="clones.md", metavar="FILE",
                        help="Output markdown file (default: clones.md)")
    args = parser.parse_args()

    bp_path = Path(args.blueprint)
    if not bp_path.exists():
        print(f"error: blueprint not found: {bp_path}", file=sys.stderr)
        sys.exit(1)

    repo_root = Path(args.repo).resolve()
    if not repo_root.is_dir():
        print(f"error: repo root not found: {repo_root}", file=sys.stderr)
        sys.exit(1)

    from blueprint import Blueprint

    if bp_path.suffix in (".yaml", ".yml"):
        bp: Blueprint = Blueprint.from_yaml_file(str(bp_path))
    else:
        bp = Blueprint.model_validate_json(bp_path.read_text())

    if not bp.clone_blocks:
        print("No clone blocks in blueprint — nothing to report.")
        sys.exit(0)

    fid_to_path = {f.id: f.path for f in bp.files}

    # Sort largest first (matches Clone ROI table ordering in the phase2 report)
    sorted_blocks = sorted(bp.clone_blocks, key=lambda b: b.lines, reverse=True)

    out_lines: list[str] = [
        "# Clone Source Report",
        "",
        f"Blueprint: `{bp_path}`  ",
        f"Repository: `{repo_root}`  ",
        f"Clone blocks: {len(sorted_blocks)}",
        "",
        "| Clone | Kind | Lines | Instances |",
        "|-------|------|------:|----------:|",
    ]
    for block in sorted_blocks:
        out_lines.append(
            f"| {block.id} | {block.kind} | {block.lines} | {len(block.instances)} |"
        )
    out_lines.append("")

    missing: list[str] = []

    for block in sorted_blocks:
        out_lines.append(
            f"## {block.id} — {block.kind}, {block.lines} lines,"
            f" {len(block.instances)} instances"
        )
        out_lines.append("")
        for inst in block.instances:
            file_rel = fid_to_path.get(inst.file_id, f"(unknown {inst.file_id})")
            abs_path = repo_root / file_rel
            out_lines.append(
                f"### `{file_rel}` lines {inst.start_line}–{inst.end_line}"
            )
            out_lines.append("")
            if abs_path.exists():
                try:
                    src = abs_path.read_text(errors="replace").splitlines()
                    snippet = src[inst.start_line - 1 : inst.end_line]
                    lang = Path(file_rel).suffix.lstrip(".")
                    out_lines.append(f"```{lang}")
                    out_lines.extend(snippet)
                    out_lines.append("```")
                except OSError as exc:
                    out_lines.append(f"_(could not read: {exc})_")
                    missing.append(file_rel)
            else:
                out_lines.append(
                    f"_(file not found at `{abs_path}` — was this report generated"
                    " on a different machine? Re-run with the correct --repo path.)_"
                )
                missing.append(file_rel)
            out_lines.append("")

    out_path = Path(args.output)
    out_path.write_text("\n".join(out_lines))

    if missing:
        print(
            f"⚠️  {len(missing)} file(s) not found under {repo_root} — snippets omitted.",
            file=sys.stderr,
        )
    print(f"✅ {len(sorted_blocks)} clone block(s) → {out_path}")


if __name__ == "__main__":
    main()
