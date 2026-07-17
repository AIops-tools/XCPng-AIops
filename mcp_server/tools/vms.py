"""VM read MCP tools: list / get / stats / health RCA."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import vm_rca as rca_ops
from xcpng_aiops.ops import vms as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def vm_list(
    power_state: Optional[str] = None,
    pool: Optional[str] = None,
    target: Optional[str] = None,
) -> list:
    """[READ] List VMs with power state, host, tools status, sizing.

    Args:
        power_state: Optional filter (Running / Halted / Paused / Suspended).
        pool: Optional pool uuid to filter by.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_vms(_get_connection(target), power_state, pool)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def vm_get(vm_id: str, target: Optional[str] = None) -> dict:
    """[READ] Detail for one VM by uuid (state, host, OS, tools, tags).

    Args:
        vm_id: VM uuid (see vm_list).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.get_vm(_get_connection(target), vm_id)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def vm_stats(vm_id: str, granularity: str = "seconds", target: Optional[str] = None) -> dict:
    """[READ] Recent CPU / memory stats for a VM (RRD-backed averages).

    Args:
        vm_id: VM uuid (see vm_list).
        granularity: seconds / minutes / hours / days (default seconds).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.vm_stats(_get_connection(target), vm_id, granularity)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def vm_health_rca(vm_id: Optional[str] = None, target: Optional[str] = None) -> dict:
    """[READ][RCA] VM health root-cause analysis — cause + action per finding.

    Flags VMs halted unexpectedly (auto-poweron / HA set), paused or suspended
    VMs, running VMs without guest tools, and CPU / memory pressure from recent
    stats. Analyze one VM (vm_id) or the whole fleet.

    Args:
        vm_id: Optional VM uuid to analyze just one VM.
        target: Xen Orchestra target name from config; omit for the default.
    """
    return rca_ops.vm_health_rca(_get_connection(target), vm_id)
