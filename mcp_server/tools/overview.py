"""Overview MCP tool: one-shot fleet health summary."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import overview as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def overview(target: Optional[str] = None) -> dict:
    """[READ] One-shot health summary: pools, hosts, VMs, SRs, recent backups.

    Start any triage here — it fans out over the other read ops (best-effort,
    a failing collection reports an error block instead of blanking the rest).

    Args:
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.health_overview(_get_connection(target))
