"""화면·출력용 숫자 서식. 금액은 모두 천 단위 쉼표를 붙인다."""

from __future__ import annotations

import pandas as pd

CURRENCY = {"KR": "원", "US": "달러"}


def price(value: float | None, market: str) -> str:
    """국내는 원 단위 정수(75,300), 미국은 센트까지(1,234.56)."""
    if value is None or pd.isna(value):
        return "-"
    return f"{value:,.0f}" if market == "KR" else f"{value:,.2f}"


def price_formatter(market: str):
    return lambda v: price(v, market)
