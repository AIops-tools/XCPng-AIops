"""Pool reads + flagship RCA: pool/host patch & HA posture.

``pool_patch_ha_posture`` answers "is this pool safe to trust?": hosts missing
patches, hosts needing a reboot, HA enabled or not, and version skew across
the pool's hosts (mixed XCP-ng versions break live migration and rolling
updates).

PREVIEW: mock-validated only — verify field/endpoint names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.ops import hosts as host_ops
from xcpng_aiops.ops._util import as_list, s

POOL_FIELDS = "uuid,name_label,name_description,master,HA_enabled,default_SR"


def _pool_summary(pool: dict) -> dict:
    """Reduce a pool record to a high-signal summary."""
    return {
        "id": s(pool.get("uuid"), 64),
        "name": s(pool.get("name_label"), 128),
        "master": s(pool.get("master"), 64),
        "haEnabled": pool.get("HA_enabled"),
        "defaultSr": s(pool.get("default_SR"), 64),
    }


def list_pools(conn: Any) -> list[dict]:
    """[READ] List XCP-ng pools with master, HA state, default SR."""
    return [_pool_summary(p) for p in as_list(conn.get("/pools", params={"fields": POOL_FIELDS}))]


def get_pool(conn: Any, pool_id: str) -> dict:
    """[READ] Return detail for a single pool by uuid."""
    pool = conn.get(f"/pools/{_seg(pool_id)}")
    if not isinstance(pool, dict):
        return {}
    summary = _pool_summary(pool)
    summary["description"] = s(pool.get("name_description"), 256)
    summary["tags"] = [s(t, 64) for t in (pool.get("tags") or [])[:16]]
    return summary


def _host_patch_row(conn: Any, host: dict) -> dict:
    """Posture row for one host: missing patches (best-effort) + reboot flag."""
    row = {
        "host": host.get("name"),
        "id": host.get("id"),
        "version": host.get("version"),
        "rebootRequired": host.get("rebootRequired"),
        "missingPatches": None,  # None = unknown (endpoint unavailable)
    }
    try:
        row["missingPatches"] = len(host_ops.missing_patches(conn, host["id"]))
    except Exception:  # noqa: BLE001 — patch data is best-effort per host
        pass
    return row


def pool_patch_ha_posture(conn: Any, pool_id: str | None = None) -> dict:
    """[READ][RCA] Patch & HA posture per pool: cause + action per finding.

    Findings: ``patches-missing``, ``reboot-required``, ``ha-disabled``,
    ``version-skew`` (mixed host versions inside one pool).
    """
    pools = list_pools(conn)
    if pool_id:
        pools = [p for p in pools if p.get("id") == pool_id]
    hosts = host_ops.list_hosts(conn)

    results = []
    findings_total = 0
    for pool in pools:
        pool_hosts = [h for h in hosts if h.get("pool") == pool.get("id")]
        rows = [_host_patch_row(conn, h) for h in pool_hosts]
        findings: list[dict] = []

        unpatched = [r for r in rows if (r.get("missingPatches") or 0) > 0]
        if unpatched:
            findings.append(
                {
                    "cause": "patches-missing",
                    "severity": "medium",
                    "evidence": ", ".join(
                        f"{r['host']}: {r['missingPatches']} missing" for r in unpatched
                    ),
                    "action": "Apply pending patches from the XO Patches tab (rolling "
                    "pool update keeps VMs running).",
                }
            )
        reboot = [r["host"] for r in rows if r.get("rebootRequired")]
        if reboot:
            findings.append(
                {
                    "cause": "reboot-required",
                    "severity": "medium",
                    "evidence": f"hosts pending reboot: {', '.join(map(str, reboot))}",
                    "action": "Schedule a rolling reboot (evacuate VMs first via "
                    "vm_migrate) to finish applying patches.",
                }
            )
        versions = sorted({r.get("version") for r in rows if r.get("version")})
        if len(versions) > 1:
            findings.append(
                {
                    "cause": "version-skew",
                    "severity": "high",
                    "evidence": f"mixed host versions in pool: {', '.join(versions)}",
                    "action": "Bring all hosts in the pool to the same version — mixed "
                    "versions break live migration and rolling updates.",
                }
            )
        if pool.get("haEnabled") is False and len(pool_hosts) > 1:
            findings.append(
                {
                    "cause": "ha-disabled",
                    "severity": "low",
                    "evidence": f"HA disabled on a {len(pool_hosts)}-host pool",
                    "action": "Consider enabling HA (needs a shared SR) so VMs restart "
                    "automatically after a host failure.",
                }
            )

        findings_total += len(findings)
        results.append(
            {
                "pool": pool.get("name"),
                "id": pool.get("id"),
                "haEnabled": pool.get("haEnabled"),
                "hosts": rows,
                "findings": findings,
            }
        )

    return {
        "poolsAnalyzed": len(results),
        "pools": results,
        "healthy": findings_total == 0,
    }
