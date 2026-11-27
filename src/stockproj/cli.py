"""명령줄 실행 진입점.

예)
    stockproj listings --market all        # 종목 목록 받기
    stockproj backfill --market kr --years 5
    stockproj daily                        # 매일 장 마감 후 실행
    stockproj financials --market us
    stockproj status                       # 저장 현황 보기
"""

from __future__ import annotations

import argparse
import logging

from stockproj import pipeline
from stockproj.config import load_settings
from stockproj.storage import Database


def _markets(value: str) -> list[str]:
    return ["KR", "US"] if value == "all" else [value.upper()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stockproj", description="주식 데이터 수집")
    p.add_argument("-v", "--verbose", action="store_true", help="자세한 로그")
    sub = p.add_subparsers(dest="command", required=True)

    market = argparse.ArgumentParser(add_help=False)
    market.add_argument("--market", choices=["kr", "us", "all"], default="all")

    sub.add_parser("listings", parents=[market], help="종목 목록 갱신")

    b = sub.add_parser("backfill", parents=[market], help="과거 일봉 백필")
    b.add_argument("--years", type=int, default=5)
    b.add_argument("--limit", type=int, help="앞에서부터 N개 종목만 (테스트용)")

    sub.add_parser("daily", parents=[market], help="최근 일봉 갱신")

    f = sub.add_parser("financials", parents=[market], help="재무제표 수집")
    f.add_argument("--years", type=int, default=3)
    f.add_argument("--quarterly", action="store_true", help="국내 분기 보고서도 수집 (호출 4배)")
    f.add_argument("--limit", type=int)

    sub.add_parser("status", help="저장 현황")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()
    db = Database(settings.db_path)
    try:
        if args.command == "status":
            print(db.status().to_string(index=False))
            return 0
        for m in _markets(args.market):
            if args.command == "listings":
                n = pipeline.update_listings(db, settings, m)
            elif args.command == "backfill":
                n = pipeline.backfill_prices(db, m, years=args.years, limit=args.limit)
            elif args.command == "daily":
                n = pipeline.update_daily(db, m)
            elif args.command == "financials":
                n = pipeline.update_financials(
                    db, settings, m, years=args.years, quarterly=args.quarterly, limit=args.limit
                )
            else:
                raise AssertionError(args.command)
            logging.info("%s %s: %d건 저장", m, args.command, n)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
