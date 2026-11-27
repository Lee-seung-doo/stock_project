"""Nasdaq Trader 종목 디렉터리: 미국 상장 ETF 목록 (무료, 키 없음).

SEC 목록에는 ETF 를 가려낼 정보가 없어서, 거래소 공식 디렉터리의 ETF 표시(Y/N)를 쓴다.
- nasdaqlisted.txt: Nasdaq 상장 (Symbol | ... | ETF | ...)
- otherlisted.txt:  NYSE 등 상장 (ACT Symbol | ... | ETF | ...)
"""

from __future__ import annotations

import io
import logging

import pandas as pd
import requests

from stockproj.collectors.http import request_with_retry

log = logging.getLogger(__name__)

URLS = {
    "Symbol": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "ACT Symbol": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}


def parse_etf_symbols(text: str, symbol_col: str) -> set[str]:
    """파이프(|)로 구분된 디렉터리 → ETF 티커 집합. SEC 표기에 맞춰 '.' 을 '-' 로 바꾼다."""
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("File Creation Time")]
    df = pd.read_csv(io.StringIO("\n".join(lines)), sep="|", dtype=str, keep_default_na=False)
    etf = df[df["ETF"].str.upper() == "Y"][symbol_col]
    return {s.strip().upper().replace(".", "-") for s in etf if s.strip()}


def etf_symbols(session: requests.Session | None = None) -> set[str]:
    """두 디렉터리의 ETF 티커. 받지 못하면 빈 집합(이름 규칙으로만 거른다)."""
    session = session or requests.Session()
    symbols: set[str] = set()
    for col, url in URLS.items():
        try:
            symbols |= parse_etf_symbols(request_with_retry(session, "GET", url).text, col)
        except Exception as e:  # noqa: BLE001 - ETF 목록이 없어도 목록 갱신은 계속한다
            log.warning("ETF 목록을 받지 못했습니다(%s): %s", url, e)
    return symbols
