"""VM lifecycle write MCP tools: start / stop / reboot / migrate.

Undo pairs: ``vm_start`` ↔ ``vm_stop``; ``vm_migrate`` records migrating back
to the REAL source host captured before the move — from the result normally, or
from the harness's ``priorState`` when the response was lost. ``vm_reboot`` has
no clean inverse (prior power state is captured for the audit record only). All
writes take a ``dry_run`` preview — no write call, no undo recorded (the undo
callbacks explicitly skip dry-run results); ``vm_stop``'s preview does one read
to compute its self-VM hint.
"""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import vm_actions as ops

_SKILL = "xcpng-aiops"


# ── undo descriptors ─────────────────────────────────────────────────────────


def _start_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if not isinstance(result, dict) or result.get("dryRun"):
        return None
    return {
        "tool": "vm_stop",
        "params": {"vm_id": params.get("vm_id")},
        "skill": _SKILL,
        "note": "Inverse of vm_start: cleanly shut the VM down again.",
    }


def _stop_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if not isinstance(result, dict) or result.get("dryRun"):
        return None
    if (result.get("priorPowerState") or "").lower() not in ("running", ""):
        return None  # it was not running before; starting it back is not an inverse
    return {
        "tool": "vm_start",
        "params": {"vm_id": params.get("vm_id")},
        "skill": _SKILL,
        "note": "Inverse of vm_stop: start the VM again.",
    }


def _migrate_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    """Inverse of a migration: move the VM back to where it actually was.

    Reads the source host from two shapes, because a lost response is precisely
    when the undo matters most. Normally it rides the returned result; when the
    response never came back the harness hands over what ``migrate_vm`` stashed
    with ``capture_prior_state`` instead, under ``priorState``.
    """
    if not isinstance(result, dict) or result.get("dryRun"):
        return None
    prior = result.get("priorState")
    source = prior.get("sourceHost") if isinstance(prior, dict) else None
    source = source or result.get("sourceHost")
    if not source:
        return None  # no captured source host — an honest "no safe inverse"
    return {
        "tool": "vm_migrate",
        "params": {"vm_id": params.get("vm_id"), "host_id": source},
        "skill": _SKILL,
        "note": "Inverse of vm_migrate: migrate the VM back to its captured source host.",
    }


# ── tools ────────────────────────────────────────────────────────────────────


@mcp.tool()
@governed_tool(risk_level="medium", undo=_start_undo)
@tool_errors("dict")
def vm_start(vm_id: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=medium] Start a VM. Inverse: vm_stop.

    Args:
        vm_id: VM uuid (see vm_list).
        dry_run: If True, preview without starting (no undo recorded).
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldStart": {"vm_id": vm_id}}
    return ops.start_vm(_get_connection(target), vm_id)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_stop_undo)
@tool_errors("dict")
def vm_stop(
    vm_id: str, force: bool = False, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Stop a VM (clean shutdown; hard with force). Inverse: vm_start.

    A clean shutdown needs the guest tools running; force maps to a hard
    power-off. Captures the prior power state.

    Refuses the VM declared as running Xen Orchestra (xo_self_vm_uuid on the
    target) — stopping XO removes the API vm_start would travel over, so
    recovery needs hypervisor console access. dry_run refuses it too: a preview
    that returns green for a call that will be refused is a wrong preview. That
    guard is exact and opt-in: an undeclared target is refused nothing, on
    either path. The dry-run adds a weaker IP-based selfVmHint (null when there
    is none) that is a coincidence to check, never a verdict and never a block —
    XO's API exposes no self endpoint, so nothing here can be certain.

    Args:
        vm_id: VM uuid (see vm_list).
        force: Hard power-off instead of a clean guest shutdown.
        dry_run: If True, preview without stopping (no undo recorded).
        target: Xen Orchestra target name from config; omit for the default.
    """
    conn = _get_connection(target)
    # Before the dry-run return, not after: a preview whose true answer is
    # "this would be refused" must say so rather than hand back a green light.
    ops.refuse_if_declared_self(conn, vm_id)
    if dry_run:
        return {
            "dryRun": True,
            "wouldStop": {"vm_id": vm_id, "force": force},
            "selfVmHint": ops.self_vm_hint(conn, vm_id),
        }
    return ops.stop_vm(conn, vm_id, force)


@mcp.tool()
@governed_tool(risk_level="medium")
@tool_errors("dict")
def vm_reboot(
    vm_id: str, force: bool = False, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Reboot a VM (clean; hard with force). No undo.

    A reboot has no meaningful inverse — the prior power state is captured for
    the audit record only.

    Args:
        vm_id: VM uuid (see vm_list).
        force: Hard reboot instead of a clean guest reboot.
        dry_run: If True, preview without rebooting.
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldReboot": {"vm_id": vm_id, "force": force}}
    return ops.reboot_vm(_get_connection(target), vm_id, force)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_migrate_undo)
@tool_errors("dict")
def vm_migrate(
    vm_id: str, host_id: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Live-migrate a VM to another host. Inverse: migrate back.

    The REAL source host is captured BEFORE the move so the recorded undo
    (migrate back to it) is replayable.

    Args:
        vm_id: VM uuid (see vm_list).
        host_id: Destination host uuid (see host_list).
        dry_run: If True, preview without migrating (no undo recorded).
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldMigrate": {"vm_id": vm_id, "host_id": host_id}}
    return ops.migrate_vm(_get_connection(target), vm_id, host_id)
