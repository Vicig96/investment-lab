from __future__ import annotations

from pathlib import Path

import pytest

import app.services.copilot as copilot_service
import app.services.copilot_forward_validation_pilot as pilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_paper_portfolio_nav as paper_nav_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_forward_validation_pilot import (
    ForwardValidationPilotRequest,
    ForwardValidationPilotResponse,
)
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_monitoring import MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_paper_portfolio_nav import PaperPortfolioNavResponse


def _seed_decision(
    *,
    user_query: str,
    timestamp: str,
    top_result: str | None = None,
    final_entity: str | None = None,
    recommendation_status: str | None = None,
    action_taken: str | None = None,
    review_date: str | None = None,
) -> None:
    record = journal_service.create_decision(
        DecisionCreateRequest(
            user_query=user_query,
            detected_intent="asset_ranking",
            top_deterministic_result=top_result,
            final_recommendation=(
                JournalRecommendationSnapshot(recommended_entity=final_entity)
                if final_entity is not None
                else None
            ),
            recommendation_status=recommendation_status,
            action_taken=action_taken,
            review_date=review_date,
        )
    )
    record.timestamp = timestamp
    journal_service.save_decision(record)


def _setup_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")


def _append_jsonl(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(row.model_dump_json() + "\n")


def _paper_nav_response(
    *,
    cohort_key: str,
    cohort_label: str,
    supported_positions: int,
    unsupported_positions: int,
    total_return: float | None,
    benchmark_supported: bool = False,
    benchmark_return: float | None = None,
    exit_delta: float | None = None,
    active_positions_count: int = 0,
    exited_positions_count: int = 0,
    unsupported_exit_count: int = 0,
    exit_reason_distribution: list[dict] | None = None,
) -> PaperPortfolioNavResponse:
    return PaperPortfolioNavResponse(
        generated_at="2026-04-14T10:00:00+00:00",
        date_range={"start": "2026-04-01", "end": "2026-04-14", "label": "2026-04-01 to 2026-04-14"},
        cohort_definition={"cohort_key": cohort_key, "label": cohort_label},
        assumptions={
            "entry_rule": "entry",
            "allocation_rule": "allocation",
            "cash_ledger_rule": "cash",
            "mark_to_market_rule": "mark",
            "duplicate_entry_rule": "duplicate",
            "lifecycle_rule": "lifecycle",
            "exit_policy_rule": "exit",
            "benchmark_rule": "benchmark",
        },
        initial_capital=10000.0,
        ending_value=(10000.0 * (1 + (total_return or 0.0) / 100.0)),
        cash_remaining=1000.0 if exited_positions_count else 0.0,
        active_positions_count=active_positions_count,
        exited_positions_count=exited_positions_count,
        unsupported_exit_count=unsupported_exit_count,
        exit_reason_distribution=exit_reason_distribution or [],
        active_positions=[],
        closed_or_inactive_positions=[],
        hold_exit_policy_summary={
            "applied": exit_delta is not None,
            "policy_version": "paper_exit_hold_policy_v1" if exit_delta is not None else "hold_only_v0",
            "active_positions_count": active_positions_count,
            "exited_positions_count": exited_positions_count,
            "unsupported_exit_count": unsupported_exit_count,
            "exit_reason_distribution": exit_reason_distribution or [],
            "notes": [],
        },
        nav_summary={
            "total_positions_entered": supported_positions,
            "supported_positions": supported_positions,
            "unsupported_positions": unsupported_positions,
            "total_portfolio_simple_return_pct": total_return,
            "max_paper_drawdown_pct": 0.0 if total_return is not None else None,
            "average_position_simple_return_pct": total_return,
            "median_position_simple_return_pct": total_return,
            "positive_positions_count": supported_positions if (total_return or 0) > 0 else 0,
            "negative_positions_count": supported_positions if (total_return or 0) < 0 else 0,
        },
        nav_points=[],
        position_summaries=[],
        benchmark_summary={
            "benchmark_ticker": "SPY",
            "supported": benchmark_supported,
            "assumed_entry_timestamp": None,
            "assumed_entry_price": None,
            "latest_mark_timestamp": None,
            "latest_mark_price": None,
            "simple_return_pct": benchmark_return,
            "ending_value": None,
            "support_notes": [],
        },
        comparison_summary={
            "benchmark_comparison_supported": benchmark_supported,
            "benchmark_ticker": "SPY",
            "portfolio_simple_return_pct": total_return,
            "benchmark_simple_return_pct": benchmark_return,
            "hold_to_window_end_ending_value": 10100.0 if exit_delta is not None else None,
            "exit_policy_ending_value_difference": exit_delta,
            "interpretation": "comparison",
            "notes": [],
        },
        warnings=[],
        missing_data_notes=[],
    )


@pytest.mark.asyncio
async def test_forward_pilot_summary_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept SPY", timestamp="2026-04-05T09:00:00+00:00", top_result="SPY", final_entity="SPY", recommendation_status="eligible_new_position", action_taken="accepted", review_date="2026-04-12")
    _seed_decision(user_query="Paper QQQ", timestamp="2026-04-06T09:00:00+00:00", top_result="QQQ", final_entity="QQQ", recommendation_status="eligible", action_taken="paper_only")
    _seed_decision(user_query="Reject TQQQ", timestamp="2026-04-07T09:00:00+00:00", top_result="TQQQ", recommendation_status="rejected_by_profile", action_taken="rejected")
    _append_jsonl(
        monitoring_service.FINDINGS_PATH,
        [
            MonitoringFinding(
                finding_id="f1",
                timestamp="2026-04-08T10:00:00+00:00",
                finding_type="holding_drawdown_breach",
                severity="warning",
                entity="SPY",
                headline="Warning",
                summary="warning",
                why_it_matters="matters",
                suggested_next_action="review",
                source_snapshot_ref="s1",
            )
        ],
    )
    _append_jsonl(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(snapshot_id="s1", timestamp="2026-04-08T10:00:00+00:00", best_eligible_asset="SPY", key_warnings=["Missing thesis"]),
            MonitoringSnapshotRecord(snapshot_id="s2", timestamp="2026-04-12T10:00:00+00:00", best_eligible_asset="QQQ", key_warnings=["Missing thesis"]),
        ],
    )

    async def _fake_paper_nav(session, request):
        if request.cohort_definition == "accepted":
            return _paper_nav_response(cohort_key="accepted", cohort_label="Accepted decisions", supported_positions=2, unsupported_positions=0, total_return=5.0)
        if request.cohort_definition == "paper_only":
            return _paper_nav_response(cohort_key="paper_only", cohort_label="Paper-only decisions", supported_positions=2, unsupported_positions=0, total_return=2.0)
        if request.apply_exit_policy:
            return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Accepted plus paper-only decisions", supported_positions=3, unsupported_positions=0, total_return=4.0, benchmark_supported=True, benchmark_return=3.0, exit_delta=150.0, active_positions_count=1, exited_positions_count=2, exit_reason_distribution=[{"item": "exited_on_negative_signal", "count": 1}])
        return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Accepted plus paper-only decisions", supported_positions=3, unsupported_positions=0, total_return=2.5)

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_paper_nav)

    response = await pilot_service.generate_forward_validation_pilot(None, ForwardValidationPilotRequest(date_from="2026-04-01", date_to="2026-04-14"))

    assert response.review_protocol.total_decisions_in_period == 3
    assert response.review_protocol.accepted_count == 1
    assert response.monitoring_summary.findings_generated == 1
    assert response.paper_portfolio_summary.exit_policy_simple_return_pct == 4.0


