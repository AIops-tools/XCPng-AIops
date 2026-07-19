"""Environment health overview for an XCP-ng fleet via Xen Orchestra (read-only).

A single high-signal summary an agent can call first: pools, hosts, VMs by
power state, SRs near full, and recent backup failures. Built by fanning out
over the other read ops; each sub-query is best-effort so one failing
collection never blanks the whole picture.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.ops import backups as backup_ops
from xcpng_aiops.ops import hosts as host_ops
from xcpng_aiops.ops import pools as pool_ops
from xcpng_aiops.ops import srs as sr_ops
from xcpng_aiops.ops import vms as vm_ops
from xcpng_aiops.ops._util import ANALYSIS_LIST_LIMIT
from xcpng_aiops.ops.srs import SR_NEAR_FULL_PERCENT

# How many recent backup logs the overview scans for failures.
_OVERVIEW_LOG_LIMIT = 20


def _pool_block(conn: Any) -> dict:
    try:
        pools = pool_ops.list_pools(conn)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}
    return {
        "total": len(pools),
        "haEnabled": [p["name"] for p in pools if p.get("haEnabled")],
    }


def _host_block(conn: Any) -> dict:
    try:
        hosts = host_ops.list_hosts(conn)
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}
    return {
        "total": len(hosts),
        "disabled": [h["name"] for h in hosts if h.get("enabled") is False],
        "rebootRequired": [h["name"] for h in hosts if h.get("rebootRequired")],
        "versions": sorted({h["version"] for h in hosts if h.get("version")}),
    }


def _vm_block(conn: Any) -> dict:
    try:
        page = vm_ops.list_vms(conn, limit=ANALYSIS_LIST_LIMIT)
        vms = page["vms"]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}
    by_state: dict[str, int] = {}
    for v in vms:
        key = (v.get("powerState") or "Unknown") or "Unknown"
        by_state[key] = by_state.get(key, 0) + 1
    missing_tools = [
        v["name"]
        for v in vms
        if (v.get("powerState") or "").lower() == "running"
        and v.get("guestToolsDetected") is False
    ]
    return {
        "total": len(vms),
        "byPowerState": by_state,
        "runningWithoutTools": missing_tools,
        "truncated": page["truncated"],
    }


def _sr_block(conn: Any) -> dict:
    try:
        page = sr_ops.list_srs(conn, limit=ANALYSIS_LIST_LIMIT)
        srs = page["srs"]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}
    near_full = [
        {"name": r.get("name"), "usedPercent": r.get("usedPercent")}
        for r in srs
        if isinstance(r.get("usedPercent"), (int, float))
        and r["usedPercent"] >= SR_NEAR_FULL_PERCENT
    ]
    return {"total": len(srs), "nearFull": near_full, "truncated": page["truncated"]}


def _backup_block(conn: Any) -> dict:
    try:
        page = backup_ops.list_backup_logs(conn, _OVERVIEW_LOG_LIMIT)
        logs = page["logs"]
    except Exception as exc:  # noqa: BLE001 — report as partial
        return {"error": str(exc)[:200]}
    bad = [
        {"job": x.get("jobName"), "status": x.get("status")}
        for x in logs
        if (x.get("status") or "").lower() in ("failure", "interrupted", "skipped")
    ]
    return {"recentRuns": len(logs), "recentFailures": bad, "truncated": page["truncated"]}


def health_overview(conn: Any) -> dict:
    """[READ] One-shot health summary: pools, hosts, VMs, SRs, recent backups."""
    return {
        "pools": _pool_block(conn),
        "hosts": _host_block(conn),
        "vms": _vm_block(conn),
        "srs": _sr_block(conn),
        "backups": _backup_block(conn),
        "srNearFullThresholdPercent": SR_NEAR_FULL_PERCENT,
    }
