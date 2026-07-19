"""Truncation announces itself — and is measured, never guessed.

Every listing that can grow without bound returns
``{<items>: [...], "returned": N, "limit": L, "truncated": bool}``. A bare list
cannot say "there is more"; the consumer has to infer it from the length
happening to equal the limit, and a smaller local model faced with a capped
result tends to report it as the complete picture.

``truncated`` must therefore come from a real comparison — the full collection
length client-side, or an over-fetched extra row server-side — never from
``len(items) == limit``, which is a coincidence.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from xcpng_aiops.cli import app
from xcpng_aiops.ops import backups as backup_ops
from xcpng_aiops.ops import srs as sr_ops
from xcpng_aiops.ops import tasks as task_ops
from xcpng_aiops.ops import vms as vm_ops

runner = CliRunner()


def _vms(n: int) -> list[dict]:
    return [{"uuid": f"vm-{i}", "name_label": f"vm{i}", "power_state": "Running"} for i in range(n)]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("fn", "key"),
    [
        (lambda conn, limit: vm_ops.list_vms(conn, limit=limit), "vms"),
        (lambda conn, limit: vm_ops.list_vm_snapshots(conn, limit=limit), "snapshots"),
        (lambda conn, limit: sr_ops.list_srs(conn, limit=limit), "srs"),
        (lambda conn, limit: sr_ops.list_vdis(conn, limit=limit), "vdis"),
        (lambda conn, limit: task_ops.list_tasks(conn, limit=limit), "tasks"),
        (lambda conn, limit: backup_ops.list_backup_jobs(conn, limit=limit), "jobs"),
    ],
)
def test_listing_envelopes_report_truncation(fn, key):
    conn = MagicMock()
    conn.get.return_value = [{"uuid": f"o-{i}", "id": f"o-{i}"} for i in range(5)]

    capped = fn(conn, 3)
    assert capped["truncated"] is True
    assert capped["returned"] == 3 == len(capped[key])
    assert capped["limit"] == 3

    whole = fn(conn, 50)
    assert whole["truncated"] is False
    assert whole["returned"] == 5


@pytest.mark.unit
def test_exactly_at_the_limit_is_not_reported_as_truncated():
    """The classic false positive: len(items) == limit is a coincidence, not proof."""
    conn = MagicMock()
    conn.get.return_value = _vms(3)
    page = vm_ops.list_vms(conn, limit=3)
    assert page["returned"] == 3
    assert page["truncated"] is False, "a full page is not evidence of more rows"


@pytest.mark.unit
def test_backup_logs_overfetch_one_extra_record():
    """XO can cap server-side, so truncation is measured by asking for limit+1."""
    conn = MagicMock()
    conn.get.return_value = [{"id": f"log-{i}", "status": "success"} for i in range(6)]

    page = backup_ops.list_backup_logs(conn, limit=5)
    conn.get.assert_called_with("/backup/logs", params={"limit": 6})
    assert page["returned"] == 5 and page["truncated"] is True

    conn.get.return_value = [{"id": "log-0", "status": "success"}]
    page = backup_ops.list_backup_logs(conn, limit=5)
    assert page["returned"] == 1 and page["truncated"] is False


@pytest.mark.unit
def test_truncation_is_applied_after_filtering():
    """The limit bounds what you asked for, not the raw collection."""
    conn = MagicMock()
    conn.get.return_value = [
        {"uuid": "vm-0", "power_state": "Halted"},
        {"uuid": "vm-1", "power_state": "Running"},
        {"uuid": "vm-2", "power_state": "Running"},
    ]
    page = vm_ops.list_vms(conn, power_state="Running", limit=2)
    assert page["returned"] == 2 and page["truncated"] is False


@pytest.mark.unit
def test_rca_reports_when_its_input_listing_was_capped():
    """A correlation over a subset must say so rather than read as fleet-wide."""
    from xcpng_aiops.ops import vm_rca

    conn = MagicMock()
    conn.get.return_value = _vms(3)
    monkey = vm_rca.vm_health_rca(conn)
    assert monkey["inputTruncated"] is False

    conn.get.return_value = _vms(3)
    original = vm_rca.ANALYSIS_LIST_LIMIT
    try:
        vm_rca.ANALYSIS_LIST_LIMIT = 2
        assert vm_rca.vm_health_rca(conn)["inputTruncated"] is True
    finally:
        vm_rca.ANALYSIS_LIST_LIMIT = original


@pytest.mark.unit
def test_backup_rca_reports_truncated_input():
    conn = MagicMock()
    conn.get.return_value = [{"id": f"log-{i}", "status": "success"} for i in range(6)]
    assert backup_ops.backup_failure_rca(conn, limit=5)["inputTruncated"] is True


@pytest.mark.unit
def test_sr_rca_reports_truncated_input():
    conn = MagicMock()
    conn.get.return_value = [{"uuid": f"sr-{i}"} for i in range(3)]
    original = sr_ops.ANALYSIS_LIST_LIMIT
    try:
        sr_ops.ANALYSIS_LIST_LIMIT = 2
        assert sr_ops.sr_usage_rca(conn)["inputTruncated"] is True
    finally:
        sr_ops.ANALYSIS_LIST_LIMIT = original


@pytest.mark.unit
@pytest.mark.parametrize(
    ("module", "argv", "noun"),
    [
        ("xcpng_aiops.cli.vm", ["vm", "list", "--limit", "2"], "VMs"),
        ("xcpng_aiops.cli.sr", ["sr", "list", "--limit", "2"], "SRs"),
        ("xcpng_aiops.cli.sr", ["sr", "vdis", "--limit", "2"], "VDIs"),
        ("xcpng_aiops.cli.task", ["task", "list", "--limit", "2"], "tasks"),
        ("xcpng_aiops.cli.snapshot", ["snapshot", "list", "--limit", "2"], "snapshots"),
        ("xcpng_aiops.cli.backup", ["backup", "jobs", "--limit", "2"], "backup jobs"),
    ],
)
def test_cli_prints_a_truncation_note(monkeypatch, module, argv, noun):
    """The operator must be told in words, not only via a JSON flag."""
    import importlib

    mod = importlib.import_module(module)
    conn = MagicMock()
    conn.get.return_value = [{"uuid": f"o-{i}", "id": f"o-{i}"} for i in range(5)]
    monkeypatch.setattr(mod, "get_connection", lambda target=None: (conn, None))

    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert "truncated" in result.output
    assert "--limit" in result.output


@pytest.mark.unit
def test_cli_is_silent_when_nothing_was_truncated(monkeypatch):
    import xcpng_aiops.cli.vm as vm_cli

    conn = MagicMock()
    conn.get.return_value = _vms(2)
    monkeypatch.setattr(vm_cli, "get_connection", lambda target=None: (conn, None))

    result = runner.invoke(app, ["vm", "list", "--limit", "10"])
    assert result.exit_code == 0, result.output
    assert "re-run with a higher" not in result.output


@pytest.mark.unit
def test_undo_list_envelope_measures_truncation(tmp_path, monkeypatch):
    """undo_list over-fetches one row rather than guessing from the row count."""
    import xcpng_aiops.governance.audit as audit_mod
    import xcpng_aiops.governance.policy as policy_mod
    import xcpng_aiops.governance.undo as undo_mod

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    try:
        from mcp_server.tools import undo as undo_tools

        store = undo_mod.get_undo_store()
        for i in range(4):
            store.record(
                skill="xcpng-aiops",
                tool="vm_start",
                undo_descriptor={
                    "tool": "vm_stop",
                    "params": {"vm_id": f"vm-{i}"},
                    "note": "test",
                },
            )

        capped = undo_tools.undo_list(limit=2)
        assert capped["returned"] == 2 and capped["truncated"] is True
        whole = undo_tools.undo_list(limit=50)
        assert whole["returned"] == 4 and whole["truncated"] is False
    finally:
        audit_mod.reset_engine()
        policy_mod.reset_policy_engine()
        undo_mod.reset_undo_store()
