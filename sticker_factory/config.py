"""Config loading -- YAML config file and .env secrets into a unified config object."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from dotenv import load_dotenv

# Project root is one level up from this file's directory
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "config.yaml"
_ENV_PATH = _PROJECT_ROOT / ".env"

_config_cache: Optional[dict] = None


def _load_yaml(path: Path = _CONFIG_PATH) -> dict:
    """Load and return the YAML config file as a dict."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _load_env_secrets(env_path: Path = _ENV_PATH) -> dict:
    """Load .env file (if it exists) and return relevant secrets as a dict.

    Missing .env or missing keys are fine -- secrets are optional until needed.
    """
    load_dotenv(env_path)  # no-op if file doesn't exist
    return {
        "anthropic_api_key": os.getenv("ANTHROPIC_API_KEY"),
        "printify_api_key": os.getenv("PRINTIFY_API_KEY"),
    }


def get_config(*, reload: bool = False) -> dict:
    """Return the merged config: YAML settings + env secrets.

    Results are cached after the first call. Pass ``reload=True`` to force
    re-reading from disk.
    """
    global _config_cache
    if _config_cache is not None and not reload:
        return _config_cache

    cfg = _load_yaml()
    cfg["secrets"] = _load_env_secrets()
    _config_cache = cfg
    return _config_cache
