"""재무(펀더멘털) 점수.

기준일까지 공시된 연간 재무제표와 기준일 종가로 지표를 만들고, 같은 시장 안 백분위로 점수화한다.

하위 점수 (각 0~100)
- 가치(value):      이익수익률(순이익/시가총액, PER 의 역수), 순자산/시가총액(PBR 의 역수), 매출/시가총액
- 수익성(quality):  ROE, 영업이익률
- 성장(growth):     매출 성장률, 순이익 성장률 (최근 연간 vs 전년)
- 안정성(stability): 부채비율 (낮을수록 높은 점수)
재무 점수 = 값이 있는 하위 점수의 평균 (최소 2개 필요)

한계: 1단계에서는 업종 구분 없이 시장 전체와 비교한다. 업종 내 비교는 업종 데이터를 붙인 뒤 바꾼다.
"""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from stockproj.analysis.common import mean_of, pct_rank
from stockproj.storage import Database

# 표준 필드 → 시장별 원본 계정 이름 (앞에 있을수록 우선)
ALIASES: dict[str, dict[str, list[str]]] = {
    "revenue": {
        "KR": ["IS:ifrs-full_Revenue", "CIS:ifrs-full_Revenue"],
        "US": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"],
    },
    "operating_income": {
        "KR": ["IS:dart_OperatingIncomeLoss", "CIS:dart_OperatingIncomeLoss"],
        "US": ["OperatingIncomeLoss"],
    },
    "net_income": {
        "KR": ["IS:ifrs-full_ProfitLoss", "CIS:ifrs-full_ProfitLoss"],
        "US": ["NetIncomeLoss"],
    },
    "equity": {"KR": ["BS:ifrs-full_Equity"], "US": ["StockholdersEquity"]},
    "assets": {"KR": ["BS:ifrs-full_Assets"], "US": ["Assets"]},
    "liabilities": {"KR": ["BS:ifrs-full_Liabilities"], "US": ["Liabilities"]},
    "shares": {"KR": ["SharesOutstanding"], "US": ["SharesOutstanding"]},
}
FLOW_FIELDS = ["revenue", "operating_income", "net_income"]  # 기간 값: 연간(FY)만 쓴다
STOCK_FIELDS = ["equity", "assets", "liabilities", "shares"]  # 시점 값: 가장 최근 값

MAX_REPORT_AGE_DAYS = 550  # 최근 연간 실적이 이보다 오래됐으면 쓰지 않는다

METRICS_HIGHER_BETTER = {
    "earnings_yield": True,
    "book_to_price": True,
    "sales_to_price": True,
    "roe": True,
    "op_margin": True,
    "revenue_growth": True,
    "ni_growth": True,
    "debt_ratio": False,
}
SUBSCORES = {
    "value": ["earnings_yield", "book_to_price", "sales_to_price"],
    "quality": ["roe", "op_margin"],
    "growth": ["revenue_growth", "ni_growth"],
    "stability": ["debt_ratio"],
}


def _alias_table(market: str) -> pd.DataFrame:
    rows = [
        {"item": item, "field": field, "prio": prio}
        for field, by_market in ALIASES.items()
        for prio, item in enumerate(by_market[market])
    ]
    return pd.DataFrame(rows)


def load_items(db: Database, market: str, as_of: date) -> pd.DataFrame:
    """기준일까지 공시된 재무 항목을 표준 필드 이름으로 읽는다."""
    aliases = _alias_table(market)
    db.con.register("_aliases", aliases)
    try:
        df = db.con.execute(
            """
            SELECT f.symbol, f.period_end, f.fiscal_period, f.value, f.unit, a.field, a.prio
            FROM financials f JOIN _aliases a ON f.item = a.item
            WHERE f.market = ? AND f.filed <= ? AND f.value IS NOT NULL
            """,
            [market, as_of],
        ).df()
    finally:
        db.con.unregister("_aliases")
    if market == "US":  # 외국 기업의 비달러 재무는 시가총액(달러)과 섞이지 않게 뺀다
        df = df[(df["unit"] == "USD") | (df["field"] == "shares")]
    df["period_end"] = pd.to_datetime(df["period_end"])
    return df


