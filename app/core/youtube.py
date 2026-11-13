"""YouTube through yt-dlp: search, and the download of one video.

Not an HLS source, so none of m3u8.py applies. The client never supplies a URL to
fetch: it supplies an 11-character id, and the watch URL is built here. Every
download lands in one folder for all of YouTube, chosen in the YouTube tab.
"""
import logging
import os
import re
import shutil
from urllib.parse import parse_qs, urlparse

import yt_dlp
from yt_dlp.utils import DownloadError

from app import config
from app.core import container
from app.core.ffmpeg_path import get_ffmpeg_exe
from app.core.headers import sanitize_filename
from app.core.paths import windows_path_problem
from app.progress import DownloadCancelledError

logger = logging.getLogger(__name__)

WATCH_URL = "https://www.youtube.com/watch?v="
# H.264 + AAC when the source has them: a stream copy into either container,
# never a re-encode. The fallbacks only keep a video that has no such streams.
FORMAT = "bv*[vcodec^=avc1]+ba[ext=m4a]/bv*+ba/b"

_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")
_HOSTS = {"youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be"}


def is_video_id(value: str) -> bool:
    return bool(_ID.match(value or ""))


def video_id_from_link(text: str) -> str | None:
    """The video id in a YouTube link, or None. A bare word is not an id here:
    an eleven-letter search term would otherwise be taken for one."""
    text = (text or "").strip()
    if "://" not in text:
        text = "https://" + text
    try:
        url = urlparse(text)
    except ValueError:
        return None
    if url.scheme not in ("http", "https") or url.hostname not in _HOSTS:
        return None
    parts = url.path.split("/")
    if url.hostname == "youtu.be":
        candidate = url.path.lstrip("/")
    elif url.path == "/watch":
        candidate = parse_qs(url.query).get("v", [""])[0]
    elif len(parts) > 2 and parts[1] in ("shorts", "embed", "live"):
        candidate = parts[2]
    else:
        return None
    return candidate if is_video_id(candidate) else None


def default_dir() -> str:
    # Read per call: VIDEOS_DIR can be repointed (tests do), and a constant
    # would keep the path it had at import.
    return str(config.VIDEOS_DIR / "YouTube")


def download_dir() -> str:
    return config.read_data().get("youtube_dir") or default_dir()


# Codes YouTube serves titles in. "" keeps the uploader's own wording.
LANGUAGES = ("", "it", "en", "es", "fr", "de", "pt", "ja", "ko")


def search_lang() -> str:
    lang = config.read_data().get("youtube_lang") or ""
    return lang if lang in LANGUAGES else ""


def _lang_opts(lang: str) -> dict:
    # Only titles that have a translation change; the rest keep their own.
    return {"extractor_args": {"youtube": {"lang": [lang]}}} if lang else {}


def _card(entry: dict) -> dict:
    return {
        "id": entry["id"],
        "title": entry.get("title") or entry["id"],
        "channel": entry.get("channel") or entry.get("uploader") or "",
        "duration": entry.get("duration"),
    }


def search(query: str, limit: int = 20, lang: str = "") -> list[dict]:
    """Results for a query, or the one video a link points at. Raises DownloadError."""
    video_id = video_id_from_link(query)
    if video_id:
        info = yt_dlp.YoutubeDL({"quiet": True, "noplaylist": True, **_lang_opts(lang)}).extract_info(
            WATCH_URL + video_id, download=False)
        return [_card(info)]
    opts = {"quiet": True, "skip_download": True, "extract_flat": True, **_lang_opts(lang)}
    info = yt_dlp.YoutubeDL(opts).extract_info(f"ytsearch{limit}:{query}", download=False)
    return [_card(e) for e in info.get("entries") or [] if e and e.get("id")]


def download_youtube(video_id: str, title: str, output_dir: str, temp_dir: str,
                     progress_factory=None, cancel_event=None) -> str:
    """Download one video into output_dir and return the final path."""
    if not is_video_id(video_id):
        raise ValueError("Identificativo video non valido")
    problem = windows_path_problem(output_dir)
    if problem:
        raise ValueError(problem)

    os.makedirs(temp_dir, exist_ok=True)
    bar = progress_factory(total=100, phase="video") if progress_factory else None
    # yt-dlp reports each stream (video, then audio) from zero; the bar must not
    # go backwards, so it counts the highest percentage reached so far.
    seen = {"done": 0, "top": 0}

    def hook(status: dict):
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError()
        if status.get("status") != "downloading" or bar is None:
            return
        done = status.get("downloaded_bytes") or 0
        total = status.get("total_bytes") or status.get("total_bytes_estimate") or 0
        if done < seen["done"]:
            seen["done"] = 0  # the next stream starts at zero
        delta_bytes = done - seen["done"]
        seen["done"] = done
        # shortcut: the percentage is per stream, so the audio stream moves the
        # bar only once it passes the video's figure; upgrade by summing the sizes
        # of requested_formats if a long audio tail looks like a stall.
        pct = min(99, int(done * 100 / total)) if total else seen["top"]
        bar.update(n=max(0, pct - seen["top"]), bytes=delta_bytes)
        seen["top"] = max(seen["top"], pct)

    opts = {
        "format": FORMAT,
        "merge_output_format": container.configured(),
        "noplaylist": True,
        "outtmpl": os.path.join(temp_dir, "%(id)s.%(ext)s"),
        "ffmpeg_location": get_ffmpeg_exe(),
        "progress_hooks": [hook],
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([WATCH_URL + video_id])
    except DownloadError:
        if cancel_event is not None and cancel_event.is_set():
            raise DownloadCancelledError()
        raise
    finally:
        if bar is not None:
            bar.close()
    if cancel_event is not None and cancel_event.is_set():
        raise DownloadCancelledError()

    # The merged file is <id>.<container>; a single-stream fallback keeps its own
    # extension. Partial and temp files are never the result.
    names = [n for n in os.listdir(temp_dir)
             if n.startswith(f"{video_id}.") and not n.endswith((".part", ".ytdl"))]
    preferred = [n for n in names if n == f"{video_id}.{container.configured()}"]
    if not names:
        raise RuntimeError("yt-dlp non ha prodotto nessun file")
    if not preferred and len(names) > 1:
        raise RuntimeError(f"file inattesi dopo il download: {', '.join(names)}")
    source = os.path.join(temp_dir, (preferred or names)[0])

    ext = os.path.splitext(source)[1]
    os.makedirs(output_dir, exist_ok=True)
    final = os.path.join(output_dir, f"{sanitize_filename(title)} [{video_id}]{ext}")
    # Staged as a dot-prefixed sibling so a library scan never indexes a half-written
    # file; os.replace is atomic only within one filesystem, hence the sibling.
    staged = os.path.join(output_dir, "." + os.path.basename(final))
    shutil.move(source, staged)
    os.replace(staged, final)
    # Jellyfin reads Film.mkv and Film.mp4 in one folder as two versions of a film.
    stem = os.path.splitext(final)[0]
    for other in (".mkv", ".mp4"):
        if other != ext and os.path.exists(stem + other):
            os.remove(stem + other)
    logger.info("YouTube download finished: %s", final)
    return final
