"""CLI confirmed-write path — past dry-run, through governance, onto disk.

The CLI write commands delegate real execution to the ``@governed_tool``
functions in ``mcp_server.tools``. These tests drive a write command PAST the
dry-run branch and the double-confirm prompts and assert the call really went
through the governed path (audit row on disk) — the regression test for the
"CLI writes were unaudited" line-wide fix.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

import xcpng_aiops.governance.audit as audit_mod
import xcpng_aiops.governance.policy as policy_mod
import xcpng_aiops.governance.undo as undo_mod


@pytest.fixture
def gov_home(tmp_path, monkeypatch):
    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def snap_conn(monkeypatch):
    """Route the governed snapshot tools to a mocked REST connection."""
    import mcp_server.tools.snapshots as gov_snapshots

    conn = MagicMock(name="conn")
    conn.get.return_value = {}
    conn.delete.return_value = True
    monkeypatch.setattr(gov_snapshots, "_get_connection", lambda target=None: conn)
    return conn


@pytest.fixture
def vm_conn(monkeypatch):
    """Route the governed vm_actions tools to a mocked REST connection."""
    import mcp_server.tools.vm_actions as gov_vm

    conn = MagicMock(name="conn")
    conn.get.return_value = {"power_state": "Running", "$container": "host-1"}
    conn.post.return_value = {}
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    return conn


@pytest.mark.unit
def test_cli_snapshot_delete_dry_run_makes_no_call_and_no_audit(gov_home, snap_conn):
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["snapshot", "delete", "snap-1", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    snap_conn.delete.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_snapshot_delete_confirmed_goes_through_governance(gov_home, snap_conn):
    """Confirmed CLI write must execute via the governed twin: the API call runs
    AND an audit row lands in audit.db (this is what the reroute fix bought)."""
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["snapshot", "delete", "snap-1"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    snap_conn.delete.assert_called_once_with("/vm-snapshots/snap-1")
    assert _audit_tools(gov_home / "audit.db") == ["snapshot_delete"]


@pytest.mark.unit
def test_cli_snapshot_delete_aborts_without_double_confirm(gov_home, snap_conn):
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["snapshot", "delete", "snap-1"], input="y\nn\n")
    assert result.exit_code != 0
    snap_conn.delete.assert_not_called()
    assert not (gov_home / "audit.db").exists()


@pytest.mark.unit
def test_cli_snapshot_revert_confirmed_goes_through_governance(gov_home, snap_conn):
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["snapshot", "revert", "snap-1"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    snap_conn.post.assert_called_once_with(
        "/vm-snapshots/snap-1/actions/revert", params={"sync": "true"}
    )
    assert _audit_tools(gov_home / "audit.db") == ["snapshot_revert"]


@pytest.mark.unit
def test_cli_vm_stop_dry_run_then_confirmed(gov_home, vm_conn):
    from xcpng_aiops.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["vm", "stop", "vm-1", "--dry-run"])
    assert result.exit_code == 0
    assert "DRY-RUN" in result.output
    vm_conn.post.assert_not_called()

    result = runner.invoke(app, ["vm", "stop", "vm-1"], input="y\ny\n")
    assert result.exit_code == 0, result.output
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/clean_shutdown", params={"sync": "true"}
    )
    assert _audit_tools(gov_home / "audit.db") == ["vm_stop"]


@pytest.mark.unit
def test_cli_vm_start_executes_without_confirm_but_audited(gov_home, vm_conn):
    """vm start is non-destructive: no confirm gate, but still governed/audited."""
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["vm", "start", "vm-1"])
    assert result.exit_code == 0, result.output
    vm_conn.post.assert_called_once_with("/vms/vm-1/actions/start", params={"sync": "true"})
    assert _audit_tools(gov_home / "audit.db") == ["vm_start"]


@pytest.mark.unit
def test_cli_vm_migrate_aborts_without_double_confirm(gov_home, vm_conn):
    from xcpng_aiops.cli import app

    result = CliRunner().invoke(app, ["vm", "migrate", "vm-1", "host-2"], input="y\nn\n")
    assert result.exit_code != 0
    vm_conn.post.assert_not_called()
    assert not (gov_home / "audit.db").exists()
