"""VM read operations over the Xen Orchestra REST API (``/vms``).

Reads request explicit ``fields=`` so XO returns objects (not href strings).
Returns are high-signal summaries; all API text is sanitized before reaching
the caller.

PREVIEW: endpoint paths are modelled against the documented Xen Orchestra
REST ``/rest/v0`` API and are mock-validated only — verify against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.governance import opt_str
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT, as_list, paged, s

# ``mainIpAddress`` is requested for the vm_stop dry-run hint (see
# ops.vm_actions.self_vm_hint) — it only appears when the guest agent is
# installed, so it is absent far more often than it is wrong.
VM_FIELDS = (
    "uuid,name_label,name_description,power_state,os_version,managementAgentDetected,"
    "pvDriversDetected,memory,CPUs,$pool,$container,auto_poweron,high_availability,"
    "startTime,tags,mainIpAddress"
)


def _tools_ok(vm: dict) -> bool | None:
    """Whether the guest management agent / PV drivers are reporting."""
    agent = vm.get("managementAgentDetected")
    drivers = vm.get("pvDriversDetected")
    if agent is None and drivers is None:
        return None
    return bool(agent or drivers)


def vm_summary(vm: dict) -> dict:
    """Reduce a VM record to a high-signal summary."""
    memory = vm.get("memory") or {}
    cpus = vm.get("CPUs") or {}
    return {
        "id": opt_str(vm.get("uuid"), 64),
        "name": opt_str(vm.get("name_label"), 128),
        "powerState": opt_str(vm.get("power_state"), 32),
        "pool": opt_str(vm.get("$pool"), 64),
        "host": opt_str(vm.get("$container"), 64),
        "vcpus": cpus.get("number") if isinstance(cpus, dict) else None,
        "memoryBytes": memory.get("size") if isinstance(memory, dict) else None,
        "guestToolsDetected": _tools_ok(vm),
        "autoPoweron": vm.get("auto_poweron"),
        "haRestartPriority": opt_str(vm.get("high_availability"), 32),
    }


def list_vms(
    conn: Any,
    power_state: str | None = None,
    pool: str | None = None,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict:
    """[READ] List VMs, optionally filtered by power state and/or pool id.

    Filters are applied first, then the ``limit`` cap, so ``limit`` bounds what
    you actually asked for. Returns a truncation-announcing envelope::

        {"vms": [...], "returned": 200, "limit": 200, "truncated": true}
    """
    rows = [vm_summary(v) for v in as_list(conn.get("/vms", params={"fields": VM_FIELDS}))]
    if power_state:
        rows = [r for r in rows if (r.get("powerState") or "").lower() == power_state.lower()]
    if pool:
        rows = [r for r in rows if r.get("pool") == pool]
    return paged("vms", rows, limit)


def get_vm(conn: Any, vm_id: str) -> dict:
    """[READ] Return detail for a single VM by uuid."""
    vm = conn.get(f"/vms/{_seg(vm_id)}")
    if not isinstance(vm, dict):
        return {}
    summary = vm_summary(vm)
    summary["description"] = opt_str(vm.get("name_description"), 256)
    summary["osVersion"] = opt_str((vm.get("os_version") or {}).get("name"), 128)
    summary["startTime"] = vm.get("startTime")
    summary["tags"] = [s(t, 64) for t in (vm.get("tags") or [])[:16]]
    return summary


def _series_avg(series: Any) -> float | None:
    """Average of the last few numeric samples of an RRD series."""
    if not isinstance(series, list):
        return None
    tail = [v for v in series[-10:] if isinstance(v, (int, float))]
    if not tail:
        return None
    return sum(tail) / len(tail)


def vm_stats(conn: Any, vm_id: str, granularity: str = "seconds") -> dict:
    """[READ] Return recent CPU/memory stats for a VM (RRD-backed).

    ``granularity`` is one of seconds / minutes / hours / days.
    """
    data = conn.get(f"/vms/{_seg(vm_id)}/stats", params={"granularity": granularity})
    if not isinstance(data, dict):
        return {"id": s(vm_id, 64), "stats": {}}
    stats = data.get("stats") or {}
    cpus = stats.get("cpus") or {}
    cpu_avgs = [
        avg for avg in (_series_avg(v) for v in cpus.values() if isinstance(v, list))
        if avg is not None
    ]
    memory_total = _series_avg(stats.get("memory"))
    memory_free = _series_avg(stats.get("memoryFree"))
    used_pct = None
    if memory_total and memory_free is not None:
        used_pct = round((memory_total - memory_free) / memory_total * 100, 1)
    return {
        "id": s(vm_id, 64),
        "granularity": s(granularity, 16),
        "interval": data.get("interval"),
        "cpuAvgPercent": round(sum(cpu_avgs) / len(cpu_avgs), 1) if cpu_avgs else None,
        "cpuCount": len(cpus) if isinstance(cpus, dict) else None,
        "memoryUsedPercent": used_pct,
    }


def list_vm_snapshots(
    conn: Any, vm_id: str | None = None, limit: int = DEFAULT_LIST_LIMIT
) -> dict:
    """[READ] List VM snapshots, optionally filtered to one VM uuid.

    Returns ``{"snapshots": [...], "returned": N, "limit": L, "truncated": b}``
    — snapshot counts grow silently, so a capped read has to say it was capped.
    """
    fields = "uuid,name_label,snapshot_time,$snapshot_of"
    rows = []
    for snap in as_list(conn.get("/vm-snapshots", params={"fields": fields})):
        rows.append(
            {
                "id": opt_str(snap.get("uuid"), 64),
                "name": opt_str(snap.get("name_label"), 128),
                "snapshotTime": snap.get("snapshot_time"),
                "vm": opt_str(snap.get("$snapshot_of"), 64),
            }
        )
    if vm_id:
        rows = [r for r in rows if r.get("vm") == vm_id]
    return paged("snapshots", rows, limit)
