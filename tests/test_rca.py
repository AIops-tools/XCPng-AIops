"""Flagship RCA analyses against mocked XO payloads.

Each RCA must produce structured cause + action findings from realistic
collection shapes — these tests pin the classification logic and thresholds.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest


def _vm(uuid, name, state="Running", **kw):
    base = {
        "uuid": uuid, "name_label": name, "power_state": state,
        "$pool": "pool-1", "$container": "host-1",
        "CPUs": {"number": 2}, "memory": {"size": 2**31},
        "managementAgentDetected": True, "auto_poweron": False,
        "high_availability": "",
    }
    base.update(kw)
    return base


class _FakeConn:
    """Routes GET paths to canned payloads (params ignored except stats)."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[str] = []

    def get(self, path, **kw):
        self.calls.append(path)
        for prefix, payload in self.routes.items():
            if path == prefix or path.startswith(prefix):
                return payload(path) if callable(payload) else payload
        return []

    def post(self, path, **kw):
        self.calls.append(path)
        return {}


# ── 1. VM health RCA ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_vm_health_rca_flags_halted_unexpectedly_and_paused_and_tools():
    from xcpng_aiops.ops.vm_rca import vm_health_rca

    conn = _FakeConn({
        "/vms": [
            _vm("vm-1", "db01", state="Halted", auto_poweron=True),
            _vm("vm-2", "cache01", state="Paused"),
            _vm("vm-3", "legacy01", state="Running",
                managementAgentDetected=False, pvDriversDetected=False),
            _vm("vm-4", "ok01", state="Running"),
        ],
    })
    result = vm_health_rca(conn)
    causes = {f["cause"]: f for f in result["findings"]}
    assert result["vmsAnalyzed"] == 4
    assert causes["halted-unexpectedly"]["vm"] == "db01"
    assert causes["halted-unexpectedly"]["severity"] == "high"
    assert "vm_start" in causes["halted-unexpectedly"]["action"]
    assert causes["paused"]["vm"] == "cache01"
    assert causes["guest-tools-missing"]["vm"] == "legacy01"
    assert result["healthy"] is False
    # High severity sorts first.
    assert result["findings"][0]["cause"] == "halted-unexpectedly"


@pytest.mark.unit
def test_vm_health_rca_ha_halted_also_flags():
    from xcpng_aiops.ops.vm_rca import vm_health_rca

    conn = _FakeConn({
        "/vms": [_vm("vm-1", "ha01", state="Halted", high_availability="restart")],
    })
    result = vm_health_rca(conn)
    assert result["findings"][0]["cause"] == "halted-unexpectedly"


@pytest.mark.unit
def test_vm_health_rca_detects_cpu_and_memory_pressure_from_stats():
    from xcpng_aiops.ops.vm_rca import vm_health_rca

    def stats(path):
        return {
            "interval": 5,
            "stats": {
                "cpus": {"0": [97, 98, 99], "1": [95, 96, 97]},
                "memory": [2**31] * 3,
                "memoryFree": [2**26] * 3,  # ~3% free → pressure
            },
        }

    conn = _FakeConn({
        "/vms/vm-1/stats": stats,
        "/vms/vm-1": _vm("vm-1", "hot01"),
        "/vms": [_vm("vm-1", "hot01")],
    })
    result = vm_health_rca(conn, vm_id="vm-1")
    causes = {f["cause"] for f in result["findings"]}
    assert "cpu-pressure" in causes
    assert "memory-pressure" in causes


@pytest.mark.unit
def test_vm_health_rca_healthy_fleet():
    from xcpng_aiops.ops.vm_rca import vm_health_rca

    conn = _FakeConn({
        "/vms/": {"interval": 5, "stats": {"cpus": {"0": [5]},
                                           "memory": [100], "memoryFree": [80]}},
        "/vms": [_vm("vm-1", "calm01")],
    })
    result = vm_health_rca(conn)
    assert result["healthy"] is True
    assert result["findings"] == []


