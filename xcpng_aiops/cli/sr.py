"""``xcpng-aiops sr ...`` sub-commands (reads + usage RCA + rescan)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from mcp_server.tools import srs as gov
from xcpng_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    dry_run_print,
    get_connection,
)
from xcpng_aiops.ops import srs

sr_app = typer.Typer(
    help="Storage repository (SR) operations (via Xen Orchestra).", no_args_is_help=True
)

PoolOption = Annotated[str | None, typer.Option("--pool", help="Filter by pool uuid")]
SrOption = Annotated[str | None, typer.Option("--sr", help="Filter by SR uuid")]
OrphanedOption = Annotated[
    bool, typer.Option("--orphaned-only", help="Only VDIs attached to no VM")
]


@sr_app.command("list")
@cli_errors
def sr_list(pool: PoolOption = None, target: TargetOption = None) -> None:
    """List SRs with capacity, physical usage, virtual allocation."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(srs.list_srs(conn, pool)))


@sr_app.command("get")
@cli_errors
def sr_get(sr_id: str, target: TargetOption = None) -> None:
    """Detail for one SR by uuid."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(srs.get_sr(conn, sr_id)))


@sr_app.command("vdis")
@cli_errors
def sr_vdis(
    sr: SrOption = None, orphaned_only: OrphanedOption = False, target: TargetOption = None
) -> None:
    """List VDIs (virtual disks), optionally per SR or orphaned-only."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(srs.list_vdis(conn, sr, orphaned_only)))


@sr_app.command("usage-rca")
@cli_errors
def sr_usage_rca(target: TargetOption = None) -> None:
    """RCA: SRs near full ranked, thin-provision overcommit, orphaned VDIs."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(srs.sr_usage_rca(conn)))


@sr_app.command("rescan")
@cli_errors
def sr_rescan(sr_id: str, target: TargetOption = None, dry_run: DryRunOption = False) -> None:
    """Rescan an SR (low risk — metadata refresh, governed)."""
    if dry_run:
        dry_run_print(
            operation="sr_rescan", api_call=f"POST /srs/{sr_id}/actions/rescan?sync=true"
        )
        return
    gov.sr_rescan(sr_id=sr_id, target=target)
    console.print(f"[green]Rescanned SR {sr_id}[/]")
