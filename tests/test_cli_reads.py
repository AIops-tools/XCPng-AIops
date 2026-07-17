"""CLI read commands — body coverage past the get_connection boundary.

Every read sub-command builds a connection then delegates to an ops function
and prints JSON. These tests patch the module-local ``get_connection`` to a
mocked (conn, cfg) pair so the command body runs end to end without a live XO,
asserting the ops layer was reached and the JSON was rendered. Dry-run write
previews (which never touch the connection) are exercised here too.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

runner = CliRunner()


@pytest.fixture
def patch_conn(monkeypatch):
    """Patch get_connection in the named CLI module to a mocked (conn, cfg)."""

    def _patch(module_path: str, get_return):
        import importlib

        mod = importlib.import_module(module_path)
        conn = MagicMock(name="conn")
        conn.get.return_value = get_return
        monkeypatch.setattr(mod, "get_connection", lambda target=None: (conn, None))
        return conn

    return _patch


@pytest.mark.unit
def test_vm_list_get_stats_health_bodies(patch_conn):
    from xcpng_aiops.cli import app

    conn = patch_conn(
        "xcpng_aiops.cli.vm",
        [{"uuid": "vm-1", "name_label": "web", "power_state": "Running"}],
    )
    r = runner.invoke(app, ["vm", "list"])
    assert r.exit_code == 0, r.output
    assert "web" in r.output
    conn.get.assert_called_with("/vms", params={"fields": _vm_fields()})

    conn.get.return_value = {"uuid": "vm-1", "name_label": "web", "power_state": "Running"}
    assert runner.invoke(app, ["vm", "get", "vm-1"]).exit_code == 0

    conn.get.return_value = {"stats": {"cpus": {"0": [1.0, 2.0]}}, "interval": 5}
    r = runner.invoke(app, ["vm", "stats", "vm-1", "-g", "minutes"])
    assert r.exit_code == 0, r.output

    conn.get.return_value = []
    assert runner.invoke(app, ["vm", "health-rca"]).exit_code == 0


def _vm_fields():
    from xcpng_aiops.ops.vms import VM_FIELDS

    return VM_FIELDS


@pytest.mark.unit
def test_host_read_bodies(patch_conn):
    from xcpng_aiops.cli import app

    conn = patch_conn(
        "xcpng_aiops.cli.host",
        [{"uuid": "h1", "name_label": "node1", "$pool": "pool-1"}],
    )
    r = runner.invoke(app, ["host", "list", "--pool", "pool-1"])
    assert r.exit_code == 0, r.output
    assert "node1" in r.output

    conn.get.return_value = {"uuid": "h1", "name_label": "node1"}
    assert runner.invoke(app, ["host", "get", "h1"]).exit_code == 0

    conn.get.return_value = [{"name": "XS71E001", "description": "fix", "version": "1"}]
    r = runner.invoke(app, ["host", "missing-patches", "h1"])
    assert r.exit_code == 0, r.output


@pytest.mark.unit
def test_pool_read_bodies(patch_conn):
    from xcpng_aiops.cli import app

    conn = patch_conn(
        "xcpng_aiops.cli.pool",
        [{"uuid": "p1", "name_label": "prod", "HA_enabled": True}],
    )
    assert runner.invoke(app, ["pool", "list"]).exit_code == 0
    conn.get.return_value = {"uuid": "p1", "name_label": "prod"}
    assert runner.invoke(app, ["pool", "get", "p1"]).exit_code == 0
    conn.get.return_value = []
    assert runner.invoke(app, ["pool", "posture"]).exit_code == 0


@pytest.mark.unit
def test_sr_read_bodies(patch_conn):
    from xcpng_aiops.cli import app

    conn = patch_conn(
        "xcpng_aiops.cli.sr",
        [{"uuid": "sr-1", "name_label": "local", "size": 100, "physical_usage": 50}],
    )
    assert runner.invoke(app, ["sr", "list", "--pool", "p1"]).exit_code == 0
    conn.get.return_value = {"uuid": "sr-1", "name_label": "local"}
    assert runner.invoke(app, ["sr", "get", "sr-1"]).exit_code == 0
    conn.get.return_value = []
    assert runner.invoke(app, ["sr", "vdis", "--orphaned-only"]).exit_code == 0
    assert runner.invoke(app, ["sr", "usage-rca"]).exit_code == 0


@pytest.mark.unit
def test_backup_and_task_read_bodies(patch_conn):
    from xcpng_aiops.cli import app

    conn = patch_conn("xcpng_aiops.cli.backup", [])
    assert runner.invoke(app, ["backup", "jobs"]).exit_code == 0
    conn.get.return_value = []
    assert runner.invoke(app, ["backup", "logs", "-n", "5"]).exit_code == 0
    assert runner.invoke(app, ["backup", "failure-rca"]).exit_code == 0

    tconn = patch_conn(
        "xcpng_aiops.cli.task",
        [{"id": "t1", "status": "success", "properties": {"name": "x"}}],
    )
    r = runner.invoke(app, ["task", "list", "--status", "success"])
    assert r.exit_code == 0, r.output
    tconn.get.assert_called()


@pytest.mark.unit
def test_overview_and_snapshot_list_bodies(patch_conn):
    from xcpng_aiops.cli import app

    patch_conn("xcpng_aiops.cli.overview", [])
    r = runner.invoke(app, ["overview"])
    assert r.exit_code == 0, r.output
    assert "srNearFullThresholdPercent" in r.output

    patch_conn("xcpng_aiops.cli.snapshot", [])
    assert runner.invoke(app, ["snapshot", "list", "--vm", "vm-1"]).exit_code == 0


@pytest.mark.unit
def test_dry_run_previews_never_touch_connection(patch_conn):
    """Dry-run write previews print the API call and make no request."""
    from xcpng_aiops.cli import app

    vconn = patch_conn("xcpng_aiops.cli.vm", {})
    for cmd in (
        ["vm", "start", "vm-1", "--dry-run"],
        ["vm", "reboot", "vm-1", "--force", "--dry-run"],
        ["vm", "migrate", "vm-1", "host-2", "--dry-run"],
    ):
        r = runner.invoke(app, cmd)
        assert r.exit_code == 0, r.output
        assert "DRY-RUN" in r.output
    assert "host = host-2" in runner.invoke(
        app, ["vm", "migrate", "vm-1", "host-2", "--dry-run"]
    ).output

    sconn = patch_conn("xcpng_aiops.cli.snapshot", {})
    for cmd in (
        ["snapshot", "create", "vm-1", "nightly", "--dry-run"],
        ["snapshot", "revert", "snap-1", "--dry-run"],
    ):
        r = runner.invoke(app, cmd)
        assert r.exit_code == 0, r.output
        assert "DRY-RUN" in r.output

    srconn = patch_conn("xcpng_aiops.cli.sr", {})
    r = runner.invoke(app, ["sr", "rescan", "sr-1", "--dry-run"])
    assert r.exit_code == 0, r.output
    assert "DRY-RUN" in r.output

    # None of the previews issued any request.
    for c in (vconn, sconn, srconn):
        c.post.assert_not_called()
        c.delete.assert_not_called()


@pytest.mark.unit
def test_cli_errors_translates_api_error_to_one_line(monkeypatch):
    """A raised XoApiError becomes one red line + exit code 1, not a traceback."""
    import xcpng_aiops.cli.vm as vm_cli
    from xcpng_aiops.cli import app
    from xcpng_aiops.connection import XoApiError

    def _boom(target=None):
        raise XoApiError("resource not found (404)", status_code=404)

    monkeypatch.setattr(vm_cli, "get_connection", _boom)
    r = runner.invoke(app, ["vm", "list"])
    assert r.exit_code == 1
    assert "Error:" in r.output
    assert "not found" in r.output


@pytest.mark.unit
def test_cli_errors_translates_keyerror_with_hint(monkeypatch):
    """A KeyError surfaces the missing-key teaching prefix."""
    import xcpng_aiops.cli.pool as pool_cli
    from xcpng_aiops.cli import app

    def _boom(target=None):
        raise KeyError("XCPNG_XO1_TOKEN")

    monkeypatch.setattr(pool_cli, "get_connection", _boom)
    r = runner.invoke(app, ["pool", "list"])
    assert r.exit_code == 1
    assert "Missing required key" in r.output


@pytest.mark.unit
def test_get_connection_helper_builds_manager(monkeypatch):
    """_common.get_connection loads config and returns (conn, cfg)."""
    import xcpng_aiops.cli._common as common

    fake_conn = object()

    class _Mgr:
        def __init__(self, cfg):
            self.cfg = cfg

        def connect(self, target):
            return fake_conn

    monkeypatch.setattr("xcpng_aiops.config.load_config", lambda p=None: "CFG")
    monkeypatch.setattr("xcpng_aiops.connection.ConnectionManager", _Mgr)
    conn, cfg = common.get_connection("xo1")
    assert conn is fake_conn
    assert cfg == "CFG"
