from __future__ import annotations

from pathlib import Path

import pytest

import app.services.copilot as copilot_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_scorecard as scorecard_service
from app.schemas.copilot import CopilotChatRequest
from app.schemas.copilot import ProfileConstraintApplied
from app.schemas.copilot_journal import DecisionCreateRequest, JournalRecommendationSnapshot
from app.schemas.copilot_monitoring import MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_scorecard import ScorecardRequest, ScorecardResponse


def _seed_decision(
    *,
    user_query: str,
    detected_intent: str = "asset_ranking",
    top_result: str | None = None,
    final_entity: str | None = None,
    recommendation_status: str | None = None,
    recommended_action_type: str | None = None,
    action_taken: str | None = None,
    outcome_notes: str | None = None,
):
    return journal_service.create_decision(
        DecisionCreateRequest(
            user_query=user_query,
            detected_intent=detected_intent,
            top_deterministic_result=top_result,
            final_recommendation=(
                JournalRecommendationSnapshot(recommended_entity=final_entity)
                if final_entity is not None
                else None
            ),
            recommendation_status=recommendation_status,
            recommended_action_type=recommended_action_type,
            action_taken=action_taken,
            outcome_notes=outcome_notes,
        )
    )


def test_scorecard_generation_over_journal_only_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal_path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", journal_path)
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")

    journal_service.save_decision(
        _seed_decision(
            user_query="Rank SPY, QQQ",
            top_result="QQQ",
            final_entity="SPY",
            recommendation_status="eligible_add_to_existing",
            recommended_action_type="add_to_existing_position",
            action_taken="accepted",
        )
    )
    blocked = _seed_decision(
        user_query="Rank TQQQ",
        top_result="TQQQ",
        final_entity=None,
        recommendation_status="rejected_by_profile",
        recommended_action_type="avoid",
        action_taken="rejected",
    )
    blocked.profile_constraints_applied = [
        ProfileConstraintApplied(
            constraint="recommended_asset_allowed",
            category="hard_block",
            detail="TQQQ is explicitly disallowed by the active investor profile.",
        )
    ]
    journal_service.save_decision(blocked)

    scorecard = scorecard_service.generate_scorecard(ScorecardRequest())

    assert scorecard.journal_summary.total_journal_decisions == 2
    assert scorecard.recommendation_summary.eligible_ideas_acted_on == 1
    assert scorecard.action_summary.decisions_by_action_taken[0].item in {"accepted", "rejected"}
    assert scorecard.constraint_summary.top_blocked_or_rejected_reasons[0].item == "TQQQ is explicitly disallowed by the active investor profile."
    assert scorecard.findings_summary.total_findings == 0


