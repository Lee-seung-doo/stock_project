"""SEC EDGAR: 미국 상장사 목록(티커↔CIK)과 XBRL 재무 데이터. 무료, 초당 10회 제한.

SEC 는 User-Agent 에 앱 이름과 연락처를 요구한다(.env 의 SEC_USER_AGENT).
"""

from __future__ import annotations

import re

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

# dei(문서 정보) 항목 → 저장할 이름. 시가총액 계산에 쓰는 발행주식수.
DEI_CONCEPTS = {"EntityCommonStockSharesOutstanding": "SharesOutstanding"}

ALLOWED_EXCHANGES = {"NYSE", "Nasdaq", "NYSE American", "NYSE Arca", "CBOE"}

# 보통주가 아닌 증권(워런트, 유닛, 권리, 우선주) 이름 패턴
_NON_COMMON_NAME = re.compile(
    r"\b(warrants?|units?|rights?|preferred|depositary shares? representing)\b", re.I
)
# ETF·ETN·펀드로 보이는 이름 (거래소 ETF 목록을 못 받았을 때의 보조 규칙)
_FUND_NAME = re.compile(
    r"\b(ETF|ETN|ETP|Fund|Funds)\b|ProShares|iShares|SPDR|Invesco DB|Direxion|WisdomTree|VanEck|Grayscale",
    re.I,
)
# 티커 접미사: BRK-B 처럼 클래스 주식은 남기고, -WT -WS -U -UN -R -RT -P* 는 뺀다
_NON_COMMON_SUFFIX = re.compile(r"-(WT|WS|W|U|UN|R|RT|P[A-Z]?)$")


def is_common_stock(symbol: str, name: str, exchange: str, etfs: frozenset[str] = frozenset()) -> bool:
    """보통주로 보이면 True. Nasdaq 5글자 티커의 끝 W/U/R 은 워런트·유닛·권리 관례다.

    etfs: 거래소 디렉터리에서 받은 ETF 티커. 여기에 있거나 이름이 ETF·펀드 같으면 제외한다.
    """
    symbol = symbol.upper()
    if symbol in etfs or _FUND_NAME.search(name or ""):
        return False
    if _NON_COMMON_SUFFIX.search(symbol) or _NON_COMMON_NAME.search(name or ""):
        return False
    if exchange == "Nasdaq" and len(symbol) == 5 and symbol[-1] in "WUR":
        return False
    return True


class EdgarError(RuntimeError):
    pass


def parse_tickers(body: dict, etfs: frozenset[str] = frozenset()) -> pd.DataFrame:
    """company_tickers_exchange.json → stocks 표준 표 (주요 거래소 보통주만)."""
    fields = body["fields"]
    df = pd.DataFrame(body["data"], columns=fields)
    df = df[df["exchange"].isin(ALLOWED_EXCHANGES)]
    df = df[
        [
            is_common_stock(t, n, e, etfs)
            for t, n, e in zip(df["ticker"], df["name"], df["exchange"], strict=True)
        ]
    ]
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
    facts_by_ns = body.get("facts", {})
    targets = [(facts_by_ns.get("us-gaap", {}), c, c) for c in concepts]
    targets += [(facts_by_ns.get("dei", {}), c, name) for c, name in DEI_CONCEPTS.items()]
    rows = []
    for ns, concept, item_name in targets:
        units = ns.get(concept, {}).get("units", {})
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
                        "item": item_name,
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

    def tickers(self, etfs: frozenset[str] = frozenset()) -> pd.DataFrame:
        self.limiter.wait()
        return parse_tickers(request_with_retry(self.session, "GET", TICKERS_URL).json(), etfs)

    def company_facts(self, cik: int | str, symbol: str) -> pd.DataFrame:
        self.limiter.wait()
        try:
            resp = request_with_retry(self.session, "GET", FACTS_URL.format(cik=int(cik)))
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                return pd.DataFrame()  # XBRL 재무가 없는 회사(일부 외국 기업 등)
            raise
        return parse_company_facts(resp.json(), symbol)
