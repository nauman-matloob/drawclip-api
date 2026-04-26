"""Whiteboard sketch animation style — image redrawn by a hand cursor."""

from typing import Callable, Optional

from pydantic import Field

from styles.base import Style, StyleParams

from .render import generate, ALLOWED_RATIOS, MAX_VIDEO_DURATION


class WhiteboardParams(StyleParams):
    total_image_duration: int = Field(
        10, ge=1, le=MAX_VIDEO_DURATION,
        description=f"Total video duration in seconds (max {MAX_VIDEO_DURATION})",
    )
    writing_duration: int = Field(
        6, ge=1, le=MAX_VIDEO_DURATION,
        description="Seconds the hand spends drawing — must be <= total_image_duration",
    )
    ratio: str = Field("auto", description=f"Aspect ratio: one of {list(ALLOWED_RATIOS)}")
    draw_hand: bool = Field(True, description="Show the drawing hand cursor")
    color_while_drawing: bool = Field(
        False, description="Draw with original colors (True) or grayscale sketch (False)",
    )


class WhiteboardStyle(Style):
    name = "whiteboard"
    description = "Whiteboard-style sketch animation, drawn by a hand cursor."
    Params = WhiteboardParams

    def render(
        self,
        image_path: str,
        output_dir: str,
        params: WhiteboardParams,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> str:
        return generate(
            image_path=image_path,
            save_path=output_dir,
            total_image_duration=params.total_image_duration,
            writing_duration=params.writing_duration,
            ratio=params.ratio,
            draw_hand=params.draw_hand,
            color_while_drawing=params.color_while_drawing,
            progress_callback=progress_callback,
        )
