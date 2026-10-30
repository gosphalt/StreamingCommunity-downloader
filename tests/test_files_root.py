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
