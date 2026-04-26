"""User identification for the API.

Temporary scheme: the client passes its own user UUID via the ``X-User-Id``
HTTP header. Format is validated (must be a real UUID string), but ownership
is otherwise unauthenticated — anyone who knows a UUID can claim it.

To be replaced with proper API key / JWT auth once the SaaS has a frontend
and a user database.

For local development, use the seed UUID printed by:

    python3 -c "import uuid; print(uuid.uuid4())"

…or the one shipped in the project README.
"""

import uuid

from fastapi import Header, HTTPException


def get_user_id(
    x_user_id: str = Header(
        ...,
        alias="X-User-Id",
        description="UUID identifying the calling user (any valid UUID string)",
    ),
) -> str:
    """FastAPI dependency that extracts and validates the X-User-Id header."""
    raw = (x_user_id or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="X-User-Id header must not be empty")
    try:
        parsed = uuid.UUID(raw)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"X-User-Id must be a valid UUID, got {raw!r}",
        )
    return str(parsed)
