"""OpenDART: 국내 상장사 고유번호와 재무제표.

- corpCode.xml: 전체 회사 고유번호(ZIP 안의 XML). 상장사만 stock_code 가 있다.
- fnlttSinglAcntAll.json: 단일회사 전체 재무제표.
"""

from __future__ import annotations

import io
import xml.etree.ElementTree as ET
import zipfile
from datetime import date

import pandas as pd
import requests

from stockproj.collectors.http import RateLimiter, request_with_retry

BASE_URL = "https://opendart.fss.or.kr/api"

# 보고서 코드 → (분기 표시, 기간 종료 월-일). 12월 결산 법인을 가정한다.
REPORT_CODES = {
    "11013": ("Q1", "03-31"),
    "11012": ("H1", "06-30"),
    "11014": ("Q3", "09-30"),
    "11011": ("FY", "12-31"),
}


class DartError(RuntimeError):
    pass


def parse_corp_codes(zip_bytes: bytes) -> pd.DataFrame:
    """corpCode.xml ZIP 을 상장사(stock_code 가 있는 회사)만 담은 표로 바꾼다."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
        xml_bytes = zf.read(zf.namelist()[0])
    rows = []
    for node in ET.fromstring(xml_bytes).iter("list"):
        stock_code = (node.findtext("stock_code") or "").strip()
        if not stock_code:
            continue
        rows.append(
            {
                "symbol": stock_code,
                "corp_code": (node.findtext("corp_code") or "").strip(),
                "corp_name": (node.findtext("corp_name") or "").strip(),
            }
        )
    return pd.DataFrame(rows, columns=["symbol", "corp_code", "corp_name"])


def _to_number(text: str | None) -> float | None:
    if text is None:
        return None
    cleaned = str(text).replace(",", "").strip()
    if cleaned in ("", "-"):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def parse_financials(body: dict, symbol: str, year: int, reprt_code: str) -> pd.DataFrame:
    """fnlttSinglAcntAll 응답을 financials 표준 표로 바꾼다."""
    status = body.get("status")
    if status == "013":  # 조회된 데이터 없음
        return pd.DataFrame()
    if status != "000":
        raise DartError(f"OpenDART 오류 {status}: {body.get('message')}")
    period, month_day = REPORT_CODES[reprt_code]
    period_end = date.fromisoformat(f"{year}-{month_day}")
    rows = []
    for item in body.get("list", []):
        account_id = (item.get("account_id") or "").strip()
        name = account_id if account_id and "미사용" not in account_id else item.get("account_nm")
        rcept_no = item.get("rcept_no") or ""
        filed = (
            date(int(rcept_no[:4]), int(rcept_no[4:6]), int(rcept_no[6:8]))
            if len(rcept_no) >= 8 and rcept_no[:8].isdigit()
            else None
        )
        rows.append(
            {
                "market": "KR",
                "symbol": symbol,
                "period_end": period_end,
                "fiscal_year": year,
                "fiscal_period": period,
                "item": f"{item.get('sj_div', '')}:{name}",  # 재무상태표(BS)/손익(IS,CIS)/현금흐름(CF) 구분
                "value": _to_number(item.get("thstrm_amount")),
                "unit": item.get("currency") or "KRW",
                "filed": filed,
                "source": "opendart",
            }
        )
    return pd.DataFrame(rows)


class DartClient:
    def __init__(self, api_key: str, session: requests.Session | None = None, per_second: float = 5):
        if not api_key:
            raise DartError("DART_API_KEY 가 설정되지 않았습니다.")
        self.api_key = api_key
        self.session = session or requests.Session()
        self.limiter = RateLimiter(per_second)

    def corp_codes(self) -> pd.DataFrame:
        resp = request_with_retry(
            self.session, "GET", f"{BASE_URL}/corpCode.xml", params={"crtfc_key": self.api_key}
        )
        return parse_corp_codes(resp.content)

    def financials(
        self, corp_code: str, symbol: str, year: int, reprt_code: str = "11011", consolidated: bool = True
    ) -> pd.DataFrame:
        self.limiter.wait()
        resp = request_with_retry(
            self.session,
            "GET",
            f"{BASE_URL}/fnlttSinglAcntAll.json",
            params={
                "crtfc_key": self.api_key,
                "corp_code": corp_code,
                "bsns_year": str(year),
                "reprt_code": reprt_code,
                "fs_div": "CFS" if consolidated else "OFS",
            },
        )
        return parse_financials(resp.json(), symbol, year, reprt_code)
