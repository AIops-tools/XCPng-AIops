"""Backup MCP tools: job list / log list / failure RCA."""

from typing import Optional

from mcp_server._shared import _get_connection, mcp, tool_errors
from xcpng_aiops.governance import governed_tool
from xcpng_aiops.ops import backups as ops
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def backup_job_list(limit: int = DEFAULT_LIST_LIMIT, target: Optional[str] = None) -> dict:
    """[READ] List VM backup jobs (id, name, mode).

    Returns {"jobs": [...], "returned": N, "limit": L, "truncated": bool}.
    When truncated is true there are more jobs than were returned.

    Args:
        limit: Max jobs to return (default 200).
        target: Xen Orchestra target name from config; omit for the default.
    """
    return ops.list_backup_jobs(_get_connection(target), limit)


@mcp.tool()
@governed_tool(risk_level="low")
@tool_errors("dict")
def backup_log_list(limit: int = 50, target: Optional[str] = None) -> dict:
    """[READ] Recent backup run logs: status + failed-task messages.

    Returns {"logs": [...], "returned": N, "limit": L, "truncated": bool}.
    Truncation is measured (one extra record is requested), so a true value
    means there really are older runs — re-run with a higher limit.

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
