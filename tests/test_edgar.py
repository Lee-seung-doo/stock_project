from datetime import date

from stockproj.collectors.edgar import is_common_stock, parse_company_facts, parse_tickers


def test_parse_tickers_filters_exchanges():
    body = {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [320193, "Apple Inc.", "AAPL", "Nasdaq"],
            [1067983, "Berkshire Hathaway", "BRK-B", "NYSE"],
            [1234, "Some OTC Co", "XXXX", "OTC"],
        ],
    }
    df = parse_tickers(body)
    assert list(df["symbol"]) == ["AAPL", "BRK-B"]
    assert list(df["external_id"]) == ["320193", "1067983"]
    assert set(df["market"]) == {"US"}


def test_parse_company_facts_classifies_periods_and_keeps_first_filing():
    body = {
        "facts": {
            "us-gaap": {
                "Revenues": {
                    "units": {
                        "USD": [
                            # 연간 값: 원래 10-K 와 다음 해 10-K 의 비교 기간 → 처음 공시만 남아야 함
                            {
                                "start": "2024-10-01",
                                "end": "2025-09-30",
                                "val": 100,
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-11-01",
                            },
                            {
                                "start": "2024-10-01",
                                "end": "2025-09-30",
                                "val": 101,
                                "form": "10-K",
                                "fy": 2026,
                                "fp": "FY",
                                "filed": "2026-11-01",
                            },
                            # 분기 값
                            {
                                "start": "2025-07-01",
                                "end": "2025-09-30",
                                "val": 30,
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-11-01",
                            },
                            # 9개월 누적 → 버림
                            {
                                "start": "2025-01-01",
                                "end": "2025-09-30",
                                "val": 70,
                                "form": "10-Q",
                                "fy": 2025,
                                "fp": "Q3",
                                "filed": "2025-10-30",
                            },
                            # 10-K/10-Q 가 아닌 서식 → 버림
                            {
                                "start": "2024-10-01",
                                "end": "2025-09-30",
                                "val": 999,
                                "form": "8-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-10-20",
                            },
                        ]
                    }
                },
                "Assets": {
                    "units": {
                        "USD": [
                            {
                                "end": "2025-09-30",
                                "val": 500,
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-11-01",
                            },
                        ]
                    }
                },
            }
        }
    }
    df = parse_company_facts(body, "AAPL").set_index(["item", "fiscal_period"])
    assert df.loc[("Revenues", "FY"), "value"] == 100
    assert df.loc[("Revenues", "FY"), "filed"] == date(2025, 11, 1)
    assert df.loc[("Revenues", "Q"), "value"] == 30
    assert df.loc[("Assets", "I"), "value"] == 500
    assert len(df) == 3


def test_parse_company_facts_empty():
    assert parse_company_facts({"facts": {}}, "X").empty


def test_is_common_stock_filters_warrants_units_rights():
    assert is_common_stock("AAPL", "Apple Inc.", "Nasdaq")
    assert is_common_stock("BRK-B", "Berkshire Hathaway", "NYSE")
    assert not is_common_stock("ABCDW", "Abc Acquisition Corp", "Nasdaq")
    assert not is_common_stock("ABCDU", "Abc Acquisition Corp", "Nasdaq")
    assert not is_common_stock("XYZ-WT", "Xyz Corp", "NYSE")
    assert not is_common_stock("XYZ-PA", "Xyz Corp", "NYSE")
    assert not is_common_stock("QQQQ", "Some SPAC Units", "NYSE")


def test_parse_company_facts_reads_dei_shares():
    body = {
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": {
                    "units": {
                        "shares": [
                            {
                                "end": "2025-10-15",
                                "val": 15000,
                                "form": "10-K",
                                "fy": 2025,
                                "fp": "FY",
                                "filed": "2025-11-01",
                            }
                        ]
                    }
                }
            }
        }
    }
    df = parse_company_facts(body, "AAPL")
    assert df.loc[0, "item"] == "SharesOutstanding"
    assert df.loc[0, "fiscal_period"] == "I"
    assert df.loc[0, "value"] == 15000


def test_etfs_and_fund_names_excluded():
    assert not is_common_stock("AGQ", "ProShares Trust II", "NYSE Arca")
    assert not is_common_stock("AAAU", "Goldman Sachs Physical Gold ETF", "NYSE Arca")
    assert not is_common_stock("XYZ", "Plain Name Corp", "NYSE", etfs=frozenset({"XYZ"}))
    assert is_common_stock("XYZ", "Plain Name Corp", "NYSE")


def test_parse_nasdaq_directory():
    from stockproj.collectors.nasdaq import parse_etf_symbols

    text = (
        "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol\n"
        "AGQ|ProShares Ultra Silver|P|AGQ|Y|100|N|AGQ\n"
        "BRK.B|Berkshire Hathaway Inc. Class B|N|BRK.B|N|100|N|BRK=B\n"
        "SPY.X|Some ETF Class X|P|SPY.X|Y|100|N|SPY=X\n"
        "File Creation Time: 1127202618:00|||||||\n"
    )
    assert parse_etf_symbols(text, "ACT Symbol") == {"AGQ", "SPY-X"}
