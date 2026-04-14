from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock

import pandas as pd
import pytest

import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_personalization as personalization_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_monitoring import (
    MonitoringFinding,
    MonitoringRunRequest,
    MonitoringRunResponse,
    MonitoringSnapshotRecord,
    SnapshotComparison,
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


def _write_profile(path: Path, *, preferred_assets: list[str], disallowed_assets: list[str], max_drawdown: float = 0.25) -> None:
    payload = {
        "profile_name": "Monitoring Test Profile",
        "investment_objective": "Compound capital",
        "time_horizon": "5y",
        "risk_tolerance": "moderate",
        "max_acceptable_drawdown": max_drawdown,
        "preferred_assets": preferred_assets,
        "disallowed_assets": disallowed_assets,
        "preferred_strategy_bias": "defensive",
        "liquidity_needs": "high",
        "notes": "Test profile",
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_portfolio(path: Path, *, cash_available: float = 5000.0, positions: list[dict] | None = None) -> None:
    payload = {
        "portfolio_name": "Monitoring Test Portfolio",
        "base_currency": "USD",
        "cash_available": cash_available,
        "positions": positions or [],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_doc(path: Path, *, title: str, doc_type: str, tags: list[str], aliases: list[str], body: str) -> None:
    path.write_text(
        (
            "---\n"
            f"title: {title}\n"
            f"doc_type: {doc_type}\n"
            f"tags: [{', '.join(tags)}]\n"
            f"aliases: [{', '.join(aliases)}]\n"
            "priority: 8\n"
            "status: active\n"
            "---\n\n"
            f"{body}\n"
        ),
        encoding="utf-8",
    )


def _patch_monitoring_environment(monkeypatch: pytest.MonkeyPatch, base_dir: Path) -> tuple[Path, Path, Path]:
    knowledge_dir = base_dir / "knowledge"
    knowledge_dir.mkdir(parents=True, exist_ok=True)
    profile_path = base_dir / "profile.json"
    portfolio_path = base_dir / "portfolio.json"
    findings_path = base_dir / "findings.jsonl"
    snapshots_path = base_dir / "monitoring_snapshots.jsonl"
    journal_path = base_dir / "journal.jsonl"

    monkeypatch.setattr(personalization_service, "PROFILE_PATH", profile_path)
    monkeypatch.setattr(personalization_service, "KNOWLEDGE_DIR", knowledge_dir)
    monkeypatch.setattr(personalization_service, "PORTFOLIO_PATH", portfolio_path)
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", findings_path)
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", snapshots_path)
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", journal_path)
    return profile_path, portfolio_path, knowledge_dir


@pytest.mark.asyncio
async def test_monitoring_finds_newly_eligible_recommendation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path, portfolio_path, knowledge_dir = _patch_monitoring_environment(monkeypatch, tmp_path / "new_eligible")
    _write_profile(profile_path, preferred_assets=["SPY"], disallowed_assets=[])
    _write_portfolio(portfolio_path, positions=[])

    async def _fake_known_tickers(session):
        return {"SPY", "QQQ"}

    async def _fake_load(*args, **kwargs):
        return {
            "SPY": _df("2023-01-02", 260, 100.0, 0.30),
            "QQQ": _df("2023-01-02", 260, 100.0, 0.05),
        }

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)
    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    baseline = await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())
    assert baseline.current_snapshot.best_eligible_asset is None

    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy", "core"],
        aliases=["spy thesis"],
        body="SPY is acceptable as a core holding.",
    )

    rerun = await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())
    assert any(f.finding_type == "newly_eligible_recommendation" and f.entity == "SPY" for f in rerun.findings)


@pytest.mark.asyncio
async def test_monitoring_flags_holding_rule_violation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path, portfolio_path, knowledge_dir = _patch_monitoring_environment(monkeypatch, tmp_path / "rule_violation")
    _write_profile(profile_path, preferred_assets=["SPY"], disallowed_assets=["QQQ"])
    _write_portfolio(
        portfolio_path,
        positions=[
            {
                "ticker": "QQQ",
                "quantity": 5,
                "avg_cost": 400,
                "asset_type": "ETF",
                "strategy_bucket": "growth",
                "max_position_size_pct": 0.5,
            }
        ],
    )
    _write_doc(
        knowledge_dir / "qqq.md",
        title="QQQ Thesis",
        doc_type="investment_thesis",
        tags=["qqq"],
        aliases=["qqq thesis"],
        body="QQQ can improve upside capture but should obey the profile.",
    )

    async def _fake_known_tickers(session):
        return {"QQQ", "SPY"}

    async def _fake_load(*args, **kwargs):
        return {
            "QQQ": _df("2023-01-02", 260, 100.0, 0.20),
            "SPY": _df("2023-01-02", 260, 100.0, 0.05),
        }

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)
    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    response = await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())
    assert any(f.finding_type == "holding_rule_violation" and f.entity == "QQQ" for f in response.findings)


