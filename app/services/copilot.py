"""Deterministic Investment Copilot tool layer."""
from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.candles import load_ohlcv_multi
from app.models.instrument import Instrument
from app.schemas.backtest import BacktestMetrics
from app.schemas.copilot import (
    AssetMarketSnapshot,
    BenchmarkSummary,
    CopilotChatAnswer,
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotChatSessionState,
    CopilotToolSpec,
    CrossPresetRankingRow,
    CrossPresetSummary,
    DataCoverage,
    EligibleAlternative,
    ExplainRecommendationRequest,
    KnowledgeBaseQueryRequest,
    KnowledgeBaseQueryResponse,
    MarketSnapshotRequest,
    MarketSnapshotResponse,
    RankAssetsRequest,
    RankAssetsResponse,
    RankedAssetCopilot,
    RecentReturns,
    RecommendationPayload,
    ScoreBreakdown,
    StrategyConfigSummary,
    StrategyEvaluationRequest,
    StrategyEvaluationResponse,
    TrendMetrics,
    WalkForwardFoldSummary,
    WalkForwardSummary,
)
from app.services.backtest.metrics import compute_all_metrics
from app.services.copilot_personalization import (
    evaluate_policy_context,
    load_investor_profile,
    query_local_knowledge_base,
)
from app.services.screener.rotation import run_buy_and_hold_benchmark, run_rotation
from app.services.screener.scorer import score_universe

BENCHMARK_TICKER = "SPY"
DEFAULT_CHAT_TICKERS = ["SPY", "QQQ", "IWM", "TLT", "GLD"]
ELIGIBLE_LABELS = {"BUY", "WATCH"}
ELIGIBLE_QUALITY = {"GOOD", "LIMITED"}
PRESET_WINDOWS = [
    {"label": "Bull run", "date_from": "2019-01-01", "date_to": "2021-12-31"},
    {"label": "Rate hike bear", "date_from": "2022-01-01", "date_to": "2023-12-31"},
    {"label": "Mixed / volatile", "date_from": "2020-01-01", "date_to": "2022-12-31"},
    {"label": "Full cycle", "date_from": "2019-01-01", "date_to": "2023-12-31"},
]
TOOL_REGISTRY = [
    CopilotToolSpec(
        name="get_market_snapshot",
        description="Latest local market snapshot for selected tickers with returns, volatility, drawdown, trend, and data quality.",
        route="/api/v1/copilot/get_market_snapshot",
    ),
    CopilotToolSpec(
        name="rank_assets",
        description="Deterministic screener ranking with score breakdown, warnings, and suggested weights.",
        route="/api/v1/copilot/rank_assets",
    ),
    CopilotToolSpec(
        name="run_strategy_evaluation",
        description="Run structured Screener Rotation evaluations across single, compare, sweep, cross-preset, and walk-forward modes.",
        route="/api/v1/copilot/run_strategy_evaluation",
    ),
    CopilotToolSpec(
        name="explain_recommendation",
        description="Produce a deterministic recommendation payload from prior tool outputs.",
        route="/api/v1/copilot/explain_recommendation",
    ),
    CopilotToolSpec(
        name="query_knowledge_base",
        description="Deterministic local retrieval over notes, rules, theses, and experiment conclusions.",
        route="/api/v1/copilot/query_knowledge_base",
    ),
]


def list_tools() -> list[CopilotToolSpec]:
    return TOOL_REGISTRY


def _normalize_tickers(tickers: list[str]) -> list[str]:
    return [ticker.strip().upper() for ticker in tickers if ticker.strip()]


def _make_config_key(top_n: int, defensive_mode: str) -> str:
    return f"Top {top_n} · {'Cash' if defensive_mode == 'cash' else 'Defensive'}"


def _parse_config_key(config_key: str) -> tuple[int, str]:
    match = re.match(r"Top\s+(\d+)\s+.\s+(Cash|Defensive)", config_key)
    if not match:
        return 1, "cash"
    return int(match.group(1)), "cash" if match.group(2) == "Cash" else "defensive_asset"


async def _get_known_tickers(session: AsyncSession) -> set[str]:
    rows = (await session.execute(select(Instrument.ticker))).scalars().all()
    return {ticker.upper() for ticker in rows}


async def _resolve_query_tickers(session: AsyncSession, query: str) -> list[str]:
    known = await _get_known_tickers(session)
    tokens = re.findall(r"[A-Za-z]{1,10}", query)
    candidates = []
    stopwords = {
        "show", "tell", "give", "what", "which", "best", "rank", "ranking", "market",
        "snapshot", "strategy", "rotation", "compare", "sweep", "cross", "preset",
        "walk", "forward", "why", "risk", "risks", "and", "the", "with", "for",
        "from", "to", "run", "test", "evaluate", "evaluation", "please",
    }
    for token in tokens:
        upper = token.upper()
        if upper.lower() in stopwords:
            continue
        if upper in known and upper not in candidates:
            candidates.append(upper)
    if candidates:
        return candidates
    return [ticker for ticker in DEFAULT_CHAT_TICKERS if ticker in known]


def _extract_dates(query: str) -> tuple[Any | None, Any | None]:
    matches = re.findall(r"\b\d{4}-\d{2}-\d{2}\b", query)
    if not matches:
        return None, None
    if len(matches) == 1:
        dt = pd.Timestamp(matches[0]).date()
        return dt, None
    return pd.Timestamp(matches[0]).date(), pd.Timestamp(matches[1]).date()


def _extract_top_n(query: str, default: int = 3) -> int:
    match = re.search(r"\btop\s+(\d+)\b", query.lower())
    if not match:
        return default
    return max(1, min(20, int(match.group(1))))


def _extract_top_n_values(query: str) -> list[int]:
    match = re.search(r"\btop\s+n\s+values?\s+([\d,\s]+)", query.lower())
    if match:
        values = []
        for piece in match.group(1).split(","):
            piece = piece.strip()
            if piece.isdigit():
                values.append(max(1, min(20, int(piece))))
        if values:
            return values
    values = sorted(set(int(value) for value in re.findall(r"\btop\s+(\d+)\b", query.lower())))
    return [value for value in values if 1 <= value <= 20] or [1, 2, 3]


def _detect_chat_intent(query: str, session_state: CopilotChatSessionState | None) -> str:
    q = query.lower()
    if any(keyword in q for keyword in ["why", "risks", "risk", "invalidate", "caveat", "recommend"]) and (
        session_state and (session_state.last_ranking or session_state.last_strategy_evaluation)
    ):
        return "recommendation_explanation"
    if any(keyword in q for keyword in ["knowledge", "note", "notes", "doc", "docs", "document", "thesis", "kb"]):
        return "knowledge_base_query"
    if any(keyword in q for keyword in ["backtest", "strategy", "rotation", "compare", "sweep", "cross-preset", "cross preset", "walk-forward", "walk forward", "evaluate"]):
        return "strategy_evaluation"
    if any(keyword in q for keyword in ["rank", "ranking", "ranked", "best asset", "screener"]):
        return "asset_ranking"
    if any(keyword in q for keyword in ["snapshot", "price", "prices", "return", "returns", "volatility", "drawdown", "trend"]):
        return "market_snapshot"
    if session_state and (session_state.last_ranking or session_state.last_strategy_evaluation) and any(
        keyword in q for keyword in ["why", "more", "explain", "what are the risks"]
    ):
        return "recommendation_explanation"
    return "unclear"


def _default_single_dates() -> tuple[Any, Any]:
    return pd.Timestamp("2021-01-01").date(), pd.Timestamp("2023-12-31").date()


def _metrics_model(metrics: dict[str, Any] | None) -> BacktestMetrics:
    metrics = metrics or compute_all_metrics([], [])
    return BacktestMetrics(**metrics)


def _extend_start(date_from, warmup_bars: int):
    if date_from is None:
        return None
    return date_from - pd.Timedelta(days=math.ceil(warmup_bars * 1.5))


