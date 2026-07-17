"""Backup job reads + flagship RCA: backup-job failure classification.

Reads XO backup jobs (``/backup/jobs/vm``) and run logs (``/backup/logs``),
then classifies failed / interrupted / skipped runs into actionable causes:

  * ``vdi-chain`` — unhealthy VDI chain / coalesce not finished (the classic
    "job skipped until chain coalesces" case).
  * ``quiesce`` — guest quiesce / VSS snapshot failures.
  * ``transport`` — remote/network errors reaching the backup remote.
  * ``storage-full`` — SR or remote out of space.
  * ``unknown`` — anything else (sample messages included for triage).

PREVIEW: mock-validated only — verify endpoint paths against a live XO.
"""

from __future__ import annotations

from typing import Any

from xcpng_aiops.ops._util import as_list, s

# How many recent log entries the RCA examines by default.
DEFAULT_LOG_LIMIT = 50

_BAD_STATUSES = {"failure", "interrupted", "skipped"}

# Ordered (class, action, patterns) — first match wins.
_CLASSIFIERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "vdi-chain",
        "Let the coalesce finish (watch the SR's advanced tab), run sr_rescan, and "
        "avoid stacking snapshots; the next run usually succeeds once the chain "
        "merges.",
        ("vdi chain", "chain protection", "coalesce", "too many vdis"),
    ),
    (
        "quiesce",
        "Guest quiesce failed — check guest tools / VSS inside the guest, or disable "
        "quiesced snapshots for this job.",
        ("quiesce", "vss"),
    ),
    (
        "transport",
        "The backup remote was unreachable — verify the remote (XO Settings → "
        "Remotes → test), network path, and credentials.",
        (
            "econnreset", "econnrefused", "etimedout", "ehostunreach", "enotconn",
            "getaddrinfo", "socket hang up", "network", "timeout",
        ),
    ),
    (
        "storage-full",
        "Out of space — free the backup remote or SR (delete old backups, extend "
        "capacity), then re-run.",
        ("enospc", "no space", "sr_backend_failure_44", "full"),
    ),
)


def list_backup_jobs(conn: Any) -> list[dict]:
    """[READ] List VM backup jobs (id, name, mode, schedules)."""
    rows = []
    for job in as_list(conn.get("/backup/jobs/vm")):
        rows.append(
            {
                "id": s(job.get("id"), 64),
                "name": s(job.get("name"), 128),
                "mode": s(job.get("mode"), 32),
                "type": s(job.get("type"), 32),
            }
        )
    return rows


def _log_summary(log: dict) -> dict:
    """Reduce one backup log record to a high-signal summary."""
    tasks = log.get("tasks") or []
    messages = []
    for t in tasks:
        if not isinstance(t, dict):
            continue
        if (t.get("status") or "").lower() in _BAD_STATUSES:
            result = t.get("result") or {}
            msg = result.get("message") if isinstance(result, dict) else str(result)
            if msg:
                messages.append(s(msg, 200))
    return {
        "id": s(log.get("id"), 64),
        "jobId": s(log.get("jobId"), 64),
        "jobName": s(log.get("jobName"), 128),
        "status": s(log.get("status"), 32),
        "start": log.get("start"),
        "end": log.get("end"),
        "failedTaskMessages": messages[:5],
    }


def list_backup_logs(conn: Any, limit: int = DEFAULT_LOG_LIMIT) -> list[dict]:
    """[READ] List recent backup run logs (status + failed-task messages)."""
    data = conn.get("/backup/logs", params={"limit": limit})
    return [_log_summary(x) for x in as_list(data)]


def _classify(message: str) -> tuple[str, str]:
    """Map a failure message to (cause class, action)."""
    lowered = message.lower()
    for cause, action, patterns in _CLASSIFIERS:
        if any(p in lowered for p in patterns):
            return cause, action
    return (
        "unknown",
        "Inspect the full run log in the XO UI (Backup → Logs) — the message did "
        "not match a known failure class.",
    )


def backup_failure_rca(conn: Any, limit: int = DEFAULT_LOG_LIMIT) -> dict:
    """[READ][RCA] Classify failed/skipped backup runs: cause + action per job.

    Examines the most recent ``limit`` run logs and groups findings by job.
    """
    jobs = {j["id"]: j for j in list_backup_jobs(conn)}
    logs = list_backup_logs(conn, limit)

    per_job: dict[str, dict] = {}
    for log in logs:
        job_id = log.get("jobId") or "?"
        entry = per_job.setdefault(
            job_id,
            {
                "job": log.get("jobName") or jobs.get(job_id, {}).get("name") or job_id,
                "jobId": job_id,
                "runs": 0,
                "badRuns": 0,
                "lastStatus": log.get("status"),
                "causes": {},
                "findings": [],
            },
        )
        entry["runs"] += 1
        if (log.get("status") or "").lower() not in _BAD_STATUSES:
            continue
        entry["badRuns"] += 1
        messages = log.get("failedTaskMessages") or [""]
        for msg in messages:
            cause, action = _classify(msg)
            entry["causes"][cause] = entry["causes"].get(cause, 0) + 1
            if len(entry["findings"]) < 3:
                entry["findings"].append(
                    {
                        "cause": cause,
                        "severity": "high" if cause != "vdi-chain" else "medium",
                        "evidence": s(msg, 200) or f"run status={log.get('status')}",
                        "action": action,
                    }
                )

    jobs_with_failures = [e for e in per_job.values() if e["badRuns"]]
    return {
        "logsExamined": len(logs),
        "jobsSeen": len(per_job),
        "jobsWithFailures": len(jobs_with_failures),
        "jobs": sorted(per_job.values(), key=lambda e: -e["badRuns"]),
        "healthy": not jobs_with_failures,
    }
