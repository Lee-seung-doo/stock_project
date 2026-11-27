"""분석 모듈 공통 도구."""

from __future__ import annotations

import pandas as pd


def pct_rank(series: pd.Series, higher_is_better: bool = True) -> pd.Series:
    """시장 안 백분위 점수(0~100). 값이 없으면 NaN 으로 남긴다."""
    s = series.astype(float).replace([float("inf"), float("-inf")], pd.NA).astype(float)
    ranked = s.rank(pct=True, ascending=higher_is_better) * 100
    return ranked


def mean_of(frame: pd.DataFrame, columns: list[str], min_count: int = 1) -> pd.Series:
    """여러 점수의 평균. 값이 있는 열이 min_count 개 미만이면 NaN."""
    part = frame[columns]
    avg = part.mean(axis=1, skipna=True)
    return avg.where(part.notna().sum(axis=1) >= min_count)
