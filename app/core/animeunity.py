import json
import logging

import requests
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)

def host() -> str:
    """AnimeUnity's current host. Read per call: Settings can change it live."""
    from app.config import configured_animeunity_host
    return configured_animeunity_host()


# A ceiling on what one call may normalise, for the day the source answers with
# more than a page.
MAX_RESULTS = 60

_scraper = None


def _get_scraper():
    global _scraper
    if _scraper is None:
        try:
            import cloudscraper
            _scraper = cloudscraper.create_scraper(
                browser={"browser": "firefox", "platform": "darwin", "desktop": True}
            )
        except ImportError:
            logger.warning("cloudscraper not installed, falling back to requests.Session")
            _scraper = requests.Session()
    return _scraper


def home_props() -> dict:
    """The home page's props: the carousel, the latest episodes and the lists."""
    return _page_props("/")


def _page_props(path: str, params: dict | None = None) -> dict:
    """The Inertia payload of an HTML page: the ``data-page`` attribute's props.

    BeautifulSoup has already decoded the attribute's entities, so it is parsed
    as it is — unescaping it again would corrupt any `&amp;` inside a plot.
    """
    r = _get_scraper().get(f"https://{host()}{path}", params=params,
                           headers={"Accept": "text/html"}, timeout=20)
    if not r.ok:
        raise RuntimeError(f"AnimeUnity {path} failed: HTTP {r.status_code}")
    tag = BeautifulSoup(r.text, "lxml").find(attrs={"data-page": True})
    if tag is None:
        raise RuntimeError(f"AnimeUnity {path}: no page payload")
    return json.loads(tag["data-page"])["props"]


def _genres(value) -> list[str]:
    """Genre names, whichever shape Laravel cast them into this time.

    Rows arrive as dicts with pivot tables, sometimes as plain strings, and
    occasionally as a JSON string. The panel wants names, and the alternative to
    tolerating all three is a TypeError raised in the middle of a search.
    """
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    names = []
    for g in (value or []):
        name = g.get("name") if isinstance(g, dict) else g
        if isinstance(name, str) and name.strip():
            names.append(name.strip())
    return names


def normalize_title(t: dict) -> dict | None:
    """One raw record into the shape the panel renders, or None if unusable."""
    title_str = (t.get("title") or t.get("title_it") or "").strip()
    id_num = t.get("id")
    if not title_str or id_num is None:
        return None
    slug = t.get("slug", "") or ""
    images = t.get("images") or {}
    studios = t.get("studios") or []
    original = (t.get("title_ja") or "").strip()
    return {
        "id": f"{id_num}-{slug}" if slug else str(id_num),
        "name": title_str,
        "type": "anime",
        # The source's own classification — movie, tv, ova, ona, special. Kept
        # beside `type` rather than in it: `type` is "anime" for every record and
        # the whole anime flow keys off that, from the detail modal to the
        # episodes endpoint to the job kind. Without this the card had nothing to
        # go on, so it labelled every film a TV series.
        "media_type": t.get("type") or "",
        "slug": slug,
        # Absolute URLs, so the frontend does not route them through /api/image.
        "poster": images.get("poster") or images.get("cover") or "",
        "episodes_count": t.get("total_episodes") or 0,
        "plot": t.get("plot") or "",
        "genres": _genres(t.get("genres")),
        # An Italian dub is a language variant of the same title now, not a
        # record of its own.
        "dubbed": any(v.get("language") == "ita" for v in (t.get("variants") or [])),
        "score": t.get("score"),
        "release_date": str(t["year"]) if t.get("year") else "",
        "backdrop": images.get("banner") or "",
        "studio": studios[0].get("name", "") if studios and isinstance(studios[0], dict) else "",
        "status": t.get("default_status") or "",
        "season": t.get("season") or "",
        # The Japanese title, when it differs from the one shown.
        "original_name": original if original != title_str else "",
    }


def _normalize_titles(titles: list) -> list[dict]:
    """Convert raw AnimeUnity records to the normalized format the frontend renders."""
    results, seen = [], set()
    for t in titles:
        item = normalize_title(t)
        if item is None or item["id"] in seen:
            continue
        seen.add(item["id"])
        results.append(item)
        if len(results) >= MAX_RESULTS:
            break
    return results


