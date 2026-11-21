"""Persist and coordinate public pull jobs across local MCP sessions."""

from contextlib import closing
from datetime import datetime, timezone
import errno
import json
from pathlib import Path
import sqlite3
import sys
from threading import Thread
from time import monotonic
from uuid import uuid4


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _try_lock(path: Path):
    """Keep the returned file open to hold the lock until close or process exit."""
    handle = path.open("a+b")
    try:
        handle.seek(0)
        if sys.platform == "win32":
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            return None
        raise
    return handle


def _summarize(result: dict) -> dict:
    """Keep counts and errors without returning thousands of archive file paths."""
    summary = {key: value for key, value in result.items() if key != "fetched_items"}
    if "categories" in summary:
        summary["categories"] = {
            name: {key: value for key, value in category.items() if key != "fetched_items"}
            for name, category in summary["categories"].items()
        }
    if errors := summary.get("errors"):
        summary["error_count"] = len(errors)
        summary["errors"] = errors[:20]
    return summary


class PullJobs:
    def __init__(self, directory: Path):
        self.directory = directory

    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        connection = sqlite3.connect(self.directory / "jobs.sqlite3")
        try:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    target TEXT NOT NULL,
                    status TEXT NOT NULL,
                    record TEXT NOT NULL
                )
            """)
            connection.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS active_pull
                ON jobs (kind, target) WHERE status = 'running'
            """)
        except Exception:
            connection.close()
            raise
        return connection

    def _lock_path(self, job_id: str) -> Path:
        return self.directory / f"{job_id}.lock"

    @staticmethod
    def _save(db, job: dict):
        db.execute(
            "INSERT INTO jobs VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(job_id) DO UPDATE SET status=excluded.status, record=excluded.record",
            (job["job_id"], job["kind"], job["target"], job["status"], json.dumps(job)),
        )

    def _reconcile(self, db, job: dict) -> None:
        if job["status"] != "running":
            return
        lock = _try_lock(self._lock_path(job["job_id"]))
        if lock is not None:
            with lock:
                job.update(status="failed", finished_at=_now(),
                           error="The MCP server stopped before recording a result. Start a new pull to retry.")
                self._save(db, job)

    def start(self, kind: str, target: str, refresh: bool, operation) -> dict:
        worker_lock = None
        try:
            with closing(self._connect()) as db, db:
                db.execute("BEGIN IMMEDIATE")
                row = db.execute(
                    "SELECT record FROM jobs WHERE kind = ? AND target = ? AND status = 'running'",
                    (kind, target),
                ).fetchone()
                if row:
                    active = json.loads(row[0])
                    self._reconcile(db, active)
                    if active["status"] == "running":
                        return {**active, "already_running": True}

                job_id = uuid4().hex
                worker_lock = _try_lock(self._lock_path(job_id))
                if worker_lock is None:
                    raise RuntimeError("Could not reserve a lock for the new pull job.")
                job = {
                    "job_id": job_id, "kind": kind, "target": target,
                    "refresh": refresh, "status": "running", "started_at": _now(),
                    "progress": {"stage": "starting"},
                }
                self._save(db, job)
            Thread(target=self._run, args=(job.copy(), operation, worker_lock),
                   name=f"substack-pull-{job_id[:8]}", daemon=True).start()
        except BaseException:
            if worker_lock is not None:
                worker_lock.close()
            raise
        return {**job, "already_running": False}

    def _run(self, job: dict, operation, worker_lock) -> None:
        def save():
            with closing(self._connect()) as db, db:
                self._save(db, job)

        last_saved = float("-inf")

        def progress(**counts):
            nonlocal last_saved
            job["progress"] = counts
            now = monotonic()
            if now - last_saved >= 2:
                save()
                last_saved = now

        with worker_lock:
            try:
                result = operation(progress)
                job["result"] = _summarize(result)
                if result.get("incomplete") or result.get("complete") is False:
                    job["status"] = "partially_completed"
                else:
                    job["status"] = "completed"
            except Exception as exc:
                # Notes report progress after writing the page and its checkpoint.
                saved_notes = job["progress"].get("created", 0) + job["progress"].get("updated", 0)
                job["status"] = "partially_completed" if saved_notes else "failed"
                job["error"] = str(exc) or type(exc).__name__
            job["finished_at"] = _now()
            save()

    def status(self, job_id: str) -> dict:
        with closing(self._connect()) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
            if row is None:
                raise LookupError("No public pull job has that ID.")
            job = json.loads(row[0])
            self._reconcile(db, job)
            return job
