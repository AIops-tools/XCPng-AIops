"""``xcpng-aiops task ...`` sub-commands (reads)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from xcpng_aiops.cli._common import (
    TargetOption,
    cli_errors,
    console,
    get_connection,
    print_truncation_note,
)
from xcpng_aiops.ops import tasks
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT

task_app = typer.Typer(help="XO task operations.", no_args_is_help=True)

StatusOption = Annotated[
    str | None, typer.Option("--status", help="Filter: pending / success / failure")
]
LimitOption = Annotated[
    int, typer.Option("--limit", "-n", help="Max rows to return (truncation is reported)")
]



@task_app.command("list")
@cli_errors
def task_list(
    status: StatusOption = None,
    limit: LimitOption = DEFAULT_LIST_LIMIT,
    target: TargetOption = None,
) -> None:
    """List XO tasks, optionally filtered by status."""
    conn, _ = get_connection(target)
    result = tasks.list_tasks(conn, status, limit)
    console.print_json(json.dumps(result))
    print_truncation_note(result, "tasks")
