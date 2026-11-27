import io
import zipfile
from datetime import date

import pandas as pd
import pytest

from stockproj.collectors.dart import DartError, parse_corp_codes, parse_financials

CORP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<result>
  <list><corp_code>00126380</corp_code><corp_name>삼성전자</corp_name>
        <stock_code>005930</stock_code><modify_date>20260101</modify_date></list>
  <list><corp_code>00999999</corp_code><corp_name>비상장회사</corp_name>
        <stock_code> </stock_code><modify_date>20260101</modify_date></list>
</result>""".encode()


def _zip(data: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("CORPCODE.xml", data)
    return buf.getvalue()


def test_parse_corp_codes_keeps_listed_only():
    df = parse_corp_codes(_zip(CORP_XML))
    assert df.to_dict("records") == [{"symbol": "005930", "corp_code": "00126380", "corp_name": "삼성전자"}]


def test_parse_financials_maps_period_and_values():
    body = {
        "status": "000",
        "list": [
            {
                "rcept_no": "20260310000123",
                "sj_div": "IS",
                "account_id": "ifrs-full_Revenue",
                "account_nm": "매출액",
                "thstrm_amount": "300,870,903,000,000",
                "currency": "KRW",
            },
            {
                "rcept_no": "20260310000123",
                "sj_div": "IS",
                "account_id": "-표준계정코드 미사용-",
                "account_nm": "기타손실",
                "thstrm_amount": "-1,000",
                "currency": "KRW",
            },
            {
                "rcept_no": "20260310000123",
                "sj_div": "BS",
                "account_id": "ifrs-full_Assets",
                "account_nm": "자산총계",
                "thstrm_amount": "",
                "currency": "KRW",
            },
        ],
    }
    df = parse_financials(body, "005930", 2025, "11011")
    assert list(df["item"]) == ["IS:ifrs-full_Revenue", "IS:기타손실", "BS:ifrs-full_Assets"]
    assert df.loc[0, "value"] == 300_870_903_000_000
    assert df.loc[1, "value"] == -1000
    assert pd.isna(df.loc[2, "value"])
    assert df.loc[0, "period_end"] == date(2025, 12, 31)
    assert df.loc[0, "fiscal_period"] == "FY"
    assert df.loc[0, "filed"] == date(2026, 3, 10)


def test_parse_financials_no_data_and_error():
    assert parse_financials({"status": "013"}, "005930", 2025, "11011").empty
    with pytest.raises(DartError):
        parse_financials({"status": "020", "message": "사용한도 초과"}, "005930", 2025, "11011")
