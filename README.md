# stock_project

국내(KOSPI·KOSDAQ)와 미국 주식을 재무, 차트, 뉴스로 분석해 단타·중타·장타별로 종목을 추천하는 시스템입니다.
나중에 토스증권 Open API 로 자동 매매를 붙일 수 있게 수집, 저장, 분석, 주문을 모듈로 나눴습니다.

설계 문서: 프로젝트의 "주식 종목 분석·추천 시스템 설계 초안" 문서를 참고하세요.

## 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 0 | 프로젝트 골격, 데이터 수집기, DuckDB 저장소 | 진행 중 |
| 1 | 재무·차트 점수, 단타·중타·장타 순위, 카카오톡 알림, 간단한 웹 화면 | 예정 |
| 2 | 뉴스·공시 감성 분석, 백테스트로 가중치 조정 | 예정 |
| 3 | 대시보드 고도화, 클라우드 서버 이전 | 예정 |
| 4 | 자동 매매 (가상 체결로 검증 후 소액 실전) | 예정 |

## 설치

Python 3.11~3.14 를 지원합니다. 3.15 에서는 pykrx 가 pandas 3 미만을 요구해서 설치되지 않습니다.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[backfill,dev]"
cp .env.example .env               # 그리고 .env 에 API 키를 채운다
```

## API 키와 계정 준비 (모두 무료)

| 이름 | 발급처 | 용도 |
| --- | --- | --- |
| `KRX_ID`, `KRX_PW` | [KRX 정보데이터시스템](https://data.krx.co.kr) 회원가입 아이디·비밀번호 (필수) | 국내 종목 목록·일봉 (pykrx 가 로그인에 사용) |
| `DART_API_KEY` | [OpenDART](https://opendart.fss.or.kr) 회원가입 후 인증키 신청 | 국내 재무제표 |
| `SEC_USER_AGENT` | 키 없음. `앱이름 본인이메일` 형식으로 적기 | 미국 재무제표 (SEC 요구 사항) |
| `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` | 토스증권 WTS > 설정 > Open API, 허용 IP 등록 필요 | 1단계부터 시세, 4단계에서 주문 |

`.env` 는 git 에 올라가지 않습니다. 키를 코드나 채팅에 붙여 넣지 마세요.

## 사용법

```bash
stockproj listings --market all          # 1) 국내·미국 종목 목록 (국내 DART 고유번호 연결)
stockproj backfill --market kr --years 5 # 2) 과거 5년 일봉 (처음 한 번, 오래 걸림)
stockproj backfill --market us --years 5
stockproj financials --market all        # 3) 재무제표 (국내는 사업보고서 3년치)
stockproj daily                          # 4) 매일 장 마감 후 최근 일봉 갱신
stockproj status                         # 저장 현황
```

처음에는 `--limit 20` 을 붙여 몇 종목만 돌려 보고 동작을 확인하는 것을 권합니다.
데이터는 `data/stock.duckdb` 한 파일에 쌓입니다.

매일 자동 실행 예시 (macOS/Linux cron, 한국 시간 기준):

```cron
40 15 * * 1-5  cd ~/stock_project && .venv/bin/stockproj daily --market kr
30  7 * * 2-6  cd ~/stock_project && .venv/bin/stockproj daily --market us
```

## 코드 구조

```
src/stockproj/
  config.py            .env 설정 읽기
  cli.py               명령줄 진입점 (stockproj ...)
  pipeline.py          수집 작업 묶음 (목록, 백필, 일일 갱신, 재무)
  storage/db.py        DuckDB 표 3개: stocks, daily_prices, financials
  collectors/
    http.py            공통 재시도(429·5xx)와 호출 간격 조절
    krx.py             국내 목록·일봉 (pykrx)
    us_prices.py       미국 일봉 (yfinance)
    dart.py            국내 재무 (OpenDART)
    edgar.py           미국 목록·재무 (SEC EDGAR)
    toss.py            토스증권 Open API (인증·공통 호출까지, 시세 변환은 공식 문서 확인 후)
tests/                 인터넷 없이 도는 단위 테스트
```

수집기는 외부 데이터를 표준 표(DataFrame)로 바꿔 돌려주기만 하고, DB 에는 `storage/db.py` 만 씁니다.
그래서 데이터 소스를 바꿔도 분석 코드는 그대로입니다.

## 알려진 한계

- pykrx·yfinance 는 비공식 라이브러리라 사이트가 바뀌면 깨질 수 있습니다. 1단계에서 일일 갱신을 토스증권 API 로 옮길 예정입니다.
- 국내 일일 갱신(날짜별 조회)은 수정주가가 아니라서, 액면분할 등이 있었던 종목은 `backfill` 을 다시 돌려야 합니다.
- 미국 종목 목록에 워런트·유닛 등 약 1,200개가 섞여 있습니다. 1단계에서 걸러낼 예정입니다.
- DART 분기 기간 종료일은 12월 결산을 가정합니다.
- 토스증권 API 의 경로와 한도는 제3자 가이드 기준이라 공식 문서로 확인이 필요합니다.

## 개발

```bash
pytest        # 테스트
ruff check .  # 린트
ruff format . # 서식 정리
```
