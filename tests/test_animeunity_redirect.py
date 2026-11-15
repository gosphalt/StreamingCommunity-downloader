"""A redirected archive POST must stay a POST (requests would turn it into a GET -> 405)."""
from types import SimpleNamespace

from app.core import animeunity


class _Scraper:
    def __init__(self):
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs.get("allow_redirects")))
        if "animeunity.to" in url:
            return SimpleNamespace(status_code=302, is_redirect=True,
                                   headers={"Location": "https://www.animeunity.co/archivio/get-animes"})
        return SimpleNamespace(status_code=200, is_redirect=False, headers={})


def test_redirected_post_is_reposted_to_the_location(monkeypatch):
    scraper = _Scraper()
    monkeypatch.setattr(animeunity, "_get_scraper", lambda: scraper)
    monkeypatch.setattr(animeunity, "_csrf_token", lambda: "tok")
    monkeypatch.setattr(animeunity, "host", lambda: "www.animeunity.to")

    r = animeunity._post_archive({"title": "", "offset": 0})

    assert r.status_code == 200
    assert scraper.calls == [
        ("https://www.animeunity.to/archivio/get-animes", False),
        ("https://www.animeunity.co/archivio/get-animes", False),
    ]
