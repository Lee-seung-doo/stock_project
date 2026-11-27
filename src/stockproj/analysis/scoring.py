"""종합 점수: 단타·중타·장타 프리셋별 가중 평균, 등급, 근거.

가중치(설계 문서 기준, 백테스트로 조정 예정)
            재무   차트(단기)  차트(중기)  뉴스
  단타      10%     60%          -          30%
  중타      30%      -          45%         25%
  장타      60%      -          20%         20%

뉴스 모듈은 2단계에서 붙는다. 그전에는 값이 없는 모듈의 가중치를 빼고 나머지를 다시 100% 로 맞춘다.
종목별로 빠진 모듈 가중치가 절반을 넘으면 점수를 내지 않는다.

등급: 80 이상 강력 추천, 65 이상 추천, 35 이상 중립, 그 아래 주의.
단, 쓰인 모듈 중 하나라도 20 미만이면 추천 등급을 주지 않는다(최대 중립).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from stockproj.analysis import fundamental, technical
from stockproj.storage import Database


@dataclass(frozen=True)
class Preset:
    key: str
    label: str
    weights: dict[str, float]


PRESETS = [
    Preset("short", "단타", {"fundamental": 0.10, "tech_short": 0.60, "news": 0.30}),
    Preset("mid", "중타", {"fundamental": 0.30, "tech_mid": 0.45, "news": 0.25}),
    Preset("long", "장타", {"fundamental": 0.60, "tech_mid": 0.20, "news": 0.20}),
]
PRESET_BY_KEY = {p.key: p for p in PRESETS}

GRADES = [(80, "강력 추천"), (65, "추천"), (35, "중립"), (float("-inf"), "주의")]
MODULE_FLOOR = 20

# 근거 문장에 쓰는 지표 이름. 프리셋마다 보는 지표가 다르다.
LABELS = {
    "earnings_yield": "이익수익률(PER 역수)",
    "book_to_price": "PBR 역수",
    "sales_to_price": "PSR 역수",
    "roe": "ROE",
    "op_margin": "영업이익률",
    "revenue_growth": "매출 성장률",
    "ni_growth": "순이익 성장률",
    "debt_ratio": "재무 안정성(부채비율)",
    "ret_5d": "5일 수익률",
    "ret_1m": "1개월 수익률",
    "ret_3m": "3개월 수익률",
    "ret_6m": "6개월 수익률",
    "ret_12_1": "12개월 모멘텀",
    "vol_ratio": "거래량 증가",
}
_FUND = ["earnings_yield", "book_to_price", "roe", "op_margin", "revenue_growth", "ni_growth", "debt_ratio"]
REASON_METRICS = {
    "short": ["ret_5d", "ret_1m", "vol_ratio", "roe", "revenue_growth"],
    "mid": ["ret_3m", "ret_6m", "ret_12_1", *_FUND],
    "long": [*_FUND, "ret_6m", "ret_12_1"],
}


def grade(score: float, module_min: float) -> str | None:
    if pd.isna(score):
        return None
    label = next(name for floor, name in GRADES if score >= floor)
    if module_min < MODULE_FLOOR and label in ("강력 추천", "추천"):
        return "중립"
    return label


def reasons(row: pd.Series, metrics: list[str]) -> str:
    """백분위 상위 30% 지표 최대 3개(강점), 하위 30% 최대 2개(약점)."""
    pairs = [(m, row.get(f"p_{m}")) for m in metrics]
    pairs = [(m, p) for m, p in pairs if pd.notna(p)]
    strong = sorted([x for x in pairs if x[1] >= 70], key=lambda x: -x[1])[:3]
    weak = sorted([x for x in pairs if x[1] <= 30], key=lambda x: x[1])[:2]
    parts = []
    if strong:
        parts.append("강점 " + ", ".join(f"{LABELS[m]} 상위 {max(1, round(100 - p))}%" for m, p in strong))
    if weak:
        parts.append("약점 " + ", ".join(f"{LABELS[m]} 하위 {max(1, round(p))}%" for m, p in weak))
    return " / ".join(parts)


def combine(modules: pd.DataFrame, preset: Preset) -> pd.DataFrame:
    """modules: 종목별 모듈 점수 열(fundamental, tech_short, tech_mid, news 중 일부)."""
    weights = {k: w for k, w in preset.weights.items() if k in modules and modules[k].notna().any()}
    total = sum(preset.weights.values())
    out = pd.DataFrame(index=modules.index)
    if not weights:
        out["score"] = float("nan")
        out["module_min"] = float("nan")
        return out
    present = pd.DataFrame({k: modules[k].notna() * w for k, w in weights.items()})
    used_weight = present.sum(axis=1)
    weighted = sum(modules[k].fillna(0) * w for k, w in weights.items())
    out["score"] = (weighted / used_weight.where(used_weight > 0)).where(used_weight >= total / 2)
    out["module_min"] = modules[list(weights)].min(axis=1)
    return out


def compute(db: Database, market: str, as_of: date) -> pd.DataFrame:
    """기준일의 프리셋별 점수 (긴 형식: 종목 × 프리셋)."""
    tech_metrics = technical.compute_metrics(technical.load_prices(db, market, as_of), market)
    if tech_metrics.empty:
        return pd.DataFrame()
    universe = tech_metrics.index[tech_metrics["liquid"]]
    tech = technical.score(tech_metrics.loc[universe])

    fund_table = fundamental.build_table(fundamental.load_items(db, market, as_of), as_of)
    fund_metrics = fundamental.compute_metrics(fund_table, tech_metrics["close"])
    fund = fundamental.score(fund_metrics.reindex(universe))

    detail = tech.join(fund, rsuffix="_f")
    names = db.symbols(market).set_index("symbol")["name"]
    rows = []
    for preset in PRESETS:
        comb = combine(detail, preset)
        tech_col = "tech_short" if preset.key == "short" else "tech_mid"
        for symbol, r in detail.iterrows():
            s = comb.at[symbol, "score"]
            if pd.isna(s):
                continue
            rows.append(
                {
                    "as_of": as_of,
                    "market": market,
                    "symbol": symbol,
                    "name": names.get(symbol),
                    "preset": preset.key,
                    "score": round(float(s), 1),
                    "grade": grade(s, comb.at[symbol, "module_min"]),
                    "fundamental": r.get("fundamental"),
                    "technical": r.get(tech_col),
                    "close": r.get("close"),
                    "reasons": reasons(r, REASON_METRICS[preset.key]),
                }
            )
    out = pd.DataFrame(rows)
    if not out.empty:
        out = out[out["symbol"].isin(names.index)]  # 목록에서 빠진 종목(상장폐지, 워런트) 제외
        out["rank"] = out.groupby("preset")["score"].rank(ascending=False, method="first").astype(int)
    return out.reset_index(drop=True)