@pytest.mark.asyncio
async def test_weekly_review_summary_generation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    async def _fake_paper_nav(session, request):
        return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Pilot", supported_positions=0, unsupported_positions=0, total_return=None)

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_paper_nav)

    response = await pilot_service.generate_forward_validation_pilot(
        None,
        ForwardValidationPilotRequest(date_from="2026-04-01", date_to="2026-04-30", review_cadence="weekly"),
    )

    assert response.pilot_window.pilot_start == "2026-04-01"
    assert response.pilot_window.pilot_end == "2026-04-30"
    assert response.review_protocol.review_cadence == "weekly"


@pytest.mark.asyncio
async def test_accepted_vs_paper_only_and_hold_vs_exit_policy_when_supported(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)
    _seed_decision(user_query="Accept SPY", timestamp="2026-04-05T09:00:00+00:00", top_result="SPY", recommendation_status="eligible_new_position", action_taken="accepted")
    _seed_decision(user_query="Paper QQQ", timestamp="2026-04-06T09:00:00+00:00", top_result="QQQ", recommendation_status="eligible", action_taken="paper_only")

    async def _fake_paper_nav(session, request):
        if request.cohort_definition == "accepted":
            return _paper_nav_response(cohort_key="accepted", cohort_label="Accepted decisions", supported_positions=2, unsupported_positions=0, total_return=6.0)
        if request.cohort_definition == "paper_only":
            return _paper_nav_response(cohort_key="paper_only", cohort_label="Paper-only decisions", supported_positions=2, unsupported_positions=0, total_return=1.0)
        if request.apply_exit_policy:
            return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Combined", supported_positions=3, unsupported_positions=0, total_return=4.0, benchmark_supported=True, benchmark_return=2.0, exit_delta=200.0)
        return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Combined", supported_positions=3, unsupported_positions=0, total_return=2.0)

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_paper_nav)

    response = await pilot_service.generate_forward_validation_pilot(None, ForwardValidationPilotRequest())

    assert response.cohort_comparison_summary.accepted_vs_paper_only.supported is True
    assert "Accepted ideas looked stronger" in response.cohort_comparison_summary.accepted_vs_paper_only.interpretation
    assert response.cohort_comparison_summary.hold_only_vs_exit_policy.supported is True
    assert "Exit policy increased" in response.cohort_comparison_summary.hold_only_vs_exit_policy.interpretation


