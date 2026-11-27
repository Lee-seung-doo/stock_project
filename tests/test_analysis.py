from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from stockproj.analysis import fundamental, scoring, technical
from stockproj.storage import Database

AS_OF = date(2026, 11, 26)


def _price_rows(symbol: str, closes: list[float], volume: float, market: str = "US") -> list[dict]:
    start = AS_OF - timedelta(days=len(closes) - 1)
    return [
        {
            "market": market,
            "symbol": symbol,
            "date": start + timedelta(days=i),
            "open": c,
            "high": c,
            "low": c,
            "close": c,
            "volume": volume,
            "source": "test",
        }
        for i, c in enumerate(closes)
    ]


def _fin(symbol, item, value, period_end, period="FY", filed=None, unit="USD"):
    return {
        "market": "US",
        "symbol": symbol,
        "period_end": period_end,
        "fiscal_year": period_end.year,
        "fiscal_period": period,
        "item": item,
        "value": value,
        "unit": unit,
        "filed": filed or period_end + timedelta(days=40),
        "source": "test",
    }


def _company(symbol, revenue, revenue_prev, ni, ni_prev, equity, liabilities, shares, filed=None):
    y1, y0 = date(2025, 12, 31), date(2024, 12, 31)
    return [
        _fin(symbol, "Revenues", revenue, y1, filed=filed),
        _fin(symbol, "Revenues", revenue_prev, y0),
        _fin(symbol, "NetIncomeLoss", ni, y1, filed=filed),
        _fin(symbol, "NetIncomeLoss", ni_prev, y0),
        _fin(symbol, "OperatingIncomeLoss", ni * 1.3, y1, filed=filed),
        _fin(symbol, "StockholdersEquity", equity, y1, "I", filed=filed),
        _fin(symbol, "Liabilities", liabilities, y1, "I", filed=filed),
        _fin(symbol, "SharesOutstanding", shares, y1, "I", filed=filed, unit="shares"),
    ]


@pytest.fixture
def db():
    db = Database()
    rng = np.random.default_rng(0)
    rows = []
    # GOOD: 꾸준히 오르는 우량주, BAD: 꾸준히 내리는 적자 기업, MID: 옆걸음, THIN: 거래대금 부족
    rows += _price_rows("GOOD", list(np.linspace(50, 100, 300)), 1e6)
    rows += _price_rows("BAD", list(np.linspace(100, 40, 300)), 1e6)
    rows += _price_rows("MID", list(70 + rng.normal(0, 1, 300)), 1e6)
    rows += _price_rows("THIN", list(np.linspace(50, 100, 300)), 10)
    db.upsert_prices(pd.DataFrame(rows))
    fins = []
    fins += _company("GOOD", 1000, 800, 200, 150, 800, 400, 10)
    fins += _company("BAD", 500, 600, -100, -20, 100, 900, 10)
    fins += _company("MID", 700, 690, 50, 50, 600, 600, 10)
    # 기준일 뒤에 공시된 실적은 쓰이면 안 된다
    fins += [_fin("MID", "Revenues", 99999, date(2026, 9, 30), filed=AS_OF + timedelta(days=5))]
    db.upsert_financials(pd.DataFrame(fins))
    db.upsert_stocks(
        pd.DataFrame(
            [
                {"market": "US", "symbol": s, "name": s.title(), "exchange": "NYSE", "external_id": "1"}
                for s in ["GOOD", "BAD", "MID", "THIN"]
            ]
        )
    )
    return db


def test_fundamental_table_and_metrics(db):
    items = fundamental.load_items(db, "US", AS_OF)
    table = fundamental.build_table(items, AS_OF)
    assert table.at["MID", "revenue"] == 700  # 기준일 뒤에 공시된 99999 는 무시
    assert table.at["GOOD", "revenue_prev"] == 800
    metrics = fundamental.compute_metrics(table, pd.Series({"GOOD": 100.0, "BAD": 40.0, "MID": 70.0}))
    assert metrics.at["GOOD", "roe"] == pytest.approx(0.25)
    assert metrics.at["GOOD", "earnings_yield"] == pytest.approx(200 / 1000)
    assert metrics.at["GOOD", "revenue_growth"] == pytest.approx(0.25)
    assert metrics.at["BAD", "debt_ratio"] == pytest.approx(9.0)
    scored = fundamental.score(metrics)
    assert scored.at["GOOD", "fundamental"] > scored.at["BAD", "fundamental"]


def test_future_filings_are_ignored(db):
    early = AS_OF.replace(year=2026, month=1, day=15)  # 2025 연간 실적 공시(2월) 전
    items = fundamental.load_items(db, "US", early)
    table = fundamental.build_table(items, early)
    assert table.at["GOOD", "revenue"] == 800  # 2024 값만 알 수 있다


def test_technical_metrics_and_liquidity(db):
    m = technical.compute_metrics(technical.load_prices(db, "US", AS_OF), "US")
    assert bool(m.at["GOOD", "liquid"]) and not bool(m.at["THIN", "liquid"])
    assert m.at["GOOD", "trend"] == 4 and m.at["BAD", "trend"] == 0
    assert m.at["GOOD", "ret_3m"] > 0 > m.at["BAD", "ret_3m"]
    scored = technical.score(m)
    assert scored.at["GOOD", "tech_mid"] > scored.at["BAD", "tech_mid"]


def test_combine_renormalizes_missing_news():
    modules = pd.DataFrame(
        {"fundamental": [80.0, 80.0, float("nan")], "tech_mid": [60.0, float("nan"), 90.0]},
        index=["A", "B", "C"],
    )
    long = scoring.PRESET_BY_KEY["long"]
    out = scoring.combine(modules, long)
    # 뉴스 없음 → 재무 0.6, 차트 0.2 만으로 다시 맞춤
    assert out.at["A", "score"] == pytest.approx((80 * 0.6 + 60 * 0.2) / 0.8)
    assert out.at["B", "score"] == pytest.approx(80.0)  # 0.6 ≥ 절반
    assert pd.isna(out.at["C", "score"])  # 0.2 < 절반 → 점수 없음


def test_grade_floor():
    assert scoring.grade(85, 50) == "강력 추천"
    assert scoring.grade(70, 10) == "중립"  # 한 모듈이 20 미만이면 추천 불가
    assert scoring.grade(20, 50) == "주의"
    assert scoring.grade(float("nan"), 50) is None


def test_reasons_text():
    row = pd.Series({"p_roe": 92.0, "p_debt_ratio": 12.0, "p_op_margin": 50.0})
    text = scoring.reasons(row, ["roe", "op_margin", "debt_ratio"])
    assert text == "강점 ROE 상위 8% / 약점 재무 안정성(부채비율) 하위 12%"


def test_compute_scores_end_to_end(db):
    scores = scoring.compute(db, "US", AS_OF)
    assert set(scores["preset"]) == {"short", "mid", "long"}
    assert "THIN" not in set(scores["symbol"])  # 유동성 필터
    long = scores[scores["preset"] == "long"].set_index("symbol")
    assert long.at["GOOD", "rank"] == 1
    assert long.at["GOOD", "score"] > long.at["BAD", "score"]
    db.replace_scores(scores)
    db.replace_scores(scores)  # 다시 넣어도 중복 없음
    assert len(db.latest_scores("US")) == len(scores)
