# Phase0 Source Bundle

This directory builds a plain-source `phase0` release bundle for client delivery.

The bundle intentionally stays simple:
- visible Python source (`phase0.py`)
- thin platform launchers
- a client-facing `INSTRUCTIONS.md`
- explicit bundle build metadata (`BUILD_COMMIT`)
- no repo checkout required for the client

Build locally with:

```bash
./installers/phase0/bundle.sh
```

Artifacts are written to `dist/phase0/`.
