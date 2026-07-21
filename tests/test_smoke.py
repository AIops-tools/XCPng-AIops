"""Smoke + ops tests for xcpng-aiops.

Proves: every module imports, the CLI Typer app builds and --help works, the
MCP server exposes the expected tools, EVERY MCP tool carries the harness
marker ``_is_governed_tool``, read ops shape correctly against a mocked REST
client, and the connection layer sends the XO token correctly.
No real Xen Orchestra is needed — the connection is a MagicMock.
"""

import asyncio
import importlib
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

EXPECTED_TOOLS = {
    # overview
    "overview",
    # vms
    "vm_list", "vm_get", "vm_stats", "vm_health_rca",
    # vm actions (writes)
    "vm_start", "vm_stop", "vm_reboot", "vm_migrate",
    # hosts
    "host_list", "host_get",
    # pools
    "pool_list", "pool_get", "pool_patch_ha_posture",
    # srs
    "sr_list", "sr_get", "vdi_list", "sr_usage_rca", "sr_rescan",
    # snapshots
    "snapshot_list", "snapshot_create", "snapshot_delete", "snapshot_revert",
    # backups
    "backup_job_list", "backup_log_list", "backup_failure_rca",
    # tasks
    "task_list",
}


@pytest.mark.unit
def test_all_modules_import():
    for name in (
        "xcpng_aiops",
        "xcpng_aiops.config",
        "xcpng_aiops.connection",
        "xcpng_aiops.doctor",
        "xcpng_aiops.secretstore",
        "xcpng_aiops.ops.vms",
        "xcpng_aiops.ops.vm_rca",
        "xcpng_aiops.ops.vm_actions",
        "xcpng_aiops.ops.hosts",
        "xcpng_aiops.ops.pools",
        "xcpng_aiops.ops.srs",
        "xcpng_aiops.ops.snapshots",
        "xcpng_aiops.ops.backups",
        "xcpng_aiops.ops.tasks",
        "xcpng_aiops.ops.overview",
        "xcpng_aiops.cli",
        "xcpng_aiops.cli._root",
        "xcpng_aiops.cli._common",
        "xcpng_aiops.cli.init",
        "xcpng_aiops.cli.secret",
        "xcpng_aiops.cli.vm",
        "xcpng_aiops.cli.host",
        "xcpng_aiops.cli.pool",
        "xcpng_aiops.cli.sr",
        "xcpng_aiops.cli.snapshot",
        "xcpng_aiops.cli.backup",
        "xcpng_aiops.cli.task",
        "xcpng_aiops.cli.overview",
        "xcpng_aiops.cli.doctor",
        "mcp_server.server",
        "mcp_server._shared",
        "mcp_server.tools.overview",
        "mcp_server.tools.vms",
        "mcp_server.tools.vm_actions",
        "mcp_server.tools.hosts",
        "mcp_server.tools.pools",
        "mcp_server.tools.srs",
        "mcp_server.tools.snapshots",
        "mcp_server.tools.backups",
        "mcp_server.tools.tasks",
    ):
        importlib.import_module(name)


@pytest.mark.unit
def test_version_matches_pyproject():
    """__version__ is single-sourced from package metadata; it must track
    pyproject.toml so a release bump can never ship a stale self-report."""
    import tomllib
    from pathlib import Path

    import xcpng_aiops

    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    expected = tomllib.loads(pyproject.read_text("utf-8"))["project"]["version"]
    assert xcpng_aiops.__version__ == expected


@pytest.mark.unit
def test_cli_app_builds_and_help_works():
    from xcpng_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for sub in (
        "vm", "host", "pool", "sr", "snapshot", "backup", "task",
        "secret", "init", "overview", "doctor", "mcp",
    ):
        assert sub in result.output


