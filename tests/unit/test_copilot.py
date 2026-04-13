from __future__ import annotations

from datetime import date
from pathlib import Path
from uuid import uuid4

import pandas as pd
import pytest

import app.services.copilot as copilot_service
import app.services.copilot_personalization as personalization_service
from app.schemas.backtest import BacktestMetrics
from app.schemas.copilot import (
    CopilotChatRequest,
    CopilotChatSessionState,
    CrossPresetRankingRow,
    CrossPresetSummary,
    ExplainRecommendationRequest,
    RankAssetsResponse,
    StrategyEvaluationResponse,
)


def _df(start: str, periods: int, base: float, step: float) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=periods)
    rows = []
    price = base
    for current_date in dates:
        rows.append(
            {
                "date": current_date.date(),
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "volume": 1000,
            }
        )
        price += step
    frame = pd.DataFrame(rows)
    return frame.set_index("date")


def _drawdown_df() -> pd.DataFrame:
    dates = pd.bdate_range(start="2023-01-02", periods=260)
    prices: list[float] = []
    for index in range(260):
        if index < 180:
            prices.append(100.0 + index * 0.3)
        elif index < 225:
            prices.append(154.0 + (index - 180) * 0.2)
        elif index < 245:
            prices.append(163.0 - (index - 225) * 2.8)
        else:
            prices.append(107.0 + (index - 245) * 0.15)
    frame = pd.DataFrame(
        {
            "date": [current_date.date() for current_date in dates],
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "volume": [1000] * len(prices),
        }
    )
    return frame.set_index("date")


def _local_temp_dir(name: str) -> Path:
    path = Path("tests") / ".tmp" / f"{name}_{uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _write_doc(
    path: Path,
    *,
    title: str,
    doc_type: str,
    tags: list[str],
    aliases: list[str],
    body: str,
    priority: int = 5,
    status: str = "active",
) -> None:
    path.write_text(
        (
            "---\n"
            f"title: {title}\n"
            f"doc_type: {doc_type}\n"
            f"tags: [{', '.join(tags)}]\n"
            f"aliases: [{', '.join(aliases)}]\n"
            f"priority: {priority}\n"
            f"status: {status}\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def test_build_rank_assets_response_includes_score_breakdowns() -> None:
    dfs = {
        "SPY": _df("2023-01-02", 260, 100.0, 0.3),
        "QQQ": _df("2023-01-02", 260, 100.0, 0.1),
        "GLD": _df("2023-01-02", 30, 100.0, 0.05),
    }

    response = copilot_service._build_rank_assets_response(dfs, top_n=2)

    assert response.tool_name == "rank_assets"
    assert response.universe_size == 3
    spy = next(asset for asset in response.ranked_assets if asset.ticker == "SPY")
    total = (
        spy.score_breakdown.ret_60d_contribution
        + spy.score_breakdown.ret_20d_contribution
        + spy.score_breakdown.ret_120d_contribution
        + spy.score_breakdown.trend_contribution
        + spy.score_breakdown.low_volatility_contribution
        + spy.score_breakdown.low_drawdown_contribution
    )
    assert total == pytest.approx(spy.score, abs=1e-4)
    gld = next(asset for asset in response.ranked_assets if asset.ticker == "GLD")
    assert gld.data_quality == "LIMITED"
    assert gld.warnings


def test_explain_recommendation_for_rank_assets_is_deterministic() -> None:
    ranking = RankAssetsResponse(
        snapshot_date="2024-12-31",
        universe_size=2,
        top_n=1,
        ranked_assets=copilot_service._build_rank_assets_response(
            {"SPY": _df("2023-01-02", 260, 100.0, 0.2), "QQQ": _df("2023-01-02", 260, 100.0, 0.05)},
            top_n=1,
        ).ranked_assets,
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
    )

    assert payload.source == "rank_assets"
    assert payload.recommended_entity_type == "asset"
    assert payload.recommended_entity in {"SPY", "QQQ"}
    assert payload.why_preferred
    assert payload.invalidation_conditions


def test_explain_recommendation_prefers_cross_preset_default() -> None:
    strategy = StrategyEvaluationResponse(
        run_mode="cross_preset",
        timestamp_utc=pd.Timestamp("2026-04-13T12:00:00Z").to_pydatetime(),
        tickers=["SPY", "QQQ", "IWM", "TLT", "GLD"],
        parameters={"run_mode": "cross_preset"},
        cross_preset=CrossPresetSummary(
            overall_winner="Top 2 · Defensive",
            most_robust_config="Top 2 · Defensive",
            best_bull_market_config="Top 3 · Cash",
            best_bear_market_config="Top 2 · Defensive",
            best_return_config="Top 3 · Cash",
            best_drawdown_control_config="Top 1 · Cash",
            recommended_default_config="Top 2 · Defensive",
            ranking_rows=[
                CrossPresetRankingRow(
                    config_key="Top 2 · Defensive",
                    bull_run_avg_rank=1.0,
                    rate_hike_bear_avg_rank=1.0,
                    mixed_volatile_avg_rank=1.5,
                    full_cycle_avg_rank=1.0,
                    average_rank=1.125,
                    rank_std_dev=0.2165,
                    times_ranked_1=3,
                    times_ranked_top_2=4,
                    robustness_score=1.3415,
                    avg_cagr=0.12,
                    avg_abs_drawdown=0.18,
                )
            ],
        ),
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="strategy_evaluation", strategy_evaluation=strategy)
    )

    assert payload.source == "strategy_evaluation"
    assert payload.recommended_entity == "Top 2 · Defensive"
    assert payload.recommendation_status in {"eligible", "eligible_with_cautions", "unsupported_by_knowledge"}


@pytest.mark.asyncio
async def test_run_strategy_evaluation_single(monkeypatch: pytest.MonkeyPatch) -> None:
    dfs = {
        "SPY": _df("2022-01-03", 400, 100.0, 0.15),
        "QQQ": _df("2022-01-03", 400, 90.0, 0.20),
        "TLT": _df("2022-01-03", 400, 110.0, -0.02),
        "GLD": _df("2022-01-03", 400, 95.0, 0.03),
    }

    async def _fake_load(*args, **kwargs):
        return dfs

    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    response = await copilot_service.run_strategy_evaluation_tool(
        None,
        copilot_service.StrategyEvaluationRequest(
            run_mode="single",
            instrument_tickers=["QQQ", "TLT", "GLD"],
            date_from=date(2023, 1, 2),
            date_to=date(2023, 12, 29),
            top_n=2,
        ),
    )

    assert response.tool_name == "run_strategy_evaluation"
    assert response.single_run is not None
    assert response.benchmark is not None


@pytest.mark.asyncio
async def test_chat_follow_up_why_uses_last_ranking(monkeypatch: pytest.MonkeyPatch) -> None:
    dfs = {
        "SPY": _df("2023-01-02", 260, 100.0, 0.2),
        "QQQ": _df("2023-01-02", 260, 100.0, 0.05),
    }

    async def _fake_load(*args, **kwargs):
        return dfs

    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    ranking = await copilot_service.rank_assets_tool(
        None,
        copilot_service.RankAssetsRequest(instrument_tickers=["SPY", "QQQ"], top_n=1),
    )

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(
            user_query="why?",
            session_state=CopilotChatSessionState(last_ranking=ranking, last_intent="asset_ranking"),
        ),
    )

    assert response.detected_intent == "recommendation_explanation"
    assert response.tools_used == ["explain_recommendation"]
    assert response.session_state.last_recommendation is not None


