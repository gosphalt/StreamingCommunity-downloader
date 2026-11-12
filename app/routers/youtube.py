import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from yt_dlp.utils import DownloadError

from app import config
from app.auth.deps import require
from app.auth.permissions import Permission
from app.core import youtube
from app.core.paths import validate_library_path

logger = logging.getLogger(__name__)

# Per route, not on the router: a MANAGE_SETTINGS grant alone must open the PUT,
# and a DOWNLOAD grant alone must open search and the path read.
router = APIRouter(prefix="/api/youtube", tags=["youtube"])
CAN_DOWNLOAD = [Depends(require(Permission.DOWNLOAD))]
CAN_MANAGE = [Depends(require(Permission.MANAGE_SETTINGS))]


class PathUpdate(BaseModel):
    path: str = Field(max_length=1000)


@router.get("/search", dependencies=CAN_DOWNLOAD)
async def search(q: str = Query(..., min_length=1, max_length=200)):
    try:
        return await asyncio.to_thread(youtube.search, q.strip())
    except DownloadError as e:
        logger.warning("YouTube search failed: %s", e)
        raise HTTPException(status_code=502, detail="YouTube non risponde o la ricerca è fallita")


@router.get("/path", dependencies=CAN_DOWNLOAD)
def get_path():
    return {"path": youtube.download_dir(), "default": youtube.default_dir()}


@router.put("/path", dependencies=CAN_MANAGE)
def set_path(body: PathUpdate):
    try:
        path = validate_library_path(body.path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    config.update_data({"youtube_dir": path})
    return {"path": path}
