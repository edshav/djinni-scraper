import pytest

from djinni_scraper.fetcher import BlockedError, Fetcher


class FakeResponse:
    def __init__(self, status_code=200, text="<html>ok</html>", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeSession:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        return self._responses.pop(0)


def make_fetcher(session, **kw):
    slept = []
    fetcher = Fetcher(
        delay=4.0,
        jitter=0.0,
        session=session,
        sleep=lambda s: slept.append(s),
        monotonic=lambda: 1000.0,
        **kw,
    )
    return fetcher, slept


def test_get_returns_text_on_200():
    session = FakeSession([FakeResponse(200, "<html>hello</html>")])
    fetcher, slept = make_fetcher(session)
    assert fetcher.get("https://djinni.co/jobs/") == "<html>hello</html>"


def test_delay_enforced_before_request():
    session = FakeSession([FakeResponse(200, "ok")])
    fetcher, slept = make_fetcher(session)
    fetcher.get("https://djinni.co/jobs/")
    assert slept and slept[0] == pytest.approx(4.0)


def test_429_raises_blocked():
    session = FakeSession([FakeResponse(429, "Too Many Requests", {"Retry-After": "0"})] * 5)
    fetcher, _ = make_fetcher(session, max_retries=2)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_403_raises_blocked():
    session = FakeSession([FakeResponse(403, "Forbidden")])
    fetcher, _ = make_fetcher(session)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_cloudflare_challenge_body_raises_blocked():
    body = "<html><title>Just a moment...</title></html>"
    session = FakeSession([FakeResponse(200, body)])
    fetcher, _ = make_fetcher(session)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")


def test_500_retries_then_succeeds():
    session = FakeSession([FakeResponse(500, "err"), FakeResponse(200, "recovered")])
    fetcher, _ = make_fetcher(session, max_retries=3)
    assert fetcher.get("https://djinni.co/jobs/") == "recovered"
    assert session.calls == 2
