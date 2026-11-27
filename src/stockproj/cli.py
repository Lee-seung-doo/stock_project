"""명령줄 실행 진입점.

예)
    stockproj listings --market all        # 종목 목록 받기
    stockproj backfill --market kr --years 5
    stockproj financials --market us
    stockproj daily                        # 최근 일봉 갱신
    stockproj score                        # 단타·중타·장타 점수 계산
    stockproj top --market kr --preset mid # 상위 종목 보기
    stockproj kakao-login                  # 카카오톡 연결 (한 번만)
    stockproj notify                       # 카카오톡으로 추천 보내기
    stockproj run-daily --market kr        # daily + score + notify 를 한 번에 (매일 자동 실행용)
    stockproj web                          # 웹 화면 열기
    stockproj status                       # 저장 현황 보기
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
from pathlib import Path

from stockproj import pipeline
from stockproj.config import load_settings
from stockproj.storage import Database

log = logging.getLogger("stockproj")


def _markets(value: str) -> list[str]:
    return ["KR", "US"] if value == "all" else [value.upper()]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="stockproj", description="주식 종목 분석·추천")
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

    sub.add_parser("score", parents=[market], help="단타·중타·장타 점수 계산")

    t = sub.add_parser("top", parents=[market], help="최근 점수 상위 종목 출력")
    t.add_argument("--preset", choices=["short", "mid", "long"], default="mid")
    t.add_argument("-n", type=int, default=20)

    sub.add_parser("kakao-login", help="카카오톡 나에게 보내기 연결 (처음 한 번)")
    sub.add_parser("notify", help="카카오톡으로 최근 추천 보내기")
    sub.add_parser("run-daily", parents=[market], help="daily + score + notify")
    sub.add_parser("web", help="웹 대시보드 실행")
    sub.add_parser("status", help="저장 현황")
    return p


def _kakao_login(settings) -> None:
    from stockproj.report.kakao import KakaoClient

    client = KakaoClient(
        settings.kakao_rest_api_key or "",
        settings.kakao_token_path,
        redirect_uri=settings.kakao_redirect_uri,
        client_secret=settings.kakao_client_secret,
    )
    print("1) 아래 주소를 브라우저에서 열고 카카오 계정으로 로그인·동의하세요.")
    print(client.authorize_url())
    print(
        "2) 이동한 페이지 주소창의 'code=' 뒤 값을 붙여 넣으세요 (페이지가 안 열려도 주소만 있으면 됩니다)."
    )
    code = input("code: ").strip()
    if "code=" in code:
        code = code.split("code=", 1)[1].split("&", 1)[0]
    client.login_with_code(code)
    print(f"연결됐습니다. 토큰을 {settings.kakao_token_path} 에 저장했습니다.")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    settings = load_settings()

    if args.command == "web":
        app = Path(__file__).parent / "report" / "web.py"
        # headless: 첫 실행 때 이메일을 묻는 질문을 건너뛴다
        return subprocess.call(
            [sys.executable, "-m", "streamlit", "run", str(app), "--server.headless", "true"]
        )
    if args.command == "kakao-login":
        _kakao_login(settings)
        return 0

    db = Database(settings.db_path)
    try:
        if args.command == "status":
            print(db.status().to_string(index=False))
        elif args.command == "notify":
            log.info("카카오톡 %d통 보냄", pipeline.send_kakao(db, settings))
        elif args.command == "top":
            _print_top(db, _markets(args.market), args.preset, args.n)
        else:
            for m in _markets(args.market):
                _run(args, db, settings, m)
            if args.command == "run-daily":
                log.info("카카오톡 %d통 보냄", pipeline.send_kakao(db, settings))
    finally:
        db.close()
    return 0


def _run(args, db: Database, settings, m: str) -> None:
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
    elif args.command == "score":
        n = pipeline.compute_scores(db, m)
    elif args.command == "run-daily":
        pipeline.update_daily(db, m)
        n = pipeline.compute_scores(db, m)
    else:
        raise AssertionError(args.command)
    log.info("%s %s: %d건 저장", m, args.command, n)


def _print_top(db: Database, markets: list[str], preset: str, n: int) -> None:
    scores = db.latest_scores()
    for m in markets:
        part = scores[(scores["market"] == m) & (scores["preset"] == preset)].head(n)
        if part.empty:
            print(f"[{m}] 점수가 없습니다. `stockproj score` 를 먼저 실행하세요.")
            continue
        print(f"[{m} · {preset} · 기준일 {part['as_of'].iloc[0]:%Y-%m-%d}]")
        cols = ["rank", "symbol", "name", "score", "grade", "fundamental", "technical", "reasons"]
        print(part[cols].round(1).to_string(index=False))


if __name__ == "__main__":
    raise SystemExit(main())
