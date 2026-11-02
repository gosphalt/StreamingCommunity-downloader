"""The library root is not a path the file manager may delete, rename or move."""

import pytest

import app.routers.files as files


@pytest.fixture
def library(tmp_path, monkeypatch):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.mkv").write_text("x")
    monkeypatch.setattr(files, "VIDEOS_DIR", tmp_path)
    return tmp_path


@pytest.mark.parametrize("rel", ["", ".", "a/.."])
def test_the_root_is_refused(library, rel):
    with pytest.raises(ValueError):
        files._safe_path_strict(rel)
    assert files._batch_delete_sync([rel])[0]["ok"] is False
    assert files._batch_move_sync([rel], "a")[0]["ok"] is False
    assert (library / "a" / "x.mkv").exists()


def test_a_file_inside_still_resolves(library):
    assert files._safe_path("a/x.mkv") == (library / "a" / "x.mkv").resolve()


def test_search_does_not_loop_on_a_symlink_back_up(library):
    (library / "a" / "up").symlink_to(library, target_is_directory=True)
    found = files._search_tree(library, library, "x.mkv", set())
    assert [r["path"] for r in found] == ["a/x.mkv"]


def test_a_listing_is_one_level_and_a_folder_only_says_whether_it_is_empty(library):
    (library / "a" / "deep").mkdir()
    (library / "e").mkdir()
    rows = {e["name"]: e for e in files._list_dir(library, library, set())}
    assert "children" not in rows["a"] and rows["a"]["empty"] is False
    assert rows["e"]["empty"] is True


def test_listing_a_folder_refuses_to_leave_the_library(library):
    from fastapi import HTTPException
    import asyncio
    with pytest.raises(HTTPException) as e:
        asyncio.run(files.list_files("../"))
    assert e.value.status_code == 400
    assert [r["name"] for r in asyncio.run(files.list_files("a"))] == ["x.mkv"]


def test_download_of_a_non_latin1_name_has_a_valid_header(library):
    # A hand-written header is latin-1 only: the curly apostrophe used to be a 500.
    (library / "L’attacco S01E01.mkv").write_text("x")
    response = files.download_file("L’attacco S01E01.mkv")
    assert "filename*=utf-8''" in response.headers["content-disposition"]


def test_data_file_is_replaced_whole(tmp_path):
    from app.config import atomic_write_text
    target = tmp_path / "data.json"
    atomic_write_text(target, "{}")
    atomic_write_text(target, '{"a": 1}')
    assert target.read_text() == '{"a": 1}' and not (tmp_path / "data.json.tmp").exists()


def test_deleting_a_symlink_removes_the_link_not_its_target(library):
    (library / "real").mkdir()
    (library / "real" / "y.mkv").write_text("y")
    (library / "link").symlink_to(library / "real", target_is_directory=True)
    assert files._batch_delete_sync(["link"])[0]["ok"] is True
    assert not (library / "link").is_symlink() and (library / "real" / "y.mkv").exists()
