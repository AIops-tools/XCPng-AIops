"""Connection error translation + config resolution against a mocked transport.

Never touches a real Xen Orchestra: all HTTP is served by httpx.MockTransport.
Pins the teaching-error mapping for each XO status class, the empty-body and
bare-string response handling, and the config target/secret resolution.
"""

from __future__ import annotations

import httpx
import pytest

from xcpng_aiops.config import (
    AppConfig,
    TargetConfig,
    _resolve_secret,
    load_config,
)
from xcpng_aiops.connection import (
    ConnectionManager,
    XoApiError,
    XoConnection,
    _seg,
)


def _conn(handler) -> XoConnection:
    target = TargetConfig(name="xo1", url="https://xo.example.com", verify_ssl=False)
    client = httpx.Client(
        base_url=target.base_url, transport=httpx.MockTransport(handler)
    )
    return XoConnection(target, client=client)


@pytest.mark.unit
@pytest.mark.parametrize(
    "status,needle",
    [
        (401, "Authentication/authorization failed"),
        (403, "Authentication/authorization failed"),
        (404, "Resource not found"),
        (422, "Validation error"),
        (500, "server error"),
        (503, "server error"),
        (418, "Xen Orchestra API error"),
    ],
)
def test_teaching_messages_per_status(status, needle):
    conn = _conn(lambda req: httpx.Response(status, text="detail-body"))
    with pytest.raises(XoApiError) as ei:
        conn.get("/vms")
    assert needle in str(ei.value)
    assert ei.value.status_code == status
    assert "detail-body" in str(ei.value)


@pytest.mark.unit
def test_transport_error_translated_to_teaching_message():
    def _handler(req):
        raise httpx.ConnectError("connection refused")

    conn = _conn(_handler)
    with pytest.raises(XoApiError) as ei:
        conn.get("/pools")
    assert "Could not reach Xen Orchestra" in str(ei.value)
    assert ei.value.status_code is None


@pytest.mark.unit
def test_empty_body_returns_empty_dict():
    conn = _conn(lambda req: httpx.Response(204))
    assert conn.post("/vms/x/actions/start") == {}


@pytest.mark.unit
def test_bare_string_response_returned_as_text():
    """Some XO action endpoints return a non-JSON bare string (a task href)."""
    conn = _conn(lambda req: httpx.Response(200, text="task/href-123"))
    assert conn.delete("/vm-snapshots/x") == "task/href-123"


@pytest.mark.unit
def test_post_and_delete_verbs_reach_transport():
    seen = {}

    def _handler(req):
        seen[req.method] = req.url.path
        return httpx.Response(200, json={"ok": True})

    conn = _conn(_handler)
    assert conn.post("/a")["ok"] is True
    assert conn.delete("/b")["ok"] is True
    assert seen["POST"].endswith("/a")
    assert seen["DELETE"].endswith("/b")


@pytest.mark.unit
def test_target_property_exposes_config():
    conn = _conn(lambda req: httpx.Response(200, json={}))
    assert conn.target.name == "xo1"


@pytest.mark.unit
def test_seg_encodes_traversal():
    assert _seg("../vms/x") == "..%2Fvms%2Fx"


# ─── ConnectionManager ──────────────────────────────────────────────────────


@pytest.mark.unit
def test_manager_connect_default_and_named_with_cache(monkeypatch):
    monkeypatch.setenv("XCPNG_XO1_TOKEN", "tok")
    monkeypatch.setenv("XCPNG_XO2_TOKEN", "tok2")
    cfg = AppConfig(
        targets=(
            TargetConfig(name="xo1", url="https://a.example", verify_ssl=False),
            TargetConfig(name="xo2", url="https://b.example", verify_ssl=False),
        )
    )
    mgr = ConnectionManager(cfg)
    try:
        default = mgr.connect()
        assert default.target.name == "xo1"
        # cache: same object on second call
        assert mgr.connect() is default
        named = mgr.connect("xo2")
        assert named.target.name == "xo2"
        assert set(mgr.list_connected()) == {"xo1", "xo2"}
        assert set(mgr.list_targets()) == {"xo1", "xo2"}
        mgr.disconnect("xo1")
        assert mgr.list_connected() == ["xo2"]
    finally:
        mgr.disconnect_all()
    assert mgr.list_connected() == []


@pytest.mark.unit
def test_manager_from_config(monkeypatch):
    monkeypatch.setattr(
        "xcpng_aiops.connection.load_config",
        lambda: AppConfig(targets=(TargetConfig(name="xo1", url="https://x"),)),
    )
    mgr = ConnectionManager.from_config()
    assert mgr.list_targets() == ["xo1"]


# ─── config.py ──────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_get_target_found_and_missing():
    cfg = AppConfig(targets=(TargetConfig(name="xo1", url="https://x"),))
    assert cfg.get_target("xo1").name == "xo1"
    with pytest.raises(KeyError, match="Available"):
        cfg.get_target("nope")


@pytest.mark.unit
def test_default_target_empty_raises_and_first_wins():
    with pytest.raises(ValueError, match="No targets"):
        AppConfig(targets=()).default_target
    cfg = AppConfig(
        targets=(
            TargetConfig(name="first", url="https://x"),
            TargetConfig(name="second", url="https://y"),
        )
    )
    assert cfg.default_target.name == "first"


@pytest.mark.unit
def test_base_url_composition():
    t = TargetConfig(name="xo1", url="https://xo.example.com/")
    assert t.base_url == "https://xo.example.com/rest/v0"


@pytest.mark.unit
def test_load_config_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="init"):
        load_config(tmp_path / "nope.yaml")


@pytest.mark.unit
def test_load_config_parses_targets(tmp_path):
    p = tmp_path / "config.yaml"
    p.write_text(
        "targets:\n"
        "  - name: xo1\n"
        "    url: https://xo.example.com\n"
        "    verify_ssl: false\n"
    )
    cfg = load_config(p)
    assert cfg.targets[0].name == "xo1"
    assert cfg.targets[0].verify_ssl is False


@pytest.mark.unit
def test_resolve_secret_prefers_encrypted_store(monkeypatch):
    monkeypatch.setattr("xcpng_aiops.config.has_store", lambda: True)
    monkeypatch.setattr("xcpng_aiops.config.get_secret", lambda name: "enc-tok")
    assert _resolve_secret("xo1") == "enc-tok"


@pytest.mark.unit
def test_resolve_secret_falls_back_to_legacy_env(monkeypatch):
    from xcpng_aiops.config import SecretStoreError

    monkeypatch.setattr("xcpng_aiops.config.has_store", lambda: True)

    def _raise(name):
        raise SecretStoreError("no secret")

    monkeypatch.setattr("xcpng_aiops.config.get_secret", _raise)
    monkeypatch.setenv("XCPNG_XO1_TOKEN", "legacy-tok")
    assert _resolve_secret("xo1") == "legacy-tok"


@pytest.mark.unit
def test_resolve_secret_missing_raises_teaching(monkeypatch):
    monkeypatch.setattr("xcpng_aiops.config.has_store", lambda: False)
    monkeypatch.delenv("XCPNG_NOPE_TOKEN", raising=False)
    with pytest.raises(OSError, match="secret set"):
        _resolve_secret("nope")
