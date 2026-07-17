"""Host read MCP tools: list / get."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import hosts as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def host_list(pool: Optional[str] = None, target: Optional[str] = None) -> list:
    """[READ] List hosts: version, state, memory usage, resident VM count.

    Args:
        pool: Optional pool uuid to filter by.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_hosts(_get_connection(target), pool)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def host_get(host_id: str, target: Optional[str] = None) -> dict:
    """[READ] Detail for one host by uuid (version, build, memory, VMs).

    Args:
        host_id: Host uuid (see host_list).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.get_host(_get_connection(target), host_id)
