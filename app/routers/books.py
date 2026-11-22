import asyncio
import logging
from typing import Literal

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request as HttpRequest
from pydantic import BaseModel, Field

from app.auth.deps import require
from app.auth.permissions import Permission
from app.config import read_data
from app.core import books
from app.jobs import job_manager
from app.routers.downloads import _acting_user_id

logger = logging.getLogger(__name__)

# Books sit beside the other sources: finding and downloading them is the DOWNLOAD permission.
router = APIRouter(prefix="/api/books", tags=["books"])
CAN_DOWNLOAD = [Depends(require(Permission.DOWNLOAD))]


class BookDownloadRequest(BaseModel):
    identifier: str = Field(..., max_length=200)
    title: str = Field(..., min_length=1, max_length=300)
    creator: str = Field(default="", max_length=200)
    year: str = Field(default="", pattern=r"^(\d{4})?$")
    fmt: Literal["epub", "pdf"] = "epub"


def _book_library() -> str:
    for lib in read_data().get("libraries", []):
        if lib.get("type") == "book" and lib.get("path"):
            return lib["path"]
    raise HTTPException(status_code=400, detail="Imposta prima la libreria Libri in Impostazioni")


@router.get("/search", dependencies=CAN_DOWNLOAD)
async def search(q: str = Query("", max_length=200),
                 language: str = Query("", max_length=3),
                 year_from: str = Query("", max_length=4),
                 year_to: str = Query("", max_length=4),
                 creator: str = Query("", max_length=120)):
    try:
        return await asyncio.to_thread(books.search, q, language=language, year_from=year_from,
                                       year_to=year_to, creator=creator)
    except books.BookError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except requests.RequestException as e:
        logger.warning("Internet Archive search failed: %s", e)
        raise HTTPException(status_code=502, detail="Internet Archive non risponde")


@router.post("/download", status_code=202, dependencies=CAN_DOWNLOAD)
def download(body: BookDownloadRequest, http_request: HttpRequest):
    job_id = job_manager.submit_book(
        body.identifier, body.title, body.creator, body.year, _book_library(),
        fmt=body.fmt, user_id=_acting_user_id(http_request),
    )
    return {"job_id": job_id, "status": "queued"}
