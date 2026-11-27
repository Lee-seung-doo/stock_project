# stock_project

국내(KOSPI·KOSDAQ)와 미국 주식을 재무, 차트, 뉴스로 분석해 단타·중타·장타별로 종목을 추천하는 시스템입니다.
나중에 토스증권 Open API 로 자동 매매를 붙일 수 있게 수집, 저장, 분석, 주문을 모듈로 나눴습니다.

설계 문서: 프로젝트의 "주식 종목 분석·추천 시스템 설계 초안" 문서를 참고하세요.

## 진행 단계

| 단계 | 내용 | 상태 |
| --- | --- | --- |
| 0 | 프로젝트 골격, 데이터 수집기, DuckDB 저장소 | 완료 |
| 1 | 재무·차트 점수, 단타·중타·장타 순위, 카카오톡 알림, 간단한 웹 화면 | 진행 중 |
| 2 | 뉴스·공시 감성 분석, 백테스트로 가중치 조정 | 예정 |
| 3 | 대시보드 고도화, 클라우드 서버 이전 | 예정 |
| 4 | 자동 매매 (가상 체결로 검증 후 소액 실전) | 예정 |

## 설치

Python 3.11~3.14 를 지원합니다. 3.15 에서는 pykrx 가 pandas 3 미만을 요구해서 설치되지 않습니다.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[backfill,web,dev]"
cp .env.example .env               # 그리고 .env 에 API 키를 채운다
```

## API 키와 계정 준비 (모두 무료)

| 이름 | 발급처 | 용도 |
| --- | --- | --- |
| `KRX_ID`, `KRX_PW` | [KRX 정보데이터시스템](https://data.krx.co.kr) 회원가입 아이디·비밀번호 (필수) | 국내 종목 목록·일봉 (pykrx 가 로그인에 사용) |
| `DART_API_KEY` | [OpenDART](https://opendart.fss.or.kr) 회원가입 후 인증키 신청 | 국내 재무제표 |
| `SEC_USER_AGENT` | 키 없음. `앱이름 본인이메일` 형식으로 적기 | 미국 재무제표 (SEC 요구 사항) |
| `TOSS_CLIENT_ID`, `TOSS_CLIENT_SECRET` | 토스증권 WTS > 설정 > Open API, 허용 IP 등록 필요 | 시세(공식 문서 확인 후), 4단계에서 주문 |
| `KAKAO_REST_API_KEY` | [카카오 디벨로퍼스](https://developers.kakao.com) 앱 생성 (아래 카카오톡 설정 참고) | 카카오톡으로 추천 받기 |

`.env` 는 git 에 올라가지 않습니다. 키를 코드나 채팅에 붙여 넣지 마세요.

## 사용법

```bash
stockproj listings --market all          # 1) 국내·미국 종목 목록 (국내 DART 고유번호 연결)
stockproj backfill --market kr --years 5 # 2) 과거 5년 일봉 (처음 한 번, 오래 걸림)
stockproj backfill --market us --years 5
stockproj financials --market all        # 3) 재무제표 (국내는 사업보고서 3년치)
stockproj daily                          # 4) 매일 장 마감 후 최근 일봉 갱신
stockproj score                          # 5) 단타·중타·장타 점수 계산
stockproj top --market kr --preset mid   #    상위 종목 보기 (preset: short, mid, long)
stockproj web                            # 6) 웹 화면 (브라우저에서 http://localhost:8501)
stockproj notify                         # 7) 카카오톡으로 추천 보내기
stockproj status                         # 저장 현황
```

`stockproj run-daily` 는 daily + score + notify 를 한 번에 합니다. 매일 자동 실행에는 이것을 씁니다.

처음에는 `--limit 20` 을 붙여 몇 종목만 돌려 보고 동작을 확인하는 것을 권합니다.
데이터는 `data/stock.duckdb` 한 파일에 쌓입니다.

매일 자동 실행 예시 (macOS/Linux cron, 한국 시간 기준):

```cron
40 15 * * 1-5  cd ~/stock_project && .venv/bin/stockproj run-daily --market kr
30  7 * * 2-6  cd ~/stock_project && .venv/bin/stockproj run-daily --market us
```

재무제표는 분기마다 한 번(실적 발표 시즌 뒤) `stockproj financials` 로 새로 받으면 됩니다.

## 점수 계산 방식

종목마다 기준일(마지막 시세 날짜)에 알 수 있던 데이터만으로 점수를 냅니다. 재무는 공시일 기준으로 자릅니다.

| 모듈 | 지표 | 비교 방식 |
| --- | --- | --- |
| 재무 | 가치(이익수익률·PBR·PSR 역수), 수익성(ROE·영업이익률), 성장(매출·순이익 성장률), 안정성(부채비율) | 같은 시장 안 백분위 |
| 차트 단기 | 5일·1개월 수익률, 거래량 증가, RSI(60 근처 최고) | 같은 시장 안 백분위 |
| 차트 중기 | 이동평균 정배열, 3·6개월 수익률, 12개월-1개월 모멘텀 | 같은 시장 안 백분위 |

| 프리셋 | 재무 | 차트 | 뉴스(2단계) |
| --- | --- | --- | --- |
| 단타 | 10% | 단기 60% | 30% |
| 중타 | 30% | 중기 45% | 25% |
| 장타 | 60% | 중기 20% | 20% |

뉴스 점수가 생기기 전에는 남은 모듈 비중을 100% 로 다시 맞춥니다.
등급은 80 이상 강력 추천, 65 이상 추천, 35 이상 중립, 그 아래 주의이고, 한 모듈이라도 20 미만이면 추천을 주지 않습니다.
최근 20일 평균 거래대금이 국내 10억 원, 미국 500만 달러 미만인 종목은 제외합니다.
추천 대상은 보통주만입니다. ETF·ETN, 우선주, 워런트·유닛·권리는 `listings` 단계에서 목록에서 뺍니다(미국 ETF 는 Nasdaq Trader 종목 디렉터리 기준).
가중치와 기준은 모두 초기값이며 2단계 백테스트로 조정합니다.

## 카카오톡 설정 (한 번만)

1. [카카오 디벨로퍼스](https://developers.kakao.com)에 로그인해 애플리케이션을 추가합니다.
2. 앱 키의 **REST API 키**를 `.env` 의 `KAKAO_REST_API_KEY` 에 넣습니다.
3. 제품 설정 > 카카오 로그인을 **활성화**하고 Redirect URI 에 `https://localhost` 를 등록합니다.
4. 동의항목에서 **카카오톡 메시지 전송**을 사용으로 바꿉니다.
5. `stockproj kakao-login` 을 실행해 나오는 주소로 로그인하고, 이동한 페이지 주소창의 값을 붙여 넣습니다.
   (페이지가 열리지 않는다는 오류가 나와도 주소창에 `code=` 가 있으면 됩니다.)
