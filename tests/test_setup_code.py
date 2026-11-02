"""The first-run wizard needs the code printed in the log."""

import pytest

from app.auth import setup_code

_real_verify = setup_code.verify  # conftest swaps the module attribute per test


@pytest.fixture
def real_gate(monkeypatch):
    monkeypatch.setattr(setup_code, "verify", _real_verify)
    setup_code.issue()
    yield setup_code._code
    setup_code._code = ""


def test_skip_refused_without_the_code(client, real_gate):
    assert client.post("/api/auth/skip").status_code == 403
    assert client.post("/api/auth/skip", json={"code": "nope"}).status_code == 403
    assert client.get("/api/auth/status").json()["setup_done"] is False


def test_skip_accepted_with_the_code(client, real_gate):
    assert client.post("/api/auth/skip", json={"code": real_gate}).status_code == 200


def test_setup_refused_without_the_code(client, real_gate):
    body = {"url": "http://jf:8096", "username": "admin", "password": "x"}
    assert client.post("/api/auth/setup", json=body).status_code == 403


def test_no_code_issued_means_nothing_passes():
    setup_code._code = ""
    assert _real_verify("") is False


def test_orphan_temp_dirs_are_purged_but_only_job_folders(tmp_path, monkeypatch):
    import uuid
    from app import config, main
    monkeypatch.setattr(config, "TMP_DIR", tmp_path)
    job = tmp_path / str(uuid.uuid4())
    (job / "video").mkdir(parents=True)
    keep = tmp_path / "segments"
    keep.mkdir()
    assert main.purge_orphan_temp_dirs() == 1
    assert not job.exists() and keep.exists()