@pytest.mark.asyncio
async def test_missing_data_and_small_sample_behavior_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    async def _fake_paper_nav(session, request):
        return _paper_nav_response(cohort_key=request.cohort_definition, cohort_label="Pilot", supported_positions=0, unsupported_positions=1, total_return=None)

    monkeypatch.setattr(paper_nav_service, "build_paper_portfolio_nav", _fake_paper_nav)

    response = await pilot_service.generate_forward_validation_pilot(None, ForwardValidationPilotRequest())

    assert response.review_protocol.total_decisions_in_period == 0
    assert response.cohort_comparison_summary.accepted_vs_paper_only.supported is False
    assert any("No pilot decisions were available" in note for note in response.missing_data_notes)


@pytest.mark.asyncio
async def test_forward_pilot_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _fake_generate(session, request):
        return ForwardValidationPilotResponse(
            generated_at="2026-04-14T10:00:00+00:00",
            pilot_window={"pilot_start": "2026-04-01", "pilot_end": "2026-04-14", "label": "2026-04-01 to 2026-04-14"},
            review_protocol={
                "pilot_start": "2026-04-01",
                "pilot_end": "2026-04-14",
                "review_cadence": "weekly",
                "total_decisions_in_period": 5,
                "accepted_count": 2,
                "rejected_count": 1,
                "watchlist_count": 1,
                "paper_only_count": 1,
                "eligible_count": 3,
                "blocked_count": 2,
                "findings_generated": 4,
                "findings_by_severity": [],
                "accepted_vs_paper_only_supported": True,
                "hold_only_vs_exit_policy_supported": True,
                "benchmark_comparison_supported": True,
            },
            operational_summary={
                "total_decisions": 5,
                "reviewed_decisions": 2,
                "still_actionable_count": 2,
                "deteriorated_count": 1,
                "decisions_with_later_findings": 2,
                "snapshots_in_period": 2,
                "sample_size_note": None,
            },
            decision_summary={"decisions_by_action_taken": [], "decisions_by_recommendation_status": [], "top_blocked_reasons": []},
            monitoring_summary={"findings_generated": 4, "findings_by_severity": [], "findings_by_type": [], "snapshots_in_period": 2, "top_warning_patterns": []},
            paper_portfolio_summary={
                "cohort_definition": "accepted_plus_paper_only",
                "supported_positions": 3,
                "unsupported_positions": 0,
                "hold_only_simple_return_pct": 2.0,
                "exit_policy_simple_return_pct": 3.0,
                "exit_policy_ending_value_difference": 100.0,
                "active_positions_count": 1,
                "exited_positions_count": 2,
                "unsupported_exit_count": 0,
                "exit_reason_distribution": [],
            },
            cohort_comparison_summary={
                "accepted_vs_paper_only": {
                    "supported": True,
                    "interpretation": "Accepted ideas looked stronger than paper-only ideas in this pilot window on a simple local paper basis.",
                    "left_label": "Accepted",
                    "right_label": "Paper only",
                    "left_value": 4.0,
                    "right_value": 2.0,
                    "notes": [],
                },
                "hold_only_vs_exit_policy": {
                    "supported": True,
                    "interpretation": "Exit policy increased paper outcome versus hold-only in this pilot window.",
                    "left_label": "Hold only",
                    "right_label": "Exit policy v1",
                    "left_value": 2.0,
                    "right_value": 3.0,
                    "notes": [],
                },
            },
            benchmark_summary={
                "supported": True,
                "benchmark_ticker": "SPY",
                "simple_return_pct": 2.0,
                "interpretation": "Benchmark comparison is only directional and uses the same broad local paper window.",
                "notes": [],
            },
            notable_patterns=["pattern"],
            next_review_actions=["Review critical monitoring findings before the next weekly pilot check."],
            warnings=[],
            missing_data_notes=[],
        )

    monkeypatch.setattr(pilot_service, "generate_forward_validation_pilot", _fake_generate)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="How is the forward pilot going this week?"),
    )

    assert response.detected_intent == "forward_validation_pilot"
    assert response.tools_used == ["run_forward_validation_pilot"]
    assert response.answer.headline == "Forward validation pilot ready"
