import asyncio
import logging

import requests
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.deps import require
from app.auth.permissions import Permission
from app.core import raiplay

logger = logging.getLogger(__name__)

# Browsing RaiPlay is part of downloading from it, so the same permission as YouTube.
router = APIRouter(prefix="/api/raiplay", tags=["raiplay"])
CAN_DOWNLOAD = [Depends(require(Permission.DOWNLOAD))]


def _upstream(exc: Exception) -> HTTPException:
    logger.warning("RaiPlay request failed: %s", exc)
    return HTTPException(status_code=502, detail="RaiPlay non risponde")


@router.get("/search", dependencies=CAN_DOWNLOAD)
async def search(q: str = Query(..., min_length=1, max_length=200)):
    try:
        return await asyncio.to_thread(raiplay.search, q)
    except requests.RequestException as e:
        raise _upstream(e)


@router.get("/program", dependencies=CAN_DOWNLOAD)
async def program(path: str = Query(..., max_length=300)):
    try:
        return await asyncio.to_thread(raiplay.program, path)
    except raiplay.RaiPlayError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests.RequestException as e:
        raise _upstream(e)


@router.get("/season", dependencies=CAN_DOWNLOAD)
async def season(path: str = Query(..., max_length=300)):
    try:
        return await asyncio.to_thread(raiplay.season, path)
    except raiplay.RaiPlayError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests.RequestException as e:
        raise _upstream(e)
