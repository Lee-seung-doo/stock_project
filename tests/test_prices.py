from datetime import date

import pandas as pd

from stockproj.collectors.krx import normalize_market_cap, normalize_ohlcv_by_date, normalize_ohlcv_by_ticker
from stockproj.collectors.us_prices import chunks, normalize_download, to_yahoo_symbol

KR_COLS = ["시가", "고가", "저가", "종가", "거래량", "등락률"]


def test_krx_by_date_drops_halted_days():
    df = pd.DataFrame(
        [[100, 110, 90, 105, 1000, 1.0], [0, 0, 0, 0, 0, 0.0]],
        columns=KR_COLS,
        index=pd.to_datetime(["2026-11-25", "2026-11-26"]),
    )
    out = normalize_ohlcv_by_date(df, "005930")
    assert len(out) == 1
    assert out.loc[0, "close"] == 105
    assert out.loc[0, "date"] == date(2026, 11, 25)
    assert out.loc[0, "symbol"] == "005930"


def test_krx_by_ticker():
    df = pd.DataFrame([[100, 110, 90, 105, 1000, 1.0]], columns=KR_COLS, index=pd.Index(["000660"]))
    out = normalize_ohlcv_by_ticker(df, date(2026, 11, 26))
    assert out.loc[0, "symbol"] == "000660"
    assert out.loc[0, "market"] == "KR"


def test_yahoo_symbol_and_chunks():
    assert to_yahoo_symbol("BF.B") == "BF-B"
    assert list(chunks(["a", "b", "c"], 2)) == [["a", "b"], ["c"]]


def test_normalize_multiindex_download():
    idx = pd.to_datetime(["2026-11-25", "2026-11-26"])
    cols = pd.MultiIndex.from_product([["AAPL", "BF-B"], ["Open", "High", "Low", "Close", "Volume"]])
    df = pd.DataFrame(
        [[1, 2, 0.5, 1.5, 10, 3, 4, 2, 3.5, 20], [1, 2, 0.5, None, 10, 3, 4, 2, 3.6, 20]],
        index=idx,
        columns=cols,
    )
    out = normalize_download(df, ["AAPL", "BF.B", "MISSING"])
    assert set(out["symbol"]) == {"AAPL", "BF.B"}
    assert len(out[out["symbol"] == "AAPL"]) == 1  # 종가 없는 날 제외
    assert len(out[out["symbol"] == "BF.B"]) == 2


def test_krx_market_cap_to_shares():
    df = pd.DataFrame(
        {
            "종가": [100, 0],
            "시가총액": [1e9, 0],
            "거래량": [1, 0],
            "거래대금": [1, 0],
            "상장주식수": [1e7, 0],
        },
        index=pd.Index(["005930", "999999"]),
    )
    out = normalize_market_cap(df, date(2026, 11, 26))
    assert out.to_dict("records")[0]["item"] == "SharesOutstanding"
    assert list(out["symbol"]) == ["005930"]


def test_request_timeout_default(monkeypatch):
    import requests

    from stockproj.collectors import krx

    seen = []

    def fake(self, method, url, **kwargs):
        seen.append(kwargs.get("timeout"))

    monkeypatch.setattr(requests.Session, "request", fake)
    krx._ensure_request_timeout()
    krx._ensure_request_timeout()  # 두 번 불러도 한 번만 감싼다
    requests.Session().request("GET", "http://x")
    requests.Session().request("GET", "http://x", timeout=5)
    assert seen == [krx.REQUEST_TIMEOUT, 5]


def test_krx_preferred_and_etf_excluded():
    from stockproj.collectors.krx import is_common_stock

    assert is_common_stock("005930", "삼성전자")
    assert not is_common_stock("005935", "삼성전자우")
    assert not is_common_stock("00104K", "CJ4우(전환)")
    assert not is_common_stock("001040", "CJ우")  # 코드 끝이 0 이어도 이름이 '우' 로 끝나면 우선주
    assert not is_common_stock("069500", "KODEX 200")
    assert is_common_stock("000880", "한화")
