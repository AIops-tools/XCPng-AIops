"""Read-op shaping/filtering against a mocked REST client (no live XO).

Covers the read paths the smoke/RCA suites do not: list filters, single-object
getters that tolerate non-dict payloads, snapshot listing, overview success and
all-blocks-fail resilience, and the pool getter.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from xcpng_aiops.ops import hosts as host_ops
from xcpng_aiops.ops import overview as ov
from xcpng_aiops.ops import pools as pool_ops
from xcpng_aiops.ops import tasks as task_ops
from xcpng_aiops.ops import vms as vm_ops


@pytest.mark.unit
def test_list_vms_filters_by_state_and_pool():
    conn = MagicMock()
    conn.get.return_value = [
        {"uuid": "1", "name_label": "a", "power_state": "Running", "$pool": "p1"},
        {"uuid": "2", "name_label": "b", "power_state": "Halted", "$pool": "p1"},
        {"uuid": "3", "name_label": "c", "power_state": "Running", "$pool": "p2"},
    ]
    running = vm_ops.list_vms(conn, power_state="running")
    assert {r["name"] for r in running} == {"a", "c"}
    p1 = vm_ops.list_vms(conn, pool="p1")
    assert {r["name"] for r in p1} == {"a", "b"}


@pytest.mark.unit
def test_get_vm_non_dict_returns_empty_and_detail_fields():
    conn = MagicMock()
    conn.get.return_value = "not-a-dict"
    assert vm_ops.get_vm(conn, "vm-1") == {}

    conn.get.return_value = {
        "uuid": "vm-1", "name_label": "web", "power_state": "Running",
        "name_description": "front end", "os_version": {"name": "Debian 12"},
        "tags": ["prod", "web"],
    }
    detail = vm_ops.get_vm(conn, "vm-1")
    assert detail["description"] == "front end"
    assert detail["osVersion"] == "Debian 12"
    assert detail["tags"] == ["prod", "web"]


@pytest.mark.unit
def test_list_vm_snapshots_filter():
    conn = MagicMock()
    conn.get.return_value = [
        {"uuid": "s1", "name_label": "n1", "$snapshot_of": "vm-1"},
        {"uuid": "s2", "name_label": "n2", "$snapshot_of": "vm-2"},
    ]
    all_snaps = vm_ops.list_vm_snapshots(conn)
    assert len(all_snaps) == 2
    one = vm_ops.list_vm_snapshots(conn, vm_id="vm-1")
    assert [s["id"] for s in one] == ["s1"]


@pytest.mark.unit
def test_vm_stats_computes_averages_and_memory_percent():
    conn = MagicMock()
    conn.get.return_value = {
        "interval": 5,
        "stats": {
            "cpus": {"0": [10.0, 20.0], "1": [30.0, 40.0]},
            "memory": [1000, 1000],
            "memoryFree": [250, 250],
        },
    }
    out = vm_ops.vm_stats(conn, "vm-1", "minutes")
    assert out["cpuCount"] == 2
    assert out["cpuAvgPercent"] == 25.0  # avg of (15, 35)
    assert out["memoryUsedPercent"] == 75.0
    assert out["interval"] == 5


@pytest.mark.unit
def test_vm_stats_non_dict_payload():
    conn = MagicMock()
    conn.get.return_value = None
    assert vm_ops.vm_stats(conn, "vm-1")["stats"] == {}


@pytest.mark.unit
def test_list_hosts_pool_filter_and_get_host():
    conn = MagicMock()
    conn.get.return_value = [
        {"uuid": "h1", "name_label": "n1", "$pool": "p1",
         "memory": {"size": 100, "usage": 50}},
        {"uuid": "h2", "name_label": "n2", "$pool": "p2"},
    ]
    rows = host_ops.list_hosts(conn, pool="p1")
    assert [r["name"] for r in rows] == ["n1"]
    assert rows[0]["memoryUsedPercent"] == 50.0

    conn.get.return_value = {
        "uuid": "h1", "name_label": "n1", "build": "release/2024",
        "tags": ["core"], "startTime": 123,
    }
    detail = host_ops.get_host(conn, "h1")
    assert detail["build"] == "release/2024"
    assert detail["tags"] == ["core"]

    conn.get.return_value = "nope"
    assert host_ops.get_host(conn, "h1") == {}


@pytest.mark.unit
def test_missing_patches_shapes_rows():
    conn = MagicMock()
    conn.get.return_value = [
        {"name": "XS8-P1", "description": "sec fix", "version": "1.2"},
    ]
    rows = host_ops.missing_patches(conn, "h1")
    assert rows == [{"name": "XS8-P1", "description": "sec fix", "version": "1.2"}]


@pytest.mark.unit
def test_get_pool_detail_and_non_dict():
    conn = MagicMock()
    conn.get.return_value = {
        "uuid": "p1", "name_label": "prod", "name_description": "d", "tags": ["x"],
    }
    detail = pool_ops.get_pool(conn, "p1")
    assert detail["description"] == "d"
    assert detail["tags"] == ["x"]

    conn.get.return_value = 42
    assert pool_ops.get_pool(conn, "p1") == {}


@pytest.mark.unit
def test_pool_posture_pool_id_filter():
    routes = {
        "/pools": [
            {"uuid": "p1", "name_label": "prod", "HA_enabled": True},
            {"uuid": "p2", "name_label": "dev", "HA_enabled": False},
        ],
        "/hosts": [],
    }

    def _get(path, **kw):
        for k, v in routes.items():
            if path == k:
                return v
        return []

    conn = MagicMock()
    conn.get.side_effect = _get
    out = pool_ops.pool_patch_ha_posture(conn, pool_id="p1")
    assert out["poolsAnalyzed"] == 1
    assert out["pools"][0]["id"] == "p1"


@pytest.mark.unit
def test_list_tasks_status_filter():
    conn = MagicMock()
    conn.get.return_value = [
        {"id": "t1", "status": "success", "properties": {"name": "backup"}},
        {"id": "t2", "status": "failure", "properties": {"name": "clone"}},
    ]
    all_tasks = task_ops.list_tasks(conn)
    assert len(all_tasks) == 2
    assert all_tasks[0]["name"] == "backup"
    failed = task_ops.list_tasks(conn, status="failure")
    assert [t["id"] for t in failed] == ["t2"]


@pytest.mark.unit
def test_overview_full_data_success_blocks():
    routes = {
        "/pools": [{"uuid": "p1", "name_label": "prod", "HA_enabled": True}],
        "/hosts": [
            {"uuid": "h1", "name_label": "n1", "enabled": False,
             "rebootRequired": True, "version": "8.2"},
            {"uuid": "h2", "name_label": "n2", "enabled": True, "version": "8.3"},
        ],
        "/vms": [
            {"uuid": "v1", "name_label": "web", "power_state": "Running",
             "managementAgentDetected": False, "pvDriversDetected": False},
            {"uuid": "v2", "name_label": "db", "power_state": "Halted"},
        ],
        "/srs": [
            {"uuid": "s1", "name_label": "full", "size": 100, "physical_usage": 95},
        ],
        "/backup/logs": [{"id": "l1", "status": "failure", "jobName": "nightly"}],
    }

    def _get(path, **kw):
        for k, v in routes.items():
            if path == k or path.startswith(k):
                return v
        return []

    conn = MagicMock()
    conn.get.side_effect = _get
    data = ov.health_overview(conn)
    assert data["pools"]["haEnabled"] == ["prod"]
    assert data["hosts"]["disabled"] == ["n1"]
    assert data["hosts"]["rebootRequired"] == ["n1"]
    assert data["hosts"]["versions"] == ["8.2", "8.3"]
    assert data["vms"]["byPowerState"] == {"Running": 1, "Halted": 1}
    assert data["vms"]["runningWithoutTools"] == ["web"]
    assert data["srs"]["nearFull"][0]["name"] == "full"
    assert data["backups"]["recentFailures"][0]["job"] == "nightly"


@pytest.mark.unit
def test_overview_every_block_reports_partial_on_failure():
    conn = MagicMock()
    conn.get.side_effect = RuntimeError("boom")
    data = ov.health_overview(conn)
    for key in ("pools", "hosts", "vms", "srs", "backups"):
        assert "error" in data[key], key
