"""Titles a user has starred in the search, listed on their own page.

Per user, and the panel's own without accounts. Nothing here reaches the source
or a library: a favorite is a bookmark, so whoever may search may keep one.
"""

import asyncio
from typing import Literal

from fastapi import APIRouter, Depends, Request as HttpRequest
from pydantic import BaseModel, Field

from app import db
from app.auth.deps import OPEN_MODE_USER, current_user, require
from app.auth.permissions import Permission
from app.requests.models import now_iso

router = APIRouter(
    prefix="/api/favorites",
    tags=["favorites"],
    dependencies=[Depends(require(Permission.REQUEST, Permission.DOWNLOAD, mode="or"))],
)

Kind = Literal["movie", "tv", "anime"]


class FavoriteBody(BaseModel):
    source: str = Field(max_length=32)
    kind: Kind
    external_id: str = Field(max_length=64)
    title: str = Field(max_length=300)
    slug: str | None = Field(default=None, max_length=300)
    year: str | None = Field(default=None, max_length=8)
    poster: str | None = Field(default=None, max_length=500)
    anime_type: str | None = Field(default=None, max_length=32)


def _owner(http_request: HttpRequest) -> int | None:
    user = current_user(http_request)
    return None if user is OPEN_MODE_USER else user.id


# `IS` compares NULL to NULL, which `=` does not: it is the open-mode owner.
_MINE = "user_id IS ?"


def _list(owner: int | None) -> list[dict]:
    rows = db.query(
        f"SELECT * FROM jf_favorite WHERE {_MINE} ORDER BY created_at DESC, id DESC",
        (owner,),
    )
    return [dict(r) for r in rows]


@router.get("")
async def list_favorites(http_request: HttpRequest):
    return {"favorites": await asyncio.to_thread(_list, _owner(http_request))}


@router.post("", status_code=201)
async def add_favorite(body: FavoriteBody, http_request: HttpRequest):
    owner = _owner(http_request)

    def insert():
        # Starring twice is not an error: the second tap on a stale card.
        db.execute(
            "INSERT OR IGNORE INTO jf_favorite(user_id, source, kind, external_id, slug, "
            "title, year, poster, anime_type, created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (owner, body.source, body.kind, body.external_id, body.slug, body.title,
             body.year, body.poster, body.anime_type, now_iso()),
        )

    await asyncio.to_thread(insert)
    return {"ok": True}


@router.delete("/{source}/{kind}/{external_id}")
async def remove_favorite(source: str, kind: Kind, external_id: str, http_request: HttpRequest):
    owner = _owner(http_request)
    await asyncio.to_thread(
        db.execute,
        f"DELETE FROM jf_favorite WHERE {_MINE} AND source = ? AND kind = ? AND external_id = ?",
        (owner, source, kind, external_id),
    )
    return {"ok": True}
