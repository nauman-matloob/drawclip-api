"""Job management: submission, status tracking, per-user FIFO eviction."""

import os
import secrets
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import Request
from pydantic import BaseModel, Field

from styles.base import Style, StyleParams

MAX_JOBS_PER_USER = 10
MAX_WORKERS = 2


class JobStatus(BaseModel):
    job_id: str
    style: str
    status: str = Field(description="pending | running | done | error")
    progress: float = Field(0.0, description="0–100")
    created_at: str
    finished_at: Optional[str] = None
    error: Optional[str] = None
    download_url: Optional[str] = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _uuid7() -> str:
    """RFC 9562 UUIDv7: 48-bit ms timestamp prefix + version/variant + random."""
    ts_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (ts_ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    h = f"{value:032x}"
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


class JobManager:
    """Thread-safe in-memory job tracker with per-user FIFO eviction.

    Each user has their own bucket of up to ``max_jobs_per_user`` jobs.
    Jobs and downloads are scoped to the owning user — calling
    :meth:`get` with a different ``user_id`` returns ``None`` (treated as 404).
    """

    def __init__(
        self,
        output_dir: str,
        max_jobs_per_user: int = MAX_JOBS_PER_USER,
        max_workers: int = MAX_WORKERS,
    ):
        self.output_dir = output_dir
        self.max_jobs_per_user = max_jobs_per_user
        os.makedirs(output_dir, exist_ok=True)
        self._jobs: "OrderedDict[str, dict]" = OrderedDict()
        self._user_jobs: Dict[str, "OrderedDict[str, None]"] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit(
        self,
        user_id: str,
        style: Style,
        params: StyleParams,
        tmp_input: str,
    ) -> dict:
        """Register a job for a user, schedule it, and return a snapshot."""
        job_id = _uuid7()
        with self._lock:
            self._jobs[job_id] = {
                "job_id": job_id,
                "user_id": user_id,
                "style": style.name,
                "status": "pending",
                "progress": 0.0,
                "created_at": _now_iso(),
                "finished_at": None,
                "error": None,
                "file_path": None,
            }
            user_bucket = self._user_jobs.setdefault(user_id, OrderedDict())
            user_bucket[job_id] = None
            self._evict_user(user_id)
            snapshot = dict(self._jobs[job_id])
        self._executor.submit(self._run, job_id, style, params, tmp_input)
        return snapshot

    def _run(self, job_id: str, style: Style, params: StyleParams, tmp_input: str) -> None:
        def update_progress(value: float) -> None:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["progress"] = float(value)

        with self._lock:
            if job_id in self._jobs:
                self._jobs[job_id]["status"] = "running"

        try:
            video_path = style.render(
                image_path=tmp_input,
                output_dir=self.output_dir,
                params=params,
                progress_callback=update_progress,
            )
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id].update(
                        status="done",
                        progress=100.0,
                        finished_at=_now_iso(),
                        file_path=video_path,
                    )
                else:
                    # Job was evicted while running — drop the orphan file.
                    try:
                        os.unlink(video_path)
                    except OSError:
                        pass
        except Exception as e:
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id].update(
                        status="error",
                        finished_at=_now_iso(),
                        error=str(e),
                    )
        finally:
            try:
                os.unlink(tmp_input)
            except OSError:
                pass

    def get(self, job_id: str, user_id: str) -> Optional[dict]:
        """Return a snapshot of the job if it exists AND belongs to ``user_id``."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job and job.get("user_id") == user_id:
                return dict(job)
            return None

    def list_for_user(self, user_id: str) -> List[dict]:
        with self._lock:
            user_bucket = self._user_jobs.get(user_id)
            if not user_bucket:
                return []
            return [dict(self._jobs[jid]) for jid in user_bucket if jid in self._jobs]

    def _evict_user(self, user_id: str) -> None:
        user_bucket = self._user_jobs.get(user_id)
        if not user_bucket:
            return
        while len(user_bucket) > self.max_jobs_per_user:
            old_job_id, _ = user_bucket.popitem(last=False)
            old_job = self._jobs.pop(old_job_id, None)
            if old_job:
                path = old_job.get("file_path")
                if path and os.path.exists(path):
                    try:
                        os.unlink(path)
                    except OSError:
                        pass

    def cleanup_outputs(self) -> None:
        if not os.path.isdir(self.output_dir):
            return
        for f in os.listdir(self.output_dir):
            try:
                os.unlink(os.path.join(self.output_dir, f))
            except OSError:
                pass

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)


def job_to_status(job: dict, request: Optional[Request] = None) -> JobStatus:
    download_url = None
    if job["status"] == "done":
        path = f"/jobs/{job['job_id']}/download"
        download_url = str(request.base_url).rstrip("/") + path if request else path
    return JobStatus(
        job_id=job["job_id"],
        style=job["style"],
        status=job["status"],
        progress=job["progress"],
        created_at=job["created_at"],
        finished_at=job.get("finished_at"),
        error=job.get("error"),
        download_url=download_url,
    )
