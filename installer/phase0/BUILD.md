# Building Phase0

The build is driven by [`bundle.sh`](/Users/micah/Developer/AI/comprehensity/installers/phase0/bundle.sh).

It:
- reads the version from `pyproject.toml`
- stages a plain-source bundle containing `phase0.py` and launcher scripts
- writes a zip artifact to `dist/phase0/`
- writes a SHA-256 checksum file next to the zip

Run:

```bash
./installers/phase0/bundle.sh
```

The GitHub Actions workflow uses the same script so local and CI builds stay aligned.