def _pct_rank(values: list[float | None]) -> list[float]:
    n = len(values)
    if n == 1:
        return [0.5]

    arr = np.array([v if v is not None else np.nan for v in values], dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        return [0.5] * n
    median = float(np.median(valid))
    filled = np.where(np.isnan(arr), median, arr)

    order = filled.argsort()
    ranks = np.empty(n, dtype=float)
    ranks[order] = np.arange(n)
    return list(ranks / max(n - 1, 1))


def _infer_trend_score(row: dict[str, Any]) -> float | None:
    dist_50 = row.get("dist_sma_50")
    dist_200 = row.get("dist_sma_200")
    if dist_50 is not None and dist_200 is not None:
        if dist_50 > 0 and dist_200 > 0 and dist_50 < dist_200:
            return 1.0
        if dist_50 > 0:
            return 0.5
        return 0.0
    if dist_50 is not None:
        return 1.0 if dist_50 > 0 else 0.0
    return 0.5


def _score_breakdowns(ranked_rows: list[dict[str, Any]]) -> dict[str, ScoreBreakdown]:
    pr_ret_60d = _pct_rank([row.get("ret_60d") for row in ranked_rows])
    pr_ret_20d = _pct_rank([row.get("ret_20d") for row in ranked_rows])
    pr_ret_120d = _pct_rank([row.get("ret_120d") for row in ranked_rows])
    pr_vol = _pct_rank([row.get("vol_20d") for row in ranked_rows])
    pr_dd = _pct_rank([row.get("drawdown_60d") for row in ranked_rows])

    breakdowns: dict[str, ScoreBreakdown] = {}
    for index, row in enumerate(ranked_rows):
        trend_score = _infer_trend_score(row)
        breakdowns[row["ticker"]] = ScoreBreakdown(
            ret_60d_contribution=round(0.30 * pr_ret_60d[index], 4),
            ret_20d_contribution=round(0.20 * pr_ret_20d[index], 4),
            ret_120d_contribution=round(0.15 * pr_ret_120d[index], 4),
            trend_contribution=round(0.15 * (trend_score or 0.0), 4),
            low_volatility_contribution=round(0.10 * (1.0 - pr_vol[index]), 4),
            low_drawdown_contribution=round(0.10 * (1.0 - pr_dd[index]), 4),
            total_score=float(row["score"]),
        )
    return breakdowns


def _asset_warnings(row: dict[str, Any]) -> list[str]:
    warnings: list[str] = []
    if row.get("data_quality") == "LIMITED":
        warnings.append(row.get("insufficient_history_reason") or "History is limited.")
    elif row.get("data_quality") == "INSUFFICIENT":
        warnings.append(row.get("insufficient_history_reason") or "History is insufficient.")

    drawdown = row.get("drawdown_60d")
    if drawdown is not None and float(drawdown) >= 0.15:
        warnings.append("Recent 60-day drawdown is elevated.")

    vol = row.get("vol_20d")
    if vol is not None and float(vol) >= 0.35:
        warnings.append("Recent 20-day volatility is elevated.")
    return warnings


def _build_market_snapshot_response(
    requested_tickers: list[str],
    dfs: dict[str, pd.DataFrame],
) -> MarketSnapshotResponse:
    if not dfs:
        raise HTTPException(status_code=404, detail="No price data found for the requested tickers.")

    snapshot_date, ranked = score_universe(dfs, top_n=max(1, len(dfs)))
    ranked_by_ticker = {row["ticker"]: row for row in ranked}
    assets: list[AssetMarketSnapshot] = []
    warnings: list[str] = []

    for ticker in requested_tickers:
        df = dfs.get(ticker)
        if df is None or df.empty:
            continue

        row = ranked_by_ticker.get(ticker, {})
        latest_date = str(df.index[-1]) if len(df.index) else None
        latest_price = float(df.iloc[-1]["close"]) if len(df.index) else None
        asset_warnings = _asset_warnings(row)
        warnings.extend([f"{ticker}: {message}" for message in asset_warnings])

        assets.append(
            AssetMarketSnapshot(
                ticker=ticker,
                latest_price=latest_price,
                latest_date=latest_date,
                recent_returns=RecentReturns(
                    ret_20d=row.get("ret_20d"),
                    ret_60d=row.get("ret_60d"),
                    ret_120d=row.get("ret_120d"),
                ),
                volatility_20d=row.get("vol_20d"),
                drawdown_60d=row.get("drawdown_60d"),
                trend=TrendMetrics(
                    dist_sma_50=row.get("dist_sma_50"),
                    dist_sma_200=row.get("dist_sma_200"),
                    trend_score=_infer_trend_score(row),
                ),
                data_quality=row.get("data_quality") or "UNKNOWN",
                history_coverage=DataCoverage(
                    start_date=str(df.index[0]) if len(df.index) else None,
                    end_date=str(df.index[-1]) if len(df.index) else None,
                    latest_date=latest_date,
                    history_bars=len(df.index),
                ),
                warnings=asset_warnings,
            )
        )

    return MarketSnapshotResponse(
        snapshot_date=str(snapshot_date) if snapshot_date else None,
        requested_tickers=requested_tickers,
        assets=assets,
        warnings=warnings,
    )


def _build_rank_assets_response(dfs: dict[str, pd.DataFrame], top_n: int) -> RankAssetsResponse:
    snapshot_date, ranked = score_universe(dfs, top_n=top_n)
    breakdowns = _score_breakdowns(ranked)
    warnings: list[str] = []

    ranked_assets = []
    for row in ranked:
        asset_warnings = _asset_warnings(row)
        warnings.extend([f"{row['ticker']}: {message}" for message in asset_warnings])
        ranked_assets.append(
            RankedAssetCopilot(
                ticker=row["ticker"],
                score=row["score"],
                label=row["label"],
                suggested_weight=row.get("suggested_weight"),
                history_bars=row["history_bars"],
                data_quality=row["data_quality"],
                insufficient_history_reason=row.get("insufficient_history_reason"),
                recent_returns=RecentReturns(
                    ret_20d=row.get("ret_20d"),
                    ret_60d=row.get("ret_60d"),
                    ret_120d=row.get("ret_120d"),
                ),
                volatility_20d=row.get("vol_20d"),
                drawdown_60d=row.get("drawdown_60d"),
                trend=TrendMetrics(
                    dist_sma_50=row.get("dist_sma_50"),
                    dist_sma_200=row.get("dist_sma_200"),
                    trend_score=_infer_trend_score(row),
                ),
                score_breakdown=breakdowns[row["ticker"]],
                warnings=asset_warnings,
            )
        )

    return RankAssetsResponse(
        snapshot_date=str(snapshot_date),
        universe_size=len(ranked_assets),
        top_n=top_n,
        ranked_assets=ranked_assets,
        warnings=warnings,
    )


def _build_rotation_summary(
    result: dict[str, Any] | None,
    benchmark: dict[str, Any] | None = None,
    *,
    config_key: str,
    top_n: int | None,
    defensive_mode: str | None,
    status: str = "ok",
    error: str | None = None,
) -> StrategyConfigSummary:
    return StrategyConfigSummary(
        config_key=config_key,
        top_n=top_n,
        defensive_mode=defensive_mode,
        metrics=_metrics_model(result.get("metrics") if result else None) if result else None,
        benchmark_metrics=_metrics_model(benchmark.get("metrics") if benchmark else None) if benchmark else None,
        status=status,
        error=error,
    )


def _dense_rank(values: list[float | None], higher_is_better: bool) -> list[int | None]:
    indexed = [(value, index) for index, value in enumerate(values) if value is not None]
    if not indexed:
        return [None] * len(values)
    indexed.sort(key=lambda item: item[0], reverse=higher_is_better)

    ranks: list[int | None] = [None] * len(values)
    rank = 1
    for pos, (value, index) in enumerate(indexed):
        if pos > 0 and value != indexed[pos - 1][0]:
            rank = pos + 1
        ranks[index] = rank
    return ranks


def _compute_cross_preset_scores(
    config_keys: list[str],
    results_by_config: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    rank_metrics = [
        ("cagr", True),
        ("sharpe_ratio", True),
        ("max_drawdown", False),
        ("calmar_ratio", True),
    ]
    preset_labels: list[str] = []
    for config_map in results_by_config.values():
        for preset_label in config_map:
            if preset_label not in preset_labels:
                preset_labels.append(preset_label)

    per_preset_ranks: dict[str, dict[str, list[int]]] = {config_key: {} for config_key in config_keys}
    for preset_label in preset_labels:
        for metric_key, higher_is_better in rank_metrics:
            raw_values = []
            for config_key in config_keys:
                metrics = results_by_config.get(config_key, {}).get(preset_label)
                if not metrics:
                    raw_values.append(None)
                    continue
                value = metrics.get(metric_key)
                if metric_key == "max_drawdown" and value is not None:
                    value = abs(value)
                raw_values.append(value)
            ranks = _dense_rank(raw_values, higher_is_better if metric_key != "max_drawdown" else False)
            for index, config_key in enumerate(config_keys):
                if ranks[index] is None:
                    continue
                per_preset_ranks.setdefault(config_key, {}).setdefault(preset_label, []).append(ranks[index])

    scores: dict[str, dict[str, Any]] = {}
    for config_key in config_keys:
        preset_avg: dict[str, float] = {}
        averages: list[float] = []
        for preset_label, ranks in per_preset_ranks.get(config_key, {}).items():
            if ranks:
                avg_rank = sum(ranks) / len(ranks)
                preset_avg[preset_label] = avg_rank
                averages.append(avg_rank)
        scores[config_key] = {
            "preset_avg": preset_avg,
            "overall": (sum(averages) / len(averages)) if averages else None,
        }
    return scores


def _best_config_for_metrics(rows: list[dict[str, Any]]) -> str | None:
    valid_rows = [row for row in rows if row.get("metrics") is not None]
    if not valid_rows:
        return None
    valid_rows.sort(
        key=lambda row: (
            -(row["metrics"].get("calmar_ratio") or float("-inf")),
            -(row["metrics"].get("cagr") or float("-inf")),
            abs(row["metrics"].get("max_drawdown") or float("inf")),
            -(row["metrics"].get("final_equity") or float("-inf")),
        )
    )
    return valid_rows[0]["config_key"]


def _generate_walk_forward_windows(request: StrategyEvaluationRequest) -> list[dict[str, Any]]:
    if request.wf_data_start is None or request.wf_data_end is None:
        return []

    windows = []
    end_date = pd.Timestamp(request.wf_data_end)
    cursor = pd.Timestamp(request.wf_data_start)
    fold_index = 1
    while True:
        train_from = cursor
        test_start = cursor + pd.DateOffset(years=request.wf_train_years)
        train_to = test_start - pd.Timedelta(days=1)
        test_end = test_start + pd.DateOffset(years=request.wf_test_years) - pd.Timedelta(days=1)
        if test_end > end_date:
            break
        windows.append(
            {
                "fold": fold_index,
                "train_from": train_from.date(),
                "train_to": train_to.date(),
                "test_from": test_start.date(),
                "test_to": test_end.date(),
            }
        )
        cursor = cursor + pd.DateOffset(years=request.wf_step_years)
        fold_index += 1
    return windows


def _pick_best_config(train_rows: list[dict[str, Any]]) -> tuple[str | None, float | None]:
    metrics = [
        ("cagr", True),
        ("sharpe_ratio", True),
        ("max_drawdown", False),
        ("calmar_ratio", True),
    ]
    if not train_rows:
        return None, None

    totals = [0.0] * len(train_rows)
    metrics_used = 0
    for metric_key, higher_is_better in metrics:
        values = []
        for row in train_rows:
            metric_value = row["metrics"].get(metric_key)
            if metric_key == "max_drawdown" and metric_value is not None:
                metric_value = abs(metric_value)
            values.append(metric_value)
        ranks = _dense_rank(values, higher_is_better if metric_key != "max_drawdown" else False)
        any_rank = False
        for index, rank in enumerate(ranks):
            if rank is not None:
                totals[index] += rank
                any_rank = True
        if any_rank:
            metrics_used += 1

    if metrics_used == 0:
        return train_rows[0]["config_key"], None

    best_index = min(range(len(train_rows)), key=lambda index: totals[index] / metrics_used)
    return train_rows[best_index]["config_key"], totals[best_index] / metrics_used


def _recommendation_risks_from_metrics(metrics: BacktestMetrics | None) -> list[str]:
    if metrics is None:
        return ["No completed metrics were available."]

    risks: list[str] = []
    if metrics.max_drawdown is not None and abs(metrics.max_drawdown) >= 0.25:
        risks.append("Observed max drawdown is meaningfully elevated.")
    if metrics.sharpe_ratio is not None and metrics.sharpe_ratio < 0.75:
        risks.append("Risk-adjusted performance is modest.")
    if metrics.cagr is not None and metrics.cagr <= 0:
        risks.append("Return profile is currently non-positive.")
    return risks or ["Historical performance may not persist in future regimes."]


def _knowledge_query_for_recommendation(
    *,
    source: str,
    recommended_entity: str | None,
    strategy: StrategyEvaluationResponse | None = None,
) -> str:
    parts = [source.replace("_", " ")]
    if recommended_entity:
        parts.append(recommended_entity)
    if strategy is not None:
        parts.append(strategy.run_mode.replace("_", " "))
        parts.extend(strategy.tickers[:5])
    parts.extend(["rules", "risk", "thesis", "experiment conclusions"])
    return " ".join(parts)


def _asset_metrics_for_policy(asset: RankedAssetCopilot) -> BacktestMetrics:
    return BacktestMetrics(
        cagr=None,
        max_drawdown=-asset.drawdown_60d if asset.drawdown_60d is not None else None,
        sharpe_ratio=None,
        calmar_ratio=None,
        win_rate=None,
        total_trades=None,
        final_equity=None,
    )


def _merge_unique(base: list[str], extras: list[str]) -> list[str]:
    merged = [*base]
    for item in extras:
        if item not in merged:
            merged.append(item)
    return merged


def _ranked_asset_policy_snapshot(
    asset: RankedAssetCopilot,
    *,
    profile,
) -> tuple[dict[str, Any], KnowledgeBaseQueryResponse]:
    kb = query_local_knowledge_base(
        KnowledgeBaseQueryRequest(
            query=_knowledge_query_for_recommendation(source="rank_assets", recommended_entity=asset.ticker),
            top_k=3,
        )
    )
    policy = evaluate_policy_context(
        recommended_entity_type="asset",
        recommended_entity=asset.ticker,
        tickers=[asset.ticker],
        metrics=_asset_metrics_for_policy(asset),
        profile=profile,
        knowledge_matches=kb.matches,
    )
    return policy, kb


def _candidate_alternatives_for_ranking(
    ranked_assets: list[RankedAssetCopilot],
    *,
    top_deterministic_result: str | None,
    profile,
) -> list[EligibleAlternative]:
    alternatives: list[EligibleAlternative] = []
    for asset in ranked_assets:
        if asset.ticker == top_deterministic_result:
            continue
        policy, _ = _ranked_asset_policy_snapshot(asset, profile=profile)
        if policy["recommendation_status"] not in {"eligible", "eligible_with_cautions"}:
            continue
        alternatives.append(
            EligibleAlternative(
                entity=asset.ticker,
                reason=policy["constraint_summary"],
                recommendation_status=policy["recommendation_status"],
            )
        )
    return alternatives


def _personalize_recommendation(
    payload: RecommendationPayload,
    *,
    tickers: list[str] | None,
    metrics: BacktestMetrics | None,
    knowledge_query: str,
    ranked_assets: list[RankedAssetCopilot] | None = None,
) -> RecommendationPayload:
    profile, profile_warnings = load_investor_profile()
    kb = query_local_knowledge_base(KnowledgeBaseQueryRequest(query=knowledge_query, top_k=3))
    policy = evaluate_policy_context(
        recommended_entity_type=payload.recommended_entity_type,
        recommended_entity=payload.recommended_entity,
        tickers=tickers,
        metrics=metrics,
        profile=profile,
        knowledge_matches=kb.matches,
    )
    caveats = _merge_unique(payload.caveats, profile_warnings)
    caveats = _merge_unique(caveats, policy["warnings"])
    caveats = _merge_unique(caveats, kb.warnings)

    top_deterministic_result = payload.top_deterministic_result or payload.recommended_entity
    recommended_entity = payload.recommended_entity
    recommendation_status = policy["recommendation_status"]
    eligible_alternatives: list[EligibleAlternative] = []

    if payload.recommended_entity_type == "asset" and ranked_assets:
        eligible_alternatives = _candidate_alternatives_for_ranking(
            ranked_assets,
            top_deterministic_result=top_deterministic_result,
            profile=profile,
        )
        if recommendation_status in {"rejected_by_profile", "unsupported_by_knowledge"} and eligible_alternatives:
            recommended_entity = eligible_alternatives[0].entity
            recommendation_status = eligible_alternatives[0].recommendation_status
            policy["constraint_summary"] = (
                f"Top deterministic result {top_deterministic_result} is not usable. "
                f"Best eligible alternative: {eligible_alternatives[0].entity}. {eligible_alternatives[0].reason}"
            )
        elif recommendation_status in {"rejected_by_profile", "unsupported_by_knowledge"}:
            recommended_entity = None

    personalized = payload.model_copy(
        update={
            "caveats": caveats,
            "recommended_entity": recommended_entity,
            "top_deterministic_result": top_deterministic_result,
            "recommendation_status": recommendation_status,
            "profile_constraints_applied": policy["constraints"],
            "knowledge_sources_used": kb.matches,
            "hard_conflicts": policy["hard_conflicts"],
            "soft_conflicts": policy["soft_conflicts"],
            "preference_matches": policy["preference_matches"],
            "constraint_summary": policy["constraint_summary"],
            "eligible_alternatives": eligible_alternatives,
        }
    )
    return _apply_recommendation_eligibility_wording(personalized)


def _apply_recommendation_eligibility_wording(payload: RecommendationPayload) -> RecommendationPayload:
    top_entity = payload.top_deterministic_result or payload.recommended_entity or "this result"
    final_entity = payload.recommended_entity
    deterministic_label = "top-ranked asset" if payload.recommended_entity_type == "asset" else "top strategy result"
    why_preferred: list[str]

    if payload.top_deterministic_result and payload.recommended_entity and payload.recommended_entity != payload.top_deterministic_result:
        summary = (
            f"Deterministically, {top_entity} is the current {deterministic_label}, "
            f"but it is not the usable recommendation for this profile. Best eligible alternative: {final_entity}."
        )
        why_preferred = [
            f"Deterministic evidence still places {top_entity} at the top of the current result set.",
            f"Top-result constraint: {payload.hard_conflicts[0] if payload.hard_conflicts else payload.constraint_summary}",
            f"Best eligible alternative: {final_entity}.",
            f"Alternative status: {payload.recommendation_status.replace('_', ' ')}.",
        ]
    elif payload.recommendation_status == "rejected_by_profile":
        summary = (
            f"Deterministically, {top_entity} is the current {deterministic_label}, "
            "but it is not eligible for the active investor profile, so it is not a justified recommendation."
        )
        why_preferred = [
            f"Deterministic evidence still places {top_entity} at the top of the current result set.",
            f"Profile conflict: {payload.hard_conflicts[0] if payload.hard_conflicts else payload.constraint_summary}",
            "Final recommendation status: rejected for this profile until the conflict is resolved.",
        ]
    elif payload.recommendation_status == "unsupported_by_knowledge":
        summary = (
            f"Deterministically, {top_entity} is currently on top, "
            "but local knowledge support is missing, so there is no justified personalized recommendation yet."
        )
        why_preferred = [
            f"Deterministic evidence still places {top_entity} at the top of the current result set.",
            "No relevant local thesis, rule, or experiment note supports this result yet.",
            "Final recommendation status: unsupported by local knowledge.",
        ]
    elif payload.recommendation_status == "eligible_with_cautions":
        chosen = final_entity or top_entity
        summary = f"{chosen} is the current usable recommendation, but only with explicit cautions."
        why_preferred = [
            f"Deterministic evidence still favors {top_entity} within the current result set.",
            payload.constraint_summary or "The profile allows this result only with cautions.",
            "Final recommendation status: eligible with cautions.",
        ]
    else:
        chosen = final_entity or top_entity
        summary = f"{chosen} is the current deterministic preference and is eligible for this profile."
        why_preferred = [
            f"Deterministic evidence still favors {top_entity} within the current result set.",
            payload.constraint_summary or "The result is eligible under the active profile.",
            "Final recommendation status: eligible.",
        ]

    if payload.top_deterministic_result and payload.recommended_entity and payload.recommended_entity != payload.top_deterministic_result:
        why_preferred.append(
            f"Best eligible alternative surfaced: {payload.recommended_entity}, while the top deterministic result remains {payload.top_deterministic_result}."
        )

    supporting_metrics = {
        **payload.supporting_metrics,
        "recommendation_status": payload.recommendation_status,
        "hard_conflicts": payload.hard_conflicts,
        "soft_conflicts": payload.soft_conflicts,
        "preference_matches": payload.preference_matches,
        "top_deterministic_result": payload.top_deterministic_result,
        "eligible_alternatives": [alternative.model_dump() for alternative in payload.eligible_alternatives],
    }
    return payload.model_copy(
        update={
            "summary": summary,
            "why_preferred": why_preferred,
            "supporting_metrics": supporting_metrics,
        }
    )


def _recommendation_headline(payload: RecommendationPayload, default: str) -> str:
    if payload.recommendation_status == "rejected_by_profile":
        return "Profile conflict: result not eligible"
    if payload.recommendation_status == "unsupported_by_knowledge":
        return "Knowledge support missing"
    if payload.recommendation_status == "eligible_with_cautions":
        return "Recommendation with cautions"
    return default


def _recommendation_answer(payload: RecommendationPayload, default_headline: str) -> CopilotChatAnswer:
    if payload.recommendation_status == "rejected_by_profile":
        final_summary = (
            f"No justified recommendation is available. Top deterministic result: {payload.top_deterministic_result or '-'}."
            if not payload.eligible_alternatives
            else (
                f"Top deterministic result {payload.top_deterministic_result or '-'} is rejected for this profile. "
                f"Best eligible alternative: {payload.recommended_entity or '-'}."
            )
        )
        actionable = (
            "This is not actionable for the active profile until the hard conflict is resolved."
            if not payload.eligible_alternatives
            else "This is actionable only through the surfaced eligible alternative, not through the blocked top result."
        )
    elif payload.recommendation_status == "unsupported_by_knowledge":
        final_summary = f"No justified personalized recommendation is available yet for {payload.top_deterministic_result or payload.recommended_entity or 'this result'}."
        actionable = "This is not actionable yet because local knowledge support is missing."
    elif payload.recommendation_status == "eligible_with_cautions":
        final_summary = f"Usable recommendation: {payload.recommended_entity or payload.top_deterministic_result or '-'}."
        actionable = "This is actionable, but only with the cautions listed in the profile decision."
    else:
        final_summary = f"Usable recommendation: {payload.recommended_entity or payload.top_deterministic_result or '-'}."
        actionable = "This is actionable under the current deterministic evidence, profile rules, and local knowledge support."

    confidence_notes = []
    if payload.knowledge_sources_used:
        confidence_notes.append(
            "Knowledge confidence: "
            + ", ".join(
                f"{match.title} ({match.confidence_tier})"
                for match in payload.knowledge_sources_used[:3]
            )
        )
    else:
        confidence_notes.append("Knowledge confidence: no relevant local support found.")

    return CopilotChatAnswer(
        headline=_recommendation_headline(payload, default_headline),
        summary=payload.summary,
        bullets=payload.why_preferred[:4],
        deterministic_evidence_summary=(
            f"Top deterministic result: {payload.top_deterministic_result or payload.recommended_entity or '-'}."
        ),
        profile_decision_summary=payload.constraint_summary or "No profile decision summary available.",
        final_recommendation_summary=final_summary,
        why_this_is_or_is_not_actionable=actionable,
        confidence_notes=confidence_notes,
    )


async def get_market_snapshot_tool(
    session: AsyncSession,
    request: MarketSnapshotRequest,
) -> MarketSnapshotResponse:
    tickers = _normalize_tickers(request.instrument_tickers)
    if not tickers:
        raise HTTPException(status_code=422, detail="instrument_tickers cannot be empty.")
    dfs = await load_ohlcv_multi(session, tickers, request.date_from, request.date_to)
    return _build_market_snapshot_response(tickers, dfs)


async def rank_assets_tool(
    session: AsyncSession,
    request: RankAssetsRequest,
) -> RankAssetsResponse:
    tickers = _normalize_tickers(request.instrument_tickers)
    if not tickers:
        raise HTTPException(status_code=422, detail="instrument_tickers cannot be empty.")
    dfs = await load_ohlcv_multi(session, tickers, request.date_from, request.date_to)
    return _build_rank_assets_response(dfs, request.top_n)


async def run_strategy_evaluation_tool(
    session: AsyncSession,
    request: StrategyEvaluationRequest,
) -> StrategyEvaluationResponse:
    tickers = _normalize_tickers(request.instrument_tickers)
    if not tickers:
        raise HTTPException(status_code=422, detail="instrument_tickers cannot be empty.")
    if request.rebalance_frequency != "monthly":
        raise HTTPException(status_code=422, detail="Only monthly rebalance_frequency is supported.")

    timestamp_utc = datetime.now(UTC)
    warnings: list[str] = []
    top_n_values = sorted({value for value in request.top_n_values if 1 <= value <= 20}) or [request.top_n]

    def run_single_rotation(local_dfs: dict[str, pd.DataFrame], *, top_n: int, defensive_mode: str, date_from, date_to):
        sliced_dfs = {
            ticker: df[(df.index >= date_from) & (df.index <= date_to)]
            for ticker, df in local_dfs.items()
        }
        benchmark_df = sliced_dfs.get(BENCHMARK_TICKER)
        universe_dfs = {
            ticker: sliced_dfs[ticker]
            for ticker in tickers
            if ticker in sliced_dfs and not sliced_dfs[ticker].empty
        }
        if not universe_dfs:
            raise HTTPException(status_code=404, detail="No strategy price data found for the requested window.")
        if benchmark_df is None or benchmark_df.empty:
            raise HTTPException(status_code=404, detail="No SPY benchmark price data found for the requested window.")

        rotation_result = run_rotation(
            dfs=universe_dfs,
            top_n=top_n,
            initial_capital=request.initial_capital,
            commission_bps=request.commission_bps,
            eval_start_date=date_from,
            defensive_mode=defensive_mode,
            defensive_tickers=request.defensive_tickers,
        )
        benchmark_result = run_buy_and_hold_benchmark(
            benchmark_df=benchmark_df,
            initial_capital=request.initial_capital,
            commission_bps=request.commission_bps,
            eval_start_date=date_from,
            eval_end_date=date_to,
        )
        return rotation_result, benchmark_result

    parameters = request.model_dump(mode="json")

    if request.run_mode in {"single", "compare_variants", "parameter_sweep"}:
        if request.date_from is None or request.date_to is None:
            raise HTTPException(status_code=422, detail="date_from and date_to are required for this run_mode.")
        load_start = _extend_start(request.date_from, request.warmup_bars)
        shared_dfs = await load_ohlcv_multi(
            session,
            list(dict.fromkeys([*tickers, BENCHMARK_TICKER])),
            load_start.date() if isinstance(load_start, pd.Timestamp) else load_start,
            request.date_to,
        )

        if request.run_mode == "single":
            rotation_result, benchmark_result = run_single_rotation(
                shared_dfs,
                top_n=request.top_n,
                defensive_mode=request.defensive_mode,
                date_from=request.date_from,
                date_to=request.date_to,
            )
            return StrategyEvaluationResponse(
                run_mode=request.run_mode,
                timestamp_utc=timestamp_utc,
                tickers=tickers,
                parameters=parameters,
                benchmark=BenchmarkSummary(ticker=BENCHMARK_TICKER, metrics=_metrics_model(benchmark_result["metrics"])),
                single_run=_build_rotation_summary(
                    rotation_result,
                    benchmark_result,
                    config_key=_make_config_key(request.top_n, request.defensive_mode),
                    top_n=request.top_n,
                    defensive_mode=request.defensive_mode,
                ),
                warnings=warnings,
            )

        if request.run_mode == "compare_variants":
            compare_rows = []
            benchmark_summary = None
            for defensive_mode in ["cash", "defensive_asset"]:
                rotation_result, benchmark_result = run_single_rotation(
                    shared_dfs,
                    top_n=request.top_n,
                    defensive_mode=defensive_mode,
                    date_from=request.date_from,
                    date_to=request.date_to,
                )
                if benchmark_summary is None:
                    benchmark_summary = BenchmarkSummary(
                        ticker=BENCHMARK_TICKER,
                        metrics=_metrics_model(benchmark_result["metrics"]),
                    )
                compare_rows.append(
                    _build_rotation_summary(
                        rotation_result,
                        None,
                        config_key=_make_config_key(request.top_n, defensive_mode),
                        top_n=request.top_n,
                        defensive_mode=defensive_mode,
                    )
                )

            return StrategyEvaluationResponse(
                run_mode=request.run_mode,
                timestamp_utc=timestamp_utc,
                tickers=tickers,
                parameters=parameters,
                benchmark=benchmark_summary,
                compare_variants=compare_rows,
                warnings=warnings,
            )

        sweep_rows: list[StrategyConfigSummary] = []
        benchmark_summary = None
        for top_n in top_n_values:
            for defensive_mode in ["cash", "defensive_asset"]:
                try:
                    rotation_result, benchmark_result = run_single_rotation(
                        shared_dfs,
                        top_n=top_n,
                        defensive_mode=defensive_mode,
                        date_from=request.date_from,
                        date_to=request.date_to,
                    )
                    if benchmark_summary is None:
                        benchmark_summary = BenchmarkSummary(
                            ticker=BENCHMARK_TICKER,
                            metrics=_metrics_model(benchmark_result["metrics"]),
                        )
                    sweep_rows.append(
                        _build_rotation_summary(
                            rotation_result,
                            None,
                            config_key=_make_config_key(top_n, defensive_mode),
                            top_n=top_n,
                            defensive_mode=defensive_mode,
                        )
                    )
                except Exception as exc:  # pragma: no cover
                    warnings.append(f"{_make_config_key(top_n, defensive_mode)} failed: {exc}")
                    sweep_rows.append(
                        _build_rotation_summary(
                            None,
                            None,
                            config_key=_make_config_key(top_n, defensive_mode),
                            top_n=top_n,
                            defensive_mode=defensive_mode,
                            status="error",
                            error=str(exc),
                        )
                    )

        return StrategyEvaluationResponse(
            run_mode=request.run_mode,
            timestamp_utc=timestamp_utc,
            tickers=tickers,
            parameters=parameters,
            benchmark=benchmark_summary,
            parameter_sweep=sweep_rows,
            warnings=warnings,
        )

    if request.run_mode == "cross_preset":
        preset_start = min(pd.Timestamp(preset["date_from"]) for preset in PRESET_WINDOWS)
        preset_end = max(pd.Timestamp(preset["date_to"]) for preset in PRESET_WINDOWS)
        load_start = _extend_start(preset_start.date(), request.warmup_bars)
        shared_dfs = await load_ohlcv_multi(
            session,
            list(dict.fromkeys([*tickers, BENCHMARK_TICKER])),
            load_start.date() if isinstance(load_start, pd.Timestamp) else load_start,
            preset_end.date(),
        )

        results_by_config: dict[str, dict[str, dict[str, Any]]] = {}
        config_keys: list[str] = []
        for top_n in top_n_values:
            for defensive_mode in ["cash", "defensive_asset"]:
                config_key = _make_config_key(top_n, defensive_mode)
                config_keys.append(config_key)
                results_by_config[config_key] = {}
                for preset in PRESET_WINDOWS:
                    try:
                        rotation_result, _ = run_single_rotation(
                            shared_dfs,
                            top_n=top_n,
                            defensive_mode=defensive_mode,
                            date_from=pd.Timestamp(preset["date_from"]).date(),
                            date_to=pd.Timestamp(preset["date_to"]).date(),
                        )
                        results_by_config[config_key][preset["label"]] = rotation_result["metrics"]
                    except Exception as exc:  # pragma: no cover
                        warnings.append(f"[{preset['label']}] {config_key} failed: {exc}")

        scores = _compute_cross_preset_scores(config_keys, results_by_config)
        ranked = sorted(
            config_keys,
            key=lambda config_key: scores.get(config_key, {}).get("overall") if scores.get(config_key, {}).get("overall") is not None else 999,
        )

        best_by_preset: dict[str, str] = {}
        for preset in PRESET_WINDOWS:
            preset_label = preset["label"]
            available = [
                (config_key, scores.get(config_key, {}).get("preset_avg", {}).get(preset_label))
                for config_key in config_keys
            ]
            available = [(config_key, value) for config_key, value in available if value is not None]
            if available:
                best_by_preset[preset_label] = min(available, key=lambda item: item[1])[0]

        preset_placement_ranks: dict[str, dict[str, int | None]] = {config_key: {} for config_key in config_keys}
        for preset in PRESET_WINDOWS:
            preset_values = [scores.get(config_key, {}).get("preset_avg", {}).get(preset["label"]) for config_key in config_keys]
            ranks = _dense_rank(preset_values, False)
            for index, config_key in enumerate(config_keys):
                preset_placement_ranks[config_key][preset["label"]] = ranks[index]

        ranking_rows: list[CrossPresetRankingRow] = []
        for config_key in ranked:
            preset_avgs = [
                scores.get(config_key, {}).get("preset_avg", {}).get(preset["label"])
                for preset in PRESET_WINDOWS
            ]
            preset_avgs = [value for value in preset_avgs if value is not None]
            placement_ranks = [
                preset_placement_ranks[config_key].get(preset["label"])
                for preset in PRESET_WINDOWS
            ]
            placement_ranks = [value for value in placement_ranks if value is not None]
            avg_rank = scores.get(config_key, {}).get("overall")
            rank_std_dev = float(np.std(preset_avgs)) if preset_avgs else None
            times_ranked_1 = sum(1 for value in placement_ranks if value == 1)
            times_ranked_top_2 = sum(1 for value in placement_ranks if value is not None and value <= 2)
            robustness_score = avg_rank + rank_std_dev if avg_rank is not None and rank_std_dev is not None else avg_rank
            metrics_by_preset = list(results_by_config.get(config_key, {}).values())
            cagr_values = [metric.get("cagr") for metric in metrics_by_preset if metric.get("cagr") is not None]
            drawdown_values = [abs(metric.get("max_drawdown")) for metric in metrics_by_preset if metric.get("max_drawdown") is not None]
            ranking_rows.append(
                CrossPresetRankingRow(
                    config_key=config_key,
                    bull_run_avg_rank=scores.get(config_key, {}).get("preset_avg", {}).get("Bull run"),
                    rate_hike_bear_avg_rank=scores.get(config_key, {}).get("preset_avg", {}).get("Rate hike bear"),
                    mixed_volatile_avg_rank=scores.get(config_key, {}).get("preset_avg", {}).get("Mixed / volatile"),
                    full_cycle_avg_rank=scores.get(config_key, {}).get("preset_avg", {}).get("Full cycle"),
                    average_rank=avg_rank,
                    rank_std_dev=rank_std_dev,
                    times_ranked_1=times_ranked_1,
                    times_ranked_top_2=times_ranked_top_2,
                    robustness_score=robustness_score,
                    avg_cagr=(sum(cagr_values) / len(cagr_values)) if cagr_values else None,
                    avg_abs_drawdown=(sum(drawdown_values) / len(drawdown_values)) if drawdown_values else None,
                )
            )

        most_robust_row = min(
            [row for row in ranking_rows if row.robustness_score is not None],
            key=lambda row: (
                row.robustness_score,
                row.rank_std_dev if row.rank_std_dev is not None else float("inf"),
                row.average_rank if row.average_rank is not None else float("inf"),
                -(row.times_ranked_1 or 0),
            ),
            default=None,
        )
        best_return_row = max(
            [row for row in ranking_rows if row.avg_cagr is not None],
            key=lambda row: (
                row.avg_cagr if row.avg_cagr is not None else float("-inf"),
                -(row.average_rank if row.average_rank is not None else float("inf")),
            ),
            default=None,
        )
        best_drawdown_row = min(
            [row for row in ranking_rows if row.avg_abs_drawdown is not None],
            key=lambda row: (
                row.avg_abs_drawdown if row.avg_abs_drawdown is not None else float("inf"),
                row.rank_std_dev if row.rank_std_dev is not None else float("inf"),
                row.average_rank if row.average_rank is not None else float("inf"),
            ),
            default=None,
        )
        recommended_default = min(
            [row for row in ranking_rows if row.robustness_score is not None],
            key=lambda row: (
                row.robustness_score,
                row.full_cycle_avg_rank if row.full_cycle_avg_rank is not None else float("inf"),
                row.avg_abs_drawdown if row.avg_abs_drawdown is not None else float("inf"),
                -(row.times_ranked_1 or 0),
                row.average_rank if row.average_rank is not None else float("inf"),
            ),
            default=None,
        )

        return StrategyEvaluationResponse(
            run_mode=request.run_mode,
            timestamp_utc=timestamp_utc,
            tickers=tickers,
            parameters=parameters,
            cross_preset=CrossPresetSummary(
                overall_winner=ranked[0] if ranked else None,
                most_robust_config=most_robust_row.config_key if most_robust_row else None,
                best_bull_market_config=best_by_preset.get("Bull run"),
                best_bear_market_config=best_by_preset.get("Rate hike bear"),
                best_return_config=best_return_row.config_key if best_return_row else None,
                best_drawdown_control_config=best_drawdown_row.config_key if best_drawdown_row else None,
                recommended_default_config=recommended_default.config_key if recommended_default else None,
                ranking_rows=ranking_rows,
            ),
            warnings=warnings,
        )

    if request.run_mode == "walk_forward":
        if request.wf_data_start is None or request.wf_data_end is None:
            raise HTTPException(status_code=422, detail="wf_data_start and wf_data_end are required for walk_forward.")
        windows = _generate_walk_forward_windows(request)
        if not windows:
            raise HTTPException(status_code=422, detail="No valid walk-forward windows fit within the requested range.")
        load_start = _extend_start(request.wf_data_start, request.warmup_bars)
        shared_dfs = await load_ohlcv_multi(
            session,
            list(dict.fromkeys([*tickers, BENCHMARK_TICKER])),
            load_start.date() if isinstance(load_start, pd.Timestamp) else load_start,
            request.wf_data_end,
        )

        folds: list[WalkForwardFoldSummary] = []
        for window in windows:
            train_rows: list[dict[str, Any]] = []
            for top_n in top_n_values:
                for defensive_mode in ["cash", "defensive_asset"]:
                    config_key = _make_config_key(top_n, defensive_mode)
                    try:
                        rotation_result, _ = run_single_rotation(
                            shared_dfs,
                            top_n=top_n,
                            defensive_mode=defensive_mode,
                            date_from=window["train_from"],
                            date_to=window["train_to"],
                        )
                        train_rows.append({"config_key": config_key, "metrics": rotation_result["metrics"]})
                    except Exception as exc:  # pragma: no cover
                        warnings.append(f"Fold {window['fold']} train {config_key} failed: {exc}")

            winner_key, winner_rank = _pick_best_config(train_rows)
            if winner_key is None:
                folds.append(
                    WalkForwardFoldSummary(
                        fold=window["fold"],
                        train_from=str(window["train_from"]),
                        train_to=str(window["train_to"]),
                        test_from=str(window["test_from"]),
                        test_to=str(window["test_to"]),
                        train_winner=None,
                        train_avg_rank=None,
                        strategy_metrics=None,
                        benchmark_metrics=None,
                        status="error",
                        error="All training configs failed.",
                    )
                )
                continue

            winner_top_n = int(winner_key.split(" · ")[0].replace("Top ", ""))
            winner_mode = "cash" if winner_key.endswith("Cash") else "defensive_asset"
            try:
                rotation_result, benchmark_result = run_single_rotation(
                    shared_dfs,
                    top_n=winner_top_n,
                    defensive_mode=winner_mode,
                    date_from=window["test_from"],
                    date_to=window["test_to"],
                )
                folds.append(
                    WalkForwardFoldSummary(
                        fold=window["fold"],
                        train_from=str(window["train_from"]),
                        train_to=str(window["train_to"]),
                        test_from=str(window["test_from"]),
                        test_to=str(window["test_to"]),
                        train_winner=winner_key,
                        train_avg_rank=winner_rank,
                        strategy_metrics=_metrics_model(rotation_result["metrics"]),
                        benchmark_metrics=_metrics_model(benchmark_result["metrics"]),
                        status="ok",
                    )
                )
            except Exception as exc:  # pragma: no cover
                warnings.append(f"Fold {window['fold']} OOS run failed: {exc}")
                folds.append(
                    WalkForwardFoldSummary(
                        fold=window["fold"],
                        train_from=str(window["train_from"]),
                        train_to=str(window["train_to"]),
                        test_from=str(window["test_from"]),
                        test_to=str(window["test_to"]),
                        train_winner=winner_key,
                        train_avg_rank=winner_rank,
                        strategy_metrics=None,
                        benchmark_metrics=None,
                        status="error",
                        error=str(exc),
                    )
                )

        successful_folds = [fold for fold in folds if fold.status == "ok" and fold.strategy_metrics is not None]
        winner_counts: dict[str, int] = {}
        for fold in successful_folds:
            if fold.train_winner:
                winner_counts[fold.train_winner] = winner_counts.get(fold.train_winner, 0) + 1
        most_frequent_winner = max(winner_counts, key=winner_counts.get) if winner_counts else None

        def _avg(values: list[float | None]) -> float | None:
            valid = [value for value in values if value is not None]
            return (sum(valid) / len(valid)) if valid else None

        average_oos_metrics = _metrics_model(
            {
                "cagr": _avg([fold.strategy_metrics.cagr for fold in successful_folds if fold.strategy_metrics]),
                "max_drawdown": _avg([fold.strategy_metrics.max_drawdown for fold in successful_folds if fold.strategy_metrics]),
                "sharpe_ratio": _avg([fold.strategy_metrics.sharpe_ratio for fold in successful_folds if fold.strategy_metrics]),
                "calmar_ratio": _avg([fold.strategy_metrics.calmar_ratio for fold in successful_folds if fold.strategy_metrics]),
                "win_rate": None,
                "total_trades": None,
                "final_equity": _avg([fold.strategy_metrics.final_equity for fold in successful_folds if fold.strategy_metrics]),
            }
        )
        average_benchmark_metrics = _metrics_model(
            {
                "cagr": _avg([fold.benchmark_metrics.cagr for fold in successful_folds if fold.benchmark_metrics]),
                "max_drawdown": _avg([fold.benchmark_metrics.max_drawdown for fold in successful_folds if fold.benchmark_metrics]),
                "sharpe_ratio": _avg([fold.benchmark_metrics.sharpe_ratio for fold in successful_folds if fold.benchmark_metrics]),
                "calmar_ratio": None,
                "win_rate": None,
                "total_trades": None,
                "final_equity": _avg([fold.benchmark_metrics.final_equity for fold in successful_folds if fold.benchmark_metrics]),
            }
        )

        return StrategyEvaluationResponse(
            run_mode=request.run_mode,
            timestamp_utc=timestamp_utc,
            tickers=tickers,
            parameters=parameters,
            walk_forward=WalkForwardSummary(
                total_folds=len(folds),
                successful_folds=len(successful_folds),
                most_frequent_winner=most_frequent_winner,
                average_oos_metrics=average_oos_metrics,
                average_benchmark_metrics=average_benchmark_metrics,
                folds=folds,
            ),
            warnings=warnings,
        )

    raise HTTPException(status_code=422, detail=f"Unsupported run_mode: {request.run_mode}")


def explain_recommendation_tool(request: ExplainRecommendationRequest) -> RecommendationPayload:
    if request.source == "rank_assets":
        ranking = request.ranking
        if ranking is None or not ranking.ranked_assets:
            raise HTTPException(status_code=422, detail="ranking payload is required for source=rank_assets.")

        candidate = next(
            (
                asset
                for asset in ranking.ranked_assets
                if asset.label in ELIGIBLE_LABELS and asset.data_quality in ELIGIBLE_QUALITY
            ),
            ranking.ranked_assets[0],
        )
        contributions = {
            "60d momentum": candidate.score_breakdown.ret_60d_contribution,
            "20d momentum": candidate.score_breakdown.ret_20d_contribution,
            "120d momentum": candidate.score_breakdown.ret_120d_contribution,
            "trend": candidate.score_breakdown.trend_contribution,
            "low volatility": candidate.score_breakdown.low_volatility_contribution,
            "low drawdown": candidate.score_breakdown.low_drawdown_contribution,
        }
        top_drivers = [name for name, _ in sorted(contributions.items(), key=lambda item: item[1], reverse=True)[:3]]
        invalidation_conditions = [
            "Label falls below WATCH on the next deterministic ranking run.",
            "Data quality drops to INSUFFICIENT.",
        ]
        if candidate.trend.trend_score is not None and candidate.trend.trend_score >= 0.5:
            invalidation_conditions.append("Trend score falls below 0.5.")
        if candidate.recent_returns.ret_60d is not None and candidate.recent_returns.ret_60d > 0:
            invalidation_conditions.append("60-day return turns negative.")

        caveats = ["Ranking is relative to the requested universe, not a full market cross-section."]
        caveats.extend(candidate.warnings)

        payload = RecommendationPayload(
            source="rank_assets",
            recommended_entity_type="asset",
            recommended_entity=candidate.ticker,
            top_deterministic_result=ranking.ranked_assets[0].ticker if ranking.ranked_assets else candidate.ticker,
            summary=f"{candidate.ticker} is the current deterministic preference because it ranks highest on the requested universe with label {candidate.label}.",
            why_preferred=[
                f"Composite score {candidate.score:.4f} leads the ranked universe.",
                f"Strongest current drivers: {', '.join(top_drivers)}.",
                f"Data quality is {candidate.data_quality}.",
            ],
            invalidation_conditions=invalidation_conditions,
            risks=_recommendation_risks_from_metrics(
                BacktestMetrics(
                    cagr=None,
                    max_drawdown=-candidate.drawdown_60d if candidate.drawdown_60d is not None else None,
                    sharpe_ratio=None,
                    calmar_ratio=None,
                    win_rate=None,
                    total_trades=None,
                    final_equity=None,
                )
            ),
            caveats=caveats,
            supporting_metrics={
                "score": candidate.score,
                "label": candidate.label,
                "suggested_weight": candidate.suggested_weight,
                "score_breakdown": candidate.score_breakdown.model_dump(),
            },
        )
        return _personalize_recommendation(
            payload,
            tickers=[asset.ticker for asset in ranking.ranked_assets],
            metrics=BacktestMetrics(
                cagr=None,
                max_drawdown=-candidate.drawdown_60d if candidate.drawdown_60d is not None else None,
                sharpe_ratio=None,
                calmar_ratio=None,
                win_rate=None,
                total_trades=None,
                final_equity=None,
            ),
            knowledge_query=_knowledge_query_for_recommendation(
                source="rank_assets",
                recommended_entity=candidate.ticker,
            ),
            ranked_assets=ranking.ranked_assets,
        )

    strategy = request.strategy_evaluation
    if strategy is None:
        raise HTTPException(status_code=422, detail="strategy_evaluation payload is required for source=strategy_evaluation.")

    recommended_entity = None
    supporting_metrics: dict[str, Any] = {"run_mode": strategy.run_mode}
    why_preferred: list[str] = []
    invalidation_conditions: list[str] = []
    selected_metrics: BacktestMetrics | None = None

    if strategy.run_mode == "single" and strategy.single_run is not None:
        recommended_entity = strategy.single_run.config_key
        selected_metrics = strategy.single_run.metrics
        why_preferred = [
            f"Single-run evaluation completed for {recommended_entity}.",
            "Recommendation reflects the only evaluated configuration in this request.",
        ]
        invalidation_conditions = [
            "Benchmark overtakes the strategy on both CAGR and drawdown on refreshed data.",
            "Re-run with updated parameters produces materially weaker Calmar ratio.",
        ]
        supporting_metrics["benchmark"] = strategy.benchmark.model_dump() if strategy.benchmark else None
    elif strategy.run_mode == "compare_variants" and strategy.compare_variants:
        valid = [row for row in strategy.compare_variants if row.metrics is not None]
        chosen = min(
            valid,
            key=lambda row: (
                -(row.metrics.calmar_ratio if row.metrics and row.metrics.calmar_ratio is not None else float("-inf")),
                -(row.metrics.cagr if row.metrics and row.metrics.cagr is not None else float("-inf")),
                abs(row.metrics.max_drawdown if row.metrics and row.metrics.max_drawdown is not None else float("inf")),
            ),
        )
        recommended_entity = chosen.config_key
        selected_metrics = chosen.metrics
        why_preferred = [
            "Chosen by highest Calmar ratio across the compared variants.",
            "Tie-breakers favor higher CAGR and lower drawdown.",
        ]
        invalidation_conditions = [
            "The alternative variant overtakes on Calmar ratio.",
            "The chosen variant loses its drawdown advantage on updated data.",
        ]
    elif strategy.run_mode == "parameter_sweep" and strategy.parameter_sweep:
        valid = [row for row in strategy.parameter_sweep if row.metrics is not None]
        chosen_key = _best_config_for_metrics([row.model_dump() for row in valid])
        chosen = next((row for row in valid if row.config_key == chosen_key), None)
        recommended_entity = chosen.config_key if chosen else None
        selected_metrics = chosen.metrics if chosen else None
        why_preferred = [
            "Chosen from the sweep by Calmar-first ranking, then CAGR, then lower drawdown.",
            f"Evaluated {len(valid)} completed sweep configurations.",
        ]
        invalidation_conditions = [
            "A different sweep configuration overtakes on Calmar ratio.",
            "Updated data causes the chosen config to lose its return/drawdown balance.",
        ]
    elif strategy.run_mode == "cross_preset" and strategy.cross_preset is not None:
        recommended_entity = (
            strategy.cross_preset.recommended_default_config
            or strategy.cross_preset.most_robust_config
            or strategy.cross_preset.overall_winner
        )
        chosen = next((row for row in strategy.cross_preset.ranking_rows if row.config_key == recommended_entity), None)
        why_preferred = [
            "Recommendation prioritizes robustness, then full-cycle quality, then drawdown control.",
            f"Most robust config: {strategy.cross_preset.most_robust_config or '-'}; overall winner: {strategy.cross_preset.overall_winner or '-'}."
        ]
        invalidation_conditions = [
            "Another config takes the lowest robustness score.",
            "The recommended config loses its Full cycle advantage on refreshed runs.",
        ]
        supporting_metrics["cross_preset_summary"] = strategy.cross_preset.model_dump()
        if chosen:
            selected_metrics = BacktestMetrics(
                cagr=chosen.avg_cagr,
                max_drawdown=-chosen.avg_abs_drawdown if chosen.avg_abs_drawdown is not None else None,
                sharpe_ratio=None,
                calmar_ratio=None,
                win_rate=None,
                total_trades=None,
                final_equity=None,
            )
    elif strategy.run_mode == "walk_forward" and strategy.walk_forward is not None:
        recommended_entity = strategy.walk_forward.most_frequent_winner
        selected_metrics = strategy.walk_forward.average_oos_metrics
        why_preferred = [
            "Recommendation uses the most frequently selected training-window winner.",
            "Quality is checked against average out-of-sample metrics rather than in-sample results.",
        ]
        invalidation_conditions = [
            "Another config becomes the most frequent winner across folds.",
            "Average out-of-sample metrics deteriorate materially on refreshed folds.",
        ]
        supporting_metrics["walk_forward_summary"] = strategy.walk_forward.model_dump()
    else:
        raise HTTPException(status_code=422, detail="Unsupported or empty strategy_evaluation payload.")

    risks = _recommendation_risks_from_metrics(selected_metrics)
    caveats = ["Recommendation is deterministic and based only on available local project data."]
    if strategy.warnings:
        caveats.extend(strategy.warnings[:3])

    payload = RecommendationPayload(
        source="strategy_evaluation",
        recommended_entity_type="strategy_config",
        recommended_entity=recommended_entity,
        top_deterministic_result=recommended_entity,
        summary=f"{recommended_entity or 'No configuration'} is the current deterministic default for {strategy.run_mode.replace('_', ' ')} analysis.",
        why_preferred=why_preferred,
        invalidation_conditions=invalidation_conditions,
        risks=risks,
        caveats=caveats,
        supporting_metrics=supporting_metrics,
    )
    return _personalize_recommendation(
        payload,
        tickers=strategy.tickers,
        metrics=selected_metrics,
        knowledge_query=_knowledge_query_for_recommendation(
            source="strategy_evaluation",
            recommended_entity=recommended_entity,
            strategy=strategy,
        ),
    )


def query_knowledge_base_tool(request: KnowledgeBaseQueryRequest) -> KnowledgeBaseQueryResponse:
    return query_local_knowledge_base(request)


async def copilot_chat_tool(
    session: AsyncSession,
    request: CopilotChatRequest,
) -> CopilotChatResponse:
    session_state = request.session_state or CopilotChatSessionState()
    detected_intent = _detect_chat_intent(request.user_query, session_state)
    tools_used: list[str] = []
    warnings: list[str] = []
    supporting_data: dict[str, Any] = {}
    next_actions: list[str] = []

    if detected_intent == "market_snapshot":
        tickers = await _resolve_query_tickers(session, request.user_query)
        date_from, date_to = _extract_dates(request.user_query)
        snapshot = await get_market_snapshot_tool(
            session,
            MarketSnapshotRequest(
                instrument_tickers=tickers,
                date_from=date_from,
                date_to=date_to,
            ),
        )
        tools_used.append("get_market_snapshot")
        supporting_data["market_snapshot"] = snapshot.model_dump(mode="json")
        warnings.extend(snapshot.warnings)
        leaders = ", ".join(asset.ticker for asset in snapshot.assets[:3]) if snapshot.assets else "no assets"
        answer = CopilotChatAnswer(
            headline="Market snapshot ready",
            summary=f"Loaded a deterministic market snapshot for {', '.join(snapshot.requested_tickers)} using local project data.",
            bullets=[
                f"Snapshot date: {snapshot.snapshot_date or 'unavailable'}.",
                f"Assets covered: {leaders}.",
                "Returns, volatility, drawdown, trend, and data-quality fields are included in supporting_data.",
            ],
        )
        next_actions = [
            "Ask 'rank these assets' to run the deterministic screener ranking.",
            "Ask for a strategy evaluation if you want the rotation engine tested on these tickers.",
        ]
        updated_state = session_state.model_copy(update={"last_intent": detected_intent})
        return CopilotChatResponse(
            user_query=request.user_query,
            detected_intent=detected_intent,
            tools_used=tools_used,
            answer=answer,
            supporting_data=supporting_data,
            recommendation_status=None,
            profile_constraints_applied=[],
            knowledge_sources_used=[],
            eligible_alternatives=[],
            warnings=warnings,
            next_actions=next_actions,
            session_state=updated_state,
        )

    if detected_intent == "asset_ranking":
        tickers = await _resolve_query_tickers(session, request.user_query)
        date_from, date_to = _extract_dates(request.user_query)
        ranking = await rank_assets_tool(
            session,
            RankAssetsRequest(
                instrument_tickers=tickers,
                top_n=_extract_top_n(request.user_query, default=3),
                date_from=date_from,
                date_to=date_to,
            ),
        )
        tools_used.append("rank_assets")
        supporting_data["ranking"] = ranking.model_dump(mode="json")
        warnings.extend(ranking.warnings)
        explanation = explain_recommendation_tool(
            ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
        )
        tools_used.append("explain_recommendation")
        supporting_data["recommendation"] = explanation.model_dump(mode="json")
        profile, _ = load_investor_profile()
        if profile is not None:
            supporting_data["active_profile"] = profile.model_dump(mode="json")
        warnings.extend(explanation.caveats)
        answer = _recommendation_answer(explanation, "Asset ranking and recommendation ready")
        if explanation.recommendation_status == "rejected_by_profile":
            next_actions = [
                "Review the profile conflicts and the surfaced eligible alternative, if one exists.",
                "Ask for risks or run a strategy evaluation on the allowed universe.",
            ]
        elif explanation.recommendation_status == "unsupported_by_knowledge":
            next_actions = [
                "Ask a more specific thesis or experiment question to strengthen knowledge support.",
                "Ask for risks or a strategy evaluation if you want more deterministic evidence.",
            ]
        else:
            next_actions = [
                "Ask 'why?' to review the decision logic again with the saved session state.",
                "Ask for a rotation strategy evaluation if you want the ranked universe backtested.",
            ]
        updated_state = session_state.model_copy(
            update={
                "last_intent": "recommendation_explanation",
                "last_ranking": ranking,
                "last_strategy_evaluation": None,
                "last_recommendation": explanation,
            }
        )
        return CopilotChatResponse(
            user_query=request.user_query,
            detected_intent=detected_intent,
            tools_used=tools_used,
            answer=answer,
            supporting_data=supporting_data,
            recommendation_status=explanation.recommendation_status,
            profile_constraints_applied=explanation.profile_constraints_applied,
            knowledge_sources_used=explanation.knowledge_sources_used,
            eligible_alternatives=explanation.eligible_alternatives,
            warnings=warnings,
            next_actions=next_actions,
            session_state=updated_state,
        )

    if detected_intent == "strategy_evaluation":
        tickers = await _resolve_query_tickers(session, request.user_query)
        date_from, date_to = _extract_dates(request.user_query)
        if date_from is None or date_to is None:
            date_from, date_to = _default_single_dates()
            warnings.append("No explicit date window found in the query, so the default 2021-01-01 to 2023-12-31 window was used.")
        q = request.user_query.lower()
        if "walk forward" in q or "walk-forward" in q:
            run_mode = "walk_forward"
        elif "cross preset" in q or "cross-preset" in q:
            run_mode = "cross_preset"
        elif "sweep" in q:
            run_mode = "parameter_sweep"
        elif "compare" in q:
            run_mode = "compare_variants"
        else:
            run_mode = "single"

        evaluation = await run_strategy_evaluation_tool(
            session,
            StrategyEvaluationRequest(
                run_mode=run_mode,
                instrument_tickers=tickers,
                date_from=date_from,
                date_to=date_to,
                top_n=_extract_top_n(request.user_query, default=3),
                top_n_values=_extract_top_n_values(request.user_query),
                initial_capital=10_000.0,
                commission_bps=10.0,
                rebalance_frequency="monthly",
                warmup_bars=252,
                defensive_mode="defensive_asset" if "defensive" in q else "cash",
                defensive_tickers=["TLT", "GLD"],
                wf_data_start=pd.Timestamp("2018-01-01").date(),
                wf_data_end=pd.Timestamp("2023-12-31").date(),
                wf_train_years=2,
                wf_test_years=1,
                wf_step_years=1,
            ),
        )
        tools_used.append("run_strategy_evaluation")
        supporting_data["strategy_evaluation"] = evaluation.model_dump(mode="json")
        warnings.extend(evaluation.warnings)

        if run_mode == "single" and evaluation.single_run is not None:
            summary_line = f"{evaluation.single_run.config_key} finished with final equity {evaluation.single_run.metrics.final_equity:.2f}."
        elif run_mode == "compare_variants" and evaluation.compare_variants:
            best = min(
                [row for row in evaluation.compare_variants if row.metrics is not None],
                key=lambda row: (
                    -(row.metrics.calmar_ratio if row.metrics and row.metrics.calmar_ratio is not None else float("-inf")),
                    -(row.metrics.cagr if row.metrics and row.metrics.cagr is not None else float("-inf")),
                ),
            )
            summary_line = f"{best.config_key} is currently the stronger compared variant."
        elif run_mode == "cross_preset" and evaluation.cross_preset is not None:
            summary_line = f"Recommended default config: {evaluation.cross_preset.recommended_default_config or 'none'}."
        elif run_mode == "walk_forward" and evaluation.walk_forward is not None:
            summary_line = f"Most frequent out-of-sample winner: {evaluation.walk_forward.most_frequent_winner or 'none'}."
        else:
            summary_line = f"{run_mode.replace('_', ' ')} evaluation completed."

        if any(keyword in q for keyword in ["why", "recommend", "risk", "risks"]):
            explanation = explain_recommendation_tool(
                ExplainRecommendationRequest(source="strategy_evaluation", strategy_evaluation=evaluation)
            )
            tools_used.append("explain_recommendation")
            supporting_data["recommendation"] = explanation.model_dump(mode="json")
            profile, _ = load_investor_profile()
            if profile is not None:
                supporting_data["active_profile"] = profile.model_dump(mode="json")
            warnings.extend(explanation.caveats)
            answer = _recommendation_answer(explanation, "Strategy evaluation and explanation ready")
            next_actions = [
                "Ask for a different run mode such as compare, sweep, cross-preset, or walk-forward.",
                "Ask for the invalidation conditions or risks again if you want them isolated.",
            ]
            updated_state = session_state.model_copy(
                update={
                    "last_intent": "recommendation_explanation",
                    "last_strategy_evaluation": evaluation,
                    "last_recommendation": explanation,
                }
            )
            profile_constraints_applied = explanation.profile_constraints_applied
            knowledge_sources_used = explanation.knowledge_sources_used
        else:
            answer = CopilotChatAnswer(
                headline="Strategy evaluation complete",
                summary=summary_line,
                bullets=[
                    f"Run mode: {evaluation.run_mode}.",
                    f"Tickers: {', '.join(evaluation.tickers)}.",
                    "Structured metrics and summaries are included in supporting_data.",
                ],
            )
            next_actions = [
                "Ask 'why is that preferred?' to turn this evaluation into a deterministic recommendation.",
                "Ask for another run mode if you want a broader comparison.",
            ]
            updated_state = session_state.model_copy(
                update={
                    "last_intent": detected_intent,
                    "last_strategy_evaluation": evaluation,
                    "last_ranking": None,
                }
            )
            profile_constraints_applied = []
            knowledge_sources_used = []
            recommendation_status = None
            eligible_alternatives = []

        return CopilotChatResponse(
            user_query=request.user_query,
            detected_intent=detected_intent,
            tools_used=tools_used,
            answer=answer,
            supporting_data=supporting_data,
            recommendation_status=(
                explanation.recommendation_status if any(keyword in q for keyword in ["why", "recommend", "risk", "risks"]) else recommendation_status
            ),
            profile_constraints_applied=profile_constraints_applied,
            knowledge_sources_used=knowledge_sources_used,
            eligible_alternatives=(
                explanation.eligible_alternatives if any(keyword in q for keyword in ["why", "recommend", "risk", "risks"]) else eligible_alternatives
            ),
            warnings=warnings,
            next_actions=next_actions,
            session_state=updated_state,
        )

    if detected_intent == "recommendation_explanation":
        if session_state.last_strategy_evaluation is not None:
            explanation = explain_recommendation_tool(
                ExplainRecommendationRequest(
                    source="strategy_evaluation",
                    strategy_evaluation=session_state.last_strategy_evaluation,
                )
            )
            tools_used.append("explain_recommendation")
            supporting_data["recommendation"] = explanation.model_dump(mode="json")
            profile, _ = load_investor_profile()
            if profile is not None:
                supporting_data["active_profile"] = profile.model_dump(mode="json")
            answer = _recommendation_answer(explanation, "Recommendation explanation ready")
            next_actions = [
                "Ask about risks or invalidation to focus on downside conditions.",
                "Ask for a different evaluation mode if you want a fresh deterministic run.",
            ]
            updated_state = session_state.model_copy(
                update={"last_intent": detected_intent, "last_recommendation": explanation}
            )
            profile_constraints_applied = explanation.profile_constraints_applied
            knowledge_sources_used = explanation.knowledge_sources_used
            recommendation_status = explanation.recommendation_status
            eligible_alternatives = explanation.eligible_alternatives
        elif session_state.last_ranking is not None:
            explanation = explain_recommendation_tool(
                ExplainRecommendationRequest(
                    source="rank_assets",
                    ranking=session_state.last_ranking,
                )
            )
            tools_used.append("explain_recommendation")
            supporting_data["recommendation"] = explanation.model_dump(mode="json")
            profile, _ = load_investor_profile()
            if profile is not None:
                supporting_data["active_profile"] = profile.model_dump(mode="json")
            answer = _recommendation_answer(explanation, "Ranking explanation ready")
            next_actions = [
                "Ask for a strategy evaluation if you want the ranked universe tested.",
                "Ask for risks to surface caveats explicitly.",
            ]
            updated_state = session_state.model_copy(
                update={"last_intent": detected_intent, "last_recommendation": explanation}
            )
            profile_constraints_applied = explanation.profile_constraints_applied
            knowledge_sources_used = explanation.knowledge_sources_used
            recommendation_status = explanation.recommendation_status
            eligible_alternatives = explanation.eligible_alternatives
        else:
            answer = CopilotChatAnswer(
                headline="No prior result to explain",
                summary="I do not have a saved ranking or strategy evaluation in this chat session yet.",
                bullets=[
                    "Run a market ranking or strategy evaluation first.",
                    "Then ask follow-ups like 'why?' or 'what are the risks?'.",
                ],
            )
            next_actions = [
                "Ask for an asset ranking on specific tickers.",
                "Ask for a strategy evaluation on the rotation engine.",
            ]
            updated_state = session_state.model_copy(update={"last_intent": "unclear"})
            profile_constraints_applied = []
            knowledge_sources_used = []
            recommendation_status = None
            eligible_alternatives = []

        return CopilotChatResponse(
            user_query=request.user_query,
            detected_intent=detected_intent,
            tools_used=tools_used,
            answer=answer,
            supporting_data=supporting_data,
            recommendation_status=recommendation_status,
            profile_constraints_applied=profile_constraints_applied,
            knowledge_sources_used=knowledge_sources_used,
            eligible_alternatives=eligible_alternatives,
            warnings=warnings,
            next_actions=next_actions,
            session_state=updated_state,
        )

    if detected_intent == "knowledge_base_query":
        kb = query_knowledge_base_tool(KnowledgeBaseQueryRequest(query=request.user_query, top_k=5))
        tools_used.append("query_knowledge_base")
        supporting_data["knowledge_base"] = kb.model_dump(mode="json")
        profile, profile_warnings = load_investor_profile()
        if profile is not None:
            supporting_data["active_profile"] = profile.model_dump(mode="json")
        warnings.extend(profile_warnings)
        warnings.extend(kb.warnings)
        answer = CopilotChatAnswer(
            headline="Knowledge-base lookup complete",
            summary=(
                f"Retrieved {len(kb.matches)} local knowledge source(s) for this query."
                if kb.matches
                else "The local knowledge base is available, but no relevant sources matched this query."
            ),
            bullets=[
                f"Backend: {kb.backend}.",
                "Matches come from local files only, with deterministic token-overlap retrieval.",
            ],
        )
        next_actions = [
            "Ask a more specific thesis, rule, or experiment question to narrow retrieval.",
            "Use ranking or strategy evaluation if you need fresh deterministic market evidence.",
        ]
        updated_state = session_state.model_copy(update={"last_intent": detected_intent})
        return CopilotChatResponse(
            user_query=request.user_query,
            detected_intent=detected_intent,
            tools_used=tools_used,
            answer=answer,
            supporting_data=supporting_data,
            recommendation_status=None,
            profile_constraints_applied=[],
            knowledge_sources_used=kb.matches,
            eligible_alternatives=[],
            warnings=warnings,
            next_actions=next_actions,
            session_state=updated_state,
        )

    answer = CopilotChatAnswer(
        headline="Intent unclear",
        summary="I could not confidently route that request to one deterministic tool flow.",
        bullets=[
            "Try asking for a market snapshot on named tickers.",
            "Or ask for ranking, a strategy evaluation, or an explanation of the last result.",
        ],
    )
    next_actions = [
        "Example: 'Show a market snapshot for SPY, QQQ, TLT, GLD'.",
        "Example: 'Run a cross-preset strategy evaluation for SPY, QQQ, IWM, TLT, GLD'.",
    ]
    updated_state = session_state.model_copy(update={"last_intent": "unclear"})
    return CopilotChatResponse(
        user_query=request.user_query,
        detected_intent="unclear",
        tools_used=[],
        answer=answer,
        supporting_data={},
        recommendation_status=None,
        profile_constraints_applied=[],
        knowledge_sources_used=[],
        eligible_alternatives=[],
        warnings=warnings,
        next_actions=next_actions,
        session_state=updated_state,
    )
