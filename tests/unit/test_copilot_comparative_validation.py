from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.copilot as copilot_service
import app.services.copilot_comparative_validation as comparative_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_outcomes as outcome_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_monitoring import MonitoringAssetState, MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_comparative_validation import ComparativeValidationRequest, ComparativeValidationResponse


class _FixedDateTime(datetime):
    @classmethod
    def now(cls, tz=None):
        current = cls(2026, 4, 14, 12, 0, 0, tzinfo=timezone.utc)
        if tz is None:
            return current.replace(tzinfo=None)
        return current.astimezone(tz)


def _seed_decision(
    *,
    user_query: str,
    timestamp: str,
    top_result: str | None = None,
    final_entity: str | None = None,
    recommendation_status: str | None = None,
    recommended_action_type: str | None = None,
    action_taken: str | None = None,
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
            recommended_action_type=recommended_action_type,
            action_taken=action_taken,
        )
    )
    record.timestamp = timestamp
    journal_service.save_decision(record)


def _append_findings(path: Path, findings: list[MonitoringFinding]) -> None:
    monitoring_service._append_jsonl(path, findings)


def _append_snapshots(path: Path, snapshots: list[MonitoringSnapshotRecord]) -> None:
    monitoring_service._append_jsonl(path, snapshots)


def _setup_paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(outcome_service, "datetime", _FixedDateTime)
    monkeypatch.setattr(comparative_service, "datetime", _FixedDateTime)


def test_cohort_comparison_over_journal_and_outcome_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    _seed_decision(
        user_query="Rank SPY",
        timestamp="2026-04-02T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        recommended_action_type="open_new_position",
        action_taken="accepted",
    )
    _seed_decision(
        user_query="Rank QQQ",
        timestamp="2026-04-03T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="rejected_by_profile",
        recommended_action_type="avoid",
        action_taken="rejected",
    )
    _append_findings(
        monitoring_service.FINDINGS_PATH,
        [
            MonitoringFinding(
                finding_id="finding-1",
                timestamp="2026-04-05T10:00:00+00:00",
                finding_type="holding_rule_violation",
                severity="critical",
                entity="QQQ",
                headline="QQQ rule violation",
                summary="QQQ later conflicted with the profile.",
                why_it_matters="The rejected idea later deteriorated.",
                suggested_next_action="Leave QQQ blocked.",
                source_snapshot_ref="snap-2",
            )
        ],
    )
    _append_snapshots(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-04T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    ),
                    MonitoringAssetState(
                        ticker="QQQ",
                        rank=2,
                        recommendation_status="rejected_by_profile",
                    ),
                ],
            ),
            MonitoringSnapshotRecord(
                snapshot_id="snap-2",
                timestamp="2026-04-06T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_add_to_existing",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_add_to_existing",
                    ),
                ],
            ),
        ],
    )

    response = comparative_service.generate_comparative_validation(ComparativeValidationRequest())

    assert len(response.comparison_groups) == 6
    accepted = next(item for item in response.cohort_summaries if item.cohort_key == "accepted")
    rejected = next(item for item in response.cohort_summaries if item.cohort_key == "rejected")
    assert accepted.total_decisions == 1
    assert accepted.proportion_still_best_eligible == 1.0
    assert accepted.proportion_later_deteriorated == 0.0
    assert rejected.proportion_later_deteriorated == 1.0
    assert rejected.proportion_later_receiving_negative_findings == 1.0


def test_accepted_vs_rejected_comparison_is_directional(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    _seed_decision(
        user_query="Accept SPY",
        timestamp="2026-04-01T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )
    _seed_decision(
        user_query="Reject QQQ",
        timestamp="2026-04-01T10:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="rejected_by_profile",
        action_taken="rejected",
    )
    _append_findings(
        monitoring_service.FINDINGS_PATH,
        [
            MonitoringFinding(
                finding_id="finding-1",
                timestamp="2026-04-03T10:00:00+00:00",
                finding_type="holding_drawdown_breach",
                severity="critical",
                entity="QQQ",
                headline="QQQ drawdown breach",
                summary="QQQ later breached drawdown limits.",
                why_it_matters="The rejected idea later deteriorated.",
                suggested_next_action="Keep avoiding QQQ.",
                source_snapshot_ref="snap-2",
            )
        ],
    )
    _append_snapshots(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-02T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(ticker="SPY", rank=1, recommendation_status="eligible_new_position"),
                    MonitoringAssetState(ticker="QQQ", rank=2, recommendation_status="rejected_by_profile"),
                ],
            ),
            MonitoringSnapshotRecord(
                snapshot_id="snap-2",
                timestamp="2026-04-04T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(ticker="SPY", rank=1, recommendation_status="eligible_new_position"),
                ],
            ),
        ],
    )

    response = comparative_service.generate_comparative_validation(ComparativeValidationRequest())

    consistency = next(item for item in response.consistency_summary if item.comparison_key == "accepted_vs_rejected")
    deterioration = next(item for item in response.deterioration_summary if item.comparison_key == "accepted_vs_rejected")
    signals = next(item for item in response.later_signal_summary if item.comparison_key == "accepted_vs_rejected")

    assert consistency.left_rate == 1.0
    assert consistency.right_rate == 0.0
    assert "Accepted" in consistency.interpretation
    assert deterioration.left_rate == 0.0
    assert deterioration.right_rate == 1.0
    assert signals.left_negative_findings_rate == 0.0
    assert signals.right_negative_findings_rate == 1.0


