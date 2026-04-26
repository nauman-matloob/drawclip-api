"""Base interfaces for video generation styles."""

from abc import ABC, abstractmethod
from typing import Callable, Optional, Type

from pydantic import BaseModel


class StyleParams(BaseModel):
    """Base class for style-specific generation parameters."""


class Style(ABC):
    """Abstract video-generation style.

    A concrete style provides:
      - a unique `name` (URL slug, e.g. "whiteboard")
      - a `description` for OpenAPI / catalog
      - a Pydantic `Params` model
      - a `render` method that takes an input image and produces an mp4
    """

    name: str = ""
    description: str = ""
    Params: Type[StyleParams] = StyleParams

    @abstractmethod
    def render(
        self,
        image_path: str,
        output_dir: str,
        params: StyleParams,
        progress_callback: Optional[Callable[[float], None]] = None,
    ) -> str:
        """Generate the video and return the absolute path to the mp4."""
