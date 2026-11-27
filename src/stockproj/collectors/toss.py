"""토스증권 Open API 클라이언트 (국내·미국 시세, 이후 주문).

주의: 아래 엔드포인트 경로와 파라미터는 제3자 가이드 블로그(AlgoLab, 2026-08/10 확인)를 근거로 했다.
공식 문서(토스증권 Open API 명세)로 확인하기 전까지 응답 형식을 표준 표로 바꾸는 부분은 만들지 않았다.
지금은 인증과 공통 호출, 원본 응답 조회만 제공하고 일일 수집은 pykrx/yfinance 를 쓴다.

알려진 사항(확인 필요):
- 인증: OAuth 2.0 Client Credentials, POST /oauth2/token, form-urlencoded, 토큰 24시간 유효
- 허용 IP 를 등록하지 않으면 403
- 캔들: interval "1m" 또는 "1d", 요청당 최대 200개, before 커서로 과거 조회, adjusted 기본 true
- 차트 조회 그룹 초당 약 20회
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from stockproj.collectors.http import RateLimiter, request_with_retry

TOKEN_PATH = "/oauth2/token"
CANDLES_PATH = "/api/v1/candles"  # TODO: 공식 문서로 경로 확인


class TossAuthError(RuntimeError):
    pass


class TossClient:
    def __init__(
        self,
        client_id: str,
        client_secret: str,
        base_url: str = "https://openapi.tossinvest.com",
        session: requests.Session | None = None,
        per_second: float = 15,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if not client_id or not client_secret:
            raise TossAuthError("TOSS_CLIENT_ID / TOSS_CLIENT_SECRET 이 설정되지 않았습니다.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.base_url = base_url.rstrip("/")
        self.session = session or requests.Session()
        self.clock = clock
        self.sleep = sleep
        self.limiter = RateLimiter(per_second, sleep=sleep)
        self._token: str | None = None
        self._token_expires_at = 0.0

    # ---- 인증 -------------------------------------------------------------

    def token(self) -> str:
        """유효한 액세스 토큰을 돌려준다. 만료 5분 전이면 새로 받는다."""
        if self._token and self.clock() < self._token_expires_at - 300:
            return self._token
        resp = request_with_retry(
            self.session,
            "POST",
            self.base_url + TOKEN_PATH,
            data={  # JSON 이 아니라 form-urlencoded 로 보내야 한다
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            },
            sleep=self.sleep,
        )
        body = resp.json()
        if "access_token" not in body:
            raise TossAuthError(f"토큰 응답에 access_token 이 없습니다: {list(body)}")
        self._token = body["access_token"]
        self._token_expires_at = self.clock() + float(body.get("expires_in", 86400))
        return self._token

    # ---- 공통 호출 ---------------------------------------------------------

    def get(self, path: str, params: dict[str, Any] | None = None, account: str | None = None) -> Any:
        self.limiter.wait()
        headers = {"Authorization": f"Bearer {self.token()}"}
        if account:
            headers["X-Tossinvest-Account"] = account
        resp = request_with_retry(
            self.session,
            "GET",
            self.base_url + path,
            params=params,
            headers=headers,
            sleep=self.sleep,
        )
        return resp.json()

    def raw_candles(
        self, symbol: str, interval: str = "1d", count: int = 200, before: str | None = None
    ) -> Any:
        """캔들 원본 응답. 국내는 6자리 종목코드, 미국은 티커(예: AAPL)."""
        params: dict[str, Any] = {"symbol": symbol, "interval": interval, "count": min(count, 200)}
        if before:
            params["before"] = before
        return self.get(CANDLES_PATH, params=params)
