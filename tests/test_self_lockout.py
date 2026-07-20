"""Refuse to stop the VM that runs this Xen Orchestra, and keep migrate's undo.

XO is commonly a VM on the very pool it manages. ``vm_stop`` on that uuid is one
plain call, and it is worse than irreversible: the ``sync=true`` POST never
returns because the process that would have answered is gone, and ``vm_start``
cannot be sent either — the API it would travel over went down with the VM.
Recovery drops to the hypervisor console.

XO's REST API has no self endpoint and its token carries no claims, so exact
detection is impossible to discover. The design is therefore two-tier and these
tests pin the honesty of both: Tier 1 (declared uuid) refuses exactly and only
that uuid and does nothing at all when undeclared; Tier 2 (IP coincidence) is a
dry-run hint that must never block and must never sound certain.

The migrate tests cover the neighbouring defect: the pre-move source host used
to live only in the return value, so a lost response took the undo's target with
it. It is now stashed via ``capture_prior_state`` before the POST.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcp_server.tools.vm_actions import _migrate_undo
from xcpng_aiops.governance.outcome import take_prior_state
from xcpng_aiops.ops.vm_actions import SelfLockout, migrate_vm, self_vm_hint, stop_vm

XO_VM = "11111111-2222-3333-4444-555555555555"
OTHER_VM = "99999999-8888-7777-6666-555555555555"


def _conn(*, self_uuid=None, url="https://xo.example.com", vm_ip=None):
    conn = MagicMock(name="conn")
    conn.target = SimpleNamespace(name="xo1", url=url, xo_self_vm_uuid=self_uuid)
    conn.get.return_value = {
        "power_state": "Running",
        "$container": "host-1",
        "mainIpAddress": vm_ip,
    }
    conn.post.return_value = {}
    return conn


# ── Tier 1: the declared XO VM is refused, exactly ───────────────────────────


@pytest.mark.unit
def test_stopping_the_declared_xo_vm_is_refused():
    conn = _conn(self_uuid=XO_VM)
    with pytest.raises(SelfLockout, match="declared as the VM running Xen Orchestra"):
        stop_vm(conn, XO_VM)
    # Must refuse BEFORE issuing the shutdown, not report it afterwards.
    conn.post.assert_not_called()


@pytest.mark.unit
def test_the_refusal_says_why_and_what_to_do_instead():
    with pytest.raises(SelfLockout) as ei:
        stop_vm(_conn(self_uuid=XO_VM), XO_VM)
    msg = str(ei.value)
    assert "vm_start" in msg, "must name the inverse that would become unsendable"
    assert "xe vm-start" in msg, "must name the concrete recovery path"
    assert "config.yaml" in msg, "must say how to correct a wrong declaration"


@pytest.mark.unit
def test_a_force_stop_of_the_xo_vm_is_refused_too():
    """--force is the more dangerous path, not an override."""
    with pytest.raises(SelfLockout):
        stop_vm(_conn(self_uuid=XO_VM), XO_VM, force=True)


@pytest.mark.unit
def test_uuid_comparison_ignores_case_and_surrounding_whitespace():
    with pytest.raises(SelfLockout):
        stop_vm(_conn(self_uuid=XO_VM.upper()), f"  {XO_VM}  ")


@pytest.mark.unit
def test_every_other_vm_still_stops():
    """The guard must be exact — over-blocking would break VM lifecycle work."""
    conn = _conn(self_uuid=XO_VM)
    out = stop_vm(conn, OTHER_VM)
    assert out["action"] == "vm_stop"
    conn.post.assert_called_once_with(
        f"/vms/{OTHER_VM}/actions/clean_shutdown", params={"sync": "true"}
    )


# ── Tier 1 fails open when nothing is declared ───────────────────────────────


@pytest.mark.unit
def test_an_undeclared_target_blocks_nothing():
    """Unknown is never 'it is me'. XO exposes no self endpoint, so an
    undeclared target genuinely cannot be guarded — it must not pretend to."""
    conn = _conn(self_uuid=None)
    stop_vm(conn, XO_VM)  # must not raise
    conn.post.assert_called_once()


@pytest.mark.unit
def test_an_empty_declaration_is_treated_as_undeclared_not_as_a_match():
    """Two empty strings compare equal — that must not become a refusal."""
    conn = _conn(self_uuid="   ")
    stop_vm(conn, "")  # must not raise
    conn.post.assert_called_once()


@pytest.mark.unit
def test_a_connection_without_a_target_blocks_nothing():
    """Older callers and test doubles carry no target; fail open, don't crash."""
    conn = MagicMock(name="conn", spec=["get", "post"])
    conn.get.return_value = {"power_state": "Running"}
    stop_vm(conn, XO_VM)  # must not raise
    conn.post.assert_called_once()


