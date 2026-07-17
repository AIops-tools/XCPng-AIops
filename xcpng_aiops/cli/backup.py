"""``xcpng-aiops backup ...`` sub-commands (reads + failure RCA)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from xcpng_aiops.cli._common import TargetOption, cli_errors, console, get_connection
from xcpng_aiops.ops import backups

backup_app = typer.Typer(help="XO backup job operations.", no_args_is_help=True)

LimitOption = Annotated[
    int, typer.Option("--limit", "-n", help="Max recent log entries to examine")
]


@backup_app.command("jobs")
@cli_errors
def backup_jobs(target: TargetOption = None) -> None:
    """List VM backup jobs (id, name, mode)."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(backups.list_backup_jobs(conn)))


@backup_app.command("logs")
@cli_errors
def backup_logs(limit: LimitOption = 50, target: TargetOption = None) -> None:
    """Recent backup run logs: status + failed-task messages."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(backups.list_backup_logs(conn, limit)))


@backup_app.command("failure-rca")
@cli_errors
def backup_failure_rca(limit: LimitOption = 50, target: TargetOption = None) -> None:
    """RCA: failed/skipped runs classified (vdi-chain, quiesce, transport, ...)."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(backups.backup_failure_rca(conn, limit)))
