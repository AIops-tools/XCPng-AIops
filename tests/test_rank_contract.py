"""Rank contract: worst-first findings must state their priority explicitly.

A consumer — notably a smaller local model summarising the result — should never
have to infer urgency from list position.
"""

from __future__ import annotations

import pytest

from tests.test_rca import _FakeConn, _vm


@pytest.mark.unit
def test_vm_health_rca_findings_carry_1_based_rank_worst_first():
    from xcpng_aiops.ops.vm_rca import vm_health_rca

    conn = _FakeConn({
        "/vms": [
            _vm("vm-1", "legacy01", state="Running",
                managementAgentDetected=False, pvDriversDetected=False),
            _vm("vm-2", "db01", state="Halted", auto_poweron=True),
        ],
    })
    findings = vm_health_rca(conn)["findings"]
    assert findings, "fixture should produce findings"
    assert [f["rank"] for f in findings] == list(range(1, len(findings) + 1))
    severity_order = {"high": 0, "medium": 1, "low": 2}
    seen = [severity_order.get(f["severity"], 3) for f in findings]
    assert seen == sorted(seen), "rank must follow worst-first severity order"
