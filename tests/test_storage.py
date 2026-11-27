from datetime import date

import pandas as pd
import pytest

from stockproj.storage import Database


def _prices(close: float) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "market": "KR",
                "symbol": "005930",
                "date": date(2026, 11, 26),
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": close,
                "volume": 100.0,
                "source": "test",
            }
        ]
    )


def test_upsert_prices_is_idempotent_and_overwrites():
    db = Database()
    assert db.upsert_prices(_prices(10.0)) == 1
    assert db.upsert_prices(_prices(11.0)) == 1
    rows = db.prices("KR", "005930")
    assert len(rows) == 1
    assert rows.loc[0, "close"] == 11.0
    assert db.last_price_date("KR") == date(2026, 11, 26)


def test_upsert_rejects_missing_columns():
    db = Database()
    with pytest.raises(ValueError, match="close"):
        db.upsert_prices(_prices(1.0).drop(columns=["close"]))


def test_status_counts_per_market():
    db = Database()
    db.upsert_stocks(
        pd.DataFrame(
            [
                {
                    "market": "KR",
                    "symbol": "005930",
                    "name": "삼성전자",
                    "exchange": "KOSPI",
                    "external_id": "00126380",
                },
                {
                    "market": "US",
                    "symbol": "AAPL",
                    "name": "Apple",
                    "exchange": "Nasdaq",
                    "external_id": "320193",
                },
            ]
        )
    )
    db.upsert_prices(_prices(10.0))
    status = db.status().set_index("market")
    assert status.loc["KR", "price_rows"] == 1
    assert status.loc["US", "price_rows"] == 0
