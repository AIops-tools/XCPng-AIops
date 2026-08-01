"""Storage repository (SR) reads + flagship RCA: SR usage.

``sr_usage_rca`` ranks SRs by fullness, flags thin-provision overcommit
(virtual allocation exceeding physical capacity), and finds orphaned VDIs
(no VBD attaching them to any VM) with their reclaimable size.

Write: ``rescan_sr`` (low risk — a metadata refresh, no data change).

PREVIEW: mock-validated only — verify field/action names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.governance import opt_str
from xcpng_aiops.ops._util import (
    ANALYSIS_LIST_LIMIT,
    DEFAULT_LIST_LIMIT,
    as_list,
    paged,
    pct,
    s,
)

SR_FIELDS = "uuid,name_label,SR_type,content_type,shared,size,physical_usage,usage,$pool"
VDI_FIELDS = "uuid,name_label,size,usage,$SR,$VBDs"

# ── Thresholds (named constants, tune per fleet) ────────────────────────────
SR_NEAR_FULL_PERCENT = 85.0  # physical usage at/above this = near-full
SR_CRITICAL_PERCENT = 95.0  # physical usage at/above this = critical
SR_OVERCOMMIT_RATIO = 1.0  # virtual allocation / capacity above this = overcommitted


def sr_summary(sr: dict) -> dict:
    """Reduce an SR record to a high-signal summary."""
    size = sr.get("size")
    physical = sr.get("physical_usage")
    return {
        "id": opt_str(sr.get("uuid"), 64),
        "name": opt_str(sr.get("name_label"), 128),
        "type": opt_str(sr.get("SR_type"), 32),
        "contentType": opt_str(sr.get("content_type"), 32),
        "shared": sr.get("shared"),
        "pool": opt_str(sr.get("$pool"), 64),
        "sizeBytes": size,
        "physicalUsageBytes": physical,
        "virtualAllocationBytes": sr.get("usage"),
        "usedPercent": pct(physical, size),
    }


def list_srs(conn: Any, pool: str | None = None, limit: int = DEFAULT_LIST_LIMIT) -> dict:
    """[READ] List SRs with capacity, physical usage, and virtual allocation.

    Returns ``{"srs": [...], "returned": N, "limit": L, "truncated": b}`` so a
    capped inventory read cannot be mistaken for the whole fleet.
    """
    rows = [sr_summary(x) for x in as_list(conn.get("/srs", params={"fields": SR_FIELDS}))]
    if pool:
        rows = [r for r in rows if r.get("pool") == pool]
    return paged("srs", rows, limit)


def get_sr(conn: Any, sr_id: str) -> dict:
    """[READ] Return detail for a single SR by uuid."""
    sr = conn.get(f"/srs/{_seg(sr_id)}")
    return sr_summary(sr) if isinstance(sr, dict) else {}


def list_vdis(
    conn: Any,
    sr: str | None = None,
    orphaned_only: bool = False,
    limit: int = DEFAULT_LIST_LIMIT,
) -> dict:
    """[READ] List VDIs (virtual disks), optionally per SR or orphaned-only.

    VDIs are the longest inventory in an XCP-ng fleet, so the result is a
    truncation-announcing envelope::

        {"vdis": [...], "returned": 200, "limit": 200, "truncated": true}
    """
    rows = []
    for vdi in as_list(conn.get("/vdis", params={"fields": VDI_FIELDS})):
        vbds = vdi.get("$VBDs") or []
        rows.append(
            {
                "id": opt_str(vdi.get("uuid"), 64),
                "name": opt_str(vdi.get("name_label"), 128),
                "sr": opt_str(vdi.get("$SR"), 64),
                "sizeBytes": vdi.get("size"),
                "usageBytes": vdi.get("usage"),
                "attached": len(vbds) > 0,
            }
        )
    if sr:
        rows = [r for r in rows if r.get("sr") == sr]
    if orphaned_only:
        rows = [r for r in rows if not r.get("attached")]
    return paged("vdis", rows, limit)


def sr_usage_rca(conn: Any) -> dict:
    """[READ][RCA] SR usage root-cause analysis: cause + action per finding.

    Findings: ``sr-critical`` / ``sr-near-full`` (physical usage), ``sr-
    overcommitted`` (thin-provision virtual allocation > capacity), and
    ``orphaned-vdis`` (unattached disks with reclaimable bytes, per SR).

    ``inputTruncated`` is true when the SR or VDI inventory this ran over was
    itself capped — the analysis is then over a subset, and says so.
    """
    sr_page = list_srs(conn, limit=ANALYSIS_LIST_LIMIT)
    vdi_page = list_vdis(conn, limit=ANALYSIS_LIST_LIMIT)
    srs = sr_page["srs"]
    vdis = vdi_page["vdis"]
    disk_srs = [x for x in srs if (x.get("contentType") or "") != "iso"]

    findings: list[dict] = []
    for sr in sorted(
        disk_srs, key=lambda x: x.get("usedPercent") or 0, reverse=True
    ):
        used = sr.get("usedPercent")
        if isinstance(used, (int, float)) and used >= SR_CRITICAL_PERCENT:
            findings.append(
                {
                    "sr": sr.get("name"),
                    "id": sr.get("id"),
                    "cause": "sr-critical",
                    "severity": "high",
                    "evidence": f"physical usage {used}% >= {SR_CRITICAL_PERCENT}%",
                    "action": "Free space NOW: delete orphaned VDIs and stale snapshots, "
                    "or migrate disks to another SR — a full SR halts its VMs.",
                }
            )
        elif isinstance(used, (int, float)) and used >= SR_NEAR_FULL_PERCENT:
            findings.append(
                {
                    "sr": sr.get("name"),
                    "id": sr.get("id"),
                    "cause": "sr-near-full",
                    "severity": "medium",
                    "evidence": f"physical usage {used}% >= {SR_NEAR_FULL_PERCENT}%",
                    "action": "Plan capacity: clean up snapshots/orphaned VDIs or extend "
                    "the SR before it reaches critical.",
                }
            )

        size = sr.get("sizeBytes")
        virtual = sr.get("virtualAllocationBytes")
        if (
            isinstance(size, (int, float))
            and size
            and isinstance(virtual, (int, float))
            and virtual / size > SR_OVERCOMMIT_RATIO
        ):
            ratio = round(virtual / size, 2)
            findings.append(
                {
                    "sr": sr.get("name"),
                    "id": sr.get("id"),
                    "cause": "sr-overcommitted",
                    "severity": "medium",
                    "evidence": f"thin-provision allocation {ratio}x capacity "
                    f"(virtual {virtual} / size {size})",
                    "action": "Overcommit is fine until guests fill their disks — watch "
                    "physical usage and keep headroom or rebalance disks across SRs.",
                }
            )

    orphaned = [v for v in vdis if not v.get("attached")]
    by_sr: dict[str, dict] = {}
    for v in orphaned:
        entry = by_sr.setdefault(v["sr"], {"count": 0, "reclaimableBytes": 0})
        entry["count"] += 1
        usage = v.get("usageBytes") or v.get("sizeBytes") or 0
        if isinstance(usage, (int, float)):
            entry["reclaimableBytes"] += int(usage)
    sr_names = {x.get("id"): x.get("name") for x in srs}
    for sr_id, entry in by_sr.items():
        findings.append(
            {
                "sr": sr_names.get(sr_id, sr_id),
                "id": sr_id,
                "cause": "orphaned-vdis",
                "severity": "low",
                "evidence": f"{entry['count']} unattached VDI(s), "
                f"~{entry['reclaimableBytes']} bytes reclaimable",
                "action": "Review with vdi_list(orphaned_only=true) and delete the ones "
                "no longer needed via the XO UI, then sr_rescan to refresh.",
            }
        )

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank.get(f["severity"], 3))
    # State the priority in the payload: a consumer — notably a smaller local
    # model — should not have to infer urgency from list position.
    findings = [{**f, "rank": i} for i, f in enumerate(findings, 1)]
    return {
        "srsAnalyzed": len(disk_srs),
        "vdisAnalyzed": len(vdis),
        "inputTruncated": bool(sr_page["truncated"] or vdi_page["truncated"]),
        "orphanedVdis": len(orphaned),
        "findings": findings,
        "healthy": not findings,
        "thresholds": {
            "nearFullPercent": SR_NEAR_FULL_PERCENT,
            "criticalPercent": SR_CRITICAL_PERCENT,
            "overcommitRatio": SR_OVERCOMMIT_RATIO,
        },
    }


def rescan_sr(conn: Any, sr_id: str) -> dict:
    """[WRITE] Rescan an SR (low risk — metadata refresh, no undo needed).

    XO names this action ``scan``, NOT ``rescan``: verified against a live XO
    REST API (XCP-ng 8.3, 2026-08-01) where ``.../actions/rescan`` returns 404
    ("Cannot POST") while ``.../actions/scan`` returns 202. The old path meant
    this write could never succeed against a real Xen Orchestra.
    """
    conn.post(f"/srs/{_seg(sr_id)}/actions/scan", params={"sync": "true"})
    return {"id": s(sr_id, 64), "action": "sr_rescan"}
