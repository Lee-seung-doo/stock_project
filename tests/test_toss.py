import pytest

from stockproj.collectors.http import RateLimiter
from stockproj.collectors.toss import TossAuthError, TossClient


class FakeResponse:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code = status
        self._body = body or {}
        self.headers = headers or {}

    def json(self):
        return self._body

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"{self.status_code}", response=self)


class FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_requires_credentials():
    with pytest.raises(TossAuthError):
        TossClient("", "secret")


def test_token_is_form_encoded_and_cached():
    session = FakeSession([FakeResponse(body={"access_token": "tok", "expires_in": 86400})])
    now = [1000.0]
    client = TossClient("id", "secret", session=session, clock=lambda: now[0], sleep=lambda s: None)
    assert client.token() == "tok"
    now[0] += 3600
    assert client.token() == "tok"  # 아직 유효하면 다시 요청하지 않음
    method, url, kwargs = session.calls[0]
    assert method == "POST" and url.endswith("/oauth2/token")
    assert kwargs["data"]["grant_type"] == "client_credentials"
    assert "json" not in kwargs
    assert len(session.calls) == 1


def test_get_retries_after_429_using_retry_after():
    waits = []
    session = FakeSession(
        [
            FakeResponse(body={"access_token": "tok", "expires_in": 86400}),
            FakeResponse(status=429, headers={"Retry-After": "2"}),
            FakeResponse(body={"ok": True}),
        ]
    )
    client = TossClient("id", "secret", session=session, sleep=waits.append, per_second=1000)
    assert client.get("/api/v1/stocks") == {"ok": True}
    assert 2.0 in waits
    assert session.calls[-1][2]["headers"]["Authorization"] == "Bearer tok"


def test_rate_limiter_spaces_calls():
    t = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        t[0] += s

    limiter = RateLimiter(per_second=10, clock=lambda: t[0], sleep=sleep)
    limiter.wait()
    limiter.wait()
    assert slept == [pytest.approx(0.1)]