def test_query_knowledge_base_returns_local_matches(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_kb")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Test Profile\","
            "\"investment_objective\":\"Compound capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"moderate\","
            "\"max_acceptable_drawdown\":0.25,"
            "\"preferred_assets\":[\"SPY\"],"
            "\"disallowed_assets\":[\"TQQQ\"],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Test\""
            "}"
        ),
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "rules.md",
        title="Rules",
        doc_type="risk_policy",
        tags=["tqqq", "drawdown", "rules"],
        aliases=["risk rules", "policy"],
        body="# Rules\nAvoid leveraged ETFs like TQQQ. Keep drawdowns controlled.",
        priority=9,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    response = copilot_service.query_knowledge_base_tool(
        copilot_service.KnowledgeBaseQueryRequest(query="What do the rules say about TQQQ drawdown?", top_k=3)
    )

    assert response.backend == "local_filesystem"
    assert response.matches
    assert response.matches[0].title == "Rules"
    assert response.matches[0].matched_terms


def test_query_knowledge_base_returns_different_matches_for_different_queries(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_kb_scoring")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        "{\"profile_name\":\"Test\",\"investment_objective\":\"Compound\",\"time_horizon\":\"5y\",\"risk_tolerance\":\"moderate\",\"max_acceptable_drawdown\":0.25,\"preferred_assets\":[\"SPY\"],\"disallowed_assets\":[],\"preferred_strategy_bias\":\"defensive\",\"liquidity_needs\":\"high\",\"notes\":\"Test\"}",
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "walk_forward.md",
        title="Walk Forward Notes",
        doc_type="experiment_conclusion",
        tags=["walk-forward", "oos"],
        aliases=["walk forward"],
        body="Walk-forward testing matters more than in-sample wins.",
        priority=8,
    )
    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy", "benchmark"],
        aliases=["spy thesis"],
        body="SPY is the benchmark and core liquid ETF.",
        priority=7,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    walk_forward = copilot_service.query_knowledge_base_tool(
        copilot_service.KnowledgeBaseQueryRequest(query="What do my notes say about walk forward testing?", top_k=2)
    )
    spy = copilot_service.query_knowledge_base_tool(
        copilot_service.KnowledgeBaseQueryRequest(query="What is my SPY thesis?", top_k=2)
    )

    assert walk_forward.matches[0].title == "Walk Forward Notes"
    assert spy.matches[0].title == "SPY Thesis"


def test_query_knowledge_base_no_match_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_kb_nomatch")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        "{\"profile_name\":\"Test\",\"investment_objective\":\"Compound\",\"time_horizon\":\"5y\",\"risk_tolerance\":\"moderate\",\"max_acceptable_drawdown\":0.25,\"preferred_assets\":[\"SPY\"],\"disallowed_assets\":[],\"preferred_strategy_bias\":\"defensive\",\"liquidity_needs\":\"high\",\"notes\":\"Test\"}",
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy"],
        aliases=["spy thesis"],
        body="SPY is the core benchmark ETF.",
        priority=7,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    response = copilot_service.query_knowledge_base_tool(
        copilot_service.KnowledgeBaseQueryRequest(query="bananas lunar mining zebra", top_k=3)
    )

    assert response.matches == []
    assert any("No relevant local knowledge documents matched this query." in warning for warning in response.warnings)


def test_explain_recommendation_applies_profile_constraints(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_profile")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Test Profile\","
            "\"investment_objective\":\"Compound capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"moderate\","
            "\"max_acceptable_drawdown\":0.10,"
            "\"preferred_assets\":[\"SPY\"],"
            "\"disallowed_assets\":[\"QQQ\"],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Test\""
            "}"
        ),
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "thesis.md",
        title="QQQ Thesis",
        doc_type="investment_thesis",
        tags=["qqq", "drawdown"],
        aliases=["qqq thesis"],
        body="# Thesis\nQQQ has higher upside but can exceed a strict drawdown budget.",
        priority=7,
    )
    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy", "core"],
        aliases=["spy thesis"],
        body="SPY is acceptable as a core holding in this profile.",
        priority=8,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    ranking = RankAssetsResponse(
        snapshot_date="2024-12-31",
        universe_size=2,
        top_n=1,
        ranked_assets=copilot_service._build_rank_assets_response(
            {"QQQ": _df("2023-01-02", 260, 100.0, 0.25), "SPY": _df("2023-01-02", 260, 100.0, 0.05)},
            top_n=1,
        ).ranked_assets,
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
    )

    assert payload.profile_constraints_applied
    assert any(item.category == "hard_block" for item in payload.profile_constraints_applied)
    assert payload.knowledge_sources_used
    assert payload.top_deterministic_result == "QQQ"
    assert payload.recommended_entity == "SPY"
    assert payload.recommendation_status in {"eligible", "eligible_with_cautions"}
    assert payload.eligible_alternatives
    assert "Best eligible alternative" in payload.summary


def test_explain_recommendation_rejects_drawdown_limit_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_drawdown_conflict")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Tight Drawdown Profile\","
            "\"investment_objective\":\"Protect capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"low\","
            "\"max_acceptable_drawdown\":0.01,"
            "\"preferred_assets\":[\"QQQ\"],"
            "\"disallowed_assets\":[],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Very tight drawdown budget\""
            "}"
        ),
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "risk.md",
        title="Risk Note",
        doc_type="risk_policy",
        tags=["drawdown", "risk"],
        aliases=["risk note"],
        body="# Risk\nTight drawdown limits should override attractive upside when breached.",
        priority=9,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    ranking = RankAssetsResponse(
        snapshot_date="2024-12-31",
        universe_size=1,
        top_n=1,
        ranked_assets=copilot_service._build_rank_assets_response(
            {"QQQ": _drawdown_df()},
            top_n=1,
        ).ranked_assets,
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
    )

    assert any("exceeds the profile limit" in item.detail for item in payload.profile_constraints_applied)
    assert "not a justified recommendation" in payload.summary
    assert payload.recommendation_status == "rejected_by_profile"
    assert payload.recommended_entity is None