def search(query: str = "", *, page: int = 1, media_type: str | None = None,
           dubbed: bool = False, genre: int | None = None, year: int | None = None,
           order: str | None = None, status: str | None = None) -> list[dict]:
    """Search AnimeUnity through ``/archivio/get-animes``.

    Not ``/livesearch``, which this used to call: the source caps that at
    **eight records** for every query, with no way to ask for more and no
    filters — measured, not guessed. The archive endpoint answers thirty at a
    time, takes a row offset, and applies both filters itself.

    Both filters go to the source rather than to what comes back: filtering here
    could only ever narrow one page, and would answer "no Italian dub" for a show
    whose dub sat on page two. ``page`` is 1-based and becomes the row offset.

    An empty ``query`` is the archive itself, which is what Esplora browses;
    ``genre`` (the source's id), ``year``, ``order`` and ``status`` are its filters.
    """
    params = {"query": query, "page": max(page, 1)}
    if dubbed:
        params["language"] = "ita"
    if media_type:
        params["type"] = media_type.lower()
    if genre:
        params["genres[]"] = genre
    for key, value in (("year", year), ("sort_by", order), ("status", status)):
        if value:
            params[key] = value

    # No rows is an answer, not a failure: a query that matches nothing is an
    # empty page, and the frontend stops offering "Carica altri" there.
    animes = _page_props("/archive", params)["animes"]
    return _normalize_titles(animes.get("data") or [])


def browse_options() -> dict:
    """The genres the archive can be filtered by, from the archive page's props."""
    genres = _page_props("/archive")["animeGenres"]
    return {"genres": [{"id": g["id"], "name": g["name"]} for g in genres]}


def get_episodes(anime_id: str) -> list[dict]:
    """
    Every episode of an anime, from ``/api/anime/{id}/episodes``, which answers
    120 at a time: ``start`` is the first episode number wanted.
    Returns the source's episode records (id, number, videos, …).
    """
    scraper = _get_scraper()
    numeric_id = str(anime_id).split("-", 1)[0]
    url = f"https://{host()}/api/anime/{numeric_id}/episodes"

    episodes: list[dict] = []
    total = None
    while total is None or len(episodes) < total:
        r = scraper.get(url, params={"start": len(episodes) + 1}, timeout=15)
        r.raise_for_status()
        body = r.json()
        total = body.get("total", 0)
        batch = body.get("episodes") or []
        if not batch:
            break
        episodes.extend(batch)
    return episodes


class NoPlayableVideoError(RuntimeError):
    """No video on offer for the languages asked. A retry cannot change that."""


def _visible_videos(episode: dict) -> list[dict]:
    return [v for v in (episode.get("videos") or []) if not v.get("is_hidden")]


def _pick_video(episode: dict, languages=("ita",)) -> dict:
    """The video to download, in the first of ``languages`` on offer.

    A visible video in that language wins. Failing that, a hidden one in that
    language: the source hides some videos without taking them down, and their
    streams still answer. A hidden video is never taken for another language.
    Only when no requested language is on offer at all does a visible video of
    another language stand in, as it always has.

    AnimeUnity has one video per language, each a complete stream with its audio
    in-band, so a language is a video, not a track of one.
    """
    visible = _visible_videos(episode)
    hidden = [v for v in (episode.get("videos") or []) if v.get("is_hidden")]
    for lang in languages:
        for pool in (visible, hidden):
            for video in pool:
                if video.get("language") == lang:
                    return video
    if visible:
        return visible[0]
    raise NoPlayableVideoError(
        f"L'episodio {episode.get('number')} non ha video in "
        f"{' o '.join(languages)} su AnimeUnity")


def _get_embed_content(anime_id: str, video_id: int) -> tuple[str, str]:
    """
    Fetch the vixcloud embed page for one video of an episode.
    Returns (script_text, embed_url) — same shape as film._get_iframe().
    """
    scraper = _get_scraper()
    au_host = host()

    # The episode page's props carry the embed URL for the video in the path.
    embed_url = _page_props(f"/anime/{anime_id}/{video_id}").get("embedUrl") or ""

    if not embed_url.startswith("http"):
        raise RuntimeError(f"Unexpected embed URL for video {video_id}: {embed_url[:100]!r}")

    from app.core._shared import apply_video_host
    embed_url = apply_video_host(embed_url)
    logger.info("Video %s embed URL: %s", video_id, embed_url[:80])

    # Fetch the vixcloud embed page. vixcloud now serves this /embed/ HTML
    # page behind Cloudflare, so plain requests.get returns a 403 challenge page.
    # Use the cloudscraper session to clear the challenge. (The downstream
    # /playlist, /storage/enc.key and CDN segment URLs are NOT Cloudflare-gated
    # and still work with plain requests.)
    req_embed = scraper.get(
        embed_url,
        headers={"Referer": f"https://{au_host}/"},
        timeout=15,
    )
    req_embed.raise_for_status()

    soup = BeautifulSoup(req_embed.text, "lxml")
    body = soup.find("body")
    if not body:
        raise RuntimeError("Empty embed page body")
    script = body.find("script")
    if not script:
        raise RuntimeError("No script tag found in vixcloud embed page")

    logger.info("Embed script (first 400 chars): %s", script.text[:400])
    return script.text, embed_url


