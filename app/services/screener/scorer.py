"""Market screener scoring logic.

For each ticker in the universe:
  1. Compute raw metrics (returns, moving averages, volatility, drawdown).
  2. Rank cross-sectionally via percentile ranks.
  3. Combine into a composite score and assign a label (BUY / WATCH / AVOID).
  4. Compute inverse-volatility portfolio weights for the top_n eligible assets.

Composite score formula
-----------------------
score =
    0.30 * pct_rank(ret_60d)
  + 0.20 * pct_rank(ret_20d)
  + 0.15 * pct_rank(ret_120d)
  + 0.15 * trend_score          (raw 0 / 0.5 / 1.0 — not cross-sectional)
  + 0.10 * (1 - pct_rank(vol_20d))
  + 0.10 * (1 - pct_rank(drawdown_60d))

Labels
------
  BUY   if score >= 0.75
  WATCH if score >= 0.55
  AVOID otherwise

Weight methodology
------------------
Take the top_n BUY/WATCH assets by score.
Use inverse-volatility weighting, cap each asset at 35 %, renormalise.
"""
from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd


# ── Data-quality thresholds ────────────────────────────────────────────────────
#
# Each metric requires a minimum number of bars to be computable:
#
#   drawdown_60d          ≥  2  bars   (window = min(bars, 60))
#   vol_20d               ≥ 21  bars   (20 log-return observations)
#   ret_20d               ≥ 21  bars
#   sma_50 / dist_sma_50  ≥ 50  bars
#   ret_60d               ≥ 61  bars
#   ret_120d              ≥ 121 bars
#   sma_200/dist_sma_200  ≥ 200 bars
#   trend_score (full)    ≥ 200 bars   (requires both SMA50 and SMA200)
#
# Quality tiers derived from the above:
#   GOOD         ≥ 200 bars  — all metrics computable
#   LIMITED      ≥  21 bars  — basic metrics work; some nulls remain
#   INSUFFICIENT <  21 bars  — nearly all metrics null; scores unreliable

_BARS_GOOD       = 200
_BARS_LIMITED    = 21

# ── Metric helpers ─────────────────────────────────────────────────────────────

def _safe_ret(close: pd.Series, lookback: int) -> float | None:
    """Simple return over `lookback` bars, or None if insufficient history."""
    if len(close) < lookback + 1:
        return None
    return float(close.iloc[-1] / close.iloc[-(lookback + 1)] - 1)


def _safe_sma(close: pd.Series, period: int) -> float | None:
    """Last value of a rolling SMA, or None if fewer than `period` bars."""
    if len(close) < period:
        return None
    val = close.rolling(period).mean().iloc[-1]
    return float(val) if not np.isnan(val) else None


# ── Cross-sectional ranking ─────────────────────────────────────────────────────

