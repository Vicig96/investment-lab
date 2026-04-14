from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_outcomes as outcome_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_monitoring import MonitoringAssetState, MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_outcomes import OutcomeReviewRequest, OutcomeReviewResponse


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
    action_taken: str | None = None,
    review_date: str | None = None,
    outcome_notes: str | None = None,
):
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
            outcome_notes=outcome_notes,
        )
    )
    record.timestamp = timestamp
    return journal_service.save_decision(record)


def _append_findings(path: Path, findings: list[MonitoringFinding]) -> None:
    monitoring_service._append_jsonl(path, findings)


def _append_snapshots(path: Path, snapshots: list[MonitoringSnapshotRecord]) -> None:
    monitoring_service._append_jsonl(path, snapshots)


def test_outcome_review_over_accepted_decisions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(outcome_service, "datetime", _FixedDateTime)

    _seed_decision(
        user_query="Rank SPY",
        timestamp="2026-04-10T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
        review_date="2026-04-12",
    )

    _append_findings(
        monitoring_service.FINDINGS_PATH,
        [
            MonitoringFinding(
                finding_id="finding-1",
                timestamp="2026-04-12T10:00:00+00:00",
                finding_type="portfolio_concentration_warning",
                severity="warning",
                entity="SPY",
                headline="Concentration warning",
                summary="SPY concentration rose.",
                why_it_matters="Sizing may need review.",
                suggested_next_action="Review sizing.",
                source_snapshot_ref="snap-2",
            )
        ],
    )
    _append_snapshots(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-11T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    )
                ],
            ),
            MonitoringSnapshotRecord(
                snapshot_id="snap-2",
                timestamp="2026-04-13T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_add_to_existing",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_add_to_existing",
                    )
                ],
            ),
        ],
    )

    review = outcome_service.review_outcomes(OutcomeReviewRequest(action_taken="accepted"))

    assert review.summary.total_decisions_reviewed == 1
    assert review.summary.reviewed_decisions == 1
    assert review.summary.accepted_decisions == 1
    assert review.summary.decisions_with_later_findings == 1
    assert review.summary.consistent_recommendations == 1
    entry = review.entries[0]
    assert entry.days_elapsed == 4
    assert entry.current_relevance_status == "still_best_eligible"
    assert entry.later_recommendation_consistency == "consistent"
    assert entry.later_monitoring_signals == ["portfolio_concentration_warning: Concentration warning"]


def test_watchlist_later_becomes_actionable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(outcome_service, "datetime", _FixedDateTime)

    _seed_decision(
        user_query="Watch SPY",
        timestamp="2026-04-01T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="unsupported_by_knowledge",
        action_taken="watchlist",
    )
    _seed_decision(
        user_query="Rank SPY again",
        timestamp="2026-04-08T09:00:00+00:00",
        top_result="SPY",
        final_entity="SPY",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )
    _append_snapshots(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-09T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    )
                ],
            )
        ],
    )

    review = outcome_service.review_outcomes(OutcomeReviewRequest(action_taken="watchlist"))

    assert review.summary.total_decisions_reviewed == 1
    assert review.summary.watchlist_or_paper_only_decisions == 1
    assert review.summary.watchlist_or_paper_only_later_actionable == 1
    assert review.entries[0].watchlist_transition_status == "later_became_actionable"


