import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth.deps import require
from app.auth.permissions import Permission
from app.core import animeunity
from app.routers.tv import _mark_in_library

logger = logging.getLogger(__name__)
router = APIRouter(
    prefix="/api/anime",
    tags=["anime"],
    dependencies=[Depends(require(Permission.REQUEST, Permission.DOWNLOAD, mode="or"))],
)


@router.get("/default-audio")
def default_audio():
    """The audio an anime title starts on. Read-only; saved from Settings."""
    from app.config import anime_default_audio
    return {"audio": anime_default_audio()}


@router.get("/{anime_id}/episodes")
async def get_episodes(anime_id: str, title: str = Query("", max_length=200),
                       year: str = Query("", max_length=10)):
    """Fetch all episodes for an anime from AnimeUnity info_api."""
    try:
        episodes = await asyncio.to_thread(animeunity.get_episodes, anime_id)
    except Exception as e:
        logger.exception("AnimeUnity episodes error for %s", anime_id)
        raise HTTPException(status_code=502, detail=str(e))
    # Same check as a TV season: an anime series sits in season 1 of its folder,
    # and an anime film matches nothing there, so it is never flagged.
    if title:
        # The source calls the number "number"; the check reads "n", as TV does.
        rows = [{"n": str(e.get("number"))} for e in episodes]
        await asyncio.to_thread(_mark_in_library, rows, title, 1, year, anime_id, "anime")
        for episode, row in zip(episodes, rows):
            episode["in_library"] = row.get("in_library", False)
    return episodes