def test_scorecard_generation_with_findings_data(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    findings_path = tmp_path / "findings.jsonl"
    snapshots_path = tmp_path / "snapshots.jsonl"
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", findings_path)
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", snapshots_path)

    monitoring_service._append_jsonl(
        findings_path,
        [
            MonitoringFinding(
                finding_id="f1",
                timestamp="2026-04-10T10:00:00+00:00",
                finding_type="best_eligible_asset_changed",
                severity="warning",
                entity="SPY",
                headline="Changed",
                summary="Changed to SPY.",
                why_it_matters="Leadership changed.",
                suggested_next_action="Review SPY.",
                source_snapshot_ref="s1",
            ),
            MonitoringFinding(
                finding_id="f2",
                timestamp="2026-04-11T10:00:00+00:00",
                finding_type="holding_rule_violation",
                severity="critical",
                entity="QQQ",
                headline="Violation",
                summary="QQQ violated a rule.",
                why_it_matters="Conflict.",
                suggested_next_action="Review QQQ.",
                source_snapshot_ref="s2",
            ),
        ],
    )
    monitoring_service._append_jsonl(
        snapshots_path,
        [
            MonitoringSnapshotRecord(
                snapshot_id="s1",
                timestamp="2026-04-10T10:00:00+00:00",
                best_eligible_asset="QQQ",
                key_warnings=["Missing thesis support"],
            ),
            MonitoringSnapshotRecord(
                snapshot_id="s2",
                timestamp="2026-04-11T10:00:00+00:00",
                best_eligible_asset="SPY",
                key_warnings=["Missing thesis support"],
            ),
        ],
    )

    scorecard = scorecard_service.generate_scorecard(ScorecardRequest())

    assert scorecard.findings_summary.total_findings == 2
    assert scorecard.findings_summary.findings_by_severity[0].count == 1
    assert scorecard.monitoring_summary.snapshots_in_range == 2
    assert scorecard.monitoring_summary.best_eligible_asset_changes == 1
    assert scorecard.monitoring_summary.top_key_warning_patterns[0].item == "Missing thesis support"


def test_scorecard_date_range_filtering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    journal_path = tmp_path / "journal.jsonl"
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", journal_path)
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")

    older = _seed_decision(user_query="Old", top_result="SPY", recommendation_status="eligible", action_taken="accepted")
    newer = _seed_decision(user_query="New", top_result="QQQ", recommendation_status="eligible", action_taken="accepted")
    older.timestamp = "2026-03-01T09:00:00+00:00"
    newer.timestamp = "2026-04-10T09:00:00+00:00"
    journal_service.save_decision(older)
    journal_service.save_decision(newer)

    scorecard = scorecard_service.generate_scorecard(
        ScorecardRequest(date_from="2026-04-01", date_to="2026-04-30")
    )

    assert scorecard.journal_summary.total_journal_decisions == 1
    assert scorecard.journal_summary.top_deterministic_results[0].item == "QQQ"


def test_scorecard_missing_data_is_explicit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(journal_service, "JOURNAL_PATH", tmp_path / "journal.jsonl")
    monkeypatch.setattr(monitoring_service, "FINDINGS_PATH", tmp_path / "findings.jsonl")
    monkeypatch.setattr(monitoring_service, "SNAPSHOTS_PATH", tmp_path / "snapshots.jsonl")

    scorecard = scorecard_service.generate_scorecard(ScorecardRequest())

    assert any("No journal decisions were available" in note for note in scorecard.journal_summary.missing_data_notes)
    assert any("No monitoring findings were available" in note for note in scorecard.findings_summary.missing_data_notes)
    assert any("No monitoring snapshots were available" in note for note in scorecard.monitoring_summary.missing_data_notes)


@pytest.mark.asyncio
async def test_scorecard_chat_intent_and_response(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_generate(request):
        return ScorecardResponse(
            generated_at="2026-04-14T10:00:00+00:00",
            date_range={"start": "2026-03-16", "end": "2026-04-14", "label": "2026-03-16 to 2026-04-14"},
            journal_summary={"total_journal_decisions": 5, "top_deterministic_results": [], "top_final_recommendations": [], "missing_data_notes": []},
            recommendation_summary={"decisions_by_recommendation_status": [], "eligible_ideas_acted_on": 2, "missing_data_notes": []},
            action_summary={"decisions_by_action_taken": [], "decisions_by_recommended_action_type": [], "missing_data_notes": []},
            constraint_summary={"top_blocked_or_rejected_reasons": [], "missing_data_notes": []},
            findings_summary={"total_findings": 3, "findings_by_finding_type": [], "findings_by_severity": [], "most_frequent_entities": [], "missing_data_notes": []},
            monitoring_summary={"snapshots_in_range": 2, "best_eligible_asset_changes": 1, "watchlist_or_paper_only_later_actionable_count": 1, "top_key_warning_patterns": [], "missing_data_notes": []},
            notable_patterns=["Accepted actionable ideas: 2."],
            warnings=[],
        )

    monkeypatch.setattr(scorecard_service, "generate_scorecard", _fake_generate)

    response = await copilot_service.copilot_chat_tool(
        None,
        CopilotChatRequest(user_query="How has the copilot been performing operationally in the last 30 days?"),
    )

    assert response.detected_intent == "scorecard_check"
    assert response.tools_used == ["get_scorecard"]
    assert response.answer.headline == "Operational scorecard ready"
