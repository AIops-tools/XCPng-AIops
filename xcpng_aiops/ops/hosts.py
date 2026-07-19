"""Host read operations over the Xen Orchestra REST API (``/hosts``).

PREVIEW: mock-validated only — verify field names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.governance import opt_str
from xcpng_aiops.ops._util import as_list, pct

HOST_FIELDS = (
    "uuid,name_label,power_state,enabled,version,productBrand,rebootRequired,"
    "memory,cpus,$pool,residentVms"
)


def host_summary(host: dict) -> dict:
    """Reduce a host record to a high-signal summary."""
    memory = host.get("memory") or {}
    cpus = host.get("cpus") or {}
    mem_size = memory.get("size") if isinstance(memory, dict) else None
    mem_usage = memory.get("usage") if isinstance(memory, dict) else None
    return {
        "id": opt_str(host.get("uuid"), 64),
        "name": opt_str(host.get("name_label"), 128),
        "powerState": opt_str(host.get("power_state"), 32),
        "enabled": host.get("enabled"),
        "version": opt_str(host.get("version"), 64),
        "product": opt_str(host.get("productBrand"), 64),
        "rebootRequired": host.get("rebootRequired"),
        "pool": opt_str(host.get("$pool"), 64),
        "cores": cpus.get("cores") if isinstance(cpus, dict) else None,
        "memoryBytes": mem_size,
        "memoryUsedPercent": pct(mem_usage, mem_size),
        "residentVms": len(host.get("residentVms") or []),
    }


def list_hosts(conn: Any, pool: str | None = None) -> list[dict]:
    """[READ] List hosts with version, state, memory usage, resident VM count."""
    rows = [host_summary(h) for h in as_list(conn.get("/hosts", params={"fields": HOST_FIELDS}))]
    if pool:
        rows = [r for r in rows if r.get("pool") == pool]
    return rows


def get_host(conn: Any, host_id: str) -> dict:
    """[READ] Return detail for a single host by uuid."""
    host = conn.get(f"/hosts/{_seg(host_id)}")
    if not isinstance(host, dict):
        return {}
    summary = host_summary(host)
    summary["build"] = opt_str(host.get("build"), 64)
    summary["startTime"] = host.get("startTime")
    summary["tags"] = [opt_str(t, 64) for t in (host.get("tags") or [])[:16]]
    return summary


def missing_patches(conn: Any, host_id: str) -> list[dict]:
    """[READ] Missing patches for one host (empty when fully patched).

    Tolerates XO versions without the endpoint by treating 404 as "unknown"
    (raises — callers that need best-effort catch it).
    """
    data = conn.get(f"/hosts/{_seg(host_id)}/missing_patches")
    rows = []
    for p in as_list(data):
        rows.append(
            {
                "name": opt_str(p.get("name"), 128),
                "description": opt_str(p.get("description"), 200),
                "version": opt_str(p.get("version"), 32),
            }
        )
    return rows
