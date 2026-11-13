"""YouTube downloads, with yt-dlp replaced by a fake: no network in the suite."""
import pytest

from app.core import youtube
from app.progress import DownloadCancelledError

VID = "dQw4w9WgXcQ"


@pytest.mark.parametrize("text, expected", [
    (f"https://www.youtube.com/watch?v={VID}", VID),
    (f"youtu.be/{VID}", VID),
    (f"https://youtube.com/shorts/{VID}?feature=share", VID),
    (f"https://www.youtube.com/watch?v={VID}&list=PL1", VID),
    ("https://youtube.attacker.tld/watch?v=" + VID, None),   # host must be exact
    ("file:///etc/passwd", None),
    ("https://www.youtube.com/playlist?list=PL1", None),
    ("Interstellar", None),
])
def test_links_yield_only_a_real_video_id(text, expected):
    assert youtube.video_id_from_link(text) == expected


def test_a_bare_eleven_letter_word_is_not_an_id_for_search():
    # Only links are ids in search; a bare word is a query, even if 11 characters long.
    assert youtube.video_id_from_link("Interstellar") is None
    assert youtube.is_video_id(VID)


class _Bar:
    def __init__(self):
        self.calls = []
        self.closed = False

    def update(self, n=1, bytes=0):
        self.calls.append((n, bytes))

    def close(self):
        self.closed = True


class _FakeYDL:
    """Writes what yt-dlp would leave in the temp folder, reporting progress first."""
    written_name = None   # set per test
    hook_status = []

    def __init__(self, opts):
        self.opts = opts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download(self, urls):
        for status in self.hook_status:
            for hook in self.opts["progress_hooks"]:
                hook(status)
        import os
        with open(os.path.join(self.opts["outtmpl"].rsplit("/", 1)[0], self.written_name), "wb") as f:
            f.write(b"video")


@pytest.fixture
def fake_ydl(monkeypatch):
    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", _FakeYDL)
    monkeypatch.setattr(youtube, "get_ffmpeg_exe", lambda: "ffmpeg")
    monkeypatch.setattr(youtube.container, "configured", lambda: "mkv")
    _FakeYDL.hook_status = []
    _FakeYDL.written_name = f"{VID}.mkv"
    return _FakeYDL


def test_download_lands_under_the_title_and_reports_progress(tmp_path, fake_ydl):
    fake_ydl.hook_status = [
        {"status": "downloading", "downloaded_bytes": 50, "total_bytes": 100},
        {"status": "downloading", "downloaded_bytes": 100, "total_bytes": 100},
        # the audio stream starts again from zero; the bar must not go backwards
        {"status": "downloading", "downloaded_bytes": 10, "total_bytes": 20},
    ]
    bar = _Bar()
    out = tmp_path / "library"
    final = youtube.download_youtube(VID, "Titolo: prova", str(out), str(tmp_path / "tmp"),
                                     progress_factory=lambda **kw: bar)

    assert final == str(out / f"Titolo prova [{VID}].mkv")
    assert (out / f"Titolo prova [{VID}].mkv").read_bytes() == b"video"
    assert not (out / f".Titolo prova [{VID}].mkv").exists()   # staged name is gone
    assert bar.closed
    total = sum(n for n, _ in bar.calls)
    assert total == 99   # capped at 99 until the file is in place, never decreasing


def test_cancel_before_the_file_is_moved_raises_and_keeps_the_library_clean(tmp_path, fake_ydl):
    import threading
    cancel = threading.Event()
    cancel.set()
    fake_ydl.hook_status = [{"status": "downloading", "downloaded_bytes": 1, "total_bytes": 2}]
    out = tmp_path / "library"
    with pytest.raises(DownloadCancelledError):
        youtube.download_youtube(VID, "x", str(out), str(tmp_path / "tmp"), cancel_event=cancel)
    assert not out.exists() or not any(out.iterdir())


def test_the_other_container_of_the_same_video_is_removed(tmp_path, fake_ydl):
    out = tmp_path / "library"
    out.mkdir()
    stale = out / f"Titolo [{VID}].mp4"
    stale.write_bytes(b"old")
    youtube.download_youtube(VID, "Titolo", str(out), str(tmp_path / "tmp"))
    assert not stale.exists()
    assert (out / f"Titolo [{VID}].mkv").exists()


def test_a_bad_id_never_reaches_yt_dlp(tmp_path, fake_ydl):
    with pytest.raises(ValueError):
        youtube.download_youtube("../../etc/passwd", "x", str(tmp_path), str(tmp_path / "tmp"))


def test_search_passes_language_only_when_set(monkeypatch):
    # The extractor arg changes which titles come back, so it must be absent
    # when no language is chosen, not sent as an empty string.
    seen = []

    class _Search:
        def __init__(self, opts):
            seen.append(opts)

        def extract_info(self, url, download=False):
            return {"entries": []}

    monkeypatch.setattr(youtube.yt_dlp, "YoutubeDL", _Search)
    youtube.search("x", lang="")
    youtube.search("x", lang="it")
    assert "extractor_args" not in seen[0]
    assert seen[1]["extractor_args"] == {"youtube": {"lang": ["it"]}}
