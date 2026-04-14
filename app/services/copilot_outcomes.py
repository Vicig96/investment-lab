"""Deterministic local outcome attribution over saved decisions and later monitoring data."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.copilot_journal import DecisionRecord
from app.schemas.copilot_monitoring import MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_outcomes import (
    DecisionOutcomeRecord,
    ForwardSnapshotComparison,
    OutcomeDateRange,
    OutcomeReviewRequest,
    OutcomeReviewResponse,
    OutcomeSummary,
)
from app.services import copilot_journal as journal_service
from app.services import copilot_monitoring as monitoring_service

_USABLE_STATUSES = {
    "eligible",
    "eligible_with_cautions",
    "eligible_new_position",
    "eligible_add_to_existing",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []

    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        payload = line.strip()
        if not payload:
            continue
        try:
            records.append(json.loads(payload))
        except json.JSONDecodeError:
            continue
    return records


def _in_range(timestamp: str, date_from: str | None, date_to: str | None) -> bool:
    ts_date = timestamp[:10]
    if date_from and ts_date < date_from:
        return False
    if date_to and ts_date > date_to:
        return False
    return True


def _entity_for_decision(record: DecisionRecord) -> str | None:
    if record.final_recommendation is not None and record.final_recommendation.recommended_entity:
        return record.final_recommendation.recommended_entity
    return record.top_deterministic_result


def _filtered_decisions(request: OutcomeReviewRequest) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for obj in _read_jsonl(journal_service.JOURNAL_PATH):
        try:
            record = DecisionRecord.model_validate(obj)
        except Exception:
            continue
        if request.action_taken and record.action_taken != request.action_taken:
            continue
        if _in_range(record.timestamp, request.date_from, request.date_to):
            records.append(record)
    records.sort(key=lambda item: item.timestamp, reverse=True)
    return records[: request.limit]


def _all_decisions() -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for obj in _read_jsonl(journal_service.JOURNAL_PATH):
        try:
            records.append(DecisionRecord.model_validate(obj))
        except Exception:
            continue
    records.sort(key=lambda item: item.timestamp)
    return records


def _all_findings() -> list[MonitoringFinding]:
    records: list[MonitoringFinding] = []
    for obj in _read_jsonl(monitoring_service.FINDINGS_PATH):
        try:
            records.append(MonitoringFinding.model_validate(obj))
        except Exception:
            continue
    records.sort(key=lambda item: item.timestamp)
    return records


def _all_snapshots() -> list[MonitoringSnapshotRecord]:
    records: list[MonitoringSnapshotRecord] = []
    for obj in _read_jsonl(monitoring_service.SNAPSHOTS_PATH):
        try:
            records.append(MonitoringSnapshotRecord.model_validate(obj))
        except Exception:
            continue
    records.sort(key=lambda item: item.timestamp)
    return records


def _days_elapsed(timestamp: str) -> int:
    start = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    now = datetime.now(timezone.utc)
    return max(0, int((now - start).days))


def _later_decisions_for_entity(entity: str | None, timestamp: str, all_decisions: list[DecisionRecord]) -> list[DecisionRecord]:
    if not entity:
        return []
    later: list[DecisionRecord] = []
    for record in all_decisions:
        if record.timestamp <= timestamp:
            continue
        if _entity_for_decision(record) == entity or record.top_deterministic_result == entity:
            later.append(record)
    return later


def _later_findings_for_entity(entity: str | None, timestamp: str, findings: list[MonitoringFinding]) -> list[MonitoringFinding]:
    if not entity:
        return []
    return [
        finding
        for finding in findings
        if finding.timestamp > timestamp and finding.entity == entity
    ]


def _later_snapshots(timestamp: str, snapshots: list[MonitoringSnapshotRecord]) -> list[MonitoringSnapshotRecord]:
    return [snapshot for snapshot in snapshots if snapshot.timestamp > timestamp]


def _asset_state(snapshot: MonitoringSnapshotRecord, entity: str) -> Any | None:
    return next((item for item in snapshot.monitored_assets if item.ticker == entity), None)


def _watchlist_transition_status(
    record: DecisionRecord,
    entity: str | None,
    later_decisions: list[DecisionRecord],
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if record.action_taken not in {"watchlist", "paper_only"}:
        return "not_watchlist_or_paper_only", notes
    if not entity:
        notes.append("Watchlist transition could not be checked because no entity was stored on the decision.")
        return "insufficient_data", notes
    if not later_decisions:
        notes.append("No later journal decisions were available for this watchlist or paper-only idea.")
        return "insufficient_data", notes
    for later in later_decisions:
        if later.recommendation_status in _USABLE_STATUSES:
            return "later_became_actionable", notes
    return "no_later_actionable_transition_observed", notes


def _recommendation_consistency(
    entity: str | None,
    later_snapshots: list[MonitoringSnapshotRecord],
) -> tuple[str, ForwardSnapshotComparison | None, list[str]]:
    notes: list[str] = []
    if not entity:
        notes.append("Recommendation consistency could not be checked because no entity was stored on the decision.")
        return "insufficient_data", None, notes
    if not later_snapshots:
        notes.append("No later monitoring snapshots were available for consistency checks.")
        return "insufficient_data", None, notes

    first = later_snapshots[0]
    latest = later_snapshots[-1]
    matches = [snapshot.best_eligible_asset == entity for snapshot in later_snapshots]
    comparison = ForwardSnapshotComparison(
        first_later_best_eligible_asset=first.best_eligible_asset,
        latest_best_eligible_asset=latest.best_eligible_asset,
        first_later_best_eligible_status=first.best_eligible_status,
        latest_best_eligible_status=latest.best_eligible_status,
        entity_matched_first_later_best=(first.best_eligible_asset == entity),
        entity_matched_latest_best=(latest.best_eligible_asset == entity),
    )
    if all(matches):
        return "consistent", comparison, notes
    if any(matches):
        return "mixed", comparison, notes
    return "changed", comparison, notes


def _current_relevance_status(
    entity: str | None,
    later_snapshots: list[MonitoringSnapshotRecord],
    later_findings: list[MonitoringFinding],
) -> tuple[str, list[str]]:
    notes: list[str] = []
    if not entity:
        notes.append("Current relevance could not be checked because the decision did not store an entity.")
        return "no_entity_recorded", notes
    if not later_snapshots:
        notes.append("No later monitoring snapshots were available for current relevance checks.")
        return "no_later_monitoring_data", notes

    latest = later_snapshots[-1]
    state = _asset_state(latest, entity)
    if latest.best_eligible_asset == entity and latest.best_eligible_status in _USABLE_STATUSES:
        return "still_best_eligible", notes
    if state is not None and state.recommendation_status in _USABLE_STATUSES:
        return "still_actionable_but_not_best", notes
    if later_findings:
        return "later_deteriorated", notes
    return "superseded_or_not_current", notes


def _later_monitoring_signals(later_findings: list[MonitoringFinding]) -> list[str]:
    signals: list[str] = []
    for finding in later_findings[:5]:
        signals.append(f"{finding.finding_type}: {finding.headline}")
    return signals


def review_outcomes(request: OutcomeReviewRequest) -> OutcomeReviewResponse:
    warnings: list[str] = [
        "Outcome attribution is operational only. It does not infer PnL, fills, execution quality, or financial returns."
    ]
    decisions = _filtered_decisions(request)
    all_decisions = _all_decisions()
    findings = _all_findings()
    snapshots = _all_snapshots()

    entries: list[DecisionOutcomeRecord] = []
    reviewed_count = 0
    accepted_count = 0
    watchlist_or_paper_only_count = 0
    watchlist_later_actionable_count = 0
    decisions_with_later_findings = 0
    consistent_count = 0
    inconsistent_or_mixed_count = 0

    if not decisions:
        warnings.append("No journal decisions were available for the selected outcome review range.")

    for record in decisions:
        entity = _entity_for_decision(record)
        later_decisions = _later_decisions_for_entity(entity, record.timestamp, all_decisions)
        later_findings = _later_findings_for_entity(entity, record.timestamp, findings)
        later_snapshots = _later_snapshots(record.timestamp, snapshots)

        consistency, comparison, consistency_notes = _recommendation_consistency(entity, later_snapshots)
        watchlist_status, watchlist_notes = _watchlist_transition_status(record, entity, later_decisions)
        relevance_status, relevance_notes = _current_relevance_status(entity, later_snapshots, later_findings)

        if record.review_date or record.outcome_notes:
            reviewed_count += 1
        if record.action_taken == "accepted":
            accepted_count += 1
        if record.action_taken in {"watchlist", "paper_only"}:
            watchlist_or_paper_only_count += 1
        if watchlist_status == "later_became_actionable":
            watchlist_later_actionable_count += 1
        if later_findings:
            decisions_with_later_findings += 1
        if consistency == "consistent":
            consistent_count += 1
        if consistency in {"changed", "mixed"}:
            inconsistent_or_mixed_count += 1

        missing_data_notes = [*consistency_notes, *watchlist_notes, *relevance_notes]
        entries.append(
            DecisionOutcomeRecord(
                decision_id=record.decision_id,
                entity=entity,
                decision_timestamp=record.timestamp,
                days_elapsed=_days_elapsed(record.timestamp),
                action_taken=record.action_taken,
                was_reviewed=bool(record.review_date or record.outcome_notes),
                current_relevance_status=relevance_status,
                later_monitoring_signals=_later_monitoring_signals(later_findings),
                later_recommendation_consistency=consistency,
                watchlist_transition_status=watchlist_status,
                forward_snapshot_comparison=comparison,
                warnings=(
                    ["Later monitoring findings were recorded for this entity."]
                    if later_findings
                    else []
                ),
                missing_data_notes=missing_data_notes,
            )
        )

    range_label = "all available local history"
    if request.date_from or request.date_to:
        range_label = f"{request.date_from or 'start'} to {request.date_to or 'latest'}"

    if not snapshots:
        warnings.append("No monitoring snapshots were available, so later consistency and relevance checks may be limited.")
    if not findings:
        warnings.append("No monitoring findings were available, so later signal detection may be limited.")

    return OutcomeReviewResponse(
        generated_at=_now_utc(),
        date_range=OutcomeDateRange(
            start=request.date_from,
            end=request.date_to,
            label=range_label,
        ),
        summary=OutcomeSummary(
            total_decisions_reviewed=len(entries),
            reviewed_decisions=reviewed_count,
            accepted_decisions=accepted_count,
            watchlist_or_paper_only_decisions=watchlist_or_paper_only_count,
            watchlist_or_paper_only_later_actionable=watchlist_later_actionable_count,
            decisions_with_later_findings=decisions_with_later_findings,
            consistent_recommendations=consistent_count,
            inconsistent_or_mixed_recommendations=inconsistent_or_mixed_count,
        ),
        entries=entries,
        warnings=warnings,
    )
