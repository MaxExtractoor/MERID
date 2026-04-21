"""
MERID Explicit Configuration Loader

Implements a deterministic, ordered config precedence chain with full
source metadata tracking for observability and debugging.

Precedence Order (later wins):
1. Hard-coded defaults in code
2. Base config files (config/base.yaml)
3. Environment-specific files (config/dev.yaml, config/live.yaml)
4. Secrets/.env or environment variables
5. CLI flags / runtime overrides
6. Feature flags / remote config (if any)

Usage:
    from core.config_loader import get_config, ConfigKey

    # Get value with full provenance
    val, meta = get_config("portfolio.max_risk_usd", with_meta=True)

    # Check source
    if meta.source_layer == "env_var":
        logger.warning("Risk value from env var, not config file!")
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

import yaml

from utils.logger import get_logger

logger = get_logger("core.config_loader")


class ConfigLayer(Enum):
    """Ordered configuration layers - later values override earlier ones."""

    DEFAULT = auto()  # Hard-coded Python defaults
    BASE_FILE = auto()  # config/base.yaml
    ENV_FILE = auto()  # config/dev.yaml, config/live.yaml
    DOT_ENV = auto()  # .env file (pydantic/envvars)
    ENV_VAR = auto()  # Actual environment variables
    CLI_FLAG = auto()  # Command-line --set flags
    FEATURE_FLAG = auto()  # Remote/dynamic feature flags
    RUNTIME_OVERRIDE = auto()  # In-memory runtime.set() calls

    @property
    def priority(self) -> int:
        """Higher number = wins in conflicts."""
        return list(ConfigLayer).index(self)


@dataclass(frozen=True)
class ConfigSource:
    """Immutable record of where a config value came from."""

    layer: ConfigLayer
    source_name: str  # e.g., "config/live.yaml", "MERID_MAX_RISK"
    line: Optional[int] = None  # Line number in file, if applicable
    raw_value: Any = None  # Original value before type coercion

    def to_dict(self) -> Dict[str, Any]:
        return {
            "layer": self.layer.name,
            "source_name": self.source_name,
            "line": self.line,
            "raw_value": str(self.raw_value) if self.raw_value is not None else None,
        }


@dataclass
class ConfigValue:
    """A config value with its full provenance chain."""

    key: str
    value: Any
    effective_source: ConfigSource
    all_sources: List[ConfigSource] = field(default_factory=list)

    def explain(self) -> str:
        """Human-readable explanation of this config value's lineage."""
        lines = [f"Config key: {self.key}", f"Effective value: {self.value}", ""]

        for i, src in enumerate(self.all_sources):
            marker = " → EFFECTIVE" if i == len(self.all_sources) - 1 else ""
            line_info = f":{src.line}" if src.line else ""
            lines.append(
                f"  [{i+1}] {src.layer.name} ({src.source_name}{line_info}) = {src.raw_value}{marker}"
            )

        return "\n".join(lines)


