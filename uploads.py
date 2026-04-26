"""Helpers for accepting image uploads."""

import os
import shutil
import tempfile

from fastapi import HTTPException, UploadFile

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def save_upload_to_tmp(upload: UploadFile) -> str:
    """Save the upload to a temporary file and return its absolute path.

    Raises HTTPException(400) if the extension is not whitelisted.
    """
    ext = os.path.splitext(upload.filename or "")[1].lower()
    if ext not in ALLOWED_EXT:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file extension '{ext}'. Allowed: {sorted(ALLOWED_EXT)}",
        )
    fd, tmp_path = tempfile.mkstemp(suffix=ext)
    with os.fdopen(fd, "wb") as out:
        shutil.copyfileobj(upload.file, out)
    return tmp_path
