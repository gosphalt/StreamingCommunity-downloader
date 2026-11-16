"""RaiPlay through yt-dlp: the public catalogue, and the download of one video.

No credentials, CSRF or Cloudflare: the catalogue and programme pages are plain
JSON. The stream is HLS, and yt-dlp's RaiPlay extractor does the rest. The panel
builds every URL from a path it validated; the client never supplies one.
"""
import logging
import os
import re
import time
import uuid

import requests

from app.core import paths, youtube
from app.core.paths import windows_path_problem

logger = logging.getLogger(__name__)

BASE = "https://www.raiplay.it"
CATALOGUE = "/dl/RaiTV/RaiPlayMobile/Prod/Config/programmiAZ-elenco.json"
CATALOGUE_TTL = 6 * 3600

# What the panel will fetch on RaiPlay's behalf. Anything else is refused before
# a request is made, so a path from the client can only name catalogue content.
_PROGRAM = re.compile(r"^/programmi/[a-z0-9-]{2,120}\.json$")
_VIDEO = re.compile(r"^/video/[A-Za-z0-9/_.-]{5,300}\.json$")
_TIMEOUT = 20

_catalogue: dict = {"at": 0.0, "items": []}


class RaiPlayError(Exception):
    """A user-facing refusal: DRM, a bad path, or a title RaiPlay does not serve."""


def is_video_path(path: str) -> bool:
    # The character class admits dots, so ".." must be refused explicitly:
    # "/video/../../x.json" would otherwise walk out of the video namespace.
    return bool(_VIDEO.match(path or "")) and ".." not in path


def _get_json(path: str) -> dict:
    r = requests.get(BASE + path, timeout=_TIMEOUT,
                     headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
                              "Accept": "application/json"})
    r.raise_for_status()
    return r.json()


def _slug_path(path_id: str) -> str | None:
    """The programme path from the catalogue's own id: .../programmi/<slug>/?json."""
    m = re.search(r"/programmi/([a-z0-9-]+)/\?json$", path_id or "")
    return f"/programmi/{m.group(1)}.json" if m else None


def catalogue() -> list[dict]:
    """Every programme in RaiPlay's A–Z index, cached for CATALOGUE_TTL."""
    if _catalogue["items"] and time.time() - _catalogue["at"] < CATALOGUE_TTL:
        return _catalogue["items"]
    rows = []
    for letter in _get_json(CATALOGUE).values():
        for row in letter if isinstance(letter, list) else []:
            path = _slug_path(row.get("PathID", ""))
            if not path or not row.get("name"):
                continue
            rows.append({"path": path, "name": row["name"].strip(),
                         "tipology": row.get("tipology") or "",
                         "year": str(row.get("PLRanno") or "")})
    _catalogue.update(at=time.time(), items=rows)
    return rows


def _kind(tipology: str, layout: str | None = None) -> str:
    """'film' for a single-video title, otherwise a series."""
    if (tipology or "").strip().lower() == "film" or layout == "single":
        return "film"
    return "tv"


def search(query: str, limit: int = 40) -> list[dict]:
    """Programmes whose name contains the query, in catalogue order."""
    needle = (query or "").strip().casefold()
    if not needle:
        return []
    hits = [row for row in catalogue() if needle in row["name"].casefold()]
    return [{"path": row["path"], "name": row["name"], "year": row["year"],
             "media_type": _kind(row["tipology"])} for row in hits[:limit]]


def program(path: str) -> dict:
    """One programme: its kind, its season sets and, for a film, its video."""
    if not _PROGRAM.match(path or ""):
        raise RaiPlayError("Percorso programma non valido")
    data = _get_json(path)
    info = data.get("program_info") or {}
    seasons = []
    for block in data.get("blocks") or []:
        for item in block.get("sets") or []:
            if item.get("path_id"):
                seasons.append({"path": item["path_id"], "name": item.get("name") or ""})
    return {
        "path": path,
        "name": info.get("name") or "",
        "year": str(info.get("year") or ""),
        "description": info.get("description") or "",
        "media_type": _kind(info.get("typology") or "", data.get("layout") or info.get("layout")),
        "seasons": seasons,
        "video": data.get("first_item_path") if _kind(info.get("typology") or "", info.get("layout")) == "film" else None,
    }


def season(path: str) -> list[dict]:
    """The episodes of one season set, each with the video path the download takes."""
    if not re.match(r"^/programmi/[a-z0-9-]{2,120}/ContentSet-[0-9a-f-]{36}\.json$", path or ""):
        raise RaiPlayError("Percorso stagione non valido")
    out = []
    for item in _get_json(path).get("items") or []:
        video = item.get("path_id") or ""
        if not is_video_path(video):
            continue
        out.append({"video": video, "title": item.get("episode_title") or item.get("name") or "",
                    "season": str(item.get("season") or ""),
                    "episode": str(item.get("episode") or ""),
                    "duration": item.get("duration_in_minutes") or ""})
    return out


def _check_playable(video_path: str) -> dict:
    """The video's own record, refused if RaiPlay locks it behind DRM."""
    if not is_video_path(video_path):
        raise RaiPlayError("Percorso video non valido")
    info = _get_json(video_path)
    drm = ((info.get("rights_management") or {}).get("rights") or {}).get("drm") or {}
    if drm:
        raise RaiPlayError("Contenuto protetto da DRM: non scaricabile")
    return info


def download_raiplay(video_path: str, title: str, kind: str, output_dir: str, temp_dir: str,
                     year: str | None = None, series: str | None = None,
                     season: str | None = None, episode: str | None = None,
                     progress_factory=None, cancel_event=None) -> str:
    """Download one RaiPlay video into the library and return its final path."""
    problem = windows_path_problem(output_dir)
    if problem:
        raise ValueError(problem)
    _check_playable(video_path)
    url = BASE + video_path[:-len(".json")] + ".html"
    source = youtube.fetch_media(url, temp_dir, uuid.uuid4().hex,
                                 progress_factory, cancel_event)
    # The source already carries the configured container, so the library path
    # is named for the same one: nothing is re-encoded to fit a template.
    container = os.path.splitext(source)[1].lstrip(".")
    if kind == "film":
        final = paths.film_path(output_dir, title, year, container=container)
    else:
        final = paths.episode_path(output_dir, series or title, int(season or 1),
                                   episode or "1", year, container=container)
    final = youtube.place_file(source, final)
    logger.info("RaiPlay download finished: %s", final)
    return final