# ── Tier 2: the IP hint informs, never decides ───────────────────────────────


@pytest.mark.unit
def test_ip_match_produces_a_hint_but_does_not_block():
    """A shared address is a coincidence to check, not grounds to refuse."""
    conn = _conn(self_uuid=None, url="https://10.0.0.5", vm_ip="10.0.0.5")
    assert self_vm_hint(conn, XO_VM) is not None
    stop_vm(conn, XO_VM)  # the hint must NEVER become a block
    conn.post.assert_called_once()


@pytest.mark.unit
def test_the_hint_admits_it_could_be_wrong():
    """Wording matters: an authoritative-sounding hint is worse than none."""
    conn = _conn(url="https://10.0.0.5", vm_ip="10.0.0.5")
    hint = self_vm_hint(conn, XO_VM)
    assert "MAY" in hint, "must not assert it as fact"
    assert "coincidence" in hint
    assert "xo_self_vm_uuid" in hint, "must point at the guard that IS exact"


@pytest.mark.unit
def test_no_hint_when_the_guest_agent_reports_no_ip():
    """Absent is the common case, not a signal — say nothing rather than guess."""
    assert self_vm_hint(_conn(vm_ip=None), XO_VM) is None


@pytest.mark.unit
def test_no_hint_when_the_ip_differs():
    conn = _conn(url="https://10.0.0.5", vm_ip="10.0.0.9")
    assert self_vm_hint(conn, XO_VM) is None


@pytest.mark.unit
def test_no_hint_when_the_read_fails():
    conn = _conn(url="https://10.0.0.5")
    conn.get.side_effect = RuntimeError("XO unreachable")
    assert self_vm_hint(conn, XO_VM) is None


# ── both entry points are guarded ────────────────────────────────────────────


@pytest.mark.unit
def test_the_mcp_tool_refuses_and_records_no_undo(monkeypatch, tmp_path):
    """A guard that only covers the ops layer is a guard an agent can walk past."""
    import mcp_server.tools.vm_actions as gov_vm

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=XO_VM)
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    out = gov_vm.vm_stop(vm_id=XO_VM)
    assert "declared as the VM running Xen Orchestra" in out["error"]
    conn.post.assert_not_called()


@pytest.mark.unit
def test_the_cli_refuses_too(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    import mcp_server.tools.vm_actions as gov_vm
    import xcpng_aiops.cli.vm as cli_vm
    from xcpng_aiops.cli import app

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=XO_VM)
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    monkeypatch.setattr(cli_vm, "get_connection", lambda target=None: (conn, None))
    result = CliRunner().invoke(app, ["vm", "stop", XO_VM], input="y\ny\n")
    # The governed twin returns {"error": ...} rather than raising; a CLI that
    # ignores that prints "Stopped VM ..." for a shutdown that never happened.
    assert "declared as the VM running Xen Orchestra" in result.output
    assert "Stopped VM" not in result.output
    assert result.exit_code == 1
    conn.post.assert_not_called()


@pytest.mark.unit
def test_the_mcp_dry_run_on_the_self_target_is_refused(monkeypatch, tmp_path):
    """A dry-run reports what would happen. If the answer is "refused", say so —
    a green preview followed by a refusal reads to a model as a retryable blip."""
    import mcp_server.tools.vm_actions as gov_vm

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=XO_VM)
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    out = gov_vm.vm_stop(vm_id=XO_VM, dry_run=True)
    assert "declared as the VM running Xen Orchestra" in out["error"]
    assert "dryRun" not in out
    conn.post.assert_not_called()


