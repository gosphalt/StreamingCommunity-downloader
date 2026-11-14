"""Download jobs in flight, persisted so a restart can run them again.

One row per job that has started and not yet finished. The record holds what
JobManager needs to rebuild the call: the function's import path, its
arguments, its keyword arguments and the job's notification fields. Segments
stay in ``tmp/<tmp_id>/`` on disk, so a resumed job skips every segment it
already has. Written from the executor threads; each statement is one
autocommit write, so there is no batch to keep consistent.
"""

import json
from datetime import datetime, timezone

from app import db


def save(job_id: str, record: dict) -> None:
    db.execute(
        "INSERT INTO download_job (job_id, record, created_at) VALUES (?, ?, ?) "
        "ON CONFLICT(job_id) DO UPDATE SET record = excluded.record",
        (job_id, json.dumps(record), datetime.now(timezone.utc).isoformat()),
    )


def delete(job_id: str) -> None:
    db.execute("DELETE FROM download_job WHERE job_id = ?", (job_id,))


def load_all() -> list[tuple[str, dict]]:
    rows = db.query("SELECT job_id, record FROM download_job ORDER BY created_at")
    return [(row["job_id"], json.loads(row["record"])) for row in rows]
