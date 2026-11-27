"""간단한 웹 대시보드 (Streamlit).

실행: `stockproj web` (또는 `streamlit run src/stockproj/report/web.py`)
가장 최근 점수를 시장·프리셋별로 보여주고, 종목을 고르면 주가 그래프와 근거를 보여준다.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st

from stockproj.analysis.scoring import PRESETS
from stockproj.config import load_settings
from stockproj.report import fmt
from stockproj.storage import Database

MARKETS = {"KR": "국내", "US": "미국"}


@st.cache_resource
def _db() -> Database:
    return Database(load_settings().db_path, read_only=True)


def main() -> None:
    st.set_page_config(page_title="종목 추천", layout="wide")
    db = _db()
    scores = db.latest_scores()
    title, refresh = st.columns([6, 1], vertical_alignment="bottom")
    title.title("종목 추천")
    if refresh.button("새로고침", width="stretch"):
        st.rerun()
    if scores.empty:
        st.info("아직 점수가 없습니다. `stockproj score` 를 먼저 실행하세요.")
        return

    col1, col2, col3 = st.columns([1, 1, 2])
    market = col1.radio("시장", list(MARKETS), format_func=MARKETS.get, horizontal=True)
    preset = col2.radio(
        "기간",
        [p.key for p in PRESETS],
        format_func=lambda k: next(p.label for p in PRESETS if p.key == k),
        horizontal=True,
    )
    only_reco = col3.checkbox("추천 등급만", value=True)

    view = scores[(scores["market"] == market) & (scores["preset"] == preset)].sort_values("rank")
    if only_reco:
        view = view[view["grade"].isin(["강력 추천", "추천"])]
    as_of = pd.to_datetime(view["as_of"]).max() if not view.empty else None
    st.caption(f"기준일 {as_of:%Y-%m-%d} · {len(view)}종목" if as_of is not None else "해당 종목 없음")

    table = view[
        ["rank", "symbol", "name", "score", "grade", "fundamental", "technical", "close", "reasons"]
    ].copy()
    # 근거는 강점과 약점을 줄을 나눠 보여준다
    table["reasons"] = table["reasons"].fillna("").str.replace(" / ", "  \n", regex=False)
    table = table.rename(
        columns={
            "rank": "순위",
            "symbol": "종목코드",
            "name": "종목명",
            "score": "점수",
            "grade": "등급",
            "fundamental": "재무",
            "technical": "차트",
            "close": f"종가({fmt.CURRENCY[market]})",
            "reasons": "근거",
        }
    )
    # 숫자 열은 정렬되도록 숫자로 두고 표시만 바꾼다
    styled = table.style.format(
        {
            "점수": "{:.1f}",
            "재무": "{:.1f}",
            "차트": "{:.1f}",
            f"종가({fmt.CURRENCY[market]})": fmt.price_formatter(market),
        },
        na_rep="-",
    )
    # st.dataframe 은 칸 안에서 줄바꿈이 안 돼서, 긴 근거가 여러 줄로 보이도록 st.table 을 쓴다
    st.table(styled, hide_index=True, height=480)

    if view.empty:
        return
    symbol = st.selectbox(
        "종목 자세히 보기",
        view["symbol"],
        format_func=lambda s: f"{s} {view.set_index('symbol').at[s, 'name']}",
    )
    prices = db.prices(market, symbol)
    if not prices.empty:
        st.line_chart(
            prices.set_index("date")["close"].tail(250), height=260, y_label=f"종가({fmt.CURRENCY[market]})"
        )
    row = view.set_index("symbol").loc[symbol]
    st.write(
        f"**{row['grade']}** · 점수 {row['score']:.1f} · 종가 {fmt.price(row['close'], market)}"
        f"{fmt.CURRENCY[market]}"
    )
    # 강점과 약점을 한 줄씩 (마크다운 줄바꿈은 줄 끝 공백 두 칸)
    st.write("  \n".join((row["reasons"] or "근거 없음").split(" / ")))
    st.caption("투자 참고용 정보이며, 투자 판단과 책임은 본인에게 있습니다.")


main()