@pytest.mark.asyncio
async def test_monitoring_no_change_path_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path, portfolio_path, knowledge_dir = _patch_monitoring_environment(monkeypatch, tmp_path / "no_change")
    _write_profile(profile_path, preferred_assets=["SPY"], disallowed_assets=[])
    _write_portfolio(portfolio_path, positions=[])
    _write_doc(
        knowledge_dir / "spy.md",
        title="SPY Thesis",
        doc_type="investment_thesis",
        tags=["spy"],
        aliases=["spy thesis"],
        body="SPY is acceptable as a core holding.",
    )

    async def _fake_known_tickers(session):
        return {"SPY"}

    async def _fake_load(*args, **kwargs):
        return {"SPY": _df("2023-01-02", 260, 100.0, 0.20)}

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)
    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())
    second = await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())

    assert second.findings == []
    assert "No material monitoring changes" in second.summary


@pytest.mark.asyncio
async def test_monitoring_missing_data_path_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    profile_path, portfolio_path, _ = _patch_monitoring_environment(monkeypatch, tmp_path / "missing_data")
    _write_profile(profile_path, preferred_assets=["SPY"], disallowed_assets=[])
    _write_portfolio(
        portfolio_path,
        positions=[
            {
                "ticker": "SPY",
                "quantity": 4,
                "avg_cost": 420,
                "asset_type": "ETF",
                "strategy_bucket": "core",
                "max_position_size_pct": 0.6,
            }
        ],
    )

    async def _fake_known_tickers(session):
        return {"SPY"}

    async def _fake_load(*args, **kwargs):
        return {}

    monkeypatch.setattr(copilot_service, "_get_known_tickers", _fake_known_tickers)
    monkeypatch.setattr(copilot_service, "load_ohlcv_multi", _fake_load)

    response = await monitoring_service.run_monitoring_checks(None, MonitoringRunRequest())
    assert any(f.finding_type == "missing_data" and f.entity == "SPY" for f in response.findings)
    assert any("No local price data" in warning for warning in response.warnings)


def test_snapshot_comparison_logic_detects_changed_asset_and_warnings() -> None:
    previous = MonitoringSnapshotRecord(
        snapshot_id="prev",
        timestamp="2026-04-13T10:00:00+00:00",
        best_eligible_asset="SPY",
        best_eligible_status="eligible_new_position",
        key_warnings=["old warning"],
    )
    current = MonitoringSnapshotRecord(
        snapshot_id="curr",
        timestamp="2026-04-14T10:00:00+00:00",
        best_eligible_asset="QQQ",
        best_eligible_status="eligible_add_to_existing",
        key_warnings=["new warning"],
    )

    comparison = monitoring_service.build_snapshot_comparison(previous, current)

    assert comparison.has_prior_snapshot is True
    assert comparison.best_eligible_asset_changed is True
    assert comparison.recommendation_status_changed is True
    assert comparison.new_key_warnings == ["new warning"]
    assert comparison.cleared_key_warnings == ["old warning"]


@pytest.mark.asyncio
async def test_chat_monitoring_query_returns_monitoring_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_run(session, request):
        return MonitoringRunResponse(
            summary="1 monitoring finding surfaced.",
            current_snapshot=MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-14T10:00:00+00:00",
                top_deterministic_result="SPY",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                best_eligible_action="open_new_position",
            ),
            comparison=SnapshotComparison(
                has_prior_snapshot=True,
                previous_best_eligible_asset="QQQ",
                current_best_eligible_asset="SPY",
                best_eligible_asset_changed=True,
                previous_recommendation_status="eligible_add_to_existing",
                current_recommendation_status="eligible_new_position",
                recommendation_status_changed=True,
                new_key_warnings=["New warning"],
                cleared_key_warnings=[],
            ),
            findings=[
                MonitoringFinding(
                    finding_id="finding-1",
                    timestamp="2026-04-14T10:00:00+00:00",
                    finding_type="best_eligible_asset_changed",
                    severity="warning",
                    entity="SPY",
                    headline="Best eligible asset changed",
                    summary="Changed from QQQ to SPY.",
                    why_it_matters="Leadership changed.",
                    suggested_next_action="Review the new leader.",
                    source_snapshot_ref="snap-1",
                )
            ],
            warnings=[],
        )

    monkeypatch.setattr(monitoring_service, "run_monitoring_checks", _fake_run)

    response = await copilot_service.copilot_chat_tool(
        AsyncMock(),
        CopilotChatRequest(user_query="What changed since the last check?"),
    )

    assert response.detected_intent == "monitoring_check"
    assert response.tools_used == ["run_monitoring_checks"]
    assert response.answer.headline == "Monitoring check complete"
    assert response.recommendation_status == "eligible_new_position"
