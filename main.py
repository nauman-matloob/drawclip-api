"""FastAPI application: generic routes (health, /jobs, /styles) + per-style routers."""

import os
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from auth import get_user_id
from jobs import JobManager, JobStatus, MAX_JOBS_PER_USER, job_to_status
from styles import list_styles
from styles.whiteboard.routes import router as whiteboard_router

OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "generated")


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.jobs = JobManager(output_dir=OUTPUT_DIR)
    app.state.jobs.cleanup_outputs()  # remove orphan files from previous runs
    yield
    app.state.jobs.shutdown()
    app.state.jobs.cleanup_outputs()


app = FastAPI(
    title="DrawClip API",
    description=(
        "Generate stylised videos from images.\n\n"
        "**Authentication (temporary)** — every request that touches jobs "
        "must include an `X-User-Id` header. Until real auth is wired up, "
        "this is just a client-supplied identifier (any non-empty string).\n\n"
        "**Workflow**\n"
        "1. `POST /generate/{style}` — submit an image with style-specific params, get a `job_id`.\n"
        "2. `GET /jobs/{job_id}` — poll the status (`pending → running → done | error`) and progress.\n"
        "3. `GET /jobs/{job_id}/download` — download the mp4 once status is `done`.\n\n"
        f"Each user keeps at most {MAX_JOBS_PER_USER} jobs; older jobs (and their files) are "
        "evicted automatically when a new job is submitted by the same user.\n\n"
        "Use `GET /styles` to list the available styles."
    ),
    version="2.0.0",
    lifespan=lifespan,
)


class StyleInfo(BaseModel):
    name: str
    description: str
    endpoint: str


@app.get("/health", tags=["meta"])
def health():
    """Liveness probe."""
    return {"status": "ok"}


@app.get("/styles", response_model=list[StyleInfo], tags=["meta"])
def get_styles():
    """List the available generation styles."""
    return [
        StyleInfo(name=s.name, description=s.description, endpoint=f"/generate/{s.name}")
        for s in list_styles()
    ]


@app.get("/jobs", response_model=list[JobStatus], tags=["jobs"])
def list_jobs(request: Request, user_id: str = Depends(get_user_id)):
    """List the calling user's jobs (most recent last)."""
    return [job_to_status(j, request) for j in request.app.state.jobs.list_for_user(user_id)]


@app.get("/jobs/{job_id}", response_model=JobStatus, tags=["jobs"])
def get_job(job_id: str, request: Request, user_id: str = Depends(get_user_id)):
    """Get the current status / progress of a job. Returns 404 if the job does not belong to the caller."""
    job = request.app.state.jobs.get(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (or evicted, or not yours)")
    return job_to_status(job, request)


@app.get(
    "/jobs/{job_id}/download",
    tags=["jobs"],
    responses={
        200: {"content": {"video/mp4": {}}, "description": "The generated mp4 video"},
        404: {"description": "Job not found or not owned by caller"},
        409: {"description": "Job not finished or failed"},
        410: {"description": "File no longer available"},
    },
)
def download_job_file(job_id: str, request: Request, user_id: str = Depends(get_user_id)):
    """Download the generated mp4. Only available when the job belongs to the caller and `status` is `done`."""
    job = request.app.state.jobs.get(job_id, user_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found (or evicted, or not yours)")
    if job["status"] == "error":
        raise HTTPException(status_code=409, detail=f"Job failed: {job.get('error')}")
    if job["status"] != "done":
        raise HTTPException(status_code=409, detail=f"Job not ready (status={job['status']})")
    file_path = job.get("file_path")
    if not file_path or not os.path.exists(file_path):
        raise HTTPException(status_code=410, detail="File no longer available")
    return FileResponse(
        path=file_path, media_type="video/mp4", filename=os.path.basename(file_path)
    )


# Per-style routers — add a new line here when you add a new style.
app.include_router(whiteboard_router, prefix="/generate", tags=["generate"])
