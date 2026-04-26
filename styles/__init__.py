"""Registry of available styles."""

from typing import Dict, List, Optional

from .base import Style, StyleParams
from .whiteboard.style import WhiteboardStyle

_REGISTRY: Dict[str, Style] = {
    style.name: style for style in [
        WhiteboardStyle(),
    ]
}


def list_styles() -> List[Style]:
    return list(_REGISTRY.values())


def get_style(name: str) -> Optional[Style]:
    return _REGISTRY.get(name)


__all__ = ["Style", "StyleParams", "list_styles", "get_style"]