def get_episode_languages(episode: dict) -> dict:
    """Audio languages of one anime episode: one per video. No subtitles are offered."""
    audio = list(dict.fromkeys(v["language"] for v in (episode.get("videos") or [])
                               if v.get("language")))
    return {"audio": audio, "subtitles": []}


def download_anime_episode(
    anime_id: str,
    episode: dict,
    anime_name: str,
    anime_type: str = "tv",
    output_dir: str = "videos",
    temp_dir: str = None,
    progress_factory=None,
    cancel_event=None,
    year: str = None,
    audio_languages: list[str] = None,
    subtitle_languages: list[str] = None,
    strict_audio: bool = False,
) -> str:
    """
    Full download pipeline for a single anime episode.
    - Movies (anime_type="movie" or "film", any case): videos/AnimeName (YYYY)/AnimeName.mkv
    - Anything else (TV, ONA, OVA, Special, …): videos/AnimeName/Season 01/AnimeName S01E01.mkv

    The extension is whatever app.core.container is configured to write.
    """
    audio_languages = audio_languages or ["ita"]
    subtitle_languages = subtitle_languages or []

    from app.core.film import _collect_audio_tracks, _collect_subtitle_tracks
    from app.core._shared import _parse_content, _get_m3u8_url, _get_m3u8_key
    from app.core.m3u8 import download_m3u8
    from app.core.paths import anime_path

    episode_number = str(episode.get("number", "0"))

    video = _pick_video(episode, audio_languages)
    embed_content, embed_url = _get_embed_content(anime_id, video["id"])
    json_win_video, json_win_param = _parse_content(embed_content, embed_url)

    logger.info(
        "Anime episode %s — video_id=%s token=%.8s...",
        episode_number, json_win_video.get("id"), json_win_param.get("token", ""),
    )

    m3u8_url = _get_m3u8_url(json_win_video, json_win_param)
    m3u8_key = _get_m3u8_key(json_win_video, json_win_param, embed_url)

    audio_track_urls = _collect_audio_tracks(
        m3u8_url, embed_url, audio_languages, strict=strict_audio
    )
    subtitle_track_urls = _collect_subtitle_tracks(m3u8_url, embed_url, subtitle_languages)

    # A folder a person associated with this anime wins — which is how the
    # parts of one series, separate titles at the source, land in one folder
    # at the season and episode their offsets say (app/library.py).
    from app.core.paths import is_anime_series
    from app.library import destination

    dest_path = destination("anime", anime_id, root=output_dir, episode=episode_number,
                            year=year, single_file=not is_anime_series(anime_type))
    if not dest_path and is_anime_series(anime_type):
        # The series' folder already on disk, whatever year it carries (#24).
        from app.requests.resolver import ANIME, series_episode_path

        dest_path = series_episode_path(ANIME, anime_id, output_dir, anime_name, 1,
                                        episode_number, year, anime_type=anime_type)
    dest_path = dest_path or anime_path(output_dir, anime_name, episode_number, anime_type, year)

    final_path = download_m3u8(
        m3u8_index=m3u8_url,
        key=m3u8_key,
        output_filename=dest_path,
        temp_dir=temp_dir,
        progress_factory=progress_factory,
        referer=embed_url,
        cancel_event=cancel_event,
        audio_languages=audio_languages,
        subtitle_languages=subtitle_languages,
        audio_track_urls=audio_track_urls,
        subtitle_track_urls=subtitle_track_urls,
    )

    # download_m3u8 returns the real output path: the destination is built in
    # whatever container is configured, and the remux keeps it.
    return final_path or dest_path
