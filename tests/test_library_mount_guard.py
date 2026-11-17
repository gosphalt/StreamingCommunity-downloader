"""A library on a drive that did not mount is refused, not written to the system disk."""
import os

import pytest

from app import writable

FSTAB = """\
# comment
UUID=1 /mnt/wdblack1 ntfs3 uid=1000,nofail 0 0
/dev/mmcblk0p2 / ext4 defaults 0 1
none /swap swap sw 0 0
"""


@pytest.fixture
def fstab(tmp_path, monkeypatch):
    f = tmp_path / "fstab"
    f.write_text(FSTAB, encoding="utf-8")
    monkeypatch.setattr(writable, "FSTAB", f)
    return f


def _mounted(*points):
    real = os.path.ismount
    return lambda p: os.path.abspath(p) in points or (real(p) if os.path.abspath(p) == "/" else False)


def test_a_library_under_an_inactive_mount_is_refused(fstab, monkeypatch):
    monkeypatch.setattr(os.path, "ismount", _mounted())
    assert writable.unmounted_library("/mnt/wdblack1/SerieTV/") == "/mnt/wdblack1"


def test_the_same_library_passes_once_the_drive_is_mounted(fstab, monkeypatch):
    monkeypatch.setattr(os.path, "ismount", _mounted("/mnt/wdblack1"))
    assert writable.unmounted_library("/mnt/wdblack1/SerieTV/") is None


def test_a_folder_outside_any_declared_mount_is_never_refused(fstab, monkeypatch):
    monkeypatch.setattr(os.path, "ismount", _mounted())
    assert writable.unmounted_library("/home/poppypi/videos") is None


def test_a_prefix_that_is_not_a_path_component_does_not_match(fstab, monkeypatch):
    monkeypatch.setattr(os.path, "ismount", _mounted())
    assert writable.unmounted_library("/mnt/wdblack10/x") is None


def test_no_fstab_means_nothing_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(writable, "FSTAB", tmp_path / "missing")
    assert writable.unmounted_library("/mnt/wdblack1/SerieTV") is None


def test_a_submission_into_an_inactive_library_creates_no_job(fstab, monkeypatch):
    from app.jobs import job_manager
    monkeypatch.setattr(os.path, "ismount", _mounted())
    job = job_manager._make_job("Titolo", "film")
    with pytest.raises(writable.LibraryUnavailable, match="wdblack1"):
        job_manager._submit_job(job, lambda *a, **k: None, output_dir="/mnt/wdblack1/Film/")
    assert job.job_id not in job_manager._jobs