def test_explain_recommendation_preserves_normal_wording_without_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_no_conflict")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Aligned Profile\","
            "\"investment_objective\":\"Compound capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"moderate\","
            "\"max_acceptable_drawdown\":0.25,"
            "\"preferred_assets\":[\"SPY\"],"
            "\"disallowed_assets\":[],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Aligned profile\""
            "}"
        ),
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "thesis.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy", "core"],
        aliases=["spy thesis"],
        body="# Thesis\nSPY is acceptable as a core holding.",
        priority=8,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    ranking = RankAssetsResponse(
        snapshot_date="2024-12-31",
        universe_size=2,
        top_n=1,
        ranked_assets=copilot_service._build_rank_assets_response(
            {"SPY": _df("2023-01-02", 260, 100.0, 0.2), "QQQ": _df("2023-01-02", 260, 100.0, 0.05)},
            top_n=1,
        ).ranked_assets,
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
    )

    assert "current deterministic preference" in payload.summary
    assert "not eligible for the active investor profile" not in payload.summary
    assert payload.recommendation_status == "eligible"


@pytest.mark.asyncio
async def test_initial_ranking_response_applies_profile_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_initial_ranking")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        "{\"profile_name\":\"Test\",\"investment_objective\":\"Compound\",\"time_horizon\":\"5y\",\"risk_tolerance\":\"moderate\",\"max_acceptable_drawdown\":0.25,\"preferred_assets\":[\"SPY\"],\"disallowed_assets\":[\"QQQ\"],\"preferred_strategy_bias\":\"defensive\",\"liquidity_needs\":\"high\",\"notes\":\"Test\"}",
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "policy.md",
        title="Policy",
        doc_type="risk_policy",
        tags=["qqq", "rules"],
        aliases=["policy"],
        body="Avoid QQQ in the default profile.",
        priority=9,
    )
    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy", "core"],
        aliases=["spy thesis"],
        body="SPY is acceptable as a core holding in this profile.",
        priority=8,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    dfs = {
        "QQQ": _df("2023-01-02", 260, 100.0, 0.25),
        "SPY": _df("2023-01-02", 260, 100.0, 0.05),
    }

    async def _fake_load(*args, **kwargs):
        return dfs

    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)
    async def _fake_known_tickers(session):
        return {"QQQ", "SPY"}

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="Rank QQQ, SPY"),
    )

    assert response.detected_intent == "asset_ranking"
    assert response.recommendation_status in {"eligible", "eligible_with_cautions"}
    assert response.profile_constraints_applied
    assert response.eligible_alternatives
    assert response.answer.profile_decision_summary


