"""Storage repository MCP tools: list / get / VDIs / usage RCA / rescan."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import srs as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def sr_list(pool: Optional[str] = None, target: Optional[str] = None) -> list:
    """[READ] List SRs with capacity, physical usage, virtual allocation.

    Args:
        pool: Optional pool uuid to filter by.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_srs(_get_connection(target), pool)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sr_get(sr_id: str, target: Optional[str] = None) -> dict:
    """[READ] Detail for one SR by uuid.

    Args:
        sr_id: SR uuid (see sr_list).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.get_sr(_get_connection(target), sr_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def vdi_list(
    sr: Optional[str] = None,
    orphaned_only: bool = False,
    target: Optional[str] = None,
) -> list:
    """[READ] List VDIs (virtual disks), optionally per SR or orphaned-only.

    Orphaned = attached to no VM (no VBD) — candidates for reclaiming space.

    Args:
        sr: Optional SR uuid to filter by.
        orphaned_only: Only VDIs not attached to any VM.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_vdis(_get_connection(target), sr, orphaned_only)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sr_usage_rca(target: Optional[str] = None) -> dict:
    """[READ][RCA] SR usage root-cause analysis — cause + action per finding.

    Ranks SRs by physical fullness (near-full / critical), flags thin-provision
    overcommit (virtual allocation > capacity), and totals orphaned VDIs with
    reclaimable bytes per SR.

    Args:
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.sr_usage_rca(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def sr_rescan(sr_id: str, dry_run: bool = False, target: Optional[str] = None) -> dict:
    """[WRITE][risk=low] Rescan an SR (metadata refresh — no data change, no undo).

    Args:
        sr_id: SR uuid (see sr_list).
        dry_run: If True, preview without rescanning.
        target: Xen Orchestra target name from config; omit for the default.
    """
    if dry_run:
        return {"dryRun": True, "wouldRescan": {"sr_id": sr_id}}
    return ops.rescan_sr(_get_connection(target), sr_id)
