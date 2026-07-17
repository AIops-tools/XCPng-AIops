"""Task read operations over the Xen Orchestra REST API (``/tasks``).

PREVIEW: mock-validated only — verify field names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.ops._util import as_list, s

TASK_FIELDS = "id,status,properties,start,end"


def list_tasks(conn: Any, status: str | None = None) -> list[dict]:
    """[READ] List XO tasks, optionally filtered by status (pending/failure/success)."""
    rows = []
    for task in as_list(conn.get("/tasks", params={"fields": TASK_FIELDS})):
        props = task.get("properties") or {}
        rows.append(
            {
                "id": s(task.get("id"), 64),
                "status": s(task.get("status"), 32),
                "name": s(props.get("name") if isinstance(props, dict) else "", 128),
                "object": s(props.get("objectId") if isinstance(props, dict) else "", 64),
                "start": task.get("start"),
                "end": task.get("end"),
            }
        )
    if status:
        rows = [r for r in rows if r.get("status", "").lower() == status.lower()]
    return rows
