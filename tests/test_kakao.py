import json
from datetime import date

import pandas as pd
import pytest

from stockproj.report.kakao import TEXT_LIMIT, KakaoClient, KakaoError, format_messages


class Resp:
    def __init__(self, body, status=200):
        self._body = body
        self.status_code = status
        self.headers = {}

    def json(self):
        return self._body

    def raise_for_status(self):
        pass


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        return self.responses.pop(0)

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def test_login_then_refresh_keeps_refresh_token(tmp_path):
    now = [1000.0]
    session = Session(
        [
            Resp(
                {
                    "access_token": "a1",
                    "expires_in": 3600,
                    "refresh_token": "r1",
                    "refresh_token_expires_in": 5_000_000,
                }
            ),
            Resp({"access_token": "a2", "expires_in": 3600}),  # 갱신 응답엔 refresh_token 없음
        ]
    )
    client = KakaoClient("key", tmp_path / "t.json", session=session, clock=lambda: now[0])
    client.login_with_code("CODE")
    assert client.access_token() == "a1"
    now[0] += 7200
    assert client.access_token() == "a2"
    saved = json.loads((tmp_path / "t.json").read_text())
    assert saved["refresh_token"] == "r1"
    assert session.calls[1][2]["data"]["grant_type"] == "refresh_token"


def test_missing_token_file(tmp_path):
    with pytest.raises(KakaoError, match="kakao-login"):
        KakaoClient("key", tmp_path / "none.json").access_token()


def test_send_text_uses_template(tmp_path):
    session = Session([Resp({"result_code": 0})])
    token = tmp_path / "t.json"
    token.write_text(json.dumps({"access_token": "a", "expires_at": 1e12}))
    KakaoClient("key", token, session=session).send_text("x" * 300, "http://localhost:8501")
    method, url, kwargs = session.calls[0]
    template = json.loads(kwargs["data"]["template_object"])
    assert template["object_type"] == "text"
    assert len(template["text"]) == TEXT_LIMIT
    assert kwargs["headers"]["Authorization"] == "Bearer a"


def test_format_messages():
    rows = []
    for preset in ["short", "mid", "long"]:
        rows += [
            {
                "as_of": date(2026, 11, 26),
                "market": "KR",
                "symbol": "005930",
                "name": "삼성전자",
                "preset": preset,
                "score": 81.2,
                "grade": "강력 추천",
            },
            {
                "as_of": date(2026, 11, 26),
                "market": "KR",
                "symbol": "000660",
                "name": "SK하이닉스",
                "preset": preset,
                "score": 50.0,
                "grade": "중립",
            },
            {
                "as_of": date(2026, 11, 26),
                "market": "US",
                "symbol": "AAPL",
                "name": "Apple Inc.",
                "preset": preset,
                "score": 70.4,
                "grade": "추천",
            },
        ]
    messages = format_messages(pd.DataFrame(rows))
    assert len(messages) == 3
    assert messages[0] == "[단타 추천 11/26]\n국내: 삼성전자 81\n미국: Apple Inc. 70"
    assert all(len(m) <= TEXT_LIMIT for m in messages)
