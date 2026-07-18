"""HTTP fetching with all anti-block behavior (the project's top priority)."""

from __future__ import annotations

import random
import time
from typing import Optional

DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_BLOCK_STATUSES = {403, 429}
_BACKOFF_STATUSES = {429, 500, 502, 503, 504}
_CHALLENGE_MARKERS = ("just a moment", "attention required", "cf-chl", "cf-browser-verification")


class BlockedError(Exception):
    """Raised when djinni appears to be throttling or blocking us."""


class Fetcher:
    def __init__(
        self,
        delay: float = 4.0,
        jitter: float = 0.5,
        user_agent: str = DEFAULT_UA,
        timeout: int = 30,
        max_retries: int = 3,
        session=None,
        sleep=time.sleep,
        monotonic=time.monotonic,
        rng: Optional[random.Random] = None,
    ):
        self._delay = delay
        self._jitter = jitter
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep
        self._monotonic = monotonic
        self._rng = rng or random.Random()
        self._last_request_at: Optional[float] = None
        self._headers = {
            "User-Agent": user_agent,
            "Accept-Language": "en-US,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        if session is None:
            import requests

            session = requests.Session()
        self._session = session

    def _wait_before_request(self) -> None:
        factor = 1.0 + self._rng.uniform(-self._jitter, self._jitter)
        target = max(0.0, self._delay * factor)
        if self._last_request_at is not None:
            elapsed = self._monotonic() - self._last_request_at
            target = max(0.0, target - elapsed)
        if target > 0:
            self._sleep(target)
        self._last_request_at = self._monotonic()

    @staticmethod
    def _is_challenge(text: str) -> bool:
        head = (text or "")[:2000].lower()
        return any(marker in head for marker in _CHALLENGE_MARKERS)

    def get(self, url: str) -> str:
        last_exc: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            self._wait_before_request()
            try:
                resp = self._session.get(url, headers=self._headers, timeout=self._timeout)
            except Exception as exc:  # network error -> backoff and retry
                last_exc = exc
                self._sleep(2 ** attempt)
                continue

            status = resp.status_code
            if status in _BLOCK_STATUSES:
                if status == 429 and attempt < self._max_retries:
                    self._sleep(self._retry_after(resp, attempt))
                    continue
                raise BlockedError(f"Blocked by djinni (HTTP {status}) at {url}")
            if status in _BACKOFF_STATUSES:
                if attempt < self._max_retries:
                    self._sleep(self._retry_after(resp, attempt))
                    continue
                raise BlockedError(f"Repeated HTTP {status} at {url}; stopping to avoid a block")
            if status >= 400:
                raise BlockedError(f"Unexpected HTTP {status} at {url}")
            if self._is_challenge(resp.text):
                raise BlockedError(f"Cloudflare challenge detected at {url}")
            return resp.text

        raise BlockedError(f"Giving up after retries at {url}: {last_exc}")

    def _retry_after(self, resp, attempt: int) -> float:
        header = resp.headers.get("Retry-After") if getattr(resp, "headers", None) else None
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return 2 ** attempt
