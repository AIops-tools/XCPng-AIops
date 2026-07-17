"""``xcpng-aiops pool ...`` sub-commands (reads + posture RCA)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from xcpng_aiops.cli._common import TargetOption, cli_errors, console, get_connection
from xcpng_aiops.ops import pools

pool_app = typer.Typer(help="Pool operations (via Xen Orchestra).", no_args_is_help=True)


@pool_app.command("list")
@cli_errors
def pool_list(target: TargetOption = None) -> None:
    """List XCP-ng pools with master, HA state, default SR."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(pools.list_pools(conn)))


@pool_app.command("get")
@cli_errors
def pool_get(pool_id: str, target: TargetOption = None) -> None:
    """Detail for one pool by uuid."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(pools.get_pool(conn, pool_id)))


@pool_app.command("posture")
@cli_errors
def pool_posture(
    pool_id: Annotated[
        str | None, typer.Argument(help="Pool uuid (omit for all pools)")
    ] = None,
    target: TargetOption = None,
) -> None:
    """RCA: patch & HA posture — missing patches, reboots pending, version skew, HA."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(pools.pool_patch_ha_posture(conn, pool_id)))
