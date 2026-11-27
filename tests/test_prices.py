from datetime import date

import pandas as pd

from stockproj.collectors.krx import normalize_ohlcv_by_date, normalize_ohlcv_by_ticker
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