def test_watchlist_transition_comparison(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    _seed_decision(
        user_query="Watch SPY",
        timestamp="2026-04-01T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="unsupported_by_knowledge",
        action_taken="watchlist",
    )
    _seed_decision(
        user_query="Paper GLD",
        timestamp="2026-04-01T10:00:00+00:00",
        top_result="GLD",
        final_entity="GLD",
        recommendation_status="eligible",
        action_taken="paper_only",
    )
    _seed_decision(
        user_query="Rank SPY again",
        timestamp="2026-04-05T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )

    response = comparative_service.generate_comparative_validation(ComparativeValidationRequest())

    transition = next(item for item in response.watchlist_transition_summary if item.comparison_key == "watchlist_vs_paper_only")
    assert transition.left_rate == 1.0
    assert transition.right_rate == 0.0
    assert "Watchlist" in transition.interpretation


def test_missing_data_and_small_sample_are_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_paths(tmp_path, monkeypatch)

    _seed_decision(
        user_query="Accept TLT",
        timestamp="2026-04-12T09:00:00+00:00",
        top_result="TLT",
        final_entity="TLT",
        recommendation_status="eligible",
        action_taken="accepted",
    )

    response = comparative_service.generate_comparative_validation(ComparativeValidationRequest())

    rejected = next(item for item in response.cohort_summaries if item.cohort_key == "rejected")
    accepted_vs_rejected = next(item for item in response.consistency_summary if item.comparison_key == "accepted_vs_rejected")
    assert any("No local decisions were available" in note for note in rejected.insufficient_data_markers)
    assert accepted_vs_rejected.supported is False
    assert any("No monitoring snapshots were available" in warning for warning in response.warnings)
    assert response.missing_data_notes


@pytest.mark.asyncio
async def test_comparison_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_generate(request):
        return ComparativeValidationResponse(
            generated_at="2026-04-14T12:00:00+00:00",
            date_range={"start": "2026-03-15", "end": "2026-04-14", "label": "2026-03-15 to 2026-04-14"},
            comparison_groups=[
                {
                    "comparison_key": "accepted_vs_rejected",
                    "left_cohort": "accepted",
                    "right_cohort": "rejected",
                    "left_label": "Accepted",
                    "right_label": "Rejected",
                }
            ],
            cohort_summaries=[
                {
                    "cohort_key": "accepted",
                    "label": "Accepted",
                    "total_decisions": 3,
                    "later_recommendation_consistency_distribution": [],
                    "current_relevance_status_distribution": [],
                    "later_monitoring_signals_frequency": [],
                    "watchlist_transition_status_distribution": [],
                    "proportion_operationally_consistent": 0.67,
                    "proportion_still_actionable": 0.67,
                    "proportion_later_deteriorated": 0.0,
                    "proportion_still_best_eligible": 0.33,
                    "proportion_superseded_or_not_current": 0.0,
                    "proportion_later_receiving_negative_findings": 0.0,
                    "insufficient_data_markers": [],
                }
            ],
            consistency_summary=[
                {
                    "comparison_key": "accepted_vs_rejected",
                    "left_cohort": "accepted",
                    "right_cohort": "rejected",
                    "left_total": 3,
                    "right_total": 2,
                    "left_rate": 0.67,
                    "right_rate": 0.0,
                    "interpretation": "Accepted were operationally more consistent later in this local sample.",
                    "supported": True,
                    "notes": [],
                }
            ],
            deterioration_summary=[],
            later_signal_summary=[],
            watchlist_transition_summary=[],
            notable_patterns=["Accepted most often remained actionable later."],
            warnings=["Comparative validation is operational only."],
            missing_data_notes=[],
        )

    monkeypatch.setattr(comparative_service, "generate_comparative_validation", _fake_generate)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="How do accepted ideas compare with rejected ones?"),
    )

    assert response.detected_intent == "comparative_validation"
    assert response.tools_used == ["get_comparative_validation"]
    assert response.answer.headline == "Comparative validation ready"
    assert response.supporting_data["comparative_validation"]["comparison_groups"][0]["comparison_key"] == "accepted_vs_rejected"