@pytest.mark.unit
def test_vm_health_rca_caps_stats_calls_fleet_wide():
    from xcpng_aiops.ops import vm_rca

    vms = [_vm(f"vm-{i}", f"vm{i}") for i in range(10)]
    conn = _FakeConn({
        "/vms/": {"interval": 5, "stats": {}},
        "/vms": vms,
    })
    vm_rca.vm_health_rca(conn)
    stats_calls = [c for c in conn.calls if c.endswith("/stats")]
    assert len(stats_calls) == vm_rca._STATS_VM_CAP


# ── 2. SR usage RCA ──────────────────────────────────────────────────────────


def _sr(uuid, name, size, physical, virtual, content="user"):
    return {
        "uuid": uuid, "name_label": name, "SR_type": "lvm",
        "content_type": content, "shared": True, "$pool": "pool-1",
        "size": size, "physical_usage": physical, "usage": virtual,
    }


@pytest.mark.unit
def test_sr_usage_rca_ranks_near_full_and_flags_overcommit_and_orphans():
    from xcpng_aiops.ops.srs import sr_usage_rca

    conn = _FakeConn({
        "/srs": [
            _sr("sr-1", "full-sr", 1000, 960, 900),      # critical (96%)
            _sr("sr-2", "warm-sr", 1000, 880, 2500),     # near-full + overcommit 2.5x
            _sr("sr-3", "cool-sr", 1000, 100, 200),      # fine
        ],
        "/vdis": [
            {"uuid": "vdi-1", "name_label": "orphan-disk", "$SR": "sr-3",
             "size": 500, "usage": 300, "$VBDs": []},
            {"uuid": "vdi-2", "name_label": "attached-disk", "$SR": "sr-1",
             "size": 500, "usage": 400, "$VBDs": ["vbd-1"]},
        ],
    })
    result = sr_usage_rca(conn)
    causes = [(f["cause"], f["sr"]) for f in result["findings"]]
    assert ("sr-critical", "full-sr") in causes
    assert ("sr-near-full", "warm-sr") in causes
    assert ("sr-overcommitted", "warm-sr") in causes
    assert ("orphaned-vdis", "cool-sr") in causes
    orphan = next(f for f in result["findings"] if f["cause"] == "orphaned-vdis")
    assert "300" in orphan["evidence"]  # reclaimable bytes from usage
    assert result["orphanedVdis"] == 1
    # critical sorts before the low-severity orphan finding
    assert result["findings"][0]["cause"] == "sr-critical"


@pytest.mark.unit
def test_sr_usage_rca_ignores_iso_srs_and_reports_healthy():
    from xcpng_aiops.ops.srs import sr_usage_rca

    conn = _FakeConn({
        "/srs": [_sr("sr-iso", "iso-library", 100, 99, 99, content="iso")],
        "/vdis": [],
    })
    result = sr_usage_rca(conn)
    assert result["srsAnalyzed"] == 0
    assert result["healthy"] is True


# ── 3. Backup failure RCA ────────────────────────────────────────────────────


def _log(job_id, job_name, status, message=""):
    tasks = []
    if message:
        tasks = [{"status": "failure", "result": {"message": message}}]
    return {
        "id": f"log-{job_id}-{status}-{message[:8]}",
        "jobId": job_id, "jobName": job_name, "status": status,
        "start": 1, "end": 2, "tasks": tasks,
    }


@pytest.mark.unit
def test_backup_failure_rca_classifies_causes():
    from xcpng_aiops.ops.backups import backup_failure_rca

    conn = _FakeConn({
        "/backup/jobs/vm": [{"id": "job-1", "name": "nightly", "mode": "delta"}],
        "/backup/logs": [
            _log("job-1", "nightly", "failure", "job canceled: VDI chain protection"),
            _log("job-1", "nightly", "failure", "connect ECONNRESET remote host"),
            _log("job-1", "nightly", "skipped", "unhealthy VDI chain, coalesce needed"),
            _log("job-2", "weekly", "failure", "ENOSPC: no space left on device"),
            _log("job-2", "weekly", "success"),
            _log("job-3", "monthly", "failure", "something entirely novel"),
        ],
    })
    result = backup_failure_rca(conn)
    jobs = {j["job"]: j for j in result["jobs"]}
    assert result["jobsWithFailures"] == 3
    assert jobs["nightly"]["causes"]["vdi-chain"] == 2
    assert jobs["nightly"]["causes"]["transport"] == 1
    assert jobs["weekly"]["causes"]["storage-full"] == 1
    assert jobs["monthly"]["causes"]["unknown"] == 1
    # findings carry actions
    nightly_actions = [f["action"] for f in jobs["nightly"]["findings"]]
    assert any("coalesce" in a for a in nightly_actions)
    # jobs sorted by failure count descending
    assert result["jobs"][0]["job"] == "nightly"


