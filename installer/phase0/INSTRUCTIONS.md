# Phase0 Instructions

This bundle is the standalone client-side pre-scan for Comprehensity.

## What you need

- Python 3.7 or newer
- Read access to the source tree you want to scan
- Optional: write access to the directory where you want `scan.json`

`phase0` is stdlib-only. It does not install packages and does not require a repo checkout.

## Files in this bundle

- `phase0.py`: the scanner itself
- `phase0.sh`: macOS / Linux launcher
- `phase0.ps1`: Windows PowerShell launcher
- `phase0.cmd`: Windows Command Prompt launcher
- `sample-output.json`: example shape of the JSON output
- `BUILD_COMMIT`: source commit used to build this bundle
- `VERSION`: bundle version

## Run on macOS / Linux

```bash
./phase0.sh /path/to/project
./phase0.sh /path/to/project -o scan.json --install-guide
```

By default, `phase0` prints a short install summary to standard error after the scan completes.
Use `--install-guide` when you want the full detailed installation steps on standard output.

If the shell script is not executable:

```bash
bash phase0.sh /path/to/project -o scan.json --install-guide
```

## Run on Windows PowerShell

```powershell
.\phase0.ps1 C:\path\to\project
.\phase0.ps1 C:\path\to\project -o scan.json --install-guide
```

If PowerShell script execution is restricted:

```powershell
py -3 .\phase0.py C:\path\to\project -o scan.json --install-guide
```

## Run on Windows Command Prompt

```bat
phase0.cmd C:\path\to\project
phase0.cmd C:\path\to\project -o scan.json --install-guide
```

## If the machine Python is too old

`phase0` requires Python 3.7+.

If the default `python` on the machine is older, use any newer Python already approved on that
machine and create a local virtual environment next to the bundle:

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

`uv` is optional. If it is already installed and approved in your environment, it may also be
used to provision an isolated Python, but `venv` is preferred here because it is built into
standard Python.

## Verify the bundle

If you received a `.zip.sha256` file alongside the bundle, verify it before unpacking:

macOS / Linux:

```bash
shasum -a 256 comprehensity-phase0-<version>.zip
cat comprehensity-phase0-<version>.zip.sha256
```

Windows PowerShell:

```powershell
Get-FileHash .\comprehensity-phase0-<version>.zip -Algorithm SHA256
Get-Content .\comprehensity-phase0-<version>.zip.sha256
```

The hash values should match exactly.

The checksum file also includes the source commit so you can record both the SHA-256 and the
source revision together in your review notes.
