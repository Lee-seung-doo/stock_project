"""미국 일봉 (yfinance, 무료·비공식).

여러 티커를 묶어서 내려받고(yf.download), 결과를 daily_prices 표준 표로 바꾼다.
수정주가(auto_adjust=True)를 쓴다. 1단계에서 토스증권 API 로 일일 갱신을 옮길 예정이다.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import date, timedelta

import pandas as pd

_COLS = {"Open": "open", "High": "high", "Low": "low", "Close": "close", "Volume": "volume"}


def to_yahoo_symbol(symbol: str) -> str:
    """SEC 표기(BRK-B, BF.B 등) → 야후 표기(BRK-B, BF-B)."""
    return symbol.replace(".", "-")


def chunks(items: list[str], size: int) -> Iterator[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def normalize_download(df: pd.DataFrame, symbols: Iterable[str]) -> pd.DataFrame:
    """yf.download(group_by="ticker") 결과 → daily_prices 표준 표.

    symbols 는 원래(SEC) 표기. 야후 표기로 바꿔 열을 찾는다.
    """
    if df is None or df.empty:
        return pd.DataFrame()
    frames = []
    multi = isinstance(df.columns, pd.MultiIndex)
    for symbol in symbols:
        ysym = to_yahoo_symbol(symbol)
        if multi:
            if ysym not in df.columns.get_level_values(0):
                continue
            part = df[ysym]
        else:
            part = df
        part = part.rename(columns=_COLS)
        if "close" not in part:
            continue
        part = part[list(_COLS.values())].dropna(subset=["close"])
        if part.empty:
            continue
        out = part.copy()
        out["date"] = pd.to_datetime(part.index).date
        out["market"] = "US"
        out["symbol"] = symbol
        out["source"] = "yfinance"
        frames.append(out.reset_index(drop=True))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def download(symbols: list[str], start: date, end: date, batch: int = 200) -> Iterator[pd.DataFrame]:
    """batch 개씩 나눠 내려받으며 표준 표를 하나씩 돌려준다. end 는 포함."""
    import yfinance as yf

    for group in chunks(symbols, batch):
        raw = yf.download(
            [to_yahoo_symbol(s) for s in group],
            start=start.isoformat(),
            end=(end + timedelta(days=1)).isoformat(),
            auto_adjust=True,
            group_by="ticker",
            threads=True,
            progress=False,
        )
        yield normalize_download(raw, group)
