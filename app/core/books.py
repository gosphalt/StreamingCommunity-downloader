"""Books from Internet Archive, public-domain items only.

The client sends an item identifier, never a URL: the file to fetch is chosen here
from the item's own metadata, so a request cannot name a host or a path. Only items
whose licence is declared public domain are searchable.
"""
import logging
import os
import re
import shutil

import requests

from app.core.headers import sanitize_filename
from app.core.paths import windows_path_problem
from app.progress import DownloadCancelledError

logger = logging.getLogger(__name__)

SEARCH_URL = "https://archive.org/advancedsearch.php"
META_URL = "https://archive.org/metadata/{}"
DOWNLOAD_URL = "https://archive.org/download/{}/{}"
TIMEOUT = 30
PUBLIC_DOMAIN = "licenseurl:*publicdomain*"

_ID = re.compile(r"^[A-Za-z0-9._-]{1,200}$")
_LANG = re.compile(r"^[a-z]{2,3}$")
# Lucene operators: a user's text must not change the shape of the query.
_LUCENE_SPECIAL = re.compile(r'([+\-&|!(){}\[\]^"~*?:\\/])')
# Formats an EPUB or PDF file is listed under in an item's metadata, best first.
_FORMATS = (("epub", ("EPUB",)), ("pdf", ("Text PDF", "PDF")))


class BookError(Exception):
    pass


def _quote(text: str) -> str:
    return _LUCENE_SPECIAL.sub(r"\\\1", text.strip())


def search(query: str = "", *, language: str = "", year_from: str = "", year_to: str = "",
           creator: str = "", rows: int = 40) -> list[dict]:
    """Public-domain books matching the text and the filters. Filters are optional."""
    clauses = ["mediatype:texts", PUBLIC_DOMAIN]
    if query.strip():
        clauses.append(f"({_quote(query)})")
    if language:
        if not _LANG.match(language):
            raise BookError("Lingua non valida")
        clauses.append(f"language:{language}")
    if creator.strip():
        clauses.append(f'creator:("{_quote(creator)}")')
    for value in (year_from, year_to):
        if value and not re.fullmatch(r"\d{1,4}", value):
            raise BookError("Anno non valido")
    if year_from or year_to:
        clauses.append(f"year:[{year_from or '*'} TO {year_to or '*'}]")
    params = [("q", " AND ".join(clauses)), ("rows", str(rows)), ("output", "json"),
              ("sort[]", "downloads desc")]
    params += [("fl[]", f) for f in ("identifier", "title", "creator", "year", "language")]
    r = requests.get(SEARCH_URL, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    docs = r.json().get("response", {}).get("docs", [])
    return [{
        "identifier": d.get("identifier", ""),
        "title": d.get("title") or d.get("identifier", ""),
        "creator": d.get("creator") if isinstance(d.get("creator"), str) else (d.get("creator") or [""])[0],
        "year": str(d.get("year") or ""),
        "language": d.get("language") if isinstance(d.get("language"), str) else (d.get("language") or [""])[0],
    } for d in docs if _ID.match(d.get("identifier", ""))]


def pick_file(identifier: str, fmt: str = "epub") -> dict:
    """The file to download for an item: the requested format, else the other one."""
    if not _ID.match(identifier or ""):
        raise BookError("Identificativo non valido")
    r = requests.get(META_URL.format(identifier), timeout=TIMEOUT)
    r.raise_for_status()
    files = r.json().get("files", [])
    order = dict(_FORMATS)
    wanted = order.get(fmt, order["epub"]) + tuple(f for k, v in _FORMATS if k != fmt for f in v)
    for label in wanted:
        for f in files:
            if f.get("format") == label and f.get("name"):
                return {"name": f["name"], "format": label, "size": int(f.get("size") or 0)}
    raise BookError("Nessun file EPUB o PDF per questo libro")


def book_path(output_dir: str, creator: str, title: str, year: str, ext: str) -> str:
    """Autore/Titolo (anno).ext, the layout Jellyfin reads for books."""
    author = sanitize_filename(creator.strip()) or "Autore sconosciuto"
    name = sanitize_filename(title.strip()) or "Senza titolo"
    if year and re.fullmatch(r"\d{4}", year):
        name = f"{name} ({year})"
    return os.path.join(output_dir, author, f"{name}.{ext}")


def download_book(identifier: str, title: str, creator: str, year: str, output_dir: str,
                  temp_dir: str, fmt: str = "epub", progress_factory=None,
                  cancel_event=None) -> str:
    """Download one book into output_dir and return the final path."""
    problem = windows_path_problem(output_dir)
    if problem:
        raise ValueError(problem)
    chosen = pick_file(identifier, fmt)
    ext = chosen["name"].rsplit(".", 1)[-1].lower()
    os.makedirs(temp_dir, exist_ok=True)
    source = os.path.join(temp_dir, f"{identifier}.{ext}")
    bar = progress_factory(total=max(chosen["size"], 1), phase="video") if progress_factory else None
    try:
        with requests.get(DOWNLOAD_URL.format(identifier, chosen["name"]), stream=True,
                          timeout=TIMEOUT) as r:
            r.raise_for_status()
            with open(source, "wb") as out:
                for chunk in r.iter_content(chunk_size=256 * 1024):
                    if cancel_event is not None and cancel_event.is_set():
                        raise DownloadCancelledError()
                    out.write(chunk)
                    if bar is not None:
                        bar.update(n=len(chunk), bytes=len(chunk))
    finally:
        if bar is not None:
            bar.close()
    final = book_path(output_dir, creator, title, year, ext)
    os.makedirs(os.path.dirname(final), exist_ok=True)
    # Staged as a dot-prefixed sibling, so a library scan never indexes a half-written file.
    staged = os.path.join(os.path.dirname(final), "." + os.path.basename(final))
    shutil.move(source, staged)
    os.replace(staged, final)
    return final