@pytest.mark.unit
def test_backup_failure_rca_healthy_when_all_green():
    from xcpng_aiops.ops.backups import backup_failure_rca

    conn = _FakeConn({
        "/backup/jobs/vm": [{"id": "job-1", "name": "nightly", "mode": "full"}],
        "/backup/logs": [_log("job-1", "nightly", "success")],
    })
    result = backup_failure_rca(conn)
    assert result["healthy"] is True
    assert result["jobsWithFailures"] == 0


# ── 4. Pool patch & HA posture ───────────────────────────────────────────────


def _host(uuid, name, version, reboot=False, pool="pool-1"):
    return {
        "uuid": uuid, "name_label": name, "power_state": "Running",
        "enabled": True, "version": version, "productBrand": "XCP-ng",
        "rebootRequired": reboot, "$pool": pool,
        "memory": {"size": 100, "usage": 50}, "cpus": {"cores": 16},
        "residentVms": [],
    }


@pytest.mark.unit
def test_pool_posture_flags_patches_reboot_skew_and_ha():
    from xcpng_aiops.ops.pools import pool_patch_ha_posture

    def missing(path):
        if "host-1" in path:
            return [{"name": "XS-1", "description": "sec fix", "version": "1"}]
        return []

    conn = _FakeConn({
        "/pools": [
            {"uuid": "pool-1", "name_label": "prod", "master": "host-1",
             "HA_enabled": False, "default_SR": "sr-1"},
        ],
        "/hosts/host-1/missing_patches": missing,
        "/hosts/host-2/missing_patches": [],
        "/hosts": [
            _host("host-1", "n1", "8.2.1", reboot=True),
            _host("host-2", "n2", "8.3.0"),
        ],
    })
    result = pool_patch_ha_posture(conn)
    pool = result["pools"][0]
    causes = {f["cause"] for f in pool["findings"]}
    assert causes == {"patches-missing", "reboot-required", "version-skew", "ha-disabled"}
    skew = next(f for f in pool["findings"] if f["cause"] == "version-skew")
    assert skew["severity"] == "high"
    assert "8.2.1" in skew["evidence"] and "8.3.0" in skew["evidence"]
    assert result["healthy"] is False


@pytest.mark.unit
def test_pool_posture_healthy_single_version_patched_ha():
    from xcpng_aiops.ops.pools import pool_patch_ha_posture

    conn = _FakeConn({
        "/pools": [
            {"uuid": "pool-1", "name_label": "lab", "master": "host-1",
             "HA_enabled": True, "default_SR": "sr-1"},
        ],
        "/hosts/": [],
        "/hosts": [_host("host-1", "n1", "8.3.0"), _host("host-2", "n2", "8.3.0")],
    })
    result = pool_patch_ha_posture(conn)
    assert result["healthy"] is True
    assert result["pools"][0]["findings"] == []


@pytest.mark.unit
def test_pool_posture_unknown_patches_tolerated():
    """Hosts whose missing_patches endpoint errors report None (unknown), and
    do not fabricate a patches-missing finding."""
    from xcpng_aiops.ops.pools import pool_patch_ha_posture

    conn = MagicMock(name="conn")

    def _get(path, **kw):
        if path == "/pools":
            return [{"uuid": "pool-1", "name_label": "prod", "master": "h",
                     "HA_enabled": True, "default_SR": "sr"}]
        if path == "/hosts":
            return [_host("host-1", "n1", "8.3.0")]
        raise RuntimeError("no such endpoint on this XO version")

    conn.get.side_effect = _get
    result = pool_patch_ha_posture(conn)
    row = result["pools"][0]["hosts"][0]
    assert row["missingPatches"] is None
    assert result["healthy"] is True
