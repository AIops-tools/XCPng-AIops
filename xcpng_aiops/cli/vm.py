"""``xcpng-aiops vm ...`` sub-commands (reads + governed lifecycle writes)."""

from __future__ import annotations

import json
from typing import Annotated

import typer

from mcp_server.tools import vm_actions as gov
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
from xcpng_aiops.ops import vm_rca, vms
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT

vm_app = typer.Typer(help="VM operations (via Xen Orchestra).", no_args_is_help=True)

PowerStateOption = Annotated[
    str | None, typer.Option("--state", help="Filter by power state (Running/Halted/...)")
]
PoolOption = Annotated[str | None, typer.Option("--pool", help="Filter by pool uuid")]
LimitOption = Annotated[
    int, typer.Option("--limit", "-n", help="Max rows to return (truncation is reported)")
]
ForceOption = Annotated[
    bool, typer.Option("--force", help="Hard power operation instead of clean (guest tools)")
]


@vm_app.command("list")
@cli_errors
def vm_list(
    state: PowerStateOption = None,
    pool: PoolOption = None,
    limit: LimitOption = DEFAULT_LIST_LIMIT,
    target: TargetOption = None,
) -> None:
    """List VMs with power state, host, guest-tools status, sizing."""
    conn, _ = get_connection(target)
    result = vms.list_vms(conn, state, pool, limit)
    console.print_json(json.dumps(result))
    print_truncation_note(result, "VMs")


@vm_app.command("get")
@cli_errors
def vm_get(vm_id: str, target: TargetOption = None) -> None:
    """Detail for one VM by uuid."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(vms.get_vm(conn, vm_id)))


@vm_app.command("stats")
@cli_errors
def vm_stats(
    vm_id: str,
    granularity: Annotated[
        str, typer.Option("--granularity", "-g", help="seconds/minutes/hours/days")
    ] = "seconds",
    target: TargetOption = None,
) -> None:
    """Recent CPU/memory stats for a VM (RRD-backed averages)."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(vms.vm_stats(conn, vm_id, granularity)))


@vm_app.command("health-rca")
@cli_errors
def vm_health_rca(
    vm_id: Annotated[str | None, typer.Argument(help="VM uuid (omit for whole fleet)")] = None,
    target: TargetOption = None,
) -> None:
    """RCA: unhealthy VMs — halted-unexpectedly, paused, tools missing, pressure."""
    conn, _ = get_connection(target)
    console.print_json(json.dumps(vm_rca.vm_health_rca(conn, vm_id)))


@vm_app.command("start")
@cli_errors
def vm_start(vm_id: str, target: TargetOption = None, dry_run: DryRunOption = False) -> None:
    """Start a VM (governed; inverse vm_stop is recorded)."""
    if dry_run:
        dry_run_print(
            operation="vm_start", api_call=f"POST /vms/{vm_id}/actions/start?sync=true"
        )
        return
    gov.vm_start(vm_id=vm_id, target=target)
    console.print(f"[green]Started VM {vm_id}[/]")


@vm_app.command("stop")
@cli_errors
def vm_stop(
    vm_id: str,
    force: ForceOption = False,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Stop a VM — clean shutdown, or hard with --force (double confirm)."""
    action = "hard_shutdown" if force else "clean_shutdown"
    if dry_run:
        dry_run_print(
            operation="vm_stop", api_call=f"POST /vms/{vm_id}/actions/{action}?sync=true"
        )
        return
    double_confirm("stop", f"VM {vm_id}")
    gov.vm_stop(vm_id=vm_id, force=force, target=target)
    console.print(f"[green]Stopped VM {vm_id} ({'hard' if force else 'clean'})[/]")


@vm_app.command("reboot")
@cli_errors
def vm_reboot(
    vm_id: str,
    force: ForceOption = False,
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Reboot a VM — clean, or hard with --force (double confirm, no undo)."""
    action = "hard_reboot" if force else "clean_reboot"
    if dry_run:
        dry_run_print(
            operation="vm_reboot", api_call=f"POST /vms/{vm_id}/actions/{action}?sync=true"
        )
        return
    double_confirm("reboot", f"VM {vm_id}")
    gov.vm_reboot(vm_id=vm_id, force=force, target=target)
    console.print(f"[green]Rebooted VM {vm_id} ({'hard' if force else 'clean'})[/]")


@vm_app.command("migrate")
@cli_errors
def vm_migrate(
    vm_id: str,
    host_id: Annotated[str, typer.Argument(help="Destination host uuid")],
    target: TargetOption = None,
    dry_run: DryRunOption = False,
) -> None:
    """Live-migrate a VM to another host (double confirm; undo = migrate back)."""
    if dry_run:
        dry_run_print(
            operation="vm_migrate",
            api_call=f"POST /vms/{vm_id}/actions/migrate?sync=true",
            parameters={"host": host_id},
        )
        return
    double_confirm("migrate", f"VM {vm_id} → host {host_id}")
    gov.vm_migrate(vm_id=vm_id, host_id=host_id, target=target)
    console.print(f"[green]Migrated VM {vm_id} to host {host_id}[/]")
