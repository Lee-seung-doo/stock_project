"""카카오톡 '나에게 보내기'로 매일 추천 요약을 보낸다 (무료).

준비 (한 번만)
1. https://developers.kakao.com 에서 앱을 만들고 REST API 키를 .env 의 KAKAO_REST_API_KEY 에 넣는다.
2. 카카오 로그인을 켜고 Redirect URI(기본 https://localhost)를 등록한다.
3. 동의항목에서 '카카오톡 메시지 전송(talk_message)'을 사용으로 바꾼다.
4. `stockproj kakao-login` 을 실행해 안내대로 로그인하면 토큰이 data/kakao_token.json 에 저장된다.

액세스 토큰은 몇 시간, 리프레시 토큰은 약 두 달 유효하다. 만료되면 자동으로 갱신하고,
리프레시 토큰까지 만료되면 kakao-login 을 다시 해야 한다.
텍스트 메시지는 200자 제한이 있어 프리셋(단타·중타·장타)마다 한 통씩 보낸다.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path
from urllib.parse import urlencode

import pandas as pd
import requests

from stockproj.analysis.scoring import PRESETS
from stockproj.collectors.http import request_with_retry

AUTH_URL = "https://kauth.kakao.com/oauth/authorize"
TOKEN_URL = "https://kauth.kakao.com/oauth/token"
SEND_URL = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
TEXT_LIMIT = 200


class KakaoError(RuntimeError):
    pass


class KakaoClient:
    def __init__(
        self,
        rest_api_key: str,
        token_path: Path,
        redirect_uri: str = "https://localhost",
        client_secret: str | None = None,
        session: requests.Session | None = None,
        clock: Callable[[], float] = time.time,
    ):
        if not rest_api_key:
            raise KakaoError("KAKAO_REST_API_KEY 가 설정되지 않았습니다.")
        self.rest_api_key = rest_api_key
        self.token_path = Path(token_path)
        self.redirect_uri = redirect_uri
        self.client_secret = client_secret
        self.session = session or requests.Session()
        self.clock = clock

    # ---- 로그인과 토큰 ------------------------------------------------------

    def authorize_url(self) -> str:
        query = {
            "client_id": self.rest_api_key,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "talk_message",
        }
        return f"{AUTH_URL}?{urlencode(query)}"

    def _token_request(self, data: dict) -> dict:
        data = {"client_id": self.rest_api_key, **data}
        if self.client_secret:
            data["client_secret"] = self.client_secret
        resp = self.session.post(TOKEN_URL, data=data, timeout=30)
        body = resp.json()
        if resp.status_code != 200 or "access_token" not in body:
            raise KakaoError(f"카카오 토큰 발급 실패: {body.get('error_description') or body}")
        return body

    def _save(self, body: dict, old: dict | None = None) -> dict:
        now = self.clock()
        token = dict(old or {})
        token["access_token"] = body["access_token"]
        token["expires_at"] = now + float(body.get("expires_in", 0))
        if "refresh_token" in body:  # 갱신 응답에는 리프레시 토큰이 없을 수도 있다
            token["refresh_token"] = body["refresh_token"]
            token["refresh_expires_at"] = now + float(body.get("refresh_token_expires_in", 0))
        self.token_path.parent.mkdir(parents=True, exist_ok=True)
        self.token_path.write_text(json.dumps(token))
        return token

    def login_with_code(self, code: str) -> None:
        body = self._token_request(
            {"grant_type": "authorization_code", "redirect_uri": self.redirect_uri, "code": code}
        )
        self._save(body)

    def access_token(self) -> str:
        if not self.token_path.exists():
            raise KakaoError("카카오 토큰이 없습니다. `stockproj kakao-login` 을 먼저 실행하세요.")
        token = json.loads(self.token_path.read_text())
        if self.clock() < token.get("expires_at", 0) - 60:
            return token["access_token"]
        if not token.get("refresh_token") or self.clock() >= token.get("refresh_expires_at", 0):
            raise KakaoError("카카오 로그인이 만료됐습니다. `stockproj kakao-login` 을 다시 실행하세요.")
        body = self._token_request({"grant_type": "refresh_token", "refresh_token": token["refresh_token"]})
        return self._save(body, old=token)["access_token"]

    # ---- 보내기 ------------------------------------------------------------

    def send_text(self, text: str, link_url: str, button_title: str = "대시보드 열기") -> None:
        template = {
            "object_type": "text",
            "text": truncate(text, TEXT_LIMIT),
            "link": {"web_url": link_url, "mobile_web_url": link_url},
            "button_title": button_title,
        }
        resp = request_with_retry(
            self.session,
            "POST",
            SEND_URL,
            headers={"Authorization": f"Bearer {self.access_token()}"},
            data={"template_object": json.dumps(template, ensure_ascii=False)},
        )
        if resp.json().get("result_code") != 0:
            raise KakaoError(f"카카오톡 전송 실패: {resp.json()}")


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_messages(scores: pd.DataFrame, top: int = 3) -> list[str]:
    """프리셋마다 한 통: 시장별 상위 종목 이름과 점수. 200자를 넘지 않게 줄인다."""
    if scores.empty:
        return []
    as_of = pd.to_datetime(scores["as_of"]).max().date()
    messages = []
    for preset in PRESETS:
        part = scores[(scores["preset"] == preset.key) & scores["grade"].isin(["강력 추천", "추천"])]
        lines = [f"[{preset.label} 추천 {as_of:%m/%d}]"]
        for market, flag in (("KR", "국내"), ("US", "미국")):
            rows = part[part["market"] == market].sort_values("score", ascending=False).head(top)
            if rows.empty:
                lines.append(f"{flag}: 추천 종목 없음")
                continue
            items = [f"{_short(r['name'] or r['symbol'])} {r['score']:.0f}" for _, r in rows.iterrows()]
            lines.append(f"{flag}: " + ", ".join(items))
        messages.append(truncate("\n".join(lines), TEXT_LIMIT))
    return messages


def _short(name: str, limit: int = 14) -> str:
    return name if len(name) <= limit else name[: limit - 1] + "…"


def notify(client: KakaoClient, scores: pd.DataFrame, dashboard_url: str) -> int:
    messages = format_messages(scores)
    for text in messages:
        client.send_text(text, dashboard_url)
    return len(messages)
