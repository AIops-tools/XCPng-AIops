"""VM lifecycle writes over the Xen Orchestra REST API (``/vms/<id>/actions/*``).

All actions are POSTed with ``sync=true`` so XO runs the action to completion
and returns the result inline (instead of a task href).

Reversibility:
  * ``start_vm`` (medium) — inverse is ``vm_stop`` (recorded by the MCP layer).
  * ``stop_vm`` (medium) — inverse is ``vm_start``.
  * ``reboot_vm`` (medium) — no clean inverse; captures prior power state only.
  * ``migrate_vm`` (medium) — inverse is migrating back to the captured source
    host (the REAL prior host, read before the move). That host is handed to the
    harness via ``capture_prior_state`` BEFORE the POST, so the inverse is
    recorded even when the response never arrives — a migration whose response
    is lost is exactly when knowing where the VM came from matters most.

**Stopping the VM that runs Xen Orchestra.** XO is commonly a VM on the very
pool it manages, and ``stop_vm`` on that uuid is one plain call: the
``sync=true`` POST never returns, because the process that would have answered
is gone, and recovery needs console access (``xe vm-start``). Detection is
honest about its limits and comes in two tiers:

  * **Tier 1 — exact, opt-in.** The operator declares ``xo_self_vm_uuid`` on the
    target (``xcpng-aiops init`` asks for it). When set, ``stop_vm`` refuses
    exactly that uuid (:class:`SelfLockout`). When unset there is NO guard — the
    tool fails open rather than guessing, because XO's REST API has no self
    endpoint and its static token carries no claims, so this genuinely cannot be
    discovered today.
  * **Tier 2 — a dry-run hint, never a block.** :func:`self_vm_hint` notices when
    a VM's reported IP equals the configured XO host. That is a coincidence
    worth mentioning, not evidence: it sees nothing without the guest agent, and
    it fires on every VM behind a shared proxy or NAT. It never blocks.

PREVIEW: mock-validated only — verify action names against a live XO.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from xcpng_aiops.connection import _seg
from xcpng_aiops.governance import capture_prior_state
from xcpng_aiops.ops._util import s

_SYNC = {"sync": "true"}


class SelfLockout(ValueError):  # noqa: N818 — teaching error, reads as a statement
    """Refused: the operation would stop the VM that runs this Xen Orchestra."""


def _power_state(conn: Any, vm_id: str) -> str:
    """Best-effort read of a VM's current power state (advisory context)."""
    try:
        vm = conn.get(f"/vms/{_seg(vm_id)}", params={"fields": "power_state"})
        if isinstance(vm, dict):
            return s(vm.get("power_state"), 32)
    except Exception:  # noqa: BLE001 — advisory context only
        pass
    return ""


def _declared_self_vm(conn: Any) -> str | None:
    """The operator-declared uuid of the VM running XO, or ``None``.

    ``None`` means "not declared", which is unknown — never "this is not it".
    There is deliberately no fallback: XO exposes no self endpoint, so a guess
    here would be a guess presented as a guarantee.
    """
    target = getattr(conn, "target", None)
    declared = str(getattr(target, "xo_self_vm_uuid", "") or "").strip()
    return declared or None


def _is_declared_self(conn: Any, vm_id: str) -> bool:
    """Exact (case-insensitive) match against the declared XO VM uuid."""
    declared = _declared_self_vm(conn)
    return bool(declared) and str(vm_id).strip().lower() == declared.lower()


def refuse_if_declared_self(conn: Any, vm_id: str) -> None:
    """Raise :class:`SelfLockout` when ``vm_id`` is the declared XO VM.

    Called by :func:`stop_vm` and, before the early return, by the dry-run paths
    — a preview whose real answer is "this would be refused" has to say so. The
    alternative is the trap this line designs against: a clean preview followed
    by a refusal reads to a model as a transient error worth retrying.

    Tier 1 only. The IP hint never routes through here: it is not certain enough
    to refuse on, and a guard that blocks on a coincidence is worse than none.
    """
    if not _is_declared_self(conn, vm_id):
        return
    target_name = getattr(getattr(conn, "target", None), "name", "?")
    raise SelfLockout(
        f"Refusing to stop VM '{vm_id}': it is declared as the VM running Xen "
        f"Orchestra ('xo_self_vm_uuid' on target '{target_name}'). Stopping it "
        f"kills the API this call is travelling over, so the inverse "
        f"(vm_start) could never be sent — recovery would need hypervisor "
        f"console access ('xe vm-start {vm_id}'). Stop XO from the host "
        f"instead, or correct 'xo_self_vm_uuid' in config.yaml if this is not "
        f"in fact the XO VM."
    )