def build_table(items: pd.DataFrame, as_of: date) -> pd.DataFrame:
    """종목별 한 줄: 최근·전년 연간 실적과 최근 재무상태, 발행주식수."""
    out = pd.DataFrame(index=pd.Index(sorted(items["symbol"].unique()), name="symbol"))
    if items.empty:
        return out
    oldest = pd.Timestamp(as_of - timedelta(days=MAX_REPORT_AGE_DAYS))

    flows = items[items["field"].isin(FLOW_FIELDS) & (items["fiscal_period"] == "FY")]
    flows = flows.sort_values(["symbol", "field", "period_end", "prio"])
    flows = flows.drop_duplicates(["symbol", "field", "period_end"], keep="first")
    flows = flows.sort_values("period_end", ascending=False)
    flows["rank"] = flows.groupby(["symbol", "field"]).cumcount()
    latest = flows[flows["rank"] == 0]
    latest = latest[latest["period_end"] >= oldest]
    prev = flows[flows["rank"] == 1].merge(
        latest[["symbol", "field", "period_end"]], on=["symbol", "field"], suffixes=("", "_latest")
    )
    gap = (prev["period_end_latest"] - prev["period_end"]).dt.days
    prev = prev[gap.between(330, 400)]  # 정확히 직전 연도만
    out = out.join(latest.pivot(index="symbol", columns="field", values="value"))
    out = out.join(prev.pivot(index="symbol", columns="field", values="value").add_suffix("_prev"))

    stocks = items[items["field"].isin(STOCK_FIELDS)]
    stocks = stocks.sort_values(
        ["symbol", "field", "period_end", "prio"], ascending=[True, True, False, True]
    )
    stocks = stocks.drop_duplicates(["symbol", "field"], keep="first")
    stocks = stocks[stocks["period_end"] >= oldest]
    out = out.join(stocks.pivot(index="symbol", columns="field", values="value"))

    for col in FLOW_FIELDS + [f + "_prev" for f in FLOW_FIELDS] + STOCK_FIELDS:
        if col not in out:
            out[col] = float("nan")
    return out


def latest_close(db: Database, market: str, as_of: date) -> pd.Series:
    df = db.con.execute(
        """
        SELECT symbol, arg_max(close, date) AS close FROM daily_prices
        WHERE market = ? AND date <= ? AND date > ? GROUP BY symbol
        """,
        [market, as_of, as_of - timedelta(days=14)],
    ).df()
    return df.set_index("symbol")["close"]


def compute_metrics(table: pd.DataFrame, close: pd.Series) -> pd.DataFrame:
    t = table.join(close.rename("close"), how="left")
    mcap = (t["shares"] * t["close"]).where(lambda s: s > 0)
    equity_pos = t["equity"].where(t["equity"] > 0)
    revenue_pos = t["revenue"].where(t["revenue"] > 0)
    liabilities = t["liabilities"].fillna(t["assets"] - t["equity"])

    m = pd.DataFrame(index=t.index)
    m["market_cap"] = mcap
    m["earnings_yield"] = t["net_income"] / mcap
    m["book_to_price"] = t["equity"] / mcap
    m["sales_to_price"] = t["revenue"] / mcap
    m["roe"] = t["net_income"] / equity_pos
    m["op_margin"] = t["operating_income"] / revenue_pos
    m["revenue_growth"] = t["revenue"] / t["revenue_prev"].where(t["revenue_prev"] > 0) - 1
    ni_prev = t["net_income_prev"].where(t["net_income_prev"] != 0)
    m["ni_growth"] = ((t["net_income"] - ni_prev) / ni_prev.abs()).clip(-5, 5)
    debt = liabilities / equity_pos
    m["debt_ratio"] = debt.where(t["equity"] > 0, float("inf")).where(t["equity"].notna())
    return m


def score(metrics: pd.DataFrame) -> pd.DataFrame:
    """지표 → 백분위 점수(p_지표), 하위 점수, 재무 점수."""
    out = metrics.copy()
    for col, higher in METRICS_HIGHER_BETTER.items():
        out[f"p_{col}"] = pct_rank(metrics[col], higher)
    # 자본잠식(부채비율 무한대)은 순위와 상관없이 0점
    out.loc[metrics["debt_ratio"] == float("inf"), "p_debt_ratio"] = 0.0
    for name, cols in SUBSCORES.items():
        out[name] = mean_of(out, [f"p_{c}" for c in cols])
    out["fundamental"] = mean_of(out, list(SUBSCORES), min_count=2)
    return out


def fundamental_scores(db: Database, market: str, as_of: date) -> pd.DataFrame:
    table = build_table(load_items(db, market, as_of), as_of)
    return score(compute_metrics(table, latest_close(db, market, as_of)))
