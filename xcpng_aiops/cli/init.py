"""``xcpng-aiops init`` — a friendly, interactive onboarding wizard.

Walks a new user through connecting their first Xen Orchestra target: collects
the non-secret connection details into ``config.yaml`` and the XO
authentication token into the *encrypted* store (never plaintext on disk).
Designed to be run on a terminal; everything it needs is prompted with
sensible defaults.

XO is the management plane — the wizard asks for the XO web URL (the address
the XO UI is served from), never for individual XCP-ng host addresses.
"""

from __future__ import annotations

import getpass

import typer
import yaml

from xcpng_aiops.cli._common import cli_errors, console
from xcpng_aiops.config import CONFIG_DIR, CONFIG_FILE, DEFAULT_API_PATH
from xcpng_aiops.secretstore import SecretStore, resolve_master_password


def _load_existing_targets() -> list[dict]:
    if not CONFIG_FILE.exists():
        return []
    raw = yaml.safe_load(CONFIG_FILE.read_text("utf-8")) or {}
    return list(raw.get("targets", []))


def _write_targets(targets: list[dict]) -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        CONFIG_DIR.chmod(0o700)
    except OSError:
        pass
    CONFIG_FILE.write_text(yaml.safe_dump({"targets": targets}, sort_keys=False), "utf-8")


@cli_errors
def init_cmd() -> None:
    """Interactively set up your first Xen Orchestra connection."""
    console.print("[bold cyan]XCP-ng AIops — setup wizard[/]")
    console.print(
        "This connects to your [bold]Xen Orchestra[/] instance (the management "
        "plane for your XCP-ng pools). It collects connection details (saved to "
        "config.yaml) and your XO authentication token (saved [bold]encrypted[/] "
        "to secrets.enc).\n"
    )

    console.print("[bold]Step 1 — master password[/]")
    console.print(
        "[dim]Encrypts secrets.enc. You'll set it via the "
        "XCPNG_AIOPS_MASTER_PASSWORD env var for non-interactive/MCP use.[/]"
    )
    password = resolve_master_password(confirm_if_new=True)
    store = SecretStore.unlock(password)

    targets = _load_existing_targets()
    existing_names = {t.get("name") for t in targets}

    while True:
        console.print("\n[bold]Step 2 — add a Xen Orchestra target[/]")
        name = typer.prompt("Target name (e.g. xo1)").strip()
        if name in existing_names:
            if not typer.confirm(f"'{name}' already exists — overwrite?", default=False):
                continue
            targets = [t for t in targets if t.get("name") != name]

        url = typer.prompt(
            "Xen Orchestra URL (e.g. https://xo.example.com)"
        ).strip().rstrip("/")
        console.print("[dim]Lab/self-signed certificate setups can answer No here.[/]")
        verify_ssl = typer.confirm(
            "Verify TLS certificate? (No for self-signed lab certs)", default=True
        )

        console.print(
            "[dim]Create a token in the XO UI: user menu → Personal tokens "
            "(or `xo-cli --createToken`). Paste it below (input hidden).[/]"
        )
        secret = getpass.getpass(f"XO authentication token for '{name}' (hidden): ")
        store = store.set(name, secret)

        console.print(
            "\n[dim]Xen Orchestra is often a VM on a pool it manages. If it is, "
            "stopping that VM kills XO mid-call and recovery needs console access "
            "(`xe vm-start`). XO's API cannot tell us which VM it runs on, so "
            "declare it here and vm_stop will refuse exactly that uuid. Find it in "
            "the XO UI (the XO VM's Advanced tab) or with `xe vm-list`.[/]"
        )
        self_vm = typer.prompt(
            "UUID of the VM running Xen Orchestra (blank if XO is not on this pool)",
            default="",
            show_default=False,
        ).strip()

        entry = {
            "name": name,
            "url": url,
            "verify_ssl": verify_ssl,
            "api_path": DEFAULT_API_PATH,
        }
        if self_vm:
            entry["xo_self_vm_uuid"] = self_vm
        targets.append(entry)
        existing_names.add(name)
        _write_targets(targets)
        console.print(f"[green]✓ Saved target '{name}' (token stored encrypted).[/]")

        if not typer.confirm("\nAdd another target?", default=False):
            break

    console.print(f"\n[green]✓ Setup complete.[/] Config: {CONFIG_FILE}")
    console.print(
        "[dim]Tip: export XCPNG_AIOPS_MASTER_PASSWORD=... in your shell profile "
        "so the MCP server and CLI can unlock secrets non-interactively.[/]"
    )
    if typer.confirm("Run a connectivity check now (xcpng-aiops doctor)?", default=True):
        from xcpng_aiops.doctor import run_doctor

        raise typer.Exit(run_doctor())
