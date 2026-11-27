"""차트(기술적) 점수.

기준일까지의 일봉을 (날짜 × 종목) 표로 펼쳐 모든 종목을 한 번에 계산한다.

- 단기 차트 점수(tech_short, 단타용): 5일·1개월 수익률, 거래량 증가(5일 평균/60일 평균), RSI
  RSI 는 과열(80 이상)이나 침체보다 60 근처를 가장 높게 친다 (초기 규칙, 백테스트로 조정 예정)
- 중기 차트 점수(tech_mid, 중타·장타용): 이동평균 정배열, 3·6개월 수익률, 12개월-1개월 모멘텀

유동성 필터: 최근 20일 평균 거래대금이 국내 10억 원, 미국 500만 달러 미만이거나
미국 주가 1달러 미만인 종목, 거래일이 61일 미만인 종목은 추천 대상에서 뺀다(liquid=False).
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from stockproj.analysis.common import mean_of, pct_rank
from stockproj.storage import Database

MIN_TRADED_VALUE = {"KR": 1e9, "US": 5e6}
MIN_PRICE = {"KR": 0.0, "US": 1.0}
MIN_DAYS_SHORT = 61
MIN_DAYS_MID = 130


def load_prices(db: Database, market: str, as_of: date, days: int = 400) -> pd.DataFrame:
    return db.con.execute(
        """
        SELECT symbol, date, close, volume FROM daily_prices
        WHERE market = ? AND date <= ? AND date > ? ORDER BY date
        """,
        [market, as_of, as_of - timedelta(days=days)],
    ).df()


def _ret(close: pd.DataFrame, n: int, skip: int = 0) -> pd.Series:
    """마지막 날 기준 n 거래일 수익률 (skip 거래일 전 기준)."""
    if len(close) <= n:
        return pd.Series(float("nan"), index=close.columns)
    end = close.iloc[-1 - skip]
    start = close.iloc[-1 - n]
    return end / start - 1


def _rsi(close: pd.DataFrame, n: int = 14) -> pd.Series:
    diff = close.diff().iloc[-n:]
    gain = diff.clip(lower=0).mean()
    loss = (-diff.clip(upper=0)).mean()
    rs = gain / loss.where(loss > 0)
    rsi = 100 - 100 / (1 + rs)
    return rsi.where(loss > 0, 100.0).where(diff.notna().sum() >= n)


def compute_metrics(prices: pd.DataFrame, market: str) -> pd.DataFrame:
    if prices.empty:
        return pd.DataFrame()
    close = prices.pivot(index="date", columns="symbol", values="close").sort_index().ffill(limit=5)
    volume = prices.pivot(index="date", columns="symbol", values="volume").sort_index()
    days = close.notna().sum()

    m = pd.DataFrame(index=close.columns)
    m.index.name = "symbol"
    last = close.iloc[-1]
    m["close"] = last
    m["days"] = days
    m["ret_5d"] = _ret(close, 5)
    m["ret_1m"] = _ret(close, 21)
    m["ret_3m"] = _ret(close, 63)
    m["ret_6m"] = _ret(close, 126)
    m["ret_12_1"] = _ret(close, 252, skip=21)
    ma20, ma60, ma120 = (close.iloc[-n:].mean().where(days >= n) for n in (20, 60, 120))
    trend = (last > ma20).astype(int) + (ma20 > ma60).astype(int) + (ma60 > ma120).astype(int)
    trend += (last > ma120).astype(int)
    m["trend"] = trend.where(days >= 120)  # 0~4
    m["rsi"] = _rsi(close)
    m["vol_ratio"] = volume.iloc[-5:].mean() / volume.iloc[-60:].mean().where(lambda s: s > 0)
    m["traded_value"] = (close * volume).iloc[-20:].mean()
    m["liquid"] = (
        (m["traded_value"] >= MIN_TRADED_VALUE[market])
        & (m["close"] >= MIN_PRICE[market])
        & (m["days"] >= MIN_DAYS_SHORT)
    )
    return m


def score(metrics: pd.DataFrame) -> pd.DataFrame:
    out = metrics.copy()
    if out.empty:
        return out
    for col in ["ret_5d", "ret_1m", "ret_3m", "ret_6m", "ret_12_1", "vol_ratio"]:
        out[f"p_{col}"] = pct_rank(metrics[col])
    out["p_trend"] = metrics["trend"] * 25
    out["p_rsi"] = (100 - (metrics["rsi"] - 60).abs() * 2.5).clip(0, 100)
    out["tech_short"] = mean_of(out, ["p_ret_5d", "p_ret_1m", "p_vol_ratio", "p_rsi"], min_count=3)
    out["tech_mid"] = mean_of(out, ["p_trend", "p_ret_3m", "p_ret_6m", "p_ret_12_1"], min_count=3)
    out.loc[metrics["days"] < MIN_DAYS_SHORT, "tech_short"] = float("nan")
    out.loc[metrics["days"] < MIN_DAYS_MID, "tech_mid"] = float("nan")
    return out


def technical_scores(db: Database, market: str, as_of: date) -> pd.DataFrame:
    return score(compute_metrics(load_prices(db, market, as_of), market))
