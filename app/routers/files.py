import asyncio
import logging
import os
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from app.auth.deps import require
from app.auth.permissions import Permission
from app.config import VIDEOS_DIR, read_data
from app.core import container

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/files", tags=["files"])

# Browsing and streaming is separate from mutating: a user may be allowed to
# watch the library without being able to delete half of it.
CAN_VIEW = [Depends(require(Permission.VIEW_LIBRARY))]
CAN_MANAGE = [Depends(require(Permission.MANAGE_FILES))]


def _safe_path_strict(rel_path: str, keep_link: bool = False) -> Path:
    """Resolve path inside VIDEOS_DIR; ValueError/FileNotFoundError otherwise.

    ``keep_link`` is for delete, rename and move: a symlink there is the thing
    acted on, not the folder it points to. Serving files still follows it.

    The root itself is refused: "", "." or "a/.." resolve to it, and a delete or
    rename of it would take the whole library.
    """
    base = VIDEOS_DIR.resolve()
    target = (base / rel_path).resolve()
    if target == base or not target.is_relative_to(base):
        raise ValueError("Invalid path")
    if not target.exists():
        raise FileNotFoundError("Not found")
    if keep_link:
        raw = Path(os.path.normpath(base / rel_path))
        if raw.is_symlink() and raw.is_relative_to(base):
            return raw
    return target


def _safe_path(rel_path: str, keep_link: bool = False) -> Path:
    """_safe_path_strict, as HTTP errors."""
    try:
        return _safe_path_strict(rel_path, keep_link)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid path")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="File not found")


# ── Disk usage ─────────────────────────────────────────────────────────────────
#
# Reported per *volume*, not per library: in practice all three libraries are
# folders on the same mount, and three identical figures said nothing useful
# while costing three stats of a possibly sleeping NFS share.

_DISK_USAGE_TTL = 20  # seconds; the file manager reloads on every navigation
_disk_usage_cache: dict = {"at": 0.0, "data": None}


def _library_paths() -> list[str]:
    paths = [lib["path"] for lib in read_data().get("libraries", []) if lib.get("path")]
    return paths or [str(VIDEOS_DIR)]


def _compute_disk_usage() -> dict:
    now = time.monotonic()
    if _disk_usage_cache["data"] is not None and now - _disk_usage_cache["at"] < _DISK_USAGE_TTL:
        return _disk_usage_cache["data"]

    volumes: dict[int, dict] = {}
    errors: list[str] = []
    for path in _library_paths():
        try:
            device = os.stat(path).st_dev
        except OSError as e:
            # An unmounted or mistyped library path is an expected failure mode
            # and must not blank out the volumes that are fine.
            errors.append(str(e))
            continue
        if device in volumes:
            volumes[device]["paths"].append(path)
            continue
        total, used, free = shutil.disk_usage(path)
        volumes[device] = {"total": total, "used": used, "free": free, "paths": [path]}

    result = {"volumes": list(volumes.values()), "errors": errors}
    _disk_usage_cache["at"] = now
    _disk_usage_cache["data"] = result
    return result


@router.get("/disk-usage", dependencies=CAN_VIEW)
async def get_disk_usage():
    return await asyncio.to_thread(_compute_disk_usage)


def _list_dir(directory: Path, base: Path, excluded: set) -> list[dict]:
    """One level only: a library of thousands of files is never walked whole.

    A folder reports just whether it holds anything (``empty``); the page asks
    for its contents when it is opened. A symlinked folder is listed, not entered.
    """
    entries = []
    try:
        for item in sorted(directory.iterdir()):
            if item.name in excluded:
                continue
            if item.is_dir():
                empty = item.is_symlink() or not any(c.name not in excluded for c in item.iterdir())
                entries.append({
                    "name": item.name,
                    "type": "directory",
                    "path": str(item.relative_to(base)),
                    "empty": empty,
                })
            elif item.is_file():
                stat = item.stat()
                entries.append({
                    "name": item.name,
                    "type": "file",
                    "path": str(item.relative_to(base)),
                    "size": stat.st_size,
                    "mtime": stat.st_mtime,
                })
    except PermissionError:
        pass
    return entries


def _build_library_tree(directory: Path, depth: int = 0, max_depth: int = 3) -> list[dict]:
    """Recursively list subdirectories only (no files) for library navigation."""
    if depth >= max_depth:
        return []
    entries = []
    try:
        for item in sorted(directory.iterdir()):
            if item.is_dir() and not item.name.startswith('.'):
                entries.append({
                    "name": item.name,
                    "abs_path": str(item.resolve()),
                    "children": _build_library_tree(item, depth + 1, max_depth),
                })
    except PermissionError:
        pass
    return entries


_DEFAULT_EXCLUDED = {"images", "snippets", "lost+found"}


_TYPE_LABELS = {"film": "Film", "tv": "Serie TV", "anime": "Anime"}


