"""The segment join runs FFmpeg asynchronously so a cancel can stop it.

run() could not be interrupted: a cancelled download kept FFmpeg busy for minutes.
These tests stand in a shell script for FFmpeg, so no media file is needed.
"""

import os
import stat
import threading
import time

import pytest

from app.core import m3u8
from app.progress import DownloadCancelledError


def _fake_ffmpeg(tmp_path, body):
    script = tmp_path / "fake_ffmpeg.sh"
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return str(script)


def _segments(tmp_path, cancel=None):
    """A bare M3U8_Segments with one real segment, bypassing the network constructor."""
    seg = m3u8.M3U8_Segments.__new__(m3u8.M3U8_Segments)
    temp = tmp_path / "temp"
    temp.mkdir()
    (temp / "0.ts").write_bytes(b"\x47" * 188)
    seg.temp_folder = str(temp)
    seg.segments = ["seg0"]
    seg.emit_join_phase = False
    seg._cancel = cancel
    seg._require_every_segment = lambda: None
    return seg


@pytest.fixture
def ffmpeg_at(monkeypatch):
    def use(path):
        monkeypatch.setattr(m3u8, "get_ffmpeg_exe", lambda: path)
    return use


def test_a_cancel_stops_ffmpeg_instead_of_waiting_for_it(tmp_path, ffmpeg_at):
    # exec: real FFmpeg is one process. Without it the shell's child keeps stderr open
    # after the kill, and the test would measure that child rather than the cancel.
    ffmpeg_at(_fake_ffmpeg(tmp_path, "exec sleep 60"))
    cancel = threading.Event()
    seg = _segments(tmp_path, cancel=cancel)
    threading.Timer(0.5, cancel.set).start()

    started = time.monotonic()
    with pytest.raises(DownloadCancelledError):
        seg.join(str(tmp_path / "out.mkv"))
    # Without the kill this would sit for the full 60 seconds of the fake process.
    assert time.monotonic() - started < 15


def test_a_clean_ffmpeg_exit_finishes_the_join(tmp_path, ffmpeg_at):
    ffmpeg_at(_fake_ffmpeg(tmp_path, "exit 0"))
    seg = _segments(tmp_path)
    seg.join(str(tmp_path / "out.mkv"))
    assert not os.path.exists(seg.temp_folder)  # the temp folder is removed after a good join


def test_an_ffmpeg_failure_reports_its_stderr(tmp_path, ffmpeg_at):
    ffmpeg_at(_fake_ffmpeg(tmp_path, "echo 'matroska muxer refused' >&2\nexit 1"))
    seg = _segments(tmp_path)
    with pytest.raises(RuntimeError, match="matroska muxer refused"):
        seg.join(str(tmp_path / "out.mkv"))
