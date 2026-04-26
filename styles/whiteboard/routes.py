"""HTTP routes for the whiteboard style."""

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile

from auth import get_user_id
from jobs import JobStatus, job_to_status
from uploads import save_upload_to_tmp

from .render import MAX_VIDEO_DURATION
from .style import ALLOWED_RATIOS, WhiteboardParams, WhiteboardStyle

router = APIRouter()
_style = WhiteboardStyle()


@router.post(
    "/whiteboard",
    response_model=JobStatus,
    status_code=202,
    summary="Whiteboard sketch animation",
    description=(
        "Generate a whiteboard-style sketch animation video. "
        "The hand draws the image grid by grid until complete, "
        "then holds the final image for the remaining duration."
    ),
)
def create_whiteboard_job(
    request: Request,
    user_id: str = Depends(get_user_id),
    image: UploadFile = File(..., description="Image (png/jpg/jpeg/webp)"),
    total_image_duration: int = Form(
        10, ge=1, le=MAX_VIDEO_DURATION,
        description=f"Total video duration in seconds (max {MAX_VIDEO_DURATION})",
    ),
    writing_duration: int = Form(
        6, ge=1, le=MAX_VIDEO_DURATION,
        description="Drawing duration (must be <= total_image_duration)",
    ),
    ratio: str = Form("auto", description=f"One of: {list(ALLOWED_RATIOS)}"),
    draw_hand: bool = Form(True),
    color_while_drawing: bool = Form(False),
):
    if ratio not in ALLOWED_RATIOS:
        raise HTTPException(
            status_code=422,
            detail=f"ratio must be one of {list(ALLOWED_RATIOS)}, got {ratio!r}",
        )
    if writing_duration > total_image_duration:
        raise HTTPException(
            status_code=422,
            detail=(
                f"writing_duration ({writing_duration}) must be <= "
                f"total_image_duration ({total_image_duration})"
            ),
        )
    params = WhiteboardParams(
        total_image_duration=total_image_duration,
        writing_duration=writing_duration,
        ratio=ratio,
        draw_hand=draw_hand,
        color_while_drawing=color_while_drawing,
    )
    tmp_input = save_upload_to_tmp(image)
    manager = request.app.state.jobs
    snapshot = manager.submit(user_id, _style, params, tmp_input)
    return job_to_status(snapshot, request)
