"""Backup MCP tools: job list / log list / failure RCA."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import backups as ops


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def backup_job_list(target: Optional[str] = None) -> list:
    """[READ] List VM backup jobs (id, name, mode).

    Args:
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_backup_jobs(_get_connection(target))


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("list")
def backup_log_list(limit: int = 50, target: Optional[str] = None) -> list:
    """[READ] Recent backup run logs: status + failed-task messages.

    Args:
        limit: Max recent log entries to return (default 50).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_backup_logs(_get_connection(target), limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def backup_failure_rca(limit: int = 50, target: Optional[str] = None) -> dict:
    """[READ][RCA] Classify failed / skipped backup runs — cause + action per job.

    Groups recent run failures by job and classifies them: vdi-chain (coalesce
    not finished), quiesce (guest VSS), transport (remote unreachable),
    storage-full, or unknown (with sample messages for triage).

    Args:
        limit: Max recent log entries to examine (default 50).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.backup_failure_rca(_get_connection(target), limit)