def _search_tree(directory: Path, base: Path, query: str, excluded: set) -> list[dict]:
    results = []
    try:
        for item in sorted(directory.iterdir()):
            if item.name in excluded:
                continue
            if query in item.name.lower():
                if item.is_dir():
                    results.append({
                        "name": item.name,
                        "type": "directory",
                        "path": str(item.relative_to(base)),
                    })
                elif item.is_file():
                    stat = item.stat()
                    results.append({
                        "name": item.name,
                        "type": "file",
                        "path": str(item.relative_to(base)),
                        "size": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
            # A symlinked folder is listed but not entered: a link back up loops forever.
            if item.is_dir() and not item.is_symlink():
                results.extend(_search_tree(item, base, query, excluded))
    except PermissionError:
        pass
    return results


@router.get("/search", dependencies=CAN_VIEW)
async def search_files(q: str):
    if not q or len(q.strip()) < 2:
        raise HTTPException(status_code=400, detail="Query troppo corta (min 2 caratteri)")
    if not VIDEOS_DIR.exists():
        return []
    excluded = _DEFAULT_EXCLUDED | set(read_data().get("excluded_folders", []))
    return await asyncio.to_thread(_search_tree, VIDEOS_DIR, VIDEOS_DIR, q.strip().lower(), excluded)


@router.get("", dependencies=CAN_VIEW)
async def list_files(path: str = ""):
    """The contents of one folder of the library (the root when ``path`` is empty)."""
    if not VIDEOS_DIR.exists():
        return []
    base = VIDEOS_DIR.resolve()
    directory = (base / path).resolve()
    if not directory.is_relative_to(base):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not directory.is_dir():
        raise HTTPException(status_code=404, detail="File not found")
    excluded = _DEFAULT_EXCLUDED | set(read_data().get("excluded_folders", []))
    return await asyncio.to_thread(_list_dir, directory, base, excluded)


@router.get("/library-tree", dependencies=CAN_VIEW)
async def list_library_tree():
    data = read_data()
    result = []
    for lib in data.get("libraries", []):
        lib_path = Path(lib["path"])
        exists = lib_path.exists()
        lib_type = lib.get("type", "")
        result.append({
            "name": _TYPE_LABELS.get(lib_type, lib_type or lib.get("name", "?")),
            "abs_path": str(lib_path.resolve()),
            "exists": exists,
            "children": (await asyncio.to_thread(_build_library_tree, lib_path)) if exists else [],
        })
    return result


@router.get("/stream/{file_path:path}", dependencies=CAN_VIEW)
def stream_file(file_path: str):
    target = _safe_path(file_path)
    # Derived from the extension: everything used to be announced as video/mp4,
    # which was already wrong for the MKVs the downloader produced and would be
    # wrong half the time now that the container is a setting.
    return FileResponse(
        path=str(target),
        media_type=container.mime_for(target),
        headers={"Content-Disposition": "inline"},
    )


@router.get("/download/{file_path:path}", dependencies=CAN_VIEW)
def download_file(file_path: str):
    target = _safe_path(file_path)
    return FileResponse(
        path=str(target),
        media_type=container.mime_for(target),
        filename=target.name,  # Starlette writes the RFC 5987 form; a hand-made header is latin-1 only
    )


class MoveRequest(BaseModel):
    path: str
    dest_dir_path: str | None = None  # destination dir relative to VIDEOS_DIR (empty = root)
    dest_abs_path: str | None = None  # destination absolute path in a library
    library_name: str | None = None   # legacy


class BatchMoveRequest(BaseModel):
    paths: list[str]
    dest_dir_path: str


class BatchDeleteRequest(BaseModel):
    paths: list[str]


class RenameRequest(BaseModel):
    path: str
    new_name: str


@router.post("/move", dependencies=CAN_MANAGE)
async def move_to_library(body: MoveRequest):
    data = read_data()
    source = _safe_path(body.path, keep_link=True)

    if body.dest_dir_path is not None:
        # Move within VIDEOS_DIR
        base = VIDEOS_DIR.resolve()
        dest_dir = (base / body.dest_dir_path).resolve() if body.dest_dir_path else base
        if not dest_dir.is_relative_to(base) and dest_dir != base:
            raise HTTPException(status_code=400, detail="Destinazione non valida")
        if not dest_dir.exists():
            raise HTTPException(status_code=400, detail="Cartella di destinazione non esiste")
        if source.is_dir():
            src_resolved = source.resolve()
            if dest_dir == src_resolved or dest_dir.is_relative_to(src_resolved):
                raise HTTPException(status_code=400, detail="Non puoi spostare una cartella dentro se stessa")
        dest = dest_dir / source.name
    elif body.dest_abs_path:
        lib_paths = [Path(lib["path"]).resolve() for lib in data.get("libraries", [])]
        dest_dir = Path(body.dest_abs_path).resolve()
        if not dest_dir.exists():
            raise HTTPException(status_code=400, detail="Cartella di destinazione non esiste")
        if not any(dest_dir == lp or dest_dir.is_relative_to(lp) for lp in lib_paths):
            raise HTTPException(status_code=400, detail="Destinazione non in una libreria configurata")
        dest = dest_dir / source.name
    elif body.library_name:
        lib_map = {lib.get("type", lib.get("name", "")): lib["path"] for lib in data.get("libraries", [])}
        if body.library_name not in lib_map:
            raise HTTPException(status_code=400, detail=f"Libreria '{body.library_name}' non configurata")
        dest_dir_root = Path(lib_map[body.library_name])
        if not dest_dir_root.exists():
            raise HTTPException(status_code=400, detail=f"Il percorso della libreria non esiste: {dest_dir_root}")
        rel = source.relative_to(VIDEOS_DIR.resolve())
        dest = dest_dir_root / rel
    else:
        raise HTTPException(status_code=400, detail="Specificare dest_dir_path, dest_abs_path o library_name")

    if dest.exists():
        raise HTTPException(status_code=409, detail=f"'{source.name}' esiste già nella destinazione")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.move, str(source), str(dest))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Spostamento fallito: {e}")

    return {"moved_to": str(dest)}


def _delete_sync(target: Path):
    """Synchronous delete helper (runs in thread)."""
    if target.is_dir() and not target.is_symlink():
        shutil.rmtree(target)
    else:
        target.unlink()


@router.delete("/delete/{file_path:path}", status_code=204, dependencies=CAN_MANAGE)
async def delete_path(file_path: str):
    target = _safe_path(file_path, keep_link=True)
    await asyncio.to_thread(_delete_sync, target)


def _batch_move_sync(paths: list[str], dest_dir_path: str) -> list[dict]:
    """Move multiple paths within VIDEOS_DIR (blocking, runs in thread)."""
    base = VIDEOS_DIR.resolve()
    dest_dir = (base / dest_dir_path).resolve() if dest_dir_path else base
    results = []
    for p in paths:
        try:
            source = (base / p).resolve()
            if source == base or not source.is_relative_to(base) or not source.exists():
                results.append({"path": p, "ok": False, "error": "File non trovato"})
                continue
            if not dest_dir.is_relative_to(base) and dest_dir != base:
                results.append({"path": p, "ok": False, "error": "Destinazione non valida"})
                continue
            if source.is_dir():
                if dest_dir == source.resolve() or dest_dir.is_relative_to(source.resolve()):
                    results.append({"path": p, "ok": False, "error": "Non puoi spostare una cartella dentro se stessa"})
                    continue
            dest = dest_dir / source.name
            if dest.exists():
                results.append({"path": p, "ok": False, "error": f"'{source.name}' esiste già nella destinazione"})
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            results.append({"path": p, "ok": True, "moved_to": str(dest)})
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})
    return results


