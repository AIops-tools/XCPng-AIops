"""``xcpng-aiops host ...`` sub-commands (reads)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from xcpng_aiops.cli._common import TargetOption, cli_errors, console, get_connection
from xcpng_aiops.ops import hosts

host_app = typer.Typer(help="Host operations (via Xen Orchestra).", no_args_is_help=True)

PoolOption = Annotated[str | None, typer.Option("--pool", help="Filter by pool uuid")]


@host_app.command("list")
@cli_errors
def host_list(pool: PoolOption = None, target: TargetOption = None) -> None:
    """List hosts: version, state, memory usage, resident VM count."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(hosts.list_hosts(conn, pool)))


@host_app.command("get")
@cli_errors
def host_get(host_id: str, target: TargetOption = None) -> None:
    """Detail for one host by uuid."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(hosts.get_host(conn, host_id)))


@host_app.command("missing-patches")
@cli_errors
def host_missing_patches(host_id: str, target: TargetOption = None) -> None:
    """List missing patches for one host (empty when fully patched)."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(hosts.missing_patches(conn, host_id)))
