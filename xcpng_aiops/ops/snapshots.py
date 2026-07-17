"""VM snapshot writes over the Xen Orchestra REST API.

Create maps to ``POST /vms/<id>/actions/snapshot?sync=true`` — XO returns the
NEW snapshot's id, which is captured for the undo descriptor (never guessed).
Delete maps to ``DELETE /vm-snapshots/<id>``; revert to
``POST /vm-snapshots/<id>/actions/revert``.

Reversibility:
  * ``create_snapshot`` (medium) — inverse is deleting THAT snapshot (the id
    comes from the XO response).
  * ``delete_snapshot`` (high) — irreversible; captures the snapshot's BEFORE
    state (name, snapshot_time, parent VM) for the audit record; no undo.
  * ``revert_snapshot`` (high) — irreversible (current disk state is replaced);
    captures the snapshot + parent VM state; no undo.

PREVIEW: mock-validated only — verify endpoint paths against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.connection import _seg
from xcpng_aiops.ops._util import s

_SYNC = {"sync": "true"}


def _snapshot_record(conn: Any, snapshot_id: str) -> dict:
    """Best-effort lookup of one snapshot record by id, or {} (advisory)."""
    try:
        snap = conn.get(f"/vm-snapshots/{_seg(snapshot_id)}")
        if isinstance(snap, dict):
            return {
                "id": s(snap.get("uuid"), 64),
                "name": s(snap.get("name_label"), 128),
                "snapshotTime": snap.get("snapshot_time"),
                "vm": s(snap.get("$snapshot_of"), 64),
            }
    except Exception:  # noqa: BLE001 — advisory context only
        pass
    return {}


def _extract_snapshot_id(result: Any) -> str:
    """Pull the new snapshot id out of XO's action response.

    With ``sync=true`` XO returns the created snapshot's id — either as a bare
    string, or as an object carrying ``uuid``/``id``.
    """
    if isinstance(result, str):
        # May be a bare id or an href like /rest/v0/vm-snapshots/<uuid>.
        return result.strip().strip('"').rstrip("/").rsplit("/", 1)[-1]
    if isinstance(result, dict):
        return str(result.get("uuid") or result.get("id") or "")
    return ""


def create_snapshot(conn: Any, vm_id: str, name: str) -> dict:
    """[WRITE] Snapshot a VM (medium). Inverse: delete THAT snapshot.

    The created snapshot's REAL id is captured from the XO response so the
    recorded undo (snapshot_delete) is replayable.
    """
    result = conn.post(
        f"/vms/{_seg(vm_id)}/actions/snapshot",
        params=_SYNC,
        json={"name_label": name},
    )
    snapshot_id = _extract_snapshot_id(result)
    return {
        "id": s(snapshot_id, 64),
        "vm": s(vm_id, 64),
        "name": s(name, 128),
        "action": "snapshot_create",
    }


def delete_snapshot(conn: Any, snapshot_id: str) -> dict:
    """[WRITE] Delete a VM snapshot by uuid (high, IRREVERSIBLE).

    Captures the snapshot's prior state (name/time/VM) for the audit record;
    declares no undo (a deleted snapshot cannot be reconstructed).
    """
    prior = _snapshot_record(conn, snapshot_id)
    conn.delete(f"/vm-snapshots/{_seg(snapshot_id)}")
    return {"id": s(snapshot_id, 64), "action": "snapshot_delete", "priorState": prior}


def revert_snapshot(conn: Any, snapshot_id: str) -> dict:
    """[WRITE] Revert a VM to a snapshot (high, IRREVERSIBLE).

    The VM's CURRENT disk/memory state is replaced by the snapshot — capture a
    fresh snapshot first if you may need to return. Records the snapshot's
    state and the parent VM for the audit record; declares no undo.
    """
    prior = _snapshot_record(conn, snapshot_id)
    conn.post(f"/vm-snapshots/{_seg(snapshot_id)}/actions/revert", params=_SYNC)
    return {"id": s(snapshot_id, 64), "action": "snapshot_revert", "priorState": prior}
