"""수집 작업 묶음: 종목 목록 → 과거 시세 백필 → 매일 갱신 → 재무.

각 함수는 몇 건을 저장했는지 돌려주고, 한 종목이 실패해도 로그만 남기고 다음 종목으로 넘어간다.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import date, timedelta

import pandas as pd

from stockproj.config import Settings
from stockproj.storage import Database

log = logging.getLogger(__name__)

Today = Callable[[], date]


def _weekdays(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)
    return days


# ---- 종목 목록 ---------------------------------------------------------------


def update_listings(db: Database, settings: Settings, market: str, today: Today = date.today) -> int:
    if market == "KR":
        from stockproj.collectors import krx

        stocks = pd.DataFrame()
        for back in range(8):  # 주말·휴일이면 가장 가까운 영업일 목록을 쓴다
            day = today() - timedelta(days=back)
            stocks = krx.list_stocks(day)
            if not stocks.empty:
                db.upsert_financials(krx.shares_outstanding(day))  # 시가총액 계산용 상장주식수
                break
        if settings.dart_api_key and not stocks.empty:
            from stockproj.collectors.dart import DartClient

            codes = DartClient(settings.dart_api_key).corp_codes()
            mapping = dict(zip(codes["symbol"], codes["corp_code"], strict=True))
            stocks["external_id"] = stocks["symbol"].map(mapping)
        else:
            log.warning("DART_API_KEY 가 없어 DART 고유번호를 연결하지 않았습니다 (국내 재무 수집 불가).")
    elif market == "US":
        from stockproj.collectors.edgar import EdgarClient

        stocks = EdgarClient(settings.sec_user_agent or "").tickers()
    else:
        raise ValueError(f"알 수 없는 시장: {market}")
    saved = db.upsert_stocks(stocks)
    if not stocks.empty:
        removed = db.remove_unlisted(market, stocks["symbol"].tolist())
        if removed:
            log.info("%s 목록에서 빠진 종목 %d개를 지웠습니다.", market, removed)
    return saved


# ---- 시세 --------------------------------------------------------------------


def backfill_prices(
    db: Database, market: str, years: int = 5, limit: int | None = None, today: Today = date.today
) -> int:
    end = today()
    start = end - timedelta(days=365 * years)
    symbols = db.symbols(market)["symbol"].tolist()[:limit]
    if not symbols:
        raise RuntimeError(f"{market} 종목 목록이 비어 있습니다. 먼저 listings 를 실행하세요.")
    saved = 0
    if market == "KR":
        from stockproj.collectors import krx

        for i, symbol in enumerate(symbols, 1):
            try:
                saved += db.upsert_prices(krx.history(symbol, start, end))
            except Exception as e:  # noqa: BLE001 - 한 종목 실패로 전체를 멈추지 않는다
                log.warning("KR %s 백필 실패: %s", symbol, e)
            if i % 100 == 0:
                log.info("KR 백필 %d/%d 종목, %d행", i, len(symbols), saved)
    elif market == "US":
        from stockproj.collectors import us_prices

        for df in us_prices.download(symbols, start, end):
            saved += db.upsert_prices(df)
            log.info("US 백필 누적 %d행", saved)
    return saved


def update_daily(db: Database, market: str, today: Today = date.today, max_days: int = 30) -> int:
    """마지막 저장일 다음 날부터 오늘까지 채운다. 처음이면 최근 max_days 일."""
    end = today()
    last = db.last_price_date(market)
    start = (
        max(last + timedelta(days=1), end - timedelta(days=max_days))
        if last
        else end - timedelta(days=max_days)
    )
    if start > end:
        return 0
    saved = 0
    if market == "KR":
        from stockproj.collectors import krx

        for day in _weekdays(start, end):
            try:
                saved += db.upsert_prices(krx.snapshot(day))
                db.upsert_financials(krx.shares_outstanding(day))  # 시가총액 계산용
            except Exception as e:  # noqa: BLE001
                log.warning("KR %s 일봉 실패: %s", day, e)
    elif market == "US":
        from stockproj.collectors import us_prices

        symbols = db.symbols("US")["symbol"].tolist()
        # 미국은 시차가 있어 며칠 겹치게 다시 받는다 (덮어쓰기라 중복 없음)
        for df in us_prices.download(symbols, start - timedelta(days=3), end):
            saved += db.upsert_prices(df)
    return saved


# ---- 재무 --------------------------------------------------------------------


def update_financials(
    db: Database,
    settings: Settings,
    market: str,
    years: int = 3,
    quarterly: bool = False,
    limit: int | None = None,
    today: Today = date.today,
) -> int:
    stocks = db.symbols(market)
    stocks = (
        stocks[stocks["external_id"].notna()].head(limit) if limit else stocks[stocks["external_id"].notna()]
    )
    saved = 0
    if market == "KR":
        from stockproj.collectors.dart import REPORT_CODES, DartClient

        client = DartClient(settings.dart_api_key or "")
        codes = list(REPORT_CODES) if quarterly else ["11011"]
        last_year = today().year - 1
        for row in stocks.itertuples():
            for year in range(last_year - years + 1, last_year + 1):
                for code in codes:
                    try:
                        saved += db.upsert_financials(
                            client.financials(row.external_id, row.symbol, year, code)
                        )
                    except Exception as e:  # noqa: BLE001
                        log.warning("KR %s %d %s 재무 실패: %s", row.symbol, year, code, e)
    elif market == "US":
        from stockproj.collectors.edgar import EdgarClient

        client = EdgarClient(settings.sec_user_agent or "")
        cutoff = date(today().year - years - 1, 1, 1)
        for i, row in enumerate(stocks.itertuples(), 1):
            try:
                df = client.company_facts(row.external_id, row.symbol)
                if not df.empty:
                    df = df[df["period_end"] >= cutoff]
                saved += db.upsert_financials(df)
            except Exception as e:  # noqa: BLE001
                log.warning("US %s 재무 실패: %s", row.symbol, e)
            if i % 200 == 0:
                log.info("US 재무 %d/%d 종목", i, len(stocks))
    return saved


# ---- 점수와 알림 --------------------------------------------------------------


def compute_scores(db: Database, market: str, today: Today = date.today) -> int:
    """마지막 시세 날짜(오늘 이전)를 기준일로 프리셋별 점수를 계산해 저장한다."""
    from stockproj.analysis import scoring

    last = db.last_price_date(market)
    if last is None:
        raise RuntimeError(f"{market} 시세가 없습니다. 먼저 backfill 또는 daily 를 실행하세요.")
    as_of = min(last, today())
    scores = scoring.compute(db, market, as_of)
    saved = db.replace_scores(scores)
    log.info(
        "%s %s 기준 점수 %d건 (추천 이상 %d건)",
        market,
        as_of,
        saved,
        int(scores["grade"].isin(["강력 추천", "추천"]).sum()) if saved else 0,
    )
    return saved


def send_kakao(db: Database, settings: Settings) -> int:
    from stockproj.report.kakao import KakaoClient, notify

    client = KakaoClient(
        settings.kakao_rest_api_key or "",
        settings.kakao_token_path,
        redirect_uri=settings.kakao_redirect_uri,
        client_secret=settings.kakao_client_secret,
    )
    return notify(client, db.latest_scores(), settings.dashboard_url)