@router.post("/move-batch", dependencies=CAN_MANAGE)
async def batch_move(body: BatchMoveRequest):
    if not body.paths:
        raise HTTPException(status_code=400, detail="Nessun file selezionato")
    results = await asyncio.to_thread(_batch_move_sync, body.paths, body.dest_dir_path)
    return {"results": results}


def _batch_delete_sync(paths: list[str]) -> list[dict]:
    """Delete multiple paths within VIDEOS_DIR (blocking, runs in thread)."""
    results = []
    for p in paths:
        try:
            target = _safe_path_strict(p, keep_link=True)
            _delete_sync(target)
            results.append({"path": p, "ok": True})
        except (ValueError, FileNotFoundError) as e:
            results.append({"path": p, "ok": False, "error": str(e)})
        except Exception as e:
            results.append({"path": p, "ok": False, "error": str(e)})
    return results


@router.post("/rename", dependencies=CAN_MANAGE)
async def rename_path(body: RenameRequest):
    if not body.new_name or '/' in body.new_name or '\\' in body.new_name or body.new_name in ('.', '..') or '\x00' in body.new_name:
        raise HTTPException(status_code=400, detail="Nome non valido")
    source = _safe_path(body.path, keep_link=True)
    dest = source.parent / body.new_name
    if dest.exists():
        raise HTTPException(status_code=409, detail=f"'{body.new_name}' esiste già")
    try:
        await asyncio.to_thread(source.rename, dest)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Rinomina fallita: {e}")
    return {"renamed_to": str(dest.relative_to(VIDEOS_DIR.resolve()))}


@router.post("/delete-batch", dependencies=CAN_MANAGE)
async def batch_delete(body: BatchDeleteRequest):
    if not body.paths:
        raise HTTPException(status_code=400, detail="Nessun file selezionato")
    results = await asyncio.to_thread(_batch_delete_sync, body.paths)
    return {"results": results}
