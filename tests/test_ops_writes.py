"""Write tools: outbound calls, prior-state capture, undo replayability, dry-run.

Everything runs against a MagicMock connection routed under the governed MCP
twins; the undo store is monkeypatched so descriptors can be captured and —
critically — REPLAYED back through the target tool to prove the recorded
params match its signature.
"""

from __future__ import annotations

import sqlite3
from unittest.mock import MagicMock

import pytest

import xcpng_aiops.governance.audit as audit_mod
import xcpng_aiops.governance.policy as policy_mod
import xcpng_aiops.governance.undo as undo_mod


@pytest.fixture(autouse=True)
def gov_home(tmp_path, monkeypatch):
    """Point the harness at a throwaway home so audit rows can be asserted.

    Autouse, not opt-in: every tool in this file is a GOVERNED write, so every
    one of them lands an audit row. Without the redirect they land in the
    developer's real ``~/.xcpng-aiops/audit.db`` — the suite quietly writes to
    the machine it runs on, and the rows it asserts on are polluted by whatever
    ran before. Tests that assert on the rows take the yielded path.
    """
    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()
    yield tmp_path
    audit_mod.reset_engine()
    policy_mod.reset_policy_engine()
    undo_mod.reset_undo_store()


def _audit_tools(db_path) -> list[str]:
    conn = sqlite3.connect(db_path)
    try:
        return [r[0] for r in conn.execute("SELECT tool FROM audit_log ORDER BY id")]
    finally:
        conn.close()


@pytest.fixture
def undo_recorder(monkeypatch):
    """Capture undo descriptors the harness would persist."""
    recorded: list[dict] = []

    class _Store:
        def record(self, *, skill, tool, undo_descriptor, orig_params, effect_verified=True):
            recorded.append(undo_descriptor)
            return f"undo-{len(recorded)}"

    monkeypatch.setattr(undo_mod, "get_undo_store", lambda: _Store())
    return recorded


@pytest.fixture
def vm_conn(monkeypatch):
    """Mocked connection routed under the governed vm_actions tools."""
    import mcp_server.tools.vm_actions as gov_vm

    conn = MagicMock(name="conn")
    conn.get.return_value = {"power_state": "Running", "$container": "host-src"}
    conn.post.return_value = {}
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    return conn


@pytest.fixture
def snap_conn(monkeypatch):
    """Mocked connection routed under the governed snapshot tools."""
    import mcp_server.tools.snapshots as gov_snap

    conn = MagicMock(name="conn")
    conn.get.return_value = {
        "uuid": "snap-1", "name_label": "pre-change",
        "snapshot_time": 1752700000, "$snapshot_of": "vm-1",
    }
    conn.post.return_value = "snap-1"
    conn.delete.return_value = True
    monkeypatch.setattr(gov_snap, "_get_connection", lambda target=None: conn)
    return conn


# ── VM lifecycle ─────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_vm_start_posts_action_and_records_stop_undo(vm_conn, undo_recorder):
    from mcp_server.tools import vm_actions as gov

    result = gov.vm_start(vm_id="vm-1")
    vm_conn.post.assert_called_once_with("/vms/vm-1/actions/start", params={"sync": "true"})
    assert result["priorPowerState"] == "Running"
    assert result["_undo_id"]
    assert undo_recorder[0]["tool"] == "vm_stop"
    assert undo_recorder[0]["params"] == {"vm_id": "vm-1"}


@pytest.mark.unit
def test_vm_stop_clean_vs_force_and_start_undo(vm_conn, undo_recorder):
    from mcp_server.tools import vm_actions as gov

    result = gov.vm_stop(vm_id="vm-1")
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/clean_shutdown", params={"sync": "true"}
    )
    assert result["mode"] == "clean"
    assert undo_recorder[-1]["tool"] == "vm_start"
    assert undo_recorder[-1]["params"] == {"vm_id": "vm-1"}

    vm_conn.post.reset_mock()
    gov.vm_stop(vm_id="vm-1", force=True)
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/hard_shutdown", params={"sync": "true"}
    )


@pytest.mark.unit
def test_vm_stop_undo_replay_goes_through_vm_start(vm_conn, undo_recorder):
    """The recorded inverse must be REPLAYABLE: calling the named tool with the
    recorded params must execute cleanly against the governed twin."""
    from mcp_server.tools import vm_actions as gov

    gov.vm_stop(vm_id="vm-1")
    descriptor = undo_recorder[-1]
    vm_conn.post.reset_mock()

    replay_tool = getattr(gov, descriptor["tool"])
    replay = replay_tool(**descriptor["params"])
    assert "error" not in replay
    vm_conn.post.assert_called_once_with("/vms/vm-1/actions/start", params={"sync": "true"})


