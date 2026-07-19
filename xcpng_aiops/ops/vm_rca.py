"""Flagship RCA: VM health — cause + action for unhealthy VMs.

Findings produced (each with cause, severity, evidence, action):

  * ``halted-unexpectedly`` — a Halted VM that is marked auto-poweron or has an
    HA restart priority (it was expected to be running).
  * ``paused`` — a Paused VM (consumes memory, does no work).
  * ``suspended`` — a Suspended VM parked on disk.
  * ``guest-tools-missing`` — a Running VM without the management agent / PV
    drivers (no graceful shutdown, no memory stats, no live migration safety).
  * ``cpu-pressure`` / ``memory-pressure`` — from recent RRD stats on Running
    VMs (stats are fetched for at most ``_STATS_VM_CAP`` VMs unless a single
    ``vm_id`` is analyzed).

PREVIEW: thresholds are named constants below; mock-validated only.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.ops import vms as vm_ops
from xcpng_aiops.ops._util import ANALYSIS_LIST_LIMIT, s

# ── Thresholds (named constants, tune per fleet) ────────────────────────────
CPU_PRESSURE_PERCENT = 90.0  # avg CPU at/above this = cpu-pressure
MEMORY_PRESSURE_USED_PERCENT = 90.0  # memory used at/above this = memory-pressure
_STATS_VM_CAP = 5  # max Running VMs to pull RRD stats for in a fleet-wide RCA


def _finding(vm: dict, cause: str, severity: str, evidence: str, action: str) -> dict:
    return {
        "vm": vm.get("name"),
        "id": vm.get("id"),
        "cause": cause,
        "severity": severity,
        "evidence": s(evidence, 300),
        "action": s(action, 300),
    }


def _state_findings(vm: dict) -> list[dict]:
    """Power-state and guest-tools findings for one VM summary."""
    findings: list[dict] = []
    state = (vm.get("powerState") or "").lower()
    expected_running = bool(vm.get("autoPoweron")) or bool(vm.get("haRestartPriority"))

    if state == "halted" and expected_running:
        findings.append(
            _finding(
                vm,
                "halted-unexpectedly",
                "high",
                f"power_state=Halted but auto_poweron={vm.get('autoPoweron')} "
                f"ha={vm.get('haRestartPriority') or 'none'}",
                "Check host/pool events for the shutdown reason, then start the VM "
                "(vm_start). If HA was expected to restart it, verify pool HA state "
                "(pool_patch_ha_posture).",
            )
        )
    elif state == "paused":
        findings.append(
            _finding(
                vm,
                "paused",
                "medium",
                "power_state=Paused — the VM holds memory but executes nothing",
                "Unpause from the XO UI, or stop/start it (vm_stop / vm_start) if the "
                "pause was unintended.",
            )
        )
    elif state == "suspended":
        findings.append(
            _finding(
                vm,
                "suspended",
                "low",
                "power_state=Suspended — VM state parked on storage",
                "Resume it from the XO UI when needed, or vm_start to boot fresh.",
            )
        )

    if state == "running" and vm.get("guestToolsDetected") is False:
        findings.append(
            _finding(
                vm,
                "guest-tools-missing",
                "medium",
                "Running with no management agent / PV drivers detected",
                "Install the XCP-ng guest tools in the guest OS — without them there "
                "is no clean shutdown, no memory reporting, and migrations are riskier.",
            )
        )
    return findings


def _pressure_findings(conn: Any, vm: dict) -> list[dict]:
    """CPU/memory pressure findings from recent RRD stats (best-effort)."""
    try:
        stats = vm_ops.vm_stats(conn, vm["id"])
    except Exception:  # noqa: BLE001 — stats are advisory; never sink the RCA
        return []
    findings: list[dict] = []
    cpu = stats.get("cpuAvgPercent")
    mem = stats.get("memoryUsedPercent")
    if isinstance(cpu, (int, float)) and cpu >= CPU_PRESSURE_PERCENT:
        findings.append(
            _finding(
                vm,
                "cpu-pressure",
                "medium",
                f"avg CPU {cpu}% >= {CPU_PRESSURE_PERCENT}% over recent samples",
                "Identify the hot process in-guest; add vCPUs or migrate the VM to a "
                "less loaded host (vm_migrate).",
            )
        )
    if isinstance(mem, (int, float)) and mem >= MEMORY_PRESSURE_USED_PERCENT:
        findings.append(
            _finding(
                vm,
                "memory-pressure",
                "medium",
                f"memory used {mem}% >= {MEMORY_PRESSURE_USED_PERCENT}%",
                "Increase the VM's memory allocation (needs guest tools + possibly a "
                "restart) or reduce in-guest memory consumers.",
            )
        )
    return findings


def vm_health_rca(conn: Any, vm_id: str | None = None) -> dict:
    """[READ][RCA] VM health root-cause analysis: cause + action per finding.

    Analyzes one VM (``vm_id``) or the whole fleet. Stats-based pressure checks
    are capped at ``_STATS_VM_CAP`` Running VMs in fleet mode.
    ``inputTruncated`` is true when the fleet listing itself was capped — the
    analysis then covers only that subset.
    """
    input_truncated = False
    if vm_id:
        vm = vm_ops.get_vm(conn, vm_id)
        vms = [vm] if vm else []
    else:
        page = vm_ops.list_vms(conn, limit=ANALYSIS_LIST_LIMIT)
        vms = page["vms"]
        input_truncated = page["truncated"]

    findings: list[dict] = []
    stats_budget = len(vms) if vm_id else _STATS_VM_CAP
    for vm in vms:
        findings.extend(_state_findings(vm))
        if (vm.get("powerState") or "").lower() == "running" and stats_budget > 0:
            findings.extend(_pressure_findings(conn, vm))
            stats_budget -= 1

    severity_rank = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: severity_rank.get(f["severity"], 3))
    # State the priority in the payload: a consumer — notably a smaller local
    # model — should not have to infer urgency from list position.
    findings = [{**f, "rank": i} for i, f in enumerate(findings, 1)]
    return {
        "vmsAnalyzed": len(vms),
        "inputTruncated": input_truncated,
        "findings": findings,
        "healthy": not findings,
        "thresholds": {
            "cpuPressurePercent": CPU_PRESSURE_PERCENT,
            "memoryPressureUsedPercent": MEMORY_PRESSURE_USED_PERCENT,
            "statsVmCap": _STATS_VM_CAP,
        },
    }