@pytest.mark.unit
def test_cli_leaf_help_triggers_lazy_imports():
    """Recurse into leaf commands so any broken lazy import surfaces."""
    from xcpng_aiops.cli import app

    runner = CliRunner()
    for cmd in (
        ["vm", "--help"], ["host", "--help"], ["pool", "--help"],
        ["sr", "--help"], ["snapshot", "--help"], ["backup", "--help"],
        ["task", "--help"], ["secret", "--help"], ["doctor", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"
    for cmd in (
        ["vm", "list", "--help"], ["vm", "get", "--help"],
        ["vm", "stats", "--help"], ["vm", "health-rca", "--help"],
        ["vm", "start", "--help"], ["vm", "stop", "--help"],
        ["vm", "reboot", "--help"], ["vm", "migrate", "--help"],
        ["host", "list", "--help"], ["host", "get", "--help"],
        ["host", "missing-patches", "--help"],
        ["pool", "list", "--help"], ["pool", "get", "--help"],
        ["pool", "posture", "--help"],
        ["sr", "list", "--help"], ["sr", "get", "--help"],
        ["sr", "vdis", "--help"], ["sr", "usage-rca", "--help"],
        ["sr", "rescan", "--help"],
        ["snapshot", "list", "--help"], ["snapshot", "create", "--help"],
        ["snapshot", "delete", "--help"], ["snapshot", "revert", "--help"],
        ["backup", "jobs", "--help"], ["backup", "logs", "--help"],
        ["backup", "failure-rca", "--help"],
        ["task", "list", "--help"],
        ["secret", "list", "--help"], ["secret", "set", "--help"],
        ["init", "--help"], ["overview", "--help"],
    ):
        result = runner.invoke(app, cmd)
        assert result.exit_code == 0, f"{cmd} failed: {result.output}"


@pytest.mark.unit
def test_mcp_list_tools_exposes_expected_tools():
    from mcp_server.server import mcp

    tools = asyncio.run(mcp.list_tools())
    names = {t.name for t in tools}
    assert EXPECTED_TOOLS <= names, f"missing: {EXPECTED_TOOLS - names}"


@pytest.mark.unit
def test_every_mcp_tool_is_governed_by_harness():
    """Every registered tool callable must carry the @governed_tool marker."""
    from mcp_server import _shared

    tool_objs = _shared.mcp._tool_manager._tools
    assert EXPECTED_TOOLS <= set(tool_objs), "tool registry incomplete"
    for name, tool in tool_objs.items():
        fn = getattr(tool, "fn", None)
        assert fn is not None, f"{name} has no fn"
        assert getattr(fn, "_is_governed_tool", False), (
            f"{name} is not wrapped with @governed_tool (harness marker missing)"
        )


@pytest.mark.unit
def test_risk_tiers_are_correct():
    """Irreversible snapshot delete/revert = high; every other write (including
    the metadata-only SR rescan) = medium — the descriptive risk tier each
    carries into its audit row."""
    from mcp_server.tools import snapshots as snap_tools
    from mcp_server.tools import srs as sr_tools
    from mcp_server.tools import vm_actions as vm_tools

    assert snap_tools.snapshot_delete._risk_level == "high"
    assert snap_tools.snapshot_revert._risk_level == "high"
    assert snap_tools.snapshot_create._risk_level == "medium"
    assert vm_tools.vm_start._risk_level == "medium"
    assert vm_tools.vm_stop._risk_level == "medium"
    assert vm_tools.vm_reboot._risk_level == "medium"
    assert vm_tools.vm_migrate._risk_level == "medium"
    assert sr_tools.sr_rescan._risk_level == "medium"


@pytest.mark.unit
def test_read_ops_shape_against_mock():
    """Read ops return high-signal shapes from a mocked REST client."""
    from xcpng_aiops.ops import srs as sr_ops
    from xcpng_aiops.ops import vms as vm_ops

    conn = MagicMock(name="conn")
    conn.get.return_value = [
        {"uuid": "vm-1", "name_label": "web01", "power_state": "Running",
         "$pool": "pool-1", "$container": "host-1",
         "CPUs": {"number": 4}, "memory": {"size": 8 * 2**30},
         "managementAgentDetected": True, "auto_poweron": True,
         "high_availability": "restart"},
    ]
    page = vm_ops.list_vms(conn)
    rows = page["vms"]
    assert page["returned"] == 1 and page["truncated"] is False
    assert rows[0]["name"] == "web01"
    assert rows[0]["powerState"] == "Running"
    assert rows[0]["guestToolsDetected"] is True
    conn.get.assert_called_with("/vms", params={"fields": vm_ops.VM_FIELDS})

    conn.get.return_value = [
        {"uuid": "sr-1", "name_label": "local-storage", "SR_type": "lvm",
         "content_type": "user", "shared": False, "$pool": "pool-1",
         "size": 1000, "physical_usage": 850, "usage": 1200},
    ]
    srs = sr_ops.list_srs(conn)["srs"]
    assert srs[0]["usedPercent"] == 85.0
    assert srs[0]["virtualAllocationBytes"] == 1200


@pytest.mark.unit
def test_overview_is_resilient_to_partial_failure():
    """One failing collection should not blank the whole overview."""
    from xcpng_aiops.ops import overview as ov

    conn = MagicMock(name="conn")

    def _get(path, **kw):
        if path == "/pools":
            raise RuntimeError("pool query boom")
        return []

    conn.get.side_effect = _get
    data = ov.health_overview(conn)
    assert "error" in data["pools"]
    assert data["vms"]["total"] == 0
    assert data["srs"]["total"] == 0


@pytest.mark.unit
def test_connection_token_headers_and_error_translation():
    """XoConnection sends the token both as Bearer and cookie, and translates
    non-2xx into XoApiError."""
    import httpx

    from xcpng_aiops.config import TargetConfig
    from xcpng_aiops.connection import XoApiError, XoConnection

    captured = {}

    def _handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["cookie"] = request.headers.get("cookie")
        if request.url.path.endswith("/notfound"):
            return httpx.Response(404, text="x")
        return httpx.Response(200, json=[{"uuid": "pool-1"}])

    target = TargetConfig(name="xo1", url="https://xo.example.com", verify_ssl=False)
    client = httpx.Client(
        base_url=target.base_url,
        transport=httpx.MockTransport(_handler),
        headers={
            "Authorization": "Bearer secret-token",
            "Cookie": "authenticationToken=secret-token",
        },
    )
    conn = XoConnection(target, client=client)
    assert conn.get("/pools")[0]["uuid"] == "pool-1"
    assert captured["auth"] == "Bearer secret-token"
    assert captured["cookie"] == "authenticationToken=secret-token"
    with pytest.raises(XoApiError) as ei:
        conn.get("/notfound")
    assert ei.value.status_code == 404
    assert "not found" in str(ei.value).lower()


@pytest.mark.unit
def test_real_connection_builds_token_headers(monkeypatch):
    """Constructing XoConnection without an injected client derives both auth
    headers from the target's token."""
    from xcpng_aiops.config import TargetConfig
    from xcpng_aiops.connection import XoConnection

    monkeypatch.setenv("XCPNG_XO1_TOKEN", "tok-abc")
    target = TargetConfig(name="xo1", url="https://xo.example.com", verify_ssl=False)
    conn = XoConnection(target)
    try:
        assert conn._client.headers["authorization"] == "Bearer tok-abc"
        assert conn._client.headers["cookie"] == "authenticationToken=tok-abc"
        # httpx normalizes base_url with a trailing slash.
        assert str(conn._client.base_url).rstrip("/") == "https://xo.example.com/rest/v0"
    finally:
        conn.close()


@pytest.mark.unit
def test_path_traversal_in_agent_supplied_id_is_encoded():
    """An id containing '../' must never reach the client as a raw path segment."""
    from xcpng_aiops.ops import snapshots as snap_ops
    from xcpng_aiops.ops import srs as sr_ops
    from xcpng_aiops.ops import vms as vm_ops

    conn = MagicMock(name="conn")
    conn.get.return_value = {}
    conn.post.return_value = {}
    conn.delete.return_value = True

    vm_ops.get_vm(conn, "../users/me")
    sr_ops.get_sr(conn, "../../tasks")
    snap_ops.delete_snapshot(conn, "../vms/x")

    for call in (
        list(conn.get.call_args_list)
        + list(conn.post.call_args_list)
        + list(conn.delete.call_args_list)
    ):
        path = call.args[0]
        assert "../" not in path, f"raw traversal survived into request path: {path}"
    assert conn.get.call_args_list[0].args[0] == "/vms/..%2Fusers%2Fme"


@pytest.mark.unit
def test_connection_manager_registers_for_atexit_cleanup():
    """Cached httpx clients are closed at interpreter exit via the atexit hook."""
    import xcpng_aiops.connection as conn_mod
    from xcpng_aiops.config import AppConfig

    mgr = conn_mod.ConnectionManager(AppConfig(targets=()))
    assert mgr in conn_mod._MANAGERS

    closed = {"n": 0}

    class _Conn:
        def close(self):
            closed["n"] += 1

    mgr._connections["xo1"] = _Conn()
    conn_mod._close_all_managers()
    assert closed["n"] == 1
    assert mgr.list_connected() == []


@pytest.mark.unit
def test_risk_level_agrees_with_read_write_docstring_tag():
    """The two write-markers must never drift apart.

    A tool's ``risk_level`` decides its audit tier and whether it gets dry-run /
    undo handling; its ``[READ]``/``[WRITE]`` docstring tag is what the docs and
    capability tables are built from. If a ``[WRITE]`` were left ``risk_level=low``
    it would be audited as a read and skip the write machinery — this test caught
    16 such mislabels line-wide once, so it is kept even though read-only mode
    (its original motivation) is gone.
    """
    from mcp_server import server

    untagged, mismatched = [], []
    for name, tool in server.mcp._tool_manager._tools.items():
        doc = (tool.fn.__doc__ or "").lstrip()
        if doc.startswith("[READ]"):
            tagged_as_read = True
        elif doc.startswith("[WRITE]"):
            tagged_as_read = False
        else:
            untagged.append(name)
            continue
        if tagged_as_read != (getattr(tool.fn, "_risk_level", "low") == "low"):
            mismatched.append(name)

    assert not untagged, f"tools missing a [READ]/[WRITE] docstring tag: {untagged}"
    assert not mismatched, f"risk_level disagrees with the docstring tag: {mismatched}"