class ConfigRegistry:
    """Thread-safe registry tracking all config values and their sources."""

    def __init__(self):
        self._lock = threading.RLock()
        self._values: Dict[str, ConfigValue] = {}
        self._fingerprints: Dict[str, str] = {}
        self._loaded_layers: set = set()

    def register(
        self,
        key: str,
        value: Any,
        source: ConfigSource,
        merge: bool = True,
    ) -> ConfigValue:
        """Register a config value from a specific source.

        If merge=True and key exists, append to provenance chain.
        If merge=False, replace entirely.
        """
        with self._lock:
            if key in self._values and merge:
                existing = self._values[key]
                # Only update if new layer has higher priority
                if source.layer.priority >= existing.effective_source.layer.priority:
                    new_sources = existing.all_sources + [source]
                    cv = ConfigValue(
                        key=key,
                        value=value,
                        effective_source=source,
                        all_sources=new_sources,
                    )
                    self._values[key] = cv
                    return cv
                else:
                    # Lower priority - just append to history but don't change effective
                    existing.all_sources.append(source)
                    return existing
            else:
                cv = ConfigValue(
                    key=key,
                    value=value,
                    effective_source=source,
                    all_sources=[source],
                )
                self._values[key] = cv
                return cv

    def get(self, key: str, default: Any = None) -> Any:
        """Get config value (effective only)."""
        with self._lock:
            if key in self._values:
                return self._values[key].value
            return default

    def get_with_meta(self, key: str) -> Optional[ConfigValue]:
        """Get full ConfigValue with provenance."""
        with self._lock:
            return self._values.get(key)

    def get_all_keys(self) -> List[str]:
        """Return all registered config keys."""
        with self._lock:
            return sorted(self._values.keys())

    def compute_fingerprint(self, subsystem: Optional[str] = None) -> str:
        """Compute stable hash of current config state.

        Args:
            subsystem: If provided, only hash keys matching this prefix.

        Returns:
            Short SHA256 hex digest of relevant config.
        """
        with self._lock:
            keys = self._values.keys()
            if subsystem:
                keys = [k for k in keys if k.startswith(subsystem)]

            # Build deterministic canonical representation
            data = {}
            for k in sorted(keys):
                cv = self._values[k]
                data[k] = {
                    "v": cv.value,
                    "s": cv.effective_source.layer.name,
                }

            canonical = json.dumps(data, sort_keys=True, separators=(",", ":"))
            digest = hashlib.sha256(canonical.encode()).hexdigest()[:16]

            if subsystem:
                self._fingerprints[subsystem] = digest

            return digest

    def dump(self, subsystem: Optional[str] = None) -> Dict[str, Any]:
        """Dump all config values with their sources."""
        with self._lock:
            keys = self._values.keys()
            if subsystem:
                keys = [k for k in keys if k.startswith(subsystem)]

            return {
                k: {
                    "value": self._values[k].value,
                    "source": self._values[k].effective_source.to_dict(),
                    "provenance": [s.to_dict() for s in self._values[k].all_sources],
                }
                for k in sorted(keys)
            }

    def explain(self, key: str) -> Optional[str]:
        """Get human-readable explanation for a specific key."""
        cv = self.get_with_meta(key)
        if cv:
            return cv.explain()
        return None


# Global singleton registry
_registry: Optional[ConfigRegistry] = None
_registry_lock = threading.Lock()


def get_registry() -> ConfigRegistry:
    """Get or create the global config registry."""
    global _registry
    if _registry is None:
        with _registry_lock:
            if _registry is None:
                _registry = ConfigRegistry()
    return _registry