def self_vm_hint(conn: Any, vm_id: str) -> str | None:
    """A dry-run coincidence worth mentioning, or ``None``. NEVER a verdict.

    Returns a note when the VM's reported IP equals the host in the configured
    XO URL — which *would* mean stopping it takes XO down with it. Deliberately
    advisory in both directions: the IP is only visible with the guest agent
    installed, so a ``None`` proves nothing; and every VM behind one reverse
    proxy or NAT reports the same address, so a hit proves nothing either. The
    text it returns says exactly that, and callers must not turn it into a
    block.

    For an actual guarantee, declare ``xo_self_vm_uuid`` on the target — that is
    what :func:`stop_vm` enforces.
    """
    target = getattr(conn, "target", None)
    xo_host = urlparse(str(getattr(target, "url", "") or "")).hostname
    if not xo_host:
        return None
    try:
        vm = conn.get(f"/vms/{_seg(vm_id)}", params={"fields": "mainIpAddress"})
    except Exception:  # noqa: BLE001 — a hint that cannot be computed is simply absent
        return None
    vm_ip = s(vm.get("mainIpAddress"), 64) if isinstance(vm, dict) else ""
    if not vm_ip or vm_ip.strip().lower() != str(xo_host).strip().lower():
        return None
    return (
        f"This VM reports IP {vm_ip}, the same address as the configured Xen "
        f"Orchestra URL. That MAY mean it is the VM running XO, in which case "
        f"stopping it kills XO mid-call and recovery needs console access "
        f"('xe vm-start'). It may equally be a coincidence — several VMs behind "
        f"one proxy or NAT share an address, and a VM without the guest agent "
        f"reports no IP at all. This is a hint, not a finding: confirm which VM "
        f"runs XO and set 'xo_self_vm_uuid' on the target to make it a refusal."
    )


def start_vm(conn: Any, vm_id: str) -> dict:
    """[WRITE] Start a VM (medium). Inverse: vm_stop."""
    prior = _power_state(conn, vm_id)
    conn.post(f"/vms/{_seg(vm_id)}/actions/start", params=_SYNC)
    return {"id": s(vm_id, 64), "action": "vm_start", "priorPowerState": prior}


def stop_vm(conn: Any, vm_id: str, force: bool = False) -> dict:
    """[WRITE] Stop a VM — clean shutdown, or hard when ``force`` (medium).

    Inverse: vm_start. A clean shutdown needs the guest tools; ``force`` maps
    to a hard power-off.

    **Refuses the VM declared as running Xen Orchestra** (``xo_self_vm_uuid`` on
    the target). Stopping XO is worse than irreversible — it removes the API the
    inverse would travel over, so ``vm_start`` cannot be sent at all and recovery
    drops to the hypervisor console (``xe vm-start``).

    That guard is EXACT and OPT-IN, and it FAILS OPEN: with no declared uuid, no
    VM is refused. XO's REST API has no self endpoint and its static token
    carries no claims, so the tool cannot work this out for itself — an
    undeclared target is unknown, and unknown must never be read as "it is me".
    Run ``xcpng-aiops init`` to declare it; until then ``dry_run`` surfaces a
    weaker, IP-based hint that never blocks.

    ``dry_run`` refuses on the same condition, via the same
    :func:`refuse_if_declared_self`, so a preview can never green-light a stop
    the real call rejects.
    """
    refuse_if_declared_self(conn, vm_id)
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
    inverse (migrate back) is replayable, and stashes it with
    ``capture_prior_state`` before issuing the POST. That second step is what
    keeps the inverse alive when the response is lost: the returned ``result``
    dies with the exception, but the harness still holds the source host and
    records the migrate-back (flagged ``effect_verified=False``).
    """
    source_host = ""
    try:
        vm = conn.get(f"/vms/{_seg(vm_id)}", params={"fields": "$container,power_state"})
        if isinstance(vm, dict):
            source_host = s(vm.get("$container"), 64)
    except Exception:  # noqa: BLE001 — advisory context only
        source_host = ""
    capture_prior_state({"sourceHost": source_host})
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