def _pct_rank(values: list[float | None]) -> list[float]:
    """Cross-sectional percentile rank in [0, 1].

    * None / NaN entries are treated as the cross-sectional median so they
      are neither rewarded nor penalised.
    * With a single asset the rank is always 0.5.
    """
    n = len(values)
    if n == 1:
        return [0.5]

    arr = np.array([v if v is not None else np.nan for v in values], dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        # No computable values for this metric — all assets are neutral
        return [0.5] * n
    median = float(np.median(valid))
    filled = np.where(np.isnan(arr), median, arr)

    order = filled.argsort()
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(n)
    return list(ranks / max(n - 1, 1))


# ── Weights ────────────────────────────────────────────────────────────────────

def _inv_vol_weights(assets: list[dict], cap: float = 0.35) -> dict[str, float]:
    """Inverse-volatility weights capped at `cap`, renormalised to sum 1."""
    vols = [a["vol_20d"] if a["vol_20d"] is not None else 0.20 for a in assets]
    inv = [1.0 / max(v, 1e-6) for v in vols]
    total = sum(inv)
    raw = [x / total for x in inv]

    capped = [min(w, cap) for w in raw]
    total_capped = sum(capped)
    if total_capped <= 0:
        n = len(capped)
        final = [1.0 / n] * n
    else:
        final = [w / total_capped for w in capped]

    return {a["ticker"]: round(final[i], 4) for i, a in enumerate(assets)}


# ── Main entry point ───────────────────────────────────────────────────────────

def score_universe(
    dfs: dict[str, pd.DataFrame],
    top_n: int,
) -> tuple[date, list[dict]]:
    """Score all tickers and return (snapshot_date, ranked_assets list).

    Args:
        dfs:   dict[ticker → OHLCV DataFrame (date index, 'close' column required)]
        top_n: Max number of BUY/WATCH assets to receive a suggested weight.

    Returns:
        snapshot_date: last trading date across all DataFrames.
        ranked_assets: list of metric dicts sorted by composite score descending.
    """
    raw: dict[str, dict] = {}

    for ticker, df in dfs.items():
        close = df["close"]
        last = float(close.iloc[-1])
        history_bars = len(close)

        ret_20d  = _safe_ret(close, 20)
        ret_60d  = _safe_ret(close, 60)
        ret_120d = _safe_ret(close, 120)

        sma_50  = _safe_sma(close, 50)
        sma_200 = _safe_sma(close, 200)

        dist_sma_50  = (last / sma_50  - 1) if sma_50  is not None else None
        dist_sma_200 = (last / sma_200 - 1) if sma_200 is not None else None

        # 20-day annualised volatility (log returns)
        if len(close) >= 21:
            lr = np.log(close / close.shift(1)).dropna()
            vol_20d = float(lr.iloc[-20:].std() * np.sqrt(252))
        else:
            vol_20d = None

        # 60-day max drawdown stored as a positive fraction (higher = worse)
        if len(close) >= 2:
            window = close.iloc[-60:]
            dd = (window / window.cummax() - 1).min()
            drawdown_60d = float(abs(dd))
        else:
            drawdown_60d = None

        # Trend score: 1.0 / 0.5 / 0.0 based on SMA alignment
        if sma_50 is not None and sma_200 is not None:
            if last > sma_50 > sma_200:
                trend_score = 1.0
            elif last > sma_50:
                trend_score = 0.5
            else:
                trend_score = 0.0
        elif sma_50 is not None:
            trend_score = 1.0 if last > sma_50 else 0.0
        else:
            trend_score = 0.5  # neutral when insufficient MA history

        # ── Data quality ───────────────────────────────────────────────────────
        if history_bars >= _BARS_GOOD:
            data_quality = "GOOD"
            insufficient_history_reason = None
        elif history_bars >= _BARS_LIMITED:
            data_quality = "LIMITED"
            null_metrics: list[str] = []
            if history_bars < 61:
                null_metrics.append(f"ret_60d (need 61)")
            if history_bars < 121:
                null_metrics.append(f"ret_120d (need 121)")
            if history_bars < 200:
                null_metrics.append(f"SMA200 (need 200)")
            insufficient_history_reason = (
                f"{history_bars} bars available. Null metrics: {', '.join(null_metrics)}."
            )
        else:
            data_quality = "INSUFFICIENT"
            insufficient_history_reason = (
                f"Only {history_bars} bars. Need ≥ 21 for ret_20d/vol_20d, "
                f"≥ 50 for SMA50, ≥ 200 for SMA200. Scores are unreliable."
            )

        raw[ticker] = {
            "history_bars":               history_bars,
            "data_quality":               data_quality,
            "insufficient_history_reason": insufficient_history_reason,
            "ret_20d":      ret_20d,
            "ret_60d":      ret_60d,
            "ret_120d":     ret_120d,
            "dist_sma_50":  dist_sma_50,
            "dist_sma_200": dist_sma_200,
            "vol_20d":      vol_20d,
            "drawdown_60d": drawdown_60d,
            "trend_score":  trend_score,
        }

    tickers = list(raw.keys())

    pr_ret_60d  = _pct_rank([raw[t]["ret_60d"]      for t in tickers])
    pr_ret_20d  = _pct_rank([raw[t]["ret_20d"]      for t in tickers])
    pr_ret_120d = _pct_rank([raw[t]["ret_120d"]     for t in tickers])
    pr_vol      = _pct_rank([raw[t]["vol_20d"]      for t in tickers])
    pr_dd       = _pct_rank([raw[t]["drawdown_60d"] for t in tickers])

    results: list[dict] = []
    for i, ticker in enumerate(tickers):
        m = raw[ticker]
        score = round(
            0.30 * pr_ret_60d[i]
            + 0.20 * pr_ret_20d[i]
            + 0.15 * pr_ret_120d[i]
            + 0.15 * m["trend_score"]
            + 0.10 * (1.0 - pr_vol[i])
            + 0.10 * (1.0 - pr_dd[i]),
            4,
        )

        if score >= 0.75:
            label = "BUY"
        elif score >= 0.55:
            label = "WATCH"
        else:
            label = "AVOID"

        results.append({
            "ticker":                      ticker,
            "score":                       score,
            "label":                       label,
            "history_bars":                m["history_bars"],
            "data_quality":                m["data_quality"],
            "insufficient_history_reason": m["insufficient_history_reason"],
            "ret_20d":          m["ret_20d"],
            "ret_60d":          m["ret_60d"],
            "ret_120d":         m["ret_120d"],
            "dist_sma_50":      m["dist_sma_50"],
            "dist_sma_200":     m["dist_sma_200"],
            "vol_20d":          m["vol_20d"],
            "drawdown_60d":     m["drawdown_60d"],
            "suggested_weight": None,
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # Assign weights only to BUY/WATCH assets with reliable data (not INSUFFICIENT)
    eligible = [
        r for r in results
        if r["label"] != "AVOID" and r["data_quality"] != "INSUFFICIENT"
    ][:top_n]
    if eligible:
        weight_map = _inv_vol_weights(eligible)
        for r in results:
            if r["ticker"] in weight_map:
                r["suggested_weight"] = weight_map[r["ticker"]]

    snapshot_date: date = max(df.index[-1] for df in dfs.values())
    return snapshot_date, results