@pytest.mark.unit
def test_vm_stop_of_non_running_vm_records_no_undo(vm_conn, undo_recorder):
    """Starting back a VM that was NOT running is not an inverse — no undo."""
    from mcp_server.tools import vm_actions as gov

    vm_conn.get.return_value = {"power_state": "Paused", "$container": "host-src"}
    result = gov.vm_stop(vm_id="vm-1")
    assert "_undo_id" not in result
    assert undo_recorder == []


@pytest.mark.unit
def test_vm_reboot_captures_prior_state_no_undo(vm_conn, undo_recorder):
    from mcp_server.tools import vm_actions as gov

    result = gov.vm_reboot(vm_id="vm-1")
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/clean_reboot", params={"sync": "true"}
    )
    assert result["priorPowerState"] == "Running"
    assert "_undo_id" not in result
    assert undo_recorder == []


@pytest.mark.unit
def test_vm_migrate_captures_source_host_and_undo_replays_back(vm_conn, undo_recorder):
    """vm_migrate must capture the REAL source host before moving, and the
    recorded inverse (migrate back) must replay through vm_migrate itself."""
    from mcp_server.tools import vm_actions as gov

    result = gov.vm_migrate(vm_id="vm-1", host_id="host-dst")
    assert result["sourceHost"] == "host-src"
    assert result["destinationHost"] == "host-dst"
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/migrate", params={"sync": "true"}, json={"host": "host-dst"}
    )
    descriptor = undo_recorder[-1]
    assert descriptor["tool"] == "vm_migrate"
    assert descriptor["params"] == {"vm_id": "vm-1", "host_id": "host-src"}

    # Replay: migrate back to the captured source host.
    vm_conn.post.reset_mock()
    replay = gov.vm_migrate(**descriptor["params"])
    assert "error" not in replay
    vm_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/migrate", params={"sync": "true"}, json={"host": "host-src"}
    )


@pytest.mark.unit
def test_vm_migrate_without_captured_source_records_no_undo(vm_conn, undo_recorder):
    """No captured source host → an honest 'no safe inverse', not a guess."""
    from mcp_server.tools import vm_actions as gov

    vm_conn.get.side_effect = RuntimeError("lookup boom")
    result = gov.vm_migrate(vm_id="vm-1", host_id="host-dst")
    assert result["sourceHost"] == ""
    assert "_undo_id" not in result
    assert undo_recorder == []


# ── Dry-run previews: audited, and never mutating ────────────────────────────
#
# The invariant is "a dry_run MAY read; it must never write" — NOT "a dry_run
# makes no calls at all". A preview that cannot read cannot answer "would this
# be refused?", and @governed_tool wraps the tool regardless of dry_run, so a
# preview lands an audit row like any other governed call. What survives from
# the old rule is the undo half: the harness deliberately records no undo token
# for a preview, because a preview leaves nothing to invert.

MUTATING_VERBS = ("post", "delete")


def _assert_never_wrote(conn) -> None:
    """Assert not one mutating verb of the XO transport was called."""
    for verb in MUTATING_VERBS:
        getattr(conn, verb).assert_not_called()


@pytest.mark.unit
def test_the_mutating_verb_list_still_matches_the_transport():
    """MUTATING_VERBS is hand-maintained while the connections under test are
    MagicMocks, which answer to any attribute. A verb added to XoConnection and
    forgotten here would silently weaken every "never wrote" assertion below
    into checking a subset of the write surface, so pin that surface: adding a
    verb must fail here and force a decision, not pass quietly.
    """
    from xcpng_aiops.connection import XoConnection

    public = {n for n in vars(XoConnection) if not n.startswith("_")}
    assert public == set(MUTATING_VERBS) | {"get", "request", "target", "close"}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("vm_start", {"vm_id": "vm-1"}),
        ("vm_stop", {"vm_id": "vm-1"}),
        ("vm_reboot", {"vm_id": "vm-1"}),
        ("vm_migrate", {"vm_id": "vm-1", "host_id": "host-dst"}),
    ],
)
def test_vm_action_dry_run_is_audited_and_never_writes(
    gov_home, vm_conn, undo_recorder, tool_name, kwargs
):
    from mcp_server.tools import vm_actions as gov

    result = getattr(gov, tool_name)(dry_run=True, **kwargs)
    assert result["dryRun"] is True
    _assert_never_wrote(vm_conn)
    assert _audit_tools(gov_home / "audit.db") == [tool_name], "previews are audited"
    assert undo_recorder == []  # nothing happened, so there is nothing to invert
    assert "_undo_id" not in result


