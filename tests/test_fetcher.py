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


def make_fetcher(session, delay=4.0, jitter=0.0, monotonic=lambda: 1000.0, **kw):
    slept = []
    fetcher = Fetcher(
        delay=delay,
        jitter=jitter,
        session=session,
        sleep=lambda s: slept.append(s),
        monotonic=monotonic,
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


class RaisingSession:
    """Session whose .get() raises a fixed exception every call, or a scripted
    sequence of exception/response items."""

    def __init__(self, items):
        self._items = list(items)
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        item = self._items.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class AlwaysRaisingSession:
    def __init__(self, exc):
        self._exc = exc
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        raise self._exc


class FixedRng:
    """Stub rng recording the (a, b) bounds it was called with and always
    returning a fixed value, so jitter math is fully deterministic."""

    def __init__(self, value):
        self.value = value
        self.calls = []

    def uniform(self, a, b):
        self.calls.append((a, b))
        return self.value


def test_503_with_challenge_body_raises_immediately_no_retry():
    # Regression test for Fix 1: Cloudflare commonly serves its "checking your
    # browser" challenge with a 503 status. That must halt immediately, not be
    # treated as a transient 5xx worth retrying.
    body = "<html><title>Just a moment...</title></html>"
    session = FakeSession([FakeResponse(503, body)])
    fetcher, _ = make_fetcher(session, max_retries=3)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")
    assert session.calls == 1


def test_retry_after_header_honored_on_429():
    session = FakeSession(
        [
            FakeResponse(429, "Too Many Requests", {"Retry-After": "7"}),
            FakeResponse(200, "recovered"),
        ]
    )
    fetcher, slept = make_fetcher(session, max_retries=2)
    assert fetcher.get("https://djinni.co/jobs/") == "recovered"
    # slept[0] is the pre-request delay for attempt 0; slept[1] is the
    # Retry-After-driven backoff before the retry.
    assert slept[1] == pytest.approx(7.0)


def test_jitter_applied_to_delay():
    session = FakeSession([FakeResponse(200, "ok")])
    rng = FixedRng(0.2)
    fetcher, slept = make_fetcher(session, jitter=0.5, rng=rng)
    fetcher.get("https://djinni.co/jobs/")
    assert rng.calls[0] == (-0.5, 0.5)
    assert slept[0] == pytest.approx(4.0 * (1 + 0.2))


def test_network_exception_is_retried():
    session = RaisingSession([ConnectionError("boom"), FakeResponse(200, "recovered")])
    fetcher, _ = make_fetcher(session, max_retries=2)
    assert fetcher.get("https://djinni.co/jobs/") == "recovered"
    assert session.calls == 2


def test_persistent_5xx_exhaustion_raises_blocked():
    session = FakeSession([FakeResponse(503, "Service Unavailable")] * 4)
    fetcher, _ = make_fetcher(session, max_retries=3)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")
    assert session.calls == 4  # max_retries + 1 attempts, no challenge body


def test_network_exception_exhaustion_no_wasted_sleep_on_last_attempt():
    # Regression test for Fix 2: the final, doomed attempt must not sleep
    # 2**attempt before giving up.
    session = AlwaysRaisingSession(ConnectionError("boom"))
    fetcher, slept = make_fetcher(session, max_retries=2)
    with pytest.raises(BlockedError):
        fetcher.get("https://djinni.co/jobs/")
    assert session.calls == 3  # attempts 0, 1, 2
    # 3 pre-request waits (4.0 each) + backoff sleeps after attempts 0 and 1
    # only (2**0=1.0, 2**1=2.0) -- nothing after the final attempt 2.
    assert slept == [4.0, 1.0, 4.0, 2.0, 4.0]


def test_elapsed_time_reduces_next_wait():
    session = FakeSession([FakeResponse(200, "a"), FakeResponse(200, "b")])
    clock = iter([1000.0, 1001.5, 1001.5])
    fetcher, slept = make_fetcher(session, monotonic=lambda: next(clock))
    fetcher.get("https://djinni.co/jobs/")
    fetcher.get("https://djinni.co/jobs/")
    assert slept[0] == pytest.approx(4.0)
    # 1.5s elapsed between requests is subtracted from the base 4.0s delay.
    assert slept[1] == pytest.approx(2.5)
    assert slept[1] < slept[0]
