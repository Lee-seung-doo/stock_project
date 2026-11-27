"""SEC EDGAR: 미국 상장사 목록(티커↔CIK)과 XBRL 재무 데이터. 무료, 초당 10회 제한.

SEC 는 User-Agent 에 앱 이름과 연락처를 요구한다(.env 의 SEC_USER_AGENT).
"""

from __future__ import annotations

import pandas as pd
import requests

from stockproj.collectors.http import RateLimiter, request_with_retry

TICKERS_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"

# 분석에 쓸 us-gaap 계정만 저장한다. 회사마다 매출 계정 이름이 달라 여러 개를 둔다.
CONCEPTS = [
    "Revenues",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    "SalesRevenueNet",
    "GrossProfit",
    "OperatingIncomeLoss",
    "NetIncomeLoss",
    "EarningsPerShareDiluted",
    "Assets",
    "Liabilities",
    "StockholdersEquity",
    "LongTermDebt",
    "InterestExpense",
    "NetCashProvidedByUsedInOperatingActivities",
    "PaymentsToAcquirePropertyPlantAndEquipment",
    "CommonStockSharesOutstanding",
]

ALLOWED_EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "CBOE"}


class EdgarError(RuntimeError):
    pass


def parse_tickers(body: dict) -> pd.DataFrame:
    """company_tickers_exchange.json → stocks 표준 표 (주요 거래소만)."""
    fields = body["fields"]
    df = pd.DataFrame(body["data"], columns=fields)
    df = df[df["exchange"].isin(ALLOWED_EXCHANGES)]
    out = pd.DataFrame(
        {
            "market": "US",
            "symbol": df["ticker"].str.upper(),
            "name": df["name"],
            "exchange": df["exchange"],
            "external_id": df["cik"].astype(int).astype(str),
        }
    )
    return out.drop_duplicates("symbol").reset_index(drop=True)


def parse_company_facts(body: dict, symbol: str, concepts: list[str] = CONCEPTS) -> pd.DataFrame:
    """companyfacts 응답 → financials 표준 표. 같은 기간이 여러 공시에 나오면 처음 공시된 값을 쓴다."""
    gaap = body.get("facts", {}).get("us-gaap", {})
    rows = []
    for concept in concepts:
        units = gaap.get(concept, {}).get("units", {})
        for unit, facts in units.items():
            for f in facts:
                if f.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A"):
                    continue
                rows.append(
                    {
                        "market": "US",
                        "symbol": symbol,
                        "period_end": f["end"],
                        "period_start": f.get("start"),
                        "fiscal_year": f.get("fy"),
                        "fiscal_period": f.get("fp") or "",
                        "item": concept,
                        "value": f.get("val"),
                        "unit": unit,
                        "filed": f.get("filed"),
                        "source": "sec-edgar",
                    }
                )
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    # SEC 의 fy/fp 는 '공시'의 회계연도라서 비교 기간 값에는 맞지 않는다. 기간 길이로 다시 정한다.
    #   I  = 시점 값(재무상태표), Q = 분기(약 3개월), FY = 연간. 6·9개월 누적 값은 버린다.
    end = pd.to_datetime(df["period_end"])
    start = pd.to_datetime(df["period_start"])
    days = (end - start).dt.days
    df["fiscal_period"] = None
    df.loc[start.isna(), "fiscal_period"] = "I"
    df.loc[days.between(80, 100), "fiscal_period"] = "Q"
    df.loc[days.between(350, 380), "fiscal_period"] = "FY"
    df["fiscal_year"] = end.dt.year
    df = df[df["fiscal_period"].notna()].copy()
    for col in ("period_end", "filed"):
        df[col] = pd.to_datetime(df[col]).dt.date
    df = df.sort_values("filed").drop_duplicates(
        ["symbol", "period_end", "fiscal_period", "item"], keep="first"
    )
    return df.drop(columns=["period_start"]).reset_index(drop=True)


class EdgarClient:
    def __init__(self, user_agent: str, session: requests.Session | None = None, per_second: float = 8):
        if not user_agent:
            raise EdgarError("SEC_USER_AGENT 가 설정되지 않았습니다 (앱 이름과 연락처).")
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.limiter = RateLimiter(per_second)

    def tickers(self) -> pd.DataFrame:
        self.limiter.wait()
        return parse_tickers(request_with_retry(self.session, "GET", TICKERS_URL).json())

    def company_facts(self, cik: int | str, symbol: str) -> pd.DataFrame:
        self.limiter.wait()
        try:
            resp = request_with_retry(self.session, "GET", FACTS_URL.format(cik=int(cik)))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return pd.DataFrame()  # XBRL 재무가 없는 회사(일부 외국 기업 등)
            raise
        return parse_company_facts(resp.json(), symbol)
