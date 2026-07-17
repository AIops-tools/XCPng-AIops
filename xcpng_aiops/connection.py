"""Connection management for the Xen Orchestra REST API (``/rest/v0``).

Thin httpx wrapper with per-target session reuse and static token auth:

  * Xen Orchestra issues long-lived **personal authentication tokens**
    (XO UI → user menu → Personal tokens, or ``xo-cli --createToken``).
    Every request carries the token in headers — both
    ``Authorization: Bearer <token>`` (newer XO releases) and
    ``Cookie: authenticationToken=<token>`` (accepted by all XO 5.x) are sent
    so one client works across XO versions. There is no token-exchange
    handshake.
  * ``base_url`` already includes the API base path (``/rest/v0``), so callers
    pass resource paths like ``/vms`` or ``/pools``.

XO is the management plane: this connection always talks to an XO instance,
never directly to an XCP-ng host's XAPI (out of scope for v0.1).

All non-2xx responses are translated centrally into ``XoApiError`` with a
teaching message — REST-wrapper skills translate HTTP errors at the connection
layer from the first version rather than leaking raw tracebacks.

The httpx client is injectable for tests: pass ``client=`` to
``XoConnection`` to substitute a mock that implements ``request`` / ``close``.
"""

from __future__ import annotations

import atexit
import weakref
from typing import Any
from urllib.parse import quote

import httpx

from xcpng_aiops.config import AppConfig, TargetConfig, load_config

_TIMEOUT = 30.0


def _seg(value: Any) -> str:
    """URL-encode one path segment (agent-supplied id) for safe interpolation.

    XO object ids are UUIDs, but they are agent-supplied strings — percent-
    encoding prevents an id containing ``../`` or ``?`` from rewriting the
    request path.
    """
    return quote(str(value), safe="")


class XoApiError(Exception):
    """A Xen Orchestra REST API call failed; carries a teaching message + status code."""

    def __init__(self, message: str, *, status_code: int | None = None, path: str = "") -> None:
        self.status_code = status_code
        self.path = path
        super().__init__(message)


def _teaching_message(status: int, path: str, body: str) -> str:
    """Map a non-2xx status to an actionable, teaching error message."""
    snippet = body[:200].strip()
    if status in (401, 403):
        return (
            f"Authentication/authorization failed ({status}) on {path}. "
            f"Check the XO authentication token (XO UI → user menu → Personal "
            f"tokens) and that the account has permission for this resource. "
            f"{snippet}"
        )
    if status == 404:
        return (
            f"Resource not found (404) on {path}. The id may be stale — list the "
            f"parent collection first to get a current id. {snippet}"
        )
    if status == 422:
        return (
            f"Validation error (422) on {path}. Xen Orchestra rejected the "
            f"request body — check required fields and value formats. {snippet}"
        )
    if status in (500, 502, 503, 504):
        return (
            f"Xen Orchestra server error ({status}) on {path}. The XO instance "
            f"may be busy or restarting; retry shortly. {snippet}"
        )
    return f"Xen Orchestra API error ({status}) on {path}. {snippet}"


class XoConnection:
    """A single authenticated session against one Xen Orchestra REST API target."""

    def __init__(self, target: TargetConfig, client: Any | None = None) -> None:
        self._target = target
        if client is not None:
            self._client = client
        else:
            token = target.token
            self._client = httpx.Client(
                base_url=target.base_url,
                verify=target.verify_ssl,
                timeout=_TIMEOUT,
                headers={
                    # Bearer works on newer XO; the cookie works on all XO 5.x.
                    "Authorization": f"Bearer {token}",
                    "Cookie": f"authenticationToken={token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )

    @property
    def target(self) -> TargetConfig:
        return self._target

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Issue a request and return parsed JSON, translating errors centrally."""
        try:
            resp = self._client.request(method, path, **kwargs)
        except httpx.HTTPError as exc:
            raise XoApiError(
                f"Could not reach Xen Orchestra at {self._target.base_url} "
                f"({method} {path}): {exc}. Check the XO URL and that the XO "
                f"REST API is reachable.",
                path=path,
            ) from exc
        if not (200 <= resp.status_code < 300):
            raise XoApiError(
                _teaching_message(resp.status_code, path, resp.text),
                status_code=resp.status_code,
                path=path,
            )
        if not resp.content:
            return {}
        try:
            return resp.json()
        except ValueError:
            # Some XO action endpoints return a bare string (e.g. a task href
            # or a new object id) that is not valid JSON.
            return resp.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self._client.close()


class ConnectionManager:
    """Manages connections to multiple Xen Orchestra targets with session reuse."""

    def __init__(self, config: AppConfig) -> None:
        self._config = config
        self._connections: dict[str, XoConnection] = {}
        _MANAGERS.add(self)

    @classmethod
    def from_config(cls, config: AppConfig | None = None) -> ConnectionManager:
        cfg = config or load_config()
        return cls(cfg)

    def connect(self, target_name: str | None = None) -> XoConnection:
        """Connect to a target by name, or the default target."""
        target = (
            self._config.get_target(target_name)
            if target_name
            else self._config.default_target
        )
        cached = self._connections.get(target.name)
        if cached is not None:
            return cached
        conn = XoConnection(target)
        self._connections[target.name] = conn
        return conn

    def disconnect(self, target_name: str) -> None:
        conn = self._connections.pop(target_name, None)
        if conn is not None:
            conn.close()

    def disconnect_all(self) -> None:
        for name in list(self._connections):
            self.disconnect(name)

    def list_targets(self) -> list[str]:
        return [t.name for t in self._config.targets]

    def list_connected(self) -> list[str]:
        return list(self._connections.keys())


# Managers hold cached httpx clients; close them all at interpreter exit so
# sockets are released deterministically (a WeakSet so short-lived CLI managers
# can still be garbage-collected normally).
_MANAGERS: weakref.WeakSet[ConnectionManager] = weakref.WeakSet()


def _close_all_managers() -> None:
    for mgr in list(_MANAGERS):
        try:
            mgr.disconnect_all()
        except Exception:  # noqa: BLE001 — exit-time cleanup must never raise
            pass


atexit.register(_close_all_managers)
