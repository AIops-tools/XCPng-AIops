"""VM snapshot MCP tools: list + create (medium) + delete / revert (high).

``snapshot_create`` passes an ``undo=`` callback so the harness records an
inverse ``snapshot_delete`` for the REAL snapshot id captured from the XO
response. ``snapshot_delete`` and ``snapshot_revert`` are irreversible
(``risk_level=high``) and declare no undo.
"""

from typing import Any, Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import snapshots as ops
from xcpng_aiops.ops import vms as vm_ops
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT

_SKILL = "xcpng-aiops"


def _create_undo(params: dict[str, Any], result: Any) -> Optional[dict]:
    if not isinstance(result, dict) or result.get("dryRun"):
        return None
    snapshot_id = result.get("id")
    if not snapshot_id:
        return None  # id not captured — an honest "no safe inverse"
    return {
        "tool": "snapshot_delete",
        "params": {"snapshot_id": snapshot_id},
        "skill": _SKILL,
        "note": "Inverse of snapshot_create: delete the just-created snapshot.",
    }


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def snapshot_list(
    vm_id: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
    target: Optional[str] = None,
) -> dict:
    """[READ] List VM snapshots, optionally filtered to one VM.

    Returns {"snapshots": [...], "returned": N, "limit": L, "truncated": bool}.
    When truncated is true there are more snapshots than were returned.

    Args:
        vm_id: Optional VM uuid to filter (see vm_list).
        limit: Max snapshots to return after filtering (default 200).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return vm_ops.list_vm_snapshots(_get_connection(target), vm_id, limit)


@mcp.tool()
@governed_tool(risk_level="medium", undo=_create_undo)
@tool_errors("dict")
def snapshot_create(
    vm_id: str, name: str, dry_run: bool = False, target: Optional[str] = None
) -> dict:
    """[WRITE][risk=medium] Snapshot a VM. Inverse: delete THAT snapshot.

    The created snapshot's REAL id is captured from the XO response, so the
    recorded undo (snapshot_delete) is replayable.

    Args:
        vm_id: VM uuid to snapshot (see vm_list).
        name: Snapshot name (e.g. 'pre-change-2026-07-17').
        dry_run: If True, preview without snapshotting (no undo recorded).
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldSnapshot": {"vm_id": vm_id, "name": name}}
    return ops.create_snapshot(_get_connection(target), vm_id, name)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def snapshot_delete(snapshot_id: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=high] Delete a VM snapshot by uuid. IRREVERSIBLE.

    Captures the snapshot's prior state (name / time / parent VM) for the audit
    record; declares no undo.

    Args:
        snapshot_id: Snapshot uuid (see snapshot_list).
        dry_run: If True, preview without deleting.
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldDelete": {"snapshot_id": snapshot_id}}
    return ops.delete_snapshot(_get_connection(target), snapshot_id)


@mcp.tool()
@governed_tool(risk_level="high")
@tool_errors("dict")
def snapshot_revert(snapshot_id: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=high] Revert a VM to a snapshot. IRREVERSIBLE.

    The VM's CURRENT state is replaced by the snapshot — take a fresh snapshot
    first (snapshot_create) if you may need to come back. Captures the
    snapshot's state for the audit record; declares no undo.

    Args:
        snapshot_id: Snapshot uuid to revert to (see snapshot_list).
        dry_run: If True, preview without reverting.
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldRevert": {"snapshot_id": snapshot_id}}
    return ops.revert_snapshot(_get_connection(target), snapshot_id)