def test_no_eligible_alternative_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_no_alt")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        "{\"profile_name\":\"Blocked\",\"investment_objective\":\"Protect capital\",\"time_horizon\":\"5y\",\"risk_tolerance\":\"low\",\"max_acceptable_drawdown\":0.03,\"preferred_assets\":[\"SPY\"],\"disallowed_assets\":[\"QQQ\"],\"preferred_strategy_bias\":\"defensive\",\"liquidity_needs\":\"high\",\"notes\":\"Blocked\"}",
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "policy.md",
        title="Policy",
        doc_type="risk_policy",
        tags=["qqq", "drawdown"],
        aliases=["policy"],
        body="Avoid QQQ and reject drawdown breaches.",
        priority=9,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    ranking = RankAssetsResponse(
        snapshot_date="2024-12-31",
        universe_size=1,
        top_n=1,
        ranked_assets=copilot_service._build_rank_assets_response({"QQQ": _drawdown_df()}, top_n=1).ranked_assets,
        warnings=[],
    )

    payload = copilot_service.explain_recommendation_tool(
        ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
    )

    assert payload.recommendation_status == "rejected_by_profile"
    assert payload.recommended_entity is None
    assert payload.eligible_alternatives == []
    assert "not a justified recommendation" in payload.summary


@pytest.mark.asyncio
async def test_chat_knowledge_query_returns_sources(monkeypatch: pytest.MonkeyPatch) -> None:
    base_dir = _local_temp_dir("copilot_chat_kb")
    profile_path = base_dir / "profile.json"
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir()
    profile_path.write_text(
        (
            "{"
            "\"profile_name\":\"Test Profile\","
            "\"investment_objective\":\"Compound capital\","
            "\"time_horizon\":\"5y\","
            "\"risk_tolerance\":\"moderate\","
            "\"max_acceptable_drawdown\":0.25,"
            "\"preferred_assets\":[\"SPY\"],"
            "\"disallowed_assets\":[\"TQQQ\"],"
            "\"preferred_strategy_bias\":\"defensive\","
            "\"liquidity_needs\":\"high\","
            "\"notes\":\"Test\""
            "}"
        ),
        encoding="utf-8",
    )
    _write_doc(
        knowledge_dir / "process.md",
        title="Process",
        doc_type="experiment_conclusion",
        tags=["cross-preset", "process"],
        aliases=["cross preset"],
        body="# Process\nCross-preset results should drive the default configuration choice.",
        priority=7,
    )
    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="What do my notes say about cross-preset results?"),
    )

    assert response.detected_intent == "knowledge_base_query"
    assert response.knowledge_sources_used
