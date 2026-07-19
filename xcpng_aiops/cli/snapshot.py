"""``xcpng-aiops snapshot ...`` sub-commands (governed VM snapshot writes)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from mcp_server.tools import snapshots as gov
from xcpng_aiops.cli._common import (
    DryRunOption,
    TargetOption,
    cli_errors,
    console,
    double_confirm,
    dry_run_print,
    get_connection,
    print_truncation_note,
)
from xcpng_aiops.ops import vms
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT

snapshot_app = typer.Typer(help="VM snapshot operations.", no_args_is_help=True)

VmOption = Annotated[str | None, typer.Option("--vm", help="Filter to one VM uuid")]
LimitOption = Annotated[
    int, typer.Option("--limit", "-n", help="Max rows to return (truncation is reported)")
]



@snapshot_app.command("list")
@cli_errors
def snapshot_list(
    vm: VmOption = None,
    limit: LimitOption = DEFAULT_LIST_LIMIT,
    target: TargetOption = None,
) -> None:
    """List VM snapshots, optionally filtered to one VM."""
    conn, _ = get_connection(target)
    result = vms.list_vm_snapshots(conn, vm, limit)
    console.print_json(json.dumps(result))
    print_truncation_note(result, "snapshots")


@snapshot_app.command("create")
@cli_errors
def snapshot_create(
    vm_id: str, name: str, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Snapshot a VM (governed; inverse delete of THAT snapshot is recorded)."""
    if dry_run:
        dry_run_print(
            operation="snapshot_create",
            api_call=f"POST /vms/{vm_id}/actions/snapshot?sync=true",
            parameters={"name_label": name},
        )
        return
    result = gov.snapshot_create(vm_id=vm_id, name=name, target=target)
    snap_id = result.get("id") if isinstance(result, dict) else ""
    console.print(f"[green]Created snapshot '{name}' of VM {vm_id} (id: {snap_id})[/]")


@snapshot_app.command("delete")
@cli_errors
def snapshot_delete(
    snapshot_id: str, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Delete a VM snapshot by uuid (IRREVERSIBLE — double confirm)."""
    if dry_run:
        dry_run_print(
            operation="snapshot_delete",
            api_call=f"DELETE /vm-snapshots/{snapshot_id}",
        )
        return
    double_confirm("delete", f"snapshot {snapshot_id}")
    gov.snapshot_delete(snapshot_id=snapshot_id, target=target)
    console.print(f"[green]Deleted snapshot {snapshot_id}[/]")


@snapshot_app.command("revert")
@cli_errors
def snapshot_revert(
    snapshot_id: str, target: TargetOption = None, dry_run: DryRunOption = False
) -> None:
    """Revert a VM to a snapshot (IRREVERSIBLE — replaces current state)."""
    if dry_run:
        dry_run_print(
            operation="snapshot_revert",
            api_call=f"POST /vm-snapshots/{snapshot_id}/actions/revert?sync=true",
        )
        return
    double_confirm("revert to", f"snapshot {snapshot_id}")
    gov.snapshot_revert(snapshot_id=snapshot_id, target=target)
    console.print(f"[green]Reverted to snapshot {snapshot_id}[/]")