def test_outcome_review_detects_changed_later_recommendation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(outcome_service, "datetime", _FixedDateTime)

    _seed_decision(
        user_query="Rank QQQ",
        timestamp="2026-04-05T09:00:00+00:00",
        top_result="QQQ",
        final_entity="QQQ",
        recommendation_status="eligible_new_position",
        action_taken="accepted",
    )
    _append_findings(
        monitoring_service.FINDINGS_PATH,
        [
            MonitoringFinding(
                finding_id="finding-1",
                timestamp="2026-04-09T10:00:00+00:00",
                finding_type="holding_rule_violation",
                severity="critical",
                entity="QQQ",
                headline="Rule violation",
                summary="QQQ no longer fits the profile.",
                why_it_matters="The holding conflicts with current rules.",
                suggested_next_action="Review QQQ immediately.",
                source_snapshot_ref="snap-2",
            )
        ],
    )
    _append_snapshots(
        monitoring_service.SNAPSHOTS_PATH,
        [
            MonitoringSnapshotRecord(
                snapshot_id="snap-1",
                timestamp="2026-04-06T10:00:00+00:00",
                best_eligible_asset="QQQ",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="QQQ",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    )
                ],
            ),
            MonitoringSnapshotRecord(
                snapshot_id="snap-2",
                timestamp="2026-04-10T10:00:00+00:00",
                best_eligible_asset="SPY",
                best_eligible_status="eligible_new_position",
                monitored_assets=[
                    MonitoringAssetState(
                        ticker="SPY",
                        rank=1,
                        recommendation_status="eligible_new_position",
                    )
                ],
            ),
        ],
    )

    review = outcome_service.review_outcomes(OutcomeReviewRequest(action_taken="accepted"))

    assert review.summary.consistent_recommendations == 0
    assert review.summary.inconsistent_or_mixed_recommendations == 1
    entry = review.entries[0]
    assert entry.later_recommendation_consistency == "mixed"
    assert entry.current_relevance_status == "later_deteriorated"
    assert entry.forward_snapshot_comparison is not None
    assert entry.forward_snapshot_comparison.first_later_best_eligible_asset == "QQQ"
    assert entry.forward_snapshot_comparison.latest_best_eligible_asset == "SPY"


def test_outcome_review_missing_data_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")
    monkeypatch.setattr(outcome_service, "datetime", _FixedDateTime)

    _seed_decision(
        user_query="Paper trade GLD",
        timestamp="2026-04-12T09:00:00+00:00",
        top_result="GLD",
        final_entity="GLD",
        recommendation_status="eligible",
        action_taken="paper_only",
    )

    review = outcome_service.review_outcomes(OutcomeReviewRequest(action_taken="paper_only"))

    assert review.summary.total_decisions_reviewed == 1
    assert any("No monitoring snapshots were available" in warning for warning in review.warnings)
    assert any("No monitoring findings were available" in warning for warning in review.warnings)
    entry = review.entries[0]
    assert entry.current_relevance_status == "no_later_monitoring_data"
    assert entry.later_recommendation_consistency == "insufficient_data"
    assert entry.watchlist_transition_status == "insufficient_data"
    assert any("No later monitoring snapshots were available" in note for note in entry.missing_data_notes)


@pytest.mark.asyncio
async def test_outcome_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_review(request):
        return OutcomeReviewResponse(
            generated_at="2026-04-14T12:00:00+00:00",
            date_range={"start": "2026-03-15", "end": "2026-04-14", "label": "2026-03-15 to 2026-04-14"},
            summary={
                "total_decisions_reviewed": 3,
                "reviewed_decisions": 1,
                "accepted_decisions": 2,
                "watchlist_or_paper_only_decisions": 1,
                "watchlist_or_paper_only_later_actionable": 1,
                "decisions_with_later_findings": 2,
                "consistent_recommendations": 1,
                "inconsistent_or_mixed_recommendations": 1,
            },
            entries=[
                {
                    "decision_id": "decision-1",
                    "entity": "SPY",
                    "decision_timestamp": "2026-04-01T09:00:00+00:00",
                    "days_elapsed": 13,
                    "action_taken": "accepted",
                    "was_reviewed": True,
                    "current_relevance_status": "still_best_eligible",
                    "later_monitoring_signals": ["best_eligible_asset_changed: Changed"],
                    "later_recommendation_consistency": "consistent",
                    "watchlist_transition_status": "not_watchlist_or_paper_only",
                    "warnings": [],
                    "missing_data_notes": [],
                }
            ],
            warnings=["Outcome attribution is operational only."],
        )

    monkeypatch.setattr(outcome_service, "review_outcomes", _fake_review)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="What happened after my accepted decisions in the last 30 days?"),
    )

    assert response.detected_intent == "outcome_review"
    assert response.tools_used == ["review_outcomes"]
    assert response.answer.headline == "Outcome review ready"
    assert response.supporting_data["outcomes"]["summary"]["accepted_decisions"] == 2
