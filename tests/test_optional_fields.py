"""Absent fields come back as null, not as an empty string.

An empty string reads as "this field exists and is empty"; a missing field is a
different fact. Collapsing the two hides information from any consumer, and a
smaller local model will confidently invent the difference. These tests pin the
contract end-to-end: helper, ops layer, and the CLI rendering that has to cope
with a null.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from xcpng_aiops.cli import app
from xcpng_aiops.governance import opt_str
from xcpng_aiops.ops import srs as sr_ops
from xcpng_aiops.ops import tasks as task_ops
from xcpng_aiops.ops import vms as vm_ops

runner = CliRunner()


@pytest.mark.unit
def test_opt_str_distinguishes_absent_from_empty():
    assert opt_str(None) is None, "absent must stay absent"
    assert opt_str("") == "", "a genuinely empty value is not the same as absent"
    assert opt_str("xcp-host-1", 64) == "xcp-host-1"


@pytest.mark.unit
def test_opt_str_still_sanitizes_and_truncates():
    assert opt_str("a\x00b") == "ab"  # control character stripped
    assert opt_str("abcdef", 3) == "abc"


@pytest.mark.unit
def test_opt_str_accepts_non_string_values():
    assert opt_str(42) == "42"


@pytest.mark.unit
def test_ops_report_absent_fields_as_none():
    """A VM record with no name/power_state reports null, not ''."""
    conn = MagicMock()
    conn.get.return_value = [{"uuid": "vm-1"}]  # name_label / power_state absent
    row = vm_ops.list_vms(conn)["vms"][0]
    assert row["id"] == "vm-1"
    assert row["name"] is None
    assert row["powerState"] is None
    assert row["pool"] is None
    assert row["host"] is None


@pytest.mark.unit
def test_ops_keep_empty_string_when_source_is_empty():
    """An explicitly empty upstream value is preserved as '' — not turned into null."""
    conn = MagicMock()
    conn.get.return_value = [{"uuid": "vm-1", "name_label": ""}]
    assert vm_ops.list_vms(conn)["vms"][0]["name"] == ""


@pytest.mark.unit
def test_ops_never_drop_the_key_itself():
    """Keys are always present; only their value may be null.

    Omitting a key entirely is worse than a null — the consumer cannot tell the
    field was even considered.
    """
    conn = MagicMock()
    conn.get.return_value = [{}]
    row = vm_ops.list_vms(conn)["vms"][0]
    for key in ("id", "name", "powerState", "pool", "host", "vcpus", "memoryBytes"):
        assert key in row, f"{key} must be present even when XO omitted it"


@pytest.mark.unit
def test_sr_and_task_rows_report_absence_as_null():
    conn = MagicMock()
    conn.get.return_value = [{"uuid": "sr-1"}]
    sr = sr_ops.list_srs(conn)["srs"][0]
    assert sr["name"] is None and sr["type"] is None and sr["contentType"] is None

    conn.get.return_value = [{"id": "task-1", "status": "success"}]
    task = task_ops.list_tasks(conn)["tasks"][0]
    assert task["name"] is None, "an absent task name is not an empty task name"
    assert task["object"] is None


@pytest.mark.unit
def test_filters_survive_null_fields():
    """A power-state filter must not crash on a VM whose state XO omitted."""
    conn = MagicMock()
    conn.get.return_value = [
        {"uuid": "vm-1"},  # no power_state at all
        {"uuid": "vm-2", "power_state": "Running"},
    ]
    assert [r["id"] for r in vm_ops.list_vms(conn, power_state="running")["vms"]] == ["vm-2"]

    conn.get.return_value = [{"id": "t1"}, {"id": "t2", "status": "failure"}]
    assert [r["id"] for r in task_ops.list_tasks(conn, status="failure")["tasks"]] == ["t2"]


@pytest.mark.unit
def test_rca_survives_null_power_state():
    """The VM health RCA reads powerState — a null must not sink the analysis."""
    from xcpng_aiops.ops import vm_rca

    conn = MagicMock()
    conn.get.return_value = [{"uuid": "vm-1"}]
    out = vm_rca.vm_health_rca(conn)
    assert out["vmsAnalyzed"] == 1


@pytest.mark.unit
def test_cli_renders_rows_with_null_fields(monkeypatch):
    """The JSON render must survive a null field rather than crashing."""
    import xcpng_aiops.cli.vm as vm_cli

    conn = MagicMock()
    conn.get.return_value = [{"uuid": "vm-1"}]  # name and power state both absent
    monkeypatch.setattr(vm_cli, "get_connection", lambda target=None: (conn, None))

    result = runner.invoke(app, ["vm", "list"])
    assert result.exit_code == 0, result.output
    assert "vm-1" in result.output
    assert "null" in result.output, "absence must reach the operator as null"
