"""Task read MCP tools."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import tasks as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def task_list(status: Optional[str] = None, target: Optional[str] = None) -> list:
    """[READ] List XO tasks, optionally filtered by status.

    Args:
        status: Optional filter: pending / success / failure.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_tasks(_get_connection(target), status)
