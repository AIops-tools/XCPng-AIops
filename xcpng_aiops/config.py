"""Configuration management for XCP-ng AIops.

Loads Xen Orchestra (XO) connection targets from a YAML config file. XO is the
management plane: this tool talks to an XO instance's REST API (``/rest/v0``),
which in turn manages one or more XCP-ng pools. **An XO instance (XO from
sources or Xen Orchestra Appliance, 5.x) is required** — per-host XAPI access
is out of scope for v0.1.

The secret (an XO *personal authentication token*) is NEVER stored in the
config file and never on disk in plaintext: it lives in the encrypted store
``~/.xcpng-aiops/secrets.enc`` (see :mod:`xcpng_aiops.secretstore`). For
backward compatibility a legacy plaintext env var (``XCPNG_<TARGET>_TOKEN``)
is still honoured as a fallback, with a warning nudging migration to the
encrypted store.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

import yaml

from xcpng_aiops.governance.paths import ops_home
from xcpng_aiops.secretstore import SecretStoreError, get_secret, has_store

CONFIG_DIR = ops_home()
CONFIG_FILE = CONFIG_DIR / "config.yaml"
ENV_FILE = CONFIG_DIR / ".env"

DEFAULT_API_PATH = "/rest/v0"

# Legacy env-var prefix/suffix; also used by the migration helper.
SECRET_ENV_PREFIX = "XCPNG_"  # nosec B105 — env-var name, not a secret
SECRET_ENV_SUFFIX = "_TOKEN"  # nosec B105 — env-var name, not a secret

_log = logging.getLogger("xcpng-aiops.config")


def _secret_env_key(name: str) -> str:
    """Legacy per-target token env var name, e.g. XCPNG_XO1_TOKEN."""
    return f"{SECRET_ENV_PREFIX}{name.upper().replace('-', '_')}{SECRET_ENV_SUFFIX}"


def _resolve_secret(name: str) -> str:
    """Return a target's XO token: encrypted store first, then legacy env var."""
    if has_store():
        try:
            return get_secret(name)
        except SecretStoreError:
            pass  # fall through to legacy env var
    legacy = os.environ.get(_secret_env_key(name))
    if legacy:
        _log.warning(
            "Using plaintext env var %s. Migrate to the encrypted store with "
            "'xcpng-aiops secret migrate'.",
            _secret_env_key(name),
        )
        return legacy
    raise OSError(
        f"No XO authentication token for target '{name}'. Add one with "
        f"'xcpng-aiops secret set {name}' (stored encrypted), or run "
        f"'xcpng-aiops init'."
    )


@dataclass(frozen=True)
class TargetConfig:
    """A Xen Orchestra REST API (``/rest/v0``) connection target.

    ``url`` is the XO web origin (e.g. ``https://xo.example.com``) — the same
    address the XO web UI is served from. The authentication token is sourced
    from the encrypted secret store (see ``token``), never the config file.
    Create the token in the XO UI (user menu → Personal tokens) or with
    ``xo-cli --createToken``.
    """

    name: str
    url: str
    verify_ssl: bool = True
    api_path: str = DEFAULT_API_PATH

    @property
    def token(self) -> str:
        return _resolve_secret(self.name)

    @property
    def base_url(self) -> str:
        return f"{self.url.rstrip('/')}{self.api_path}"


@dataclass(frozen=True)
class AppConfig:
    """Top-level application config."""

    targets: tuple[TargetConfig, ...] = ()

    def get_target(self, name: str) -> TargetConfig:
        for t in self.targets:
            if t.name == name:
                return t
        available = ", ".join(t.name for t in self.targets) or "(none)"
        raise KeyError(f"Target '{name}' not found. Available: {available}")

    @property
    def default_target(self) -> TargetConfig:
        if not self.targets:
            raise ValueError("No targets configured. Check config.yaml")
        return self.targets[0]


def load_config(config_path: Path | None = None) -> AppConfig:
    """Load config from YAML; the XO token comes from the encrypted store."""
    path = config_path or CONFIG_FILE
    if not path.exists():
        raise FileNotFoundError(
            f"Config file not found: {path}\n"
            f"Run 'xcpng-aiops init' to set up a Xen Orchestra target and store "
            f"its token encrypted, or create {CONFIG_FILE} with a 'targets' list."
        )

    with open(path) as f:
        raw = yaml.safe_load(f) or {}

    targets = tuple(
        TargetConfig(
            name=t["name"],
            url=t["url"],
            verify_ssl=t.get("verify_ssl", True),
            api_path=t.get("api_path", DEFAULT_API_PATH),
        )
        for t in raw.get("targets", [])
    )

    return AppConfig(targets=targets)
