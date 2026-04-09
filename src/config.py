"""
config.py — Comprehensity configuration management.

Search order (first file found wins):
  1. Same directory as the running executable (for client deployments)
  2. ~/.comprehensity/config.toml
  3. Built-in defaults (backend = "none", graceful degradation)

Environment variable override:
  COMPREHENSITY_LLM_API_KEY  — overrides [phase2.llm] api_key from config file

Config file sections by phase:
  [scan]               # Phase 0 — future: ignore-dirs, extension overrides
  [extract]            # Phase 1 — future: clone detection defaults, LSP timeouts
  [phase2.llm]         # Phase 2 only — never included in blueprint.yaml
  [phase2.token_budget] # Phase 2 only — never included in blueprint.yaml

Usage:
  from config import load_config
  cfg, cfg_path, cfg_raw = load_config()
  # cfg_path is None when built-in defaults are used
  # Access phase2 settings via cfg.phase2.llm, cfg.phase2.token_budget
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Optional, Tuple

from pydantic import BaseModel, Field

# tomllib is stdlib in Python ≥ 3.11; tomli is the backport for 3.8–3.10.
try:
    import tomllib  # type: ignore[import]
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[import,no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]  # no TOML support — use defaults only


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

class ScanConfig(BaseModel):
    """Phase 0 settings — no configurable fields yet."""


class ExtractConfig(BaseModel):
    """Phase 1 (extract_blueprint) settings."""
    semantic_enrichment: bool = True  # set false to skip LSP in air-gapped / CI environments


class JavaConfig(BaseModel):
    """Java-specific settings.

    java_home: path to a JDK installation directory (the directory that
    contains ``bin/java``).  Equivalent to the ``COMPREHENSITY_JAVA_HOME``
    environment variable but stored in the config file for reproducibility.
    The env var takes precedence over this setting.
    """
    java_home: Optional[str] = None


class LlmConfig(BaseModel):
    backend: str = "none"          # ollama | lmstudio | openai | anthropic | none
    base_url: str = "http://localhost:11434"
    model: str = "phi4"
    api_key: str = ""
    timeout: int = Field(default=30, ge=1)


class TokenBudgetConfig(BaseModel):
    max_tokens_per_run: int = Field(default=0, ge=0)   # 0 = unlimited
    report_usage: bool = True


class Phase2Config(BaseModel):
    """Phase 2 settings — LLM and token budget. Never stamped into blueprint.yaml."""
    llm: LlmConfig = Field(default_factory=LlmConfig)
    token_budget: TokenBudgetConfig = Field(default_factory=TokenBudgetConfig)


class ComprehensityConfig(BaseModel):
    scan: ScanConfig = Field(default_factory=ScanConfig)
    extract: ExtractConfig = Field(default_factory=ExtractConfig)
    java: JavaConfig = Field(default_factory=JavaConfig)
    phase2: Phase2Config = Field(default_factory=Phase2Config)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

def _candidate_paths(exe_dir):
    """Yield candidate config file paths in search-order priority."""
    if exe_dir and exe_dir is not False:
        yield Path(exe_dir) / "config.toml"
    yield Path.home() / ".comprehensity" / "config.toml"


def _parse_toml(path: Path) -> dict:
    if tomllib is None:
        return {}
    with open(path, "rb") as fh:
        return tomllib.load(fh)


def _build_config(data: dict) -> ComprehensityConfig:
    scan_data = data.get("scan", {})
    extract_data = data.get("extract", {})
    java_data = data.get("java", {})
    phase2_data = data.get("phase2", {})
    llm_data = phase2_data.get("llm", {})
    budget_data = phase2_data.get("token_budget", {})
    return ComprehensityConfig(
        scan=ScanConfig(**scan_data) if scan_data else ScanConfig(),
        extract=ExtractConfig(**extract_data) if extract_data else ExtractConfig(),
        java=JavaConfig(**java_data) if java_data else JavaConfig(),
        phase2=Phase2Config(
            llm=LlmConfig(**llm_data) if llm_data else LlmConfig(),
            token_budget=TokenBudgetConfig(**budget_data) if budget_data else TokenBudgetConfig(),
        ),
    )


def load_config(
    exe_dir: Optional[Path] = None,
) -> Tuple[ComprehensityConfig, Optional[str], Optional[str]]:
    """Load and return (config, config_path, config_raw).

    config_path is None when built-in defaults are used.
    config_raw  is None when built-in defaults are used.

    exe_dir defaults to the directory containing the running script (sys.argv[0]).
    Pass exe_dir=False to skip the exe-dir search step (useful in tests).
    """
    if exe_dir is None and sys.argv:
        exe_dir = Path(sys.argv[0]).resolve().parent

    for candidate in _candidate_paths(exe_dir):
        if candidate.is_file():
            try:
                raw = candidate.read_text(encoding="utf-8")
                data = _parse_toml(candidate)
                cfg = _build_config(data)
                # Env var override
                env_key = os.environ.get("COMPREHENSITY_LLM_API_KEY", "").strip()
                if env_key:
                    cfg.phase2.llm.api_key = env_key
                return cfg, str(candidate), raw
            except Exception:
                # Malformed config → fall through to next candidate
                pass

    # Built-in defaults
    cfg = ComprehensityConfig()
    env_key = os.environ.get("COMPREHENSITY_LLM_API_KEY", "").strip()
    if env_key:
        cfg.phase2.llm.api_key = env_key
    return cfg, None, None