6. `stockproj notify` 로 시험 메시지를 보내 봅니다.

로그인은 약 두 달 유지되며, 만료되면 5번을 다시 하면 됩니다.
메시지의 버튼은 `DASHBOARD_URL` 을 엽니다. 카카오 앱 설정의 플랫폼 > Web 에 그 도메인을 등록해야 버튼이 동작합니다.

## 코드 구조

```
src/stockproj/
  config.py            .env 설정 읽기
  cli.py               명령줄 진입점 (stockproj ...)
  pipeline.py          작업 묶음 (목록, 백필, 일일 갱신, 재무, 점수, 알림)
  storage/db.py        DuckDB 표 4개: stocks, daily_prices, financials, scores
  analysis/
    fundamental.py     재무 점수
    technical.py       차트 점수와 유동성 필터
    scoring.py         단타·중타·장타 종합 점수, 등급, 근거
  report/
    kakao.py           카카오톡 나에게 보내기
    web.py             Streamlit 웹 화면
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

- pykrx·yfinance 는 비공식 라이브러리라 사이트가 바뀌면 깨질 수 있습니다. 토스증권 API 공식 문서를 확인한 뒤 일일 갱신을 옮길 예정입니다.
- 국내 일일 갱신(날짜별 조회)은 수정주가가 아니라서, 액면분할 등이 있었던 종목은 `backfill` 을 다시 돌려야 합니다.
- 재무 점수는 아직 업종 구분 없이 시장 전체와 비교합니다. 은행·보험처럼 재무 구조가 다른 업종은 점수가 왜곡될 수 있습니다.
- DART 분기 기간 종료일은 12월 결산을 가정합니다.
- 토스증권 API 의 경로와 한도는 제3자 가이드 기준이라 공식 문서로 확인이 필요합니다.

## 개발

```bash
pytest        # 테스트
ruff check .  # 린트
ruff format . # 서식 정리
```