@pytest.mark.unit
@pytest.mark.parametrize(
    ("tool_name", "kwargs"),
    [
        ("snapshot_create", {"vm_id": "vm-1", "name": "s"}),
        ("snapshot_delete", {"snapshot_id": "snap-1"}),
        ("snapshot_revert", {"snapshot_id": "snap-1"}),
    ],
)
def test_snapshot_dry_run_is_audited_and_never_writes(
    gov_home, snap_conn, undo_recorder, tool_name, kwargs
):
    from mcp_server.tools import snapshots as gov

    result = getattr(gov, tool_name)(dry_run=True, **kwargs)
    assert result["dryRun"] is True
    _assert_never_wrote(snap_conn)
    assert _audit_tools(gov_home / "audit.db") == [tool_name], "previews are audited"
    assert undo_recorder == []  # nothing happened, so there is nothing to invert


@pytest.mark.unit
def test_sr_rescan_dry_run_and_execute(monkeypatch, undo_recorder):
    import mcp_server.tools.srs as gov_srs

    conn = MagicMock(name="conn")
    monkeypatch.setattr(gov_srs, "_get_connection", lambda target=None: conn)

    preview = gov_srs.sr_rescan(sr_id="sr-1", dry_run=True)
    assert preview["dryRun"] is True
    _assert_never_wrote(conn)

    result = gov_srs.sr_rescan(sr_id="sr-1")
    # XO names this action `scan`; `rescan` 404s on a real XO (verified against
    # XCP-ng 8.3 + XO's OpenAPI spec, 2026-08-01).
    conn.post.assert_called_once_with("/srs/sr-1/actions/scan", params={"sync": "true"})
    assert result["action"] == "sr_rescan"
    assert undo_recorder == []  # low-risk metadata refresh — no undo by design


# ── Snapshots ────────────────────────────────────────────────────────────────


@pytest.mark.unit
def test_snapshot_create_captures_real_id_and_undo_replays_delete(
    snap_conn, undo_recorder
):
    """The undo must target the snapshot id XO RETURNED (never a guess), and
    replaying it must drive snapshot_delete cleanly."""
    from mcp_server.tools import snapshots as gov

    result = gov.snapshot_create(vm_id="vm-1", name="pre-change")
    snap_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/snapshot",
        params={"sync": "true"},
        json={"name_label": "pre-change"},
    )
    assert result["id"] == "snap-1"  # the REAL id from the response
    descriptor = undo_recorder[-1]
    assert descriptor["tool"] == "snapshot_delete"
    assert descriptor["params"] == {"snapshot_id": "snap-1"}

    # Replay the inverse through the governed twin.
    replay = gov.snapshot_delete(**descriptor["params"])
    assert "error" not in replay
    snap_conn.delete.assert_called_once_with("/vm-snapshots/snap-1")


@pytest.mark.unit
def test_snapshot_create_extracts_id_from_href_and_dict_responses(snap_conn):
    from mcp_server.tools import snapshots as gov

    snap_conn.post.return_value = "/rest/v0/vm-snapshots/snap-href"
    assert gov.snapshot_create(vm_id="vm-1", name="a")["id"] == "snap-href"

    snap_conn.post.return_value = {"uuid": "snap-dict"}
    assert gov.snapshot_create(vm_id="vm-1", name="b")["id"] == "snap-dict"


@pytest.mark.unit
def test_snapshot_create_without_id_records_no_undo(snap_conn, undo_recorder):
    """If XO's response carries no id there is no replayable inverse — record none."""
    from mcp_server.tools import snapshots as gov

    snap_conn.post.return_value = {}
    result = gov.snapshot_create(vm_id="vm-1", name="x")
    assert result["id"] == ""
    assert "_undo_id" not in result
    assert undo_recorder == []


@pytest.mark.unit
def test_snapshot_delete_captures_before_state(snap_conn, undo_recorder):
    """delete captures the snapshot's REAL prior state (name/time/VM); no undo."""
    from mcp_server.tools import snapshots as gov

    result = gov.snapshot_delete(snapshot_id="snap-1")
    snap_conn.get.assert_called_once_with("/vm-snapshots/snap-1")
    snap_conn.delete.assert_called_once_with("/vm-snapshots/snap-1")
    assert result["priorState"]["name"] == "pre-change"
    assert result["priorState"]["snapshotTime"] == 1752700000
    assert result["priorState"]["vm"] == "vm-1"
    assert "_undo_id" not in result
    assert undo_recorder == []


@pytest.mark.unit
def test_snapshot_revert_captures_before_state_no_undo(snap_conn, undo_recorder):
    from mcp_server.tools import snapshots as gov

    result = gov.snapshot_revert(snapshot_id="snap-1")
    # XO exposes revert on the PARENT VM as `revert_snapshot`, with the
    # snapshot id in the body — `/vm-snapshots/<id>/actions/revert` 404s on a
    # real XO (verified against XCP-ng 8.3, 2026-08-01).
    snap_conn.post.assert_called_once_with(
        "/vms/vm-1/actions/revert_snapshot",
        params={"sync": "true"},
        json={"snapshotId": "snap-1"},
    )
    assert result["priorState"]["name"] == "pre-change"
    assert "_undo_id" not in result
    assert undo_recorder == []
