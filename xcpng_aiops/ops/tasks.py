"""Task read operations over the Xen Orchestra REST API (``/tasks``).

PREVIEW: mock-validated only — verify field names against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.governance import opt_str
from xcpng_aiops.ops._util import DEFAULT_LIST_LIMIT, as_list, paged

TASK_FIELDS = "id,status,properties,start,end"


def list_tasks(
    conn: Any, status: str | None = None, limit: int = DEFAULT_LIST_LIMIT
) -> dict:
    """[READ] List XO tasks, optionally filtered by status (pending/failure/success).

    The task feed is unbounded on a busy pool, so the result is a
    truncation-announcing envelope::

        {"tasks": [...], "returned": 200, "limit": 200, "truncated": true}

    The status filter runs before the cap, and ``truncated`` is measured
    against the full filtered set rather than inferred from the row count.
    """
    rows = []
    for task in as_list(conn.get("/tasks", params={"fields": TASK_FIELDS})):
        props = task.get("properties") or {}
        rows.append(
            {
                "id": opt_str(task.get("id"), 64),
                "status": opt_str(task.get("status"), 32),
                "name": opt_str(props.get("name") if isinstance(props, dict) else None, 128),
                "object": opt_str(
                    props.get("objectId") if isinstance(props, dict) else None, 64
                ),
                "start": task.get("start"),
                "end": task.get("end"),
            }
        )
    if status:
        rows = [r for r in rows if (r.get("status") or "").lower() == status.lower()]
    return paged("tasks", rows, limit)
