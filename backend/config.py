"""
ARAM Oracle — Configuration loader.

Reads from ~/.aram-oracle/config.toml at startup.
All values have hardcoded defaults — the config file is optional.
"""

import logging
import tomllib
from pathlib import Path

logger = logging.getLogger("aram-oracle.config")

CONFIG_PATH = Path.home() / ".aram-oracle" / "config.toml"

# Expected types for each config key (used for validation on load)
_TYPE_SPECS: dict[str, type | tuple[type, ...]] = {
    "match_threshold": (int, float),
    "hash_change_threshold": (int, float),
    "confidence_threshold": (int, float),
    "confidence_gap": (int, float),
    "zero_delta_threshold": (int, float),
    "overlay_width": int,
    "poll_interval": (int, float),
    "port": int,
    "github_token": str,
    "github_repo": str,
    "ocr_region": list,
}

DEFAULTS: dict = {
    # OCR thresholds
    "match_threshold": 65,
    "hash_change_threshold": 30,

    # Augment detector thresholds
    "confidence_threshold": 0.3,
    "confidence_gap": 0.05,
    "zero_delta_threshold": 2.0,

    # OCR region override (null = auto-detect by aspect ratio)
    "ocr_region": None,

    # Overlay dimensions
    "overlay_width": 320,

    # Poll interval (seconds)
    "poll_interval": 2.0,

    # Server port
    "port": 8765,

    # GitHub bug report integration
    "github_token": "",   # personal access token (repo scope)
    "github_repo": "",    # "owner/repo" format
}


class Config:
    """Configuration store. Loads TOML, falls back to DEFAULTS."""

    def __init__(self) -> None:
        self._data: dict = dict(DEFAULTS)

    def load(self, path: Path | None = None) -> None:
        """Load config from TOML file. Missing keys use defaults."""
        config_path = path or CONFIG_PATH
        if not config_path.exists():
            logger.info("No config file at %s — using defaults", config_path)
            return

        try:
            with open(config_path, "rb") as f:
                user_config = tomllib.load(f)

            # Flatten nested TOML sections into top-level keys
            flat: dict = {}
            for key, value in user_config.items():
                if key == "role_weights":
                    # Special handling: nested role weight overrides
                    self._data["role_weights"] = value
                    logger.info("Config override: role_weights (%d roles)", len(value))
                elif isinstance(value, dict):
                    for subkey, subval in value.items():
                        flat[subkey] = subval
                else:
                    flat[key] = value

            _SENSITIVE_KEYS = {"github_token"}
            for key, value in flat.items():
                if key not in DEFAULTS:
                    logger.warning("Unknown config key: %s", key)
                    continue
                expected = _TYPE_SPECS.get(key)
                if expected and not isinstance(value, expected):
                    logger.warning(
                        "Config key %s: expected %s, got %s — using default",
                        key, expected, type(value).__name__,
                    )
                    continue
                self._data[key] = value
                display = "***" if key in _SENSITIVE_KEYS else value
                logger.info("Config override: %s = %s", key, display)

        except (OSError, tomllib.TOMLDecodeError) as e:
            logger.error("Failed to load config from %s: %s", config_path, e)

    def get(self, key: str, default=None):
        return self._data.get(key, default)

    def __getitem__(self, key: str):
        return self._data[key]


# Module-level singleton
config = Config()
