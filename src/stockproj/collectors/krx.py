"""국내 종목 목록과 일봉 (pykrx, 무료).

pykrx 는 KRX 정보데이터시스템을 읽는 비공식 라이브러리라 사이트가 바뀌면 깨질 수 있다.
그래서 import 를 함수 안에서 하고, 결과를 표준 표로 바꾸는 부분(normalize_*)은 따로 둬서 테스트한다.

- 과거 백필: 종목별 수정주가 일봉 (get_market_ohlcv_by_date, adjusted=True)
- 매일 갱신: 날짜별 전 종목 일봉 (get_market_ohlcv_by_ticker) — 호출 1번에 전 종목
  날짜별 조회는 수정주가가 아니어서, 액면분할 등이 생긴 종목은 백필을 다시 돌려야 한다.
  1단계에서 토스증권 API(수정주가 캔들)로 바꿀 예정이다.
"""

from __future__ import annotations

import re
from datetime import date

import pandas as pd

MARKETS = ("KOSPI", "KOSDAQ")
_KR_COLS = {"시가": "open", "고가": "high", "저가": "low", "종가": "close", "거래량": "volume"}

REQUEST_TIMEOUT = 30  # 초. pykrx 는 요청에 timeout 을 주지 않아 응답이 없으면 무한정 멈춘다.


def _ensure_request_timeout() -> None:
    """requests.Session.request 를 한 번만 감싸 timeout 이 없는 요청에 기본값을 넣는다.

    pykrx 내부 요청을 고칠 방법이 없어서 쓰는 방법이다. 다른 코드가 timeout 을 직접 주면 그 값을 그대로 쓴다.
    """
    import requests

    original = requests.Session.request
    if getattr(original, "_stockproj_timeout", False):
        return

    def request(self, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = REQUEST_TIMEOUT
        return original(self, method, url, **kwargs)

    request._stockproj_timeout = True
    requests.Session.request = request


def _ymd(d: date) -> str:
    return d.strftime("%Y%m%d")


def normalize_ohlcv_by_date(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """index=날짜, 열=시가/고가/저가/종가/거래량 → daily_prices 표준 표."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=_KR_COLS)[list(_KR_COLS.values())].copy()
    out["date"] = pd.to_datetime(df.index).date
    out["market"] = "KR"
    out["symbol"] = symbol
    out["source"] = "pykrx"
    # 거래정지일은 시가·고가·저가가 0 으로 나온다
    out = out[out["close"] > 0]
    return out.reset_index(drop=True)


def normalize_ohlcv_by_ticker(df: pd.DataFrame, day: date) -> pd.DataFrame:
    """index=티커, 열=시가/고가/저가/종가/거래량 → daily_prices 표준 표 (하루치 전 종목)."""
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.rename(columns=_KR_COLS)[list(_KR_COLS.values())].copy()
    out["symbol"] = df.index.astype(str)
    out["date"] = day
    out["market"] = "KR"
    out["source"] = "pykrx"
    out = out[out["close"] > 0]
    return out.reset_index(drop=True)


# 우선주: 종목코드 끝자리가 0 이 아니거나(005935 삼성전자우 등) 이름이 '우', '1우', '2우B' 로 끝난다
_PREFERRED_NAME = re.compile(r"\d?우[A-C]?$")
# 혹시 섞여 들어오는 ETF·ETN (운용사 브랜드로 시작)
_ETF_NAME = re.compile(
    r"^(KODEX|TIGER|KBSTAR|RISE|ACE|ARIRANG|HANARO|SOL|KOSEF|PLUS|TIMEFOLIO|KIWOOM|1Q|WON)\b|ETN"
)


def is_common_stock(symbol: str, name: str) -> bool:
    """추천 대상(보통주)이면 True. 우선주와 ETF·ETN 은 False."""
    name = (name or "").strip()
    if not symbol.endswith("0") or _PREFERRED_NAME.search(name):
        return False
    return not _ETF_NAME.search(name)


def list_stocks(day: date) -> pd.DataFrame:
    """KOSPI·KOSDAQ 보통주 → stocks 표준 표 (우선주, ETF·ETN 제외)."""
    _ensure_request_timeout()
    from pykrx import stock

    rows = []
    for market in MARKETS:
        for ticker in stock.get_market_ticker_list(_ymd(day), market=market):
            rows.append(
                {
                    "market": "KR",
                    "symbol": ticker,
                    "name": stock.get_market_ticker_name(ticker),
                    "exchange": market,
                    "external_id": None,
                }
            )
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    keep = [is_common_stock(s, n) for s, n in zip(df["symbol"], df["name"], strict=True)]
    return df[keep].reset_index(drop=True)


def history(symbol: str, start: date, end: date) -> pd.DataFrame:
    _ensure_request_timeout()
    from pykrx import stock

    df = stock.get_market_ohlcv_by_date(_ymd(start), _ymd(end), symbol, adjusted=True)
    return normalize_ohlcv_by_date(df, symbol)


def snapshot(day: date) -> pd.DataFrame:
    """하루치 전 종목 일봉. 휴장일이면 빈 표."""
    _ensure_request_timeout()
    from pykrx import stock

    frames = [
        normalize_ohlcv_by_ticker(stock.get_market_ohlcv_by_ticker(_ymd(day), market=m), day) for m in MARKETS
    ]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def normalize_market_cap(df: pd.DataFrame, day: date) -> pd.DataFrame:
    """get_market_cap_by_ticker 결과(index=티커, 열=상장주식수 등) → financials 표준 표.

    상장주식수를 재무 표에 시점 값(I)으로 넣어 두면, 미국(SEC 발행주식수)과 같은 방식으로 시가총액을 계산한다.
    """
    if df is None or df.empty or "상장주식수" not in df:
        return pd.DataFrame()
    out = pd.DataFrame(
        {
            "market": "KR",
            "symbol": df.index.astype(str),
            "period_end": day,
            "fiscal_year": day.year,
            "fiscal_period": "I",
            "item": "SharesOutstanding",
            "value": df["상장주식수"].astype(float).to_numpy(),
            "unit": "shares",
            "filed": day,
            "source": "pykrx",
        }
    )
    return out[out["value"] > 0].reset_index(drop=True)


def shares_outstanding(day: date) -> pd.DataFrame:
    """하루치 전 종목 상장주식수. 휴장일이면 빈 표."""
    _ensure_request_timeout()
    from pykrx import stock

    return normalize_market_cap(stock.get_market_cap_by_ticker(_ymd(day), market="ALL"), day)