class ExplicitConfigLoader:
    """Explicit precedence config loader with source tracking.

    Loads configs in strict precedence order, tracking the source
    of every value for observability and debugging.
    """

    # Known config file patterns
    BASE_CONFIG_PATHS = [
        "config/base.yaml",
        "config/settings.yaml",
    ]

    ENV_CONFIG_PATTERNS = [
        "config/{env}.yaml",
        "config/profiles/{env}.yaml",
    ]

    # Danger keys that affect trading risk
    DANGER_KEYS = {
        "portfolio.max_risk_usd",
        "portfolio.max_position_usd",
        "portfolio.global_risk_budget",
        "kalshi.spot_strike_warn_pct",
        "kalshi.spot_strike_max_pct",
        "risk.max_daily_loss_usd",
        "risk.max_order_size_usd",
        "feature_flags.live_trading",
        "feature_flags.auto_execute",
    }

    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path(__file__).resolve().parents[1]
        self.registry = get_registry()
        self._dot_env_loaded = False

    def _find_config_file(self, pattern: str) -> Optional[Path]:
        """Find a config file by pattern relative to project root."""
        path = self.project_root / pattern
        if path.exists():
            return path
        return None

    def _load_yaml(self, path: Path, layer: ConfigLayer) -> Dict[str, Any]:
        """Load YAML file and flatten to dot-notation keys with source tracking."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
                raw = yaml.safe_load(content) or {}

            # Track line numbers for each key (approximate)
            lines = content.split("\n")
            line_map = self._build_line_map(lines)

            flattened = {}
            self._flatten_dict(raw, "", flattened, layer, str(path), line_map)
            return flattened

        except Exception as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            return {}

    def _build_line_map(self, lines: List[str]) -> Dict[str, int]:
        """Build approximate line number mapping for keys."""
        line_map = {}
        current_path = []

        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue

            # Count indentation to determine depth
            indent = len(line) - len(line.lstrip())
            depth = indent // 2  # Assume 2-space indentation

            # Adjust current path based on depth
            current_path = current_path[:depth]

            # Extract key
            if ":" in stripped:
                key = stripped.split(":")[0].strip()
                current_path.append(key)
                full_key = ".".join(current_path)
                line_map[full_key] = i

        return line_map

    def _flatten_dict(
        self,
        d: Dict[str, Any],
        prefix: str,
        result: Dict[str, Any],
        layer: ConfigLayer,
        source_name: str,
        line_map: Dict[str, int],
    ) -> None:
        """Flatten nested dict to dot-notation keys."""
        for key, value in d.items():
            full_key = f"{prefix}.{key}" if prefix else key
            line = line_map.get(full_key)

            if isinstance(value, dict) and not self._is_special_dict(value):
                self._flatten_dict(value, full_key, result, layer, source_name, line_map)
            else:
                result[full_key] = (value, layer, source_name, line)

    def _is_special_dict(self, d: Dict) -> bool:
        """Check if dict is a special structure (likeStrikeSelectionConfig)."""
        # These should not be flattened further
        special_keys = {"max_spot_to_strike_pct", "target_spot_band_pct", "deep_otm_allowed"}
        return bool(set(d.keys()) & special_keys)

    def load_defaults(self, defaults: Dict[str, Any]) -> None:
        """Load hard-coded Python defaults."""
        for key, value in defaults.items():
            source = ConfigSource(
                layer=ConfigLayer.DEFAULT,
                source_name="python_defaults",
                line=None,
                raw_value=value,
            )
            self.registry.register(key, value, source, merge=False)

    def load_base_configs(self) -> None:
        """Load base config files (lowest priority files)."""
        for pattern in self.BASE_CONFIG_PATHS:
            path = self._find_config_file(pattern)
            if path:
                flattened = self._load_yaml(path, ConfigLayer.BASE_FILE)
                for key, (value, layer, source_name, line) in flattened.items():
                    source = ConfigSource(
                        layer=layer,
                        source_name=source_name,
                        line=line,
                        raw_value=value,
                    )
                    self.registry.register(key, value, source)
                logger.info(f"Loaded base config: {path}")

    def load_env_config(self, env: Optional[str] = None) -> None:
        """Load environment-specific config file."""
        env = env or os.getenv("MERID_ENV", "development")

        for pattern in self.ENV_CONFIG_PATTERNS:
            formatted = pattern.format(env=env.lower())
            path = self._find_config_file(formatted)
            if path:
                flattened = self._load_yaml(path, ConfigLayer.ENV_FILE)
                for key, (value, layer, source_name, line) in flattened.items():
                    source = ConfigSource(
                        layer=layer,
                        source_name=source_name,
                        line=line,
                        raw_value=value,
                    )
                    self.registry.register(key, value, source)
                logger.info(f"Loaded env config: {path}")
                return

        logger.debug(f"No env-specific config found for {env}")

    def load_dot_env(self, env_file: Optional[Path] = None) -> None:
        """Load .env file and track sources."""
        if self._dot_env_loaded:
            return

        env_file = env_file or (self.project_root / ".env")
        if not env_file.exists():
            return

        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for i, line in enumerate(f, 1):
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    if "=" in line:
                        key, _, value = line.partition("=")
                        key = key.strip()
                        value = value.strip().strip('"\'')

                        # Convert MERID_PORTFOLIO__MAX_RISK_USD to portfolio.max_risk_usd
                        # __ (double underscore) becomes . (dot) for nesting
                        # _ (single underscore) stays as _ in key names
                        config_key = key.lower()
                        if config_key.startswith("merid_"):
                            config_key = config_key[6:]  # Strip 'merid_' prefix
                        config_key = config_key.replace("__", ".")  # Double underscore becomes dot

                        source = ConfigSource(
                            layer=ConfigLayer.DOT_ENV,
                            source_name=str(env_file),
                            line=i,
                            raw_value=value,
                        )

                        # Try to coerce value
                        coerced = self._coerce_value(value)
                        self.registry.register(config_key, coerced, source)

            self._dot_env_loaded = True
            logger.info(f"Loaded .env: {env_file}")

        except Exception as e:
            logger.warning(f"Failed to load .env: {e}")

    def load_env_vars(self) -> None:
        """Load actual environment variables (higher priority than .env)."""
        for key, value in os.environ.items():
            if key.startswith("MERID_"):
                # Convert MERID_PORTFOLIO__MAX_RISK_USD to portfolio.max_risk_usd
                # __ (double underscore) becomes . (dot) for nesting
                # _ (single underscore) stays as _ in key names
                config_key = key[6:].lower()
                config_key = config_key.replace("__", ".")  # Double underscore becomes dot

                source = ConfigSource(
                    layer=ConfigLayer.ENV_VAR,
                    source_name=key,  # The actual env var name
                    line=None,
                    raw_value=value,
                )

                coerced = self._coerce_value(value)
                self.registry.register(config_key, coerced, source)

    def _coerce_value(self, value: str) -> Union[str, int, float, bool, None]:
        """Coerce string value to appropriate type."""
        if value.lower() in ("true", "yes", "1"):
            return True
        if value.lower() in ("false", "no", "0"):
            return False
        if value.lower() in ("null", "none", ""):
            return None

        try:
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

        return value

    def load_all(
        self,
        defaults: Optional[Dict[str, Any]] = None,
        env: Optional[str] = None,
    ) -> ConfigRegistry:
        """Load all config layers in precedence order."""
        # 1. Hard-coded defaults
        if defaults:
            self.load_defaults(defaults)

        # 2. Base config files
        self.load_base_configs()

        # 3. Environment-specific files
        self.load_env_config(env)

        # 4. .env file
        self.load_dot_env()

        # 5. Environment variables
        self.load_env_vars()

        # Log danger keys with their sources
        self._log_danger_keys()

        return self.registry

    def _log_danger_keys(self) -> None:
        """Log critical config values with their sources for safety."""
        for key in self.DANGER_KEYS:
            cv = self.registry.get_with_meta(key)
            if cv:
                logger.info(
                    f"[CONFIG-DANGER] {key} = {cv.value} "
                    f"(from {cv.effective_source.source_name}, "
                    f"layer={cv.effective_source.layer.name})"
                )


def get_config(key: str, default: Any = None, with_meta: bool = False) -> Any:
    """Get config value by key.

    Args:
        key: Dot-notation config key (e.g., "portfolio.max_risk_usd")
        default: Default value if key not found
        with_meta: If True, returns (value, ConfigValue) tuple

    Returns:
        Config value, or (value, ConfigValue) if with_meta=True
    """
    registry = get_registry()
    cv = registry.get_with_meta(key)

    if cv is None:
        if with_meta:
            return default, None
        return default

    if with_meta:
        return cv.value, cv
    return cv.value


def explain_config(key: str) -> Optional[str]:
    """Get human-readable explanation of a config key's lineage."""
    return get_registry().explain(key)


def get_config_fingerprint(subsystem: Optional[str] = None) -> str:
    """Get stable hash of current config state."""
    return get_registry().compute_fingerprint(subsystem)


def dump_config(subsystem: Optional[str] = None) -> Dict[str, Any]:
    """Dump all config values with full provenance."""
    return get_registry().dump(subsystem)


def init_config_loader(
    defaults: Optional[Dict[str, Any]] = None,
    env: Optional[str] = None,
) -> ConfigRegistry:
    """Initialize and load all config layers.

    Call this once at application startup.
    """
    loader = ExplicitConfigLoader()
    return loader.load_all(defaults=defaults, env=env)
