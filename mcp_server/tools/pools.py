"""Pool MCP tools: list / get / patch & HA posture RCA."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import pools as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def pool_list(target: Optional[str] = None) -> list:
    """[READ] List XCP-ng pools with master, HA state, default SR.

    Args:
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_pools(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pool_get(pool_id: str, target: Optional[str] = None) -> dict:
    """[READ] Detail for one pool by uuid.

    Args:
        pool_id: Pool uuid (see pool_list).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.get_pool(_get_connection(target), pool_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def pool_patch_ha_posture(pool_id: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ][RCA] Patch & HA posture per pool — cause + action per finding.

    Flags hosts missing patches, hosts pending a reboot, version skew across a
    pool's hosts (breaks live migration / rolling updates), and multi-host
    pools running without HA.

    Args:
        pool_id: Optional pool uuid to analyze just one pool.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.pool_patch_ha_posture(_get_connection(target), pool_id)