@pytest.mark.unit
def test_the_mcp_dry_run_on_any_other_vm_still_previews(monkeypatch, tmp_path):
    """The dry-run must never refuse something the real call would allow."""
    import mcp_server.tools.vm_actions as gov_vm

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=XO_VM)
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    out = gov_vm.vm_stop(vm_id=OTHER_VM, dry_run=True)
    assert out["dryRun"] is True
    assert out["wouldStop"] == {"vm_id": OTHER_VM, "force": False}
    conn.post.assert_not_called()


@pytest.mark.unit
def test_the_dry_run_fails_open_on_an_undeclared_target(monkeypatch, tmp_path):
    """Fail-open semantics must be identical on both paths."""
    import mcp_server.tools.vm_actions as gov_vm

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=None)
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    assert gov_vm.vm_stop(vm_id=XO_VM, dry_run=True)["dryRun"] is True


@pytest.mark.unit
def test_the_ip_hint_never_blocks_the_dry_run_either(monkeypatch, tmp_path):
    """Tier 2 stays advisory on BOTH paths — it is a coincidence, not a finding."""
    import mcp_server.tools.vm_actions as gov_vm

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=None, url="https://10.0.0.5", vm_ip="10.0.0.5")
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    out = gov_vm.vm_stop(vm_id=XO_VM, dry_run=True)
    assert out["dryRun"] is True, "an IP coincidence must never refuse"
    assert out["selfVmHint"] is not None


@pytest.mark.unit
def test_the_cli_dry_run_on_the_self_target_is_refused(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    import mcp_server.tools.vm_actions as gov_vm
    from xcpng_aiops.cli import app

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(self_uuid=XO_VM)
    # The dry-run runs through the governed twin, so patch the twin's connection.
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["vm", "stop", XO_VM, "--dry-run"])
    assert result.exit_code == 1
    assert "declared as the VM running Xen Orchestra" in " ".join(result.output.split())
    assert "DRY-RUN" not in result.output


@pytest.mark.unit
def test_the_cli_dry_run_surfaces_the_ip_hint(monkeypatch, tmp_path):
    from typer.testing import CliRunner

    import mcp_server.tools.vm_actions as gov_vm
    from xcpng_aiops.cli import app

    monkeypatch.setenv("XCPNG_AIOPS_HOME", str(tmp_path))
    conn = _conn(url="https://10.0.0.5", vm_ip="10.0.0.5")
    monkeypatch.setattr(gov_vm, "_get_connection", lambda target=None: conn)
    result = CliRunner().invoke(app, ["vm", "stop", XO_VM, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "Possible self-target" in result.output
    conn.post.assert_not_called()


# ── migrate: the inverse must survive a lost response ────────────────────────


@pytest.mark.unit
def test_migrate_stashes_the_source_host_before_issuing_the_post():
    """The whole point: the capture has to happen before the call that may die."""
    captured: list = []
    conn = _conn()
    conn.post.side_effect = lambda *a, **k: captured.append(take_prior_state())
    migrate_vm(conn, OTHER_VM, "host-2")
    assert captured == [{"sourceHost": "host-1"}]


@pytest.mark.unit
def test_migrate_undo_uses_the_stashed_host_when_the_response_was_lost():
    """The harness hands over priorState instead of a result on the unknown path."""
    undo = _migrate_undo(
        {"vm_id": OTHER_VM},
        {"priorState": {"sourceHost": "host-1"}, "outcomeUnknown": True},
    )
    assert undo["tool"] == "vm_migrate"
    assert undo["params"] == {"vm_id": OTHER_VM, "host_id": "host-1"}


@pytest.mark.unit
def test_migrate_undo_still_reads_the_normal_result():
    undo = _migrate_undo({"vm_id": OTHER_VM}, {"sourceHost": "host-1"})
    assert undo["params"] == {"vm_id": OTHER_VM, "host_id": "host-1"}


@pytest.mark.unit
def test_migrate_undo_declines_when_the_source_host_was_never_read():
    """An honest 'no safe inverse' beats migrating the VM somewhere invented."""
    assert _migrate_undo({"vm_id": OTHER_VM}, {"priorState": {"sourceHost": ""}}) is None
    assert _migrate_undo({"vm_id": OTHER_VM}, {"sourceHost": ""}) is None
