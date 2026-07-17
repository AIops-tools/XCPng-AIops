"""``xcpng-aiops overview`` — one-shot fleet health summary."""

from __future__ import annotations

import json

from xcpng_aiops.cli._common import TargetOption, cli_errors, console, get_connection
from xcpng_aiops.ops import overview


@cli_errors
def overview_cmd(target: TargetOption = None) -> None:
    """Health summary: pools, hosts, VMs by state, SRs near full, recent backups."""
    conn, _ = get_connection(target)
    data = overview.health_overview(conn)
    console.print_json(json.dumps(data))
