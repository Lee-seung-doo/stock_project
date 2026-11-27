"""환경변수(.env)에서 설정을 읽는다.

API 키는 코드나 저장소에 적지 않고 반드시 .env 또는 환경변수로만 넘긴다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    db_path: Path
    toss_client_id: str | None
    toss_client_secret: str | None
    toss_base_url: str
    dart_api_key: str | None
    sec_user_agent: str | None
    kakao_rest_api_key: str | None = None
    kakao_client_secret: str | None = None
    kakao_redirect_uri: str = "https://localhost"
    kakao_token_path: Path = Path("data/kakao_token.json")
    dashboard_url: str = "http://localhost:8501"


def _get(name: str) -> str | None:
    value = os.getenv(name, "").strip()
    return value or None


def load_settings(env_file: str | None = ".env") -> Settings:
    if env_file:
        load_dotenv(env_file, override=False)
    return Settings(
        db_path=Path(_get("STOCKPROJ_DB_PATH") or "data/stock.duckdb"),
        toss_client_id=_get("TOSS_CLIENT_ID"),
        toss_client_secret=_get("TOSS_CLIENT_SECRET"),
        toss_base_url=_get("TOSS_BASE_URL") or "https://openapi.tossinvest.com",
        dart_api_key=_get("DART_API_KEY"),
        sec_user_agent=_get("SEC_USER_AGENT"),
        kakao_rest_api_key=_get("KAKAO_REST_API_KEY"),
        kakao_client_secret=_get("KAKAO_CLIENT_SECRET"),
        kakao_redirect_uri=_get("KAKAO_REDIRECT_URI") or "https://localhost",
        kakao_token_path=Path(_get("KAKAO_TOKEN_PATH") or "data/kakao_token.json"),
        dashboard_url=_get("DASHBOARD_URL") or "http://localhost:8501",
    )
