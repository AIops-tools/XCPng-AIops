"""``xcpng-aiops task ...`` sub-commands (reads)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from xcpng_aiops.cli._common import TargetOption, cli_errors, console, get_connection
from xcpng_aiops.ops import tasks

task_app = typer.Typer(help="XO task operations.", no_args_is_help=True)

StatusOption = Annotated[
    str | None, typer.Option("--status", help="Filter: pending / success / failure")
]


@task_app.command("list")
@cli_errors
def task_list(status: StatusOption = None, target: TargetOption = None) -> None:
    """List XO tasks, optionally filtered by status."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(tasks.list_tasks(conn, status)))
