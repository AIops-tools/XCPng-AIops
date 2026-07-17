"""VM lifecycle writes over the Xen Orchestra REST API (``/vms/<id>/actions/*``).

All actions are POSTed with ``sync=true`` so XO runs the action to completion
and returns the result inline (instead of a task href).

Reversibility:
  * ``start_vm`` (medium) — inverse is ``vm_stop`` (recorded by the MCP layer).
  * ``stop_vm`` (medium) — inverse is ``vm_start``.
  * ``reboot_vm`` (medium) — no clean inverse; captures prior power state only.
  * ``migrate_vm`` (medium) — inverse is migrating back to the captured source
    host (the REAL prior host, read before the move).

PREVIEW: mock-validated only — verify action names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.ops._util import s

_SYNC = {"sync": "true"}


def _power_state(conn: Any, vm_id: str) -> str:
    """Best-effort read of a VM's current power state (advisory context)."""
    try:
        vm = conn.get(f"/vms/{_seg(vm_id)}", params={"fields": "power_state"})
        if isinstance(vm, dict):
            return s(vm.get("power_state"), 32)
    except Exception:  # noqa: BLE001 — advisory context only
        pass
    return ""


def start_vm(conn: Any, vm_id: str) -> dict:
    """[WRITE] Start a VM (medium). Inverse: vm_stop."""
    prior = _power_state(conn, vm_id)
    conn.post(f"/vms/{_seg(vm_id)}/actions/start", params=_SYNC)
    return {"id": s(vm_id, 64), "action": "vm_start", "priorPowerState": prior}


def stop_vm(conn: Any, vm_id: str, force: bool = False) -> dict:
    """[WRITE] Stop a VM — clean shutdown, or hard when ``force`` (medium).

    Inverse: vm_start. A clean shutdown needs the guest tools; ``force`` maps
    to a hard power-off.
    """
    prior = _power_state(conn, vm_id)
    action = "hard_shutdown" if force else "clean_shutdown"
    conn.post(f"/vms/{_seg(vm_id)}/actions/{action}", params=_SYNC)
    return {
        "id": s(vm_id, 64),
        "action": "vm_stop",
        "mode": "hard" if force else "clean",
        "priorPowerState": prior,
    }


def reboot_vm(conn: Any, vm_id: str, force: bool = False) -> dict:
    """[WRITE] Reboot a VM — clean, or hard when ``force`` (medium, no undo)."""
    prior = _power_state(conn, vm_id)
    action = "hard_reboot" if force else "clean_reboot"
    conn.post(f"/vms/{_seg(vm_id)}/actions/{action}", params=_SYNC)
    return {
        "id": s(vm_id, 64),
        "action": "vm_reboot",
        "mode": "hard" if force else "clean",
        "priorPowerState": prior,
    }


def migrate_vm(conn: Any, vm_id: str, host_id: str) -> dict:
    """[WRITE] Live-migrate a VM to another host (medium).

    Captures the REAL source host (``$container``) BEFORE the move so the
    inverse (migrate back) is replayable.
    """
    source_host = ""
    try:
        vm = conn.get(f"/vms/{_seg(vm_id)}", params={"fields": "$container,power_state"})
        if isinstance(vm, dict):
            source_host = s(vm.get("$container"), 64)
    except Exception:  # noqa: BLE001 — advisory context only
        source_host = ""
    conn.post(
        f"/vms/{_seg(vm_id)}/actions/migrate",
        params=_SYNC,
        json={"host": host_id},
    )
    return {
        "id": s(vm_id, 64),
        "action": "vm_migrate",
        "destinationHost": s(host_id, 64),
        "sourceHost": source_host,
    }
