"""Task read MCP tools."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import tasks as ops
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def task_list(
    status: Optional[str] = None,
    limit: int = DEFAULT_LIST_LIMIT,
    target: Optional[str] = None,
) -> dict:
    """[READ] List XO tasks, optionally filtered by status.

    Returns {"tasks": [...], "returned": N, "limit": L, "truncated": bool}.
    When truncated is true the task feed had more entries than were returned —
    re-run with a higher limit or a narrower status filter.

    Args:
        status: Optional filter: pending / success / failure.
        limit: Max tasks to return after filtering (default 200).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_tasks(_get_connection(target), status, limit)
