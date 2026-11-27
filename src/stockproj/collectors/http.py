"""공통 HTTP 호출: 호출 한도(429)와 일시 오류(5xx)에 대해 기다렸다가 다시 시도한다."""

from __future__ import annotations

import time
from collections.abc import Callable

import requests

RETRY_STATUS = {429, 500, 502, 503, 504}


def request_with_retry(
    session: requests.Session,
    method: str,
    url: str,
    *,
    max_retries: int = 4,
    backoff: float = 1.0,
    sleep: Callable[[float], None] = time.sleep,
    **kwargs,
) -> requests.Response:
    """요청을 보내고, 429/5xx 이면 Retry-After 헤더(없으면 지수 백오프)만큼 기다렸다 재시도한다."""
    kwargs.setdefault("timeout", 30)
    for attempt in range(max_retries + 1):
        resp = session.request(method, url, **kwargs)
        if resp.status_code not in RETRY_STATUS or attempt == max_retries:
            resp.raise_for_status()
            return resp
        retry_after = resp.headers.get("Retry-After")
        try:
            wait = float(retry_after) if retry_after else backoff * (2**attempt)
        except ValueError:
            wait = backoff * (2**attempt)
        sleep(wait)
    raise RuntimeError("unreachable")


class RateLimiter:
    """초당 호출 수를 넘지 않게 호출 사이에 간격을 둔다."""

    def __init__(
        self,
        per_second: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.interval = 1.0 / per_second
        self.clock = clock
        self.sleep = sleep
        self._last = -1e9

    def wait(self) -> None:
        now = self.clock()
        gap = self._last + self.interval - now
        if gap > 0:
            self.sleep(gap)
            now += gap
        self._last = now
