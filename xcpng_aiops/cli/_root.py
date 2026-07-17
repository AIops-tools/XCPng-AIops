"""Top-level Typer app: assembles sub-apps and top-level commands."""

from __future__ import annotations

import typer

from xcpng_aiops.cli._common import cli_errors
from xcpng_aiops.cli.backup import backup_app
from xcpng_aiops.cli.doctor import doctor_cmd
from xcpng_aiops.cli.host import host_app
from xcpng_aiops.cli.init import init_cmd
from xcpng_aiops.cli.overview import overview_cmd
from xcpng_aiops.cli.pool import pool_app
from xcpng_aiops.cli.secret import secret_app
from xcpng_aiops.cli.snapshot import snapshot_app
from xcpng_aiops.cli.sr import sr_app
from xcpng_aiops.cli.task import task_app
from xcpng_aiops.cli.undo import undo_app
from xcpng_aiops.cli.vm import vm_app

app = typer.Typer(
    name="xcpng-aiops",
    help="XCP-ng AI-powered operations via Xen Orchestra.",
    no_args_is_help=True,
)

app.add_typer(vm_app, name="vm")
app.add_typer(host_app, name="host")
app.add_typer(pool_app, name="pool")
app.add_typer(sr_app, name="sr")
app.add_typer(snapshot_app, name="snapshot")
app.add_typer(backup_app, name="backup")
app.add_typer(task_app, name="task")
app.add_typer(secret_app, name="secret")
app.add_typer(undo_app, name="undo")
app.command("init")(init_cmd)
app.command("overview")(overview_cmd)
app.command("doctor")(doctor_cmd)


@app.command("mcp")
@cli_errors
def mcp_cmd() -> None:
    """Start the MCP server (stdio transport).

    Single-command entry point for MCP clients (does not go through uvx/PyPI
    resolution at launch):
        xcpng-aiops mcp
    """
    import sys

    if sys.version_info < (3, 11):
        typer.echo(
            f"ERROR: xcpng-aiops requires Python >= 3.11 "
            f"(got {sys.version_info.major}.{sys.version_info.minor}).\n"
            f"Fix: uv python install 3.12 && "
            f"uv tool install --python 3.12 --force xcpng-aiops",
            err=True,
        )
        raise typer.Exit(2)

    from mcp_server.server import main as _mcp_main

    _mcp_main()


if __name__ == "__main__":
    app()
