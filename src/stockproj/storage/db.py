"""DuckDB 저장소.

모든 수집기는 아래 세 표준 표 형식으로 데이터를 넘기고, 여기서만 DB에 쓴다.
같은 키로 다시 넣으면 덮어쓰므로(upsert) 수집을 여러 번 돌려도 중복이 생기지 않는다.

- stocks:       종목 목록 (market, symbol 이 키)
- daily_prices: 일봉 (market, symbol, date 가 키)
- financials:   재무 항목 (market, symbol, period_end, fiscal_period, item 이 키)

market 값은 "KR"(국내) 또는 "US"(미국)이다.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import duckdb
import pandas as pd

SCHEMA = """
CREATE TABLE IF NOT EXISTS stocks (
    market      VARCHAR NOT NULL,
    symbol      VARCHAR NOT NULL,
    name        VARCHAR,
    exchange    VARCHAR,
    external_id VARCHAR,          -- 국내: DART 고유번호, 미국: SEC CIK
    updated_at  TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (market, symbol)
);

CREATE TABLE IF NOT EXISTS daily_prices (
    market  VARCHAR NOT NULL,
    symbol  VARCHAR NOT NULL,
    date    DATE NOT NULL,
    open    DOUBLE,
    high    DOUBLE,
    low     DOUBLE,
    close   DOUBLE,
    volume  DOUBLE,
    source  VARCHAR,
    PRIMARY KEY (market, symbol, date)
);

CREATE TABLE IF NOT EXISTS financials (
    market        VARCHAR NOT NULL,
    symbol        VARCHAR NOT NULL,
    period_end    DATE NOT NULL,
    fiscal_year   INTEGER,
    fiscal_period VARCHAR NOT NULL,   -- FY, Q1, H1(=Q2 누적), Q3 등
    item          VARCHAR NOT NULL,   -- 계정 이름 (예: ifrs-full_Revenue, Revenues)
    value         DOUBLE,
    unit          VARCHAR,
    filed         DATE,               -- 공시일: 백테스트에서 미래 정보가 섞이지 않게 이 날짜 기준으로만 사용
    source        VARCHAR,
    PRIMARY KEY (market, symbol, period_end, fiscal_period, item)
);
"""

STOCK_COLUMNS = ["market", "symbol", "name", "exchange", "external_id"]
PRICE_COLUMNS = ["market", "symbol", "date", "open", "high", "low", "close", "volume", "source"]
FINANCIAL_COLUMNS = [
    "market",
    "symbol",
    "period_end",
    "fiscal_year",
    "fiscal_period",
    "item",
    "value",
    "unit",
    "filed",
    "source",
]


class Database:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.con = duckdb.connect(str(path))
        self.con.execute(SCHEMA)

    def close(self) -> None:
        self.con.close()

    # ---- 쓰기 -------------------------------------------------------------

    def _upsert(self, table: str, df: pd.DataFrame, columns: list[str], keys: list[str]) -> int:
        if df is None or df.empty:
            return 0
        missing = set(columns) - set(df.columns)
        if missing:
            raise ValueError(f"{table}: 필요한 열이 없습니다: {sorted(missing)}")
        frame = df[columns].drop_duplicates(subset=keys, keep="last")
        self.con.register("_incoming", frame)
        try:
            cols = ", ".join(columns)
            self.con.execute(f"INSERT OR REPLACE INTO {table} ({cols}) SELECT {cols} FROM _incoming")
        finally:
            self.con.unregister("_incoming")
        return len(frame)

    def upsert_stocks(self, df: pd.DataFrame) -> int:
        return self._upsert("stocks", df, STOCK_COLUMNS, ["market", "symbol"])

    def upsert_prices(self, df: pd.DataFrame) -> int:
        return self._upsert("daily_prices", df, PRICE_COLUMNS, ["market", "symbol", "date"])

    def upsert_financials(self, df: pd.DataFrame) -> int:
        keys = ["market", "symbol", "period_end", "fiscal_period", "item"]
        return self._upsert("financials", df, FINANCIAL_COLUMNS, keys)

    # ---- 읽기 -------------------------------------------------------------

    def symbols(self, market: str) -> pd.DataFrame:
        return self.con.execute(
            "SELECT symbol, name, external_id FROM stocks WHERE market = ? ORDER BY symbol",
            [market],
        ).df()

    def last_price_date(self, market: str) -> date | None:
        row = self.con.execute("SELECT max(date) FROM daily_prices WHERE market = ?", [market]).fetchone()
        return row[0] if row else None

    def prices(self, market: str, symbol: str) -> pd.DataFrame:
        return self.con.execute(
            "SELECT * FROM daily_prices WHERE market = ? AND symbol = ? ORDER BY date",
            [market, symbol],
        ).df()

    def status(self) -> pd.DataFrame:
        return self.con.execute(
            """
            SELECT s.market,
                   count(DISTINCT s.symbol) AS stocks,
                   (SELECT count(*) FROM daily_prices p WHERE p.market = s.market) AS price_rows,
                   (SELECT max(date) FROM daily_prices p WHERE p.market = s.market) AS last_price,
                   (SELECT count(DISTINCT symbol) FROM financials f
                     WHERE f.market = s.market) AS with_financials
            FROM stocks s GROUP BY s.market ORDER BY s.market
            """
        ).df()
