#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/../.." && pwd)"
INSTALLER_DIR="$ROOT_DIR/installer/phase0"
DIST_DIR="$ROOT_DIR/dist/phase0"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required to build the phase0 bundle" >&2
  exit 1
fi

VERSION="$(
  python3 - "$ROOT_DIR/pyproject.toml" <<'PY'
import pathlib
import re
import sys

text = pathlib.Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
if not match:
    raise SystemExit("Could not find version in pyproject.toml")
print(match.group(1))
PY
)"
BUILD_VERSION="$(python3 - <<'PY'
from datetime import datetime, timezone
print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ"))
PY
)"
BUILD_COMMIT="$(git -C "$ROOT_DIR" rev-parse --short=12 HEAD)"

BUNDLE_NAME="comprehensity-phase0-${VERSION}"
STAGING_DIR="$(mktemp -d "${TMPDIR:-/tmp}/phase0-bundle.XXXXXX")"
trap 'rm -rf "$STAGING_DIR"' EXIT

mkdir -p "$DIST_DIR"
mkdir -p "$STAGING_DIR/$BUNDLE_NAME"

rm -f "$DIST_DIR/$BUNDLE_NAME.zip" "$DIST_DIR/$BUNDLE_NAME.zip.sha256"

cp "$INSTALLER_DIR/README.md" "$STAGING_DIR/$BUNDLE_NAME/README.md"
cp "$INSTALLER_DIR/INSTRUCTIONS.md" "$STAGING_DIR/$BUNDLE_NAME/INSTRUCTIONS.md"
cp "$INSTALLER_DIR/sample-output.json" "$STAGING_DIR/$BUNDLE_NAME/sample-output.json"
cp "$INSTALLER_DIR/launchers/phase0.sh" "$STAGING_DIR/$BUNDLE_NAME/phase0.sh"
cp "$INSTALLER_DIR/launchers/phase0.ps1" "$STAGING_DIR/$BUNDLE_NAME/phase0.ps1"
cp "$INSTALLER_DIR/launchers/phase0.cmd" "$STAGING_DIR/$BUNDLE_NAME/phase0.cmd"
printf '%s\n' "$VERSION" > "$STAGING_DIR/$BUNDLE_NAME/VERSION"
printf '%s\n' "$BUILD_COMMIT" > "$STAGING_DIR/$BUNDLE_NAME/BUILD_COMMIT"

python3 - "$ROOT_DIR/src/phase0.py" "$STAGING_DIR/$BUNDLE_NAME/phase0.py" "$VERSION" "$BUILD_COMMIT" "$BUILD_VERSION" <<'PY'
import pathlib
import sys

source_path = pathlib.Path(sys.argv[1])
dest_path = pathlib.Path(sys.argv[2])
version = sys.argv[3]
build_commit = sys.argv[4]
build_version = sys.argv[5]

source = source_path.read_text(encoding="utf-8")
dest_path.write_text(
    "# Bundle source version: %s\n# Bundle source commit: %s\n# Bundle build version (UTC): %s\n%s"
    % (version, build_commit, build_version, source),
    encoding="utf-8",
)
PY

chmod +x "$STAGING_DIR/$BUNDLE_NAME/phase0.sh"

(
  cd "$STAGING_DIR"
  python3 -m zipfile -c "$DIST_DIR/$BUNDLE_NAME.zip" "$BUNDLE_NAME"
)

python3 - "$DIST_DIR/$BUNDLE_NAME.zip" "$VERSION" "$BUILD_COMMIT" "$BUILD_VERSION" <<'PY' > "$DIST_DIR/$BUNDLE_NAME.zip.sha256"
import hashlib
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
version = sys.argv[2]
build_commit = sys.argv[3]
build_version = sys.argv[4]
digest = hashlib.sha256(path.read_bytes()).hexdigest()
print(f"# version: {version}")
print(f"# commit: {build_commit}")
print(f"# build-version: {build_version}")
print(f"{digest}  {path.name}")
PY

echo "Built:"
echo "  $DIST_DIR/$BUNDLE_NAME.zip"
echo "  $DIST_DIR/$BUNDLE_NAME.zip.sha256"
