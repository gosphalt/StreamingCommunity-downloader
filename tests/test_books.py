"""Internet Archive books: public-domain search, file choice, download and the routes.

The network is replaced, so the suite stays offline.
"""
import pytest

from app.core import books


@pytest.fixture
def signed_in(client, admin_credentials):
    from app.auth.permissions import ALL_PERMISSIONS
    from tests.conftest import do_setup, make_user, session_for
    do_setup(client, admin_credentials)
    user = make_user("boss", "jf-boss-id", int(ALL_PERMISSIONS))
    client.cookies.clear()
    return session_for(client, user.id)


class _Resp:
    def __init__(self, payload=None, chunks=None):
        self._payload = payload
        self._chunks = chunks or []

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=0):
        yield from self._chunks

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def ia(monkeypatch):
    """Record every request and answer from canned payloads."""
    state = {"calls": [], "search": {"response": {"docs": []}}, "meta": {"files": []}, "bytes": [b"x" * 10]}

    def fake_get(url, params=None, timeout=None, stream=False):
        state["calls"].append((url, params))
        if url == books.SEARCH_URL:
            return _Resp(state["search"])
        if url.startswith("https://archive.org/metadata/"):
            return _Resp(state["meta"])
        return _Resp(chunks=state["bytes"])

    monkeypatch.setattr(books.requests, "get", fake_get)
    return state


def _query(state):
    params = dict(state["calls"][-1][1])
    return params["q"]


def test_the_search_is_limited_to_public_domain(ia):
    books.search("dante")
    assert "licenseurl:*publicdomain*" in _query(ia)
    assert "mediatype:texts" in _query(ia)


def test_filters_are_added_to_the_query(ia):
    books.search("dante", language="ita", year_from="1800", year_to="1900", creator="Alighieri")
    q = _query(ia)
    assert "language:ita" in q
    assert "year:[1800 TO 1900]" in q
    assert 'creator:("Alighieri")' in q


def test_user_text_cannot_change_the_shape_of_the_query(ia):
    books.search('dante" OR mediatype:* ')
    q = _query(ia)
    # The quote is escaped, so the search stays inside the text clause.
    assert '\\"' in q
    assert q.count("mediatype:texts") == 1


def test_a_bad_language_or_year_never_reaches_the_network(ia):
    with pytest.raises(books.BookError):
        books.search("x", language="ita OR 1")
    with pytest.raises(books.BookError):
        books.search("x", year_from="19xx")
    assert ia["calls"] == []


def test_a_bad_identifier_is_refused_before_any_request(ia):
    with pytest.raises(books.BookError):
        books.pick_file("../../etc/passwd")
    assert ia["calls"] == []


def test_epub_is_preferred_and_pdf_is_the_fallback(ia):
    ia["meta"] = {"files": [{"name": "a.pdf", "format": "Text PDF", "size": "5"},
                            {"name": "a.epub", "format": "EPUB", "size": "3"}]}
    assert books.pick_file("a")["name"] == "a.epub"
    ia["meta"] = {"files": [{"name": "a.pdf", "format": "Text PDF", "size": "5"}]}
    assert books.pick_file("a", "epub")["name"] == "a.pdf"


def test_an_item_with_no_readable_file_is_refused(ia):
    ia["meta"] = {"files": [{"name": "a.djvu", "format": "DjVu", "size": "5"}]}
    with pytest.raises(books.BookError):
        books.pick_file("a")


def test_a_book_lands_under_its_author(ia, tmp_path):
    ia["meta"] = {"files": [{"name": "dante.epub", "format": "EPUB", "size": "10"}]}
    final = books.download_book("dante", "La Divina Commedia", "Alighieri, Dante", "1900",
                                str(tmp_path / "Libri"), str(tmp_path / "tmp"))
    assert final == str(tmp_path / "Libri" / "Alighieri, Dante" / "La Divina Commedia (1900).epub")
    with open(final, "rb") as f:
        assert f.read() == b"x" * 10


def test_the_author_cannot_escape_the_library(tmp_path):
    path = books.book_path(str(tmp_path), "../../evil", "Titolo", "", "epub")
    assert path.startswith(str(tmp_path) + "/")
    assert ".." not in path.split(str(tmp_path))[1]


def test_a_cancel_stops_the_download_and_writes_nothing(ia, tmp_path):
    import threading
    ia["meta"] = {"files": [{"name": "a.epub", "format": "EPUB", "size": "10"}]}
    cancel = threading.Event()
    cancel.set()
    from app.progress import DownloadCancelledError
    with pytest.raises(DownloadCancelledError):
        books.download_book("a", "T", "A", "", str(tmp_path / "Libri"), str(tmp_path / "tmp"),
                            cancel_event=cancel)
    assert not (tmp_path / "Libri").exists() or not any((tmp_path / "Libri").rglob("*.epub"))


# ── routes ───────────────────────────────────────────────────────────────────

def test_the_download_route_needs_a_book_library(client, signed_in, monkeypatch):
    from app.routers import books as books_router
    monkeypatch.setattr(books_router, "read_data", lambda: {"libraries": []})
    r = client.post("/api/books/download", headers={"X-CSRF-Token": signed_in},
                    json={"identifier": "a", "title": "T"})
    assert r.status_code == 400


def test_a_valid_download_is_queued_into_the_book_library(client, signed_in, monkeypatch):
    from app.routers import books as books_router
    seen = {}

    def fake_submit(identifier, title, creator, year, output_dir, fmt="epub", user_id=None):
        seen.update(output_dir=output_dir, fmt=fmt, identifier=identifier)
        return "job-b"

    monkeypatch.setattr(books_router, "read_data",
                        lambda: {"libraries": [{"type": "book", "path": "/mnt/wdblack1/Libri"}]})
    monkeypatch.setattr(books_router.job_manager, "submit_book", fake_submit)
    r = client.post("/api/books/download", headers={"X-CSRF-Token": signed_in},
                    json={"identifier": "dante", "title": "La Divina Commedia", "year": "1900",
                          "fmt": "pdf"})
    assert r.status_code == 202
    assert seen == {"output_dir": "/mnt/wdblack1/Libri", "fmt": "pdf", "identifier": "dante"}


def test_the_client_cannot_pick_a_format_outside_the_list(client, signed_in):
    r = client.post("/api/books/download", headers={"X-CSRF-Token": signed_in},
                    json={"identifier": "a", "title": "T", "fmt": "exe"})
    assert r.status_code == 422


def test_a_year_must_be_four_digits(client, signed_in):
    r = client.post("/api/books/download", headers={"X-CSRF-Token": signed_in},
                    json={"identifier": "a", "title": "T", "year": "19"})
    assert r.status_code == 422
