"""Deterministic local scorecard service for journal and monitoring validation."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.copilot_journal import DecisionRecord
from app.schemas.copilot_monitoring import MonitoringFinding, MonitoringSnapshotRecord
from app.schemas.copilot_scorecard import (
    ActionScorecardSummary,
    ConstraintScorecardSummary,
    CountItem,
    FindingsScorecardSummary,
    JournalScorecardSummary,
    MonitoringScorecardSummary,
    RecommendationScorecardSummary,
    ScorecardDateRange,
    ScorecardRequest,
    ScorecardResponse,
)
from app.services import copilot_journal as journal_service
from app.services import copilot_monitoring as monitoring_service

_USABLE_STATUSES = {
    "eligible",
    "eligible_with_cautions",
    "eligible_new_position",
    "eligible_add_to_existing",
}
_BLOCKED_STATUSES = {
    "rejected_by_profile",
    "rejected_by_portfolio_constraints",
    "not_actionable_without_cash",
    "redundant_exposure",
    "eligible_but_overconcentrated",
    "unsupported_by_knowledge",
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


def _top_items(counter: Counter[str], *, limit: int = 5) -> list[CountItem]:
    return [
        CountItem(item=item, count=count)
        for item, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def _entity_for_decision(record: DecisionRecord) -> str | None:
    if record.final_recommendation is not None and record.final_recommendation.recommended_entity:
        return record.final_recommendation.recommended_entity
    return record.top_deterministic_result


def _blocked_reason_strings(record: DecisionRecord) -> list[str]:
    reasons: list[str] = []

    for constraint in record.profile_constraints_applied:
        if constraint.category == "hard_block":
            reasons.append(constraint.detail)
    for context in record.portfolio_context_applied:
        if context.status == "block":
            reasons.append(context.detail)

    if not reasons and record.recommendation_status == "unsupported_by_knowledge":
        reasons.append("Local knowledge support was missing for the idea.")
    if not reasons and record.portfolio_decision_summary and record.recommendation_status in {
        "not_actionable_without_cash",
        "redundant_exposure",
        "eligible_but_overconcentrated",
        "rejected_by_portfolio_constraints",
    }:
        reasons.append(record.portfolio_decision_summary)

    return reasons


def _filtered_decisions(request: ScorecardRequest) -> list[DecisionRecord]:
    records: list[DecisionRecord] = []
    for obj in _read_jsonl(journal_service.JOURNAL_PATH):
        try:
            record = DecisionRecord.model_validate(obj)
        except Exception:
            continue
        if _in_range(record.timestamp, request.date_from, request.date_to):
            records.append(record)
    records.sort(key=lambda item: item.timestamp)
    return records


def _filtered_findings(request: ScorecardRequest) -> list[MonitoringFinding]:
    records: list[MonitoringFinding] = []
    for obj in _read_jsonl(monitoring_service.FINDINGS_PATH):
        try:
            record = MonitoringFinding.model_validate(obj)
        except Exception:
            continue
        if _in_range(record.timestamp, request.date_from, request.date_to):
            records.append(record)
    records.sort(key=lambda item: item.timestamp)
    return records


def _filtered_snapshots(request: ScorecardRequest) -> list[MonitoringSnapshotRecord]:
    records: list[MonitoringSnapshotRecord] = []
    for obj in _read_jsonl(monitoring_service.SNAPSHOTS_PATH):
        try:
            record = MonitoringSnapshotRecord.model_validate(obj)
        except Exception:
            continue
        if _in_range(record.timestamp, request.date_from, request.date_to):
            records.append(record)
    records.sort(key=lambda item: item.timestamp)
    return records


def _watchlist_or_paper_later_actionable(decisions: list[DecisionRecord]) -> tuple[int | None, list[str]]:
    notes: list[str] = []
    if not decisions:
        notes.append("No journal decisions were available to evaluate watchlist or paper-only follow-through.")
        return None, notes

    actionable_by_entity: dict[str, bool] = {}
    watched_entities: dict[str, bool] = {}
    trackable_entities = 0

    for record in decisions:
        entity = _entity_for_decision(record)
        if not entity:
            continue
        trackable_entities += 1
        if record.action_taken in {"watchlist", "paper_only"}:
            watched_entities[entity] = True
        elif watched_entities.get(entity) and record.recommendation_status in _USABLE_STATUSES:
            actionable_by_entity[entity] = True

    if trackable_entities == 0:
        notes.append("Journal records did not include enough entity identifiers to evaluate watchlist or paper-only transitions.")
        return None, notes

    return len(actionable_by_entity), notes


def generate_scorecard(request: ScorecardRequest) -> ScorecardResponse:
    warnings: list[str] = [
        "This scorecard is operational only. It does not infer returns, PnL, or financial performance from incomplete local data."
    ]
    decisions = _filtered_decisions(request)
    findings = _filtered_findings(request)
    snapshots = _filtered_snapshots(request)

    status_counter = Counter(
        record.recommendation_status
        for record in decisions
        if record.recommendation_status
    )
    action_taken_counter = Counter(
        record.action_taken
        for record in decisions
        if record.action_taken
    )
    recommended_action_counter = Counter(
        record.recommended_action_type
        for record in decisions
        if record.recommended_action_type
    )
    top_deterministic_counter = Counter(
        record.top_deterministic_result
        for record in decisions
        if record.top_deterministic_result
    )
    top_final_recommendation_counter = Counter(
        record.final_recommendation.recommended_entity
        for record in decisions
        if record.final_recommendation is not None and record.final_recommendation.recommended_entity
    )

    blocked_reason_counter: Counter[str] = Counter()
    for record in decisions:
        if record.recommendation_status in _BLOCKED_STATUSES:
            for reason in _blocked_reason_strings(record):
                blocked_reason_counter[reason] += 1

    findings_type_counter = Counter(finding.finding_type for finding in findings)
    findings_severity_counter = Counter(finding.severity for finding in findings)
    findings_entity_counter = Counter(finding.entity for finding in findings if finding.entity)
    key_warning_counter = Counter(
        warning
        for snapshot in snapshots
        for warning in snapshot.key_warnings
    )

    journal_missing: list[str] = []
    recommendation_missing: list[str] = []
    action_missing: list[str] = []
    constraint_missing: list[str] = []
    findings_missing: list[str] = []
    monitoring_missing: list[str] = []

    if not decisions:
        note = "No journal decisions were available in the selected date range."
        journal_missing.append(note)
        recommendation_missing.append(note)
        action_missing.append(note)
        constraint_missing.append(note)
        warnings.append(note)

    if not top_deterministic_counter:
        journal_missing.append("No top deterministic results were stored in journal entries for this range.")
    if not top_final_recommendation_counter:
        journal_missing.append("No final recommended entities were stored in journal entries for this range.")
    if not blocked_reason_counter:
        constraint_missing.append("Blocked or rejected reason details were not available from the stored journal fields for this range.")

    if not findings:
        findings_missing.append("No monitoring findings were available in the selected date range.")
    if not snapshots:
        monitoring_missing.append("No monitoring snapshots were available in the selected date range.")
    if len(snapshots) < 2:
        monitoring_missing.append("Fewer than two snapshots were available, so change-frequency metrics are limited.")

    watchlist_later_actionable_count, watchlist_notes = _watchlist_or_paper_later_actionable(decisions)
    monitoring_missing.extend(watchlist_notes)

    best_asset_changes = 0
    for previous, current in zip(snapshots, snapshots[1:]):
        if previous.best_eligible_asset != current.best_eligible_asset:
            best_asset_changes += 1

    journal_summary = JournalScorecardSummary(
        total_journal_decisions=len(decisions),
        top_deterministic_results=_top_items(top_deterministic_counter),
        top_final_recommendations=_top_items(top_final_recommendation_counter),
        missing_data_notes=journal_missing,
    )
    recommendation_summary = RecommendationScorecardSummary(
        decisions_by_recommendation_status=_top_items(status_counter, limit=10),
        eligible_ideas_acted_on=sum(
            1
            for record in decisions
            if record.action_taken == "accepted" and record.recommendation_status in _USABLE_STATUSES
        ),
        missing_data_notes=recommendation_missing,
    )
    action_summary = ActionScorecardSummary(
        decisions_by_action_taken=_top_items(action_taken_counter, limit=10),
        decisions_by_recommended_action_type=_top_items(recommended_action_counter, limit=10),
        missing_data_notes=action_missing,
    )
    constraint_summary = ConstraintScorecardSummary(
        top_blocked_or_rejected_reasons=_top_items(blocked_reason_counter),
        missing_data_notes=constraint_missing,
    )
    findings_summary = FindingsScorecardSummary(
        total_findings=len(findings),
        findings_by_finding_type=_top_items(findings_type_counter, limit=10),
        findings_by_severity=_top_items(findings_severity_counter, limit=10),
        most_frequent_entities=_top_items(findings_entity_counter),
        missing_data_notes=findings_missing,
    )
    monitoring_summary = MonitoringScorecardSummary(
        snapshots_in_range=len(snapshots),
        best_eligible_asset_changes=best_asset_changes,
        watchlist_or_paper_only_later_actionable_count=watchlist_later_actionable_count,
        top_key_warning_patterns=_top_items(key_warning_counter),
        missing_data_notes=monitoring_missing,
    )

    notable_patterns: list[str] = []
    if recommendation_summary.eligible_ideas_acted_on:
        notable_patterns.append(
            f"Accepted actionable ideas: {recommendation_summary.eligible_ideas_acted_on} journal decision(s) with usable recommendation status were marked accepted."
        )
    if constraint_summary.top_blocked_or_rejected_reasons:
        top_reason = constraint_summary.top_blocked_or_rejected_reasons[0]
        notable_patterns.append(
            f"Most common blocked or rejected reason: {top_reason.item} ({top_reason.count})."
        )
    if findings_summary.findings_by_finding_type:
        top_finding = findings_summary.findings_by_finding_type[0]
        notable_patterns.append(
            f"Most frequent finding pattern: {top_finding.item} ({top_finding.count})."
        )
    if monitoring_summary.watchlist_or_paper_only_later_actionable_count:
        notable_patterns.append(
            "Some watchlist or paper-only ideas later became actionable in subsequent journal records."
        )
    if not notable_patterns:
        notable_patterns.append("No strong operational patterns were available from the selected local data range.")

    for note in [
        *journal_missing,
        *constraint_missing,
        *findings_missing,
        *monitoring_missing,
    ]:
        if note not in warnings:
            warnings.append(note)

    range_label = "all available local history"
    if request.date_from or request.date_to:
        range_label = f"{request.date_from or 'start'} to {request.date_to or 'latest'}"

    return ScorecardResponse(
        generated_at=_now_utc(),
        date_range=ScorecardDateRange(
            start=request.date_from,
            end=request.date_to,
            label=range_label,
        ),
        journal_summary=journal_summary,
        recommendation_summary=recommendation_summary,
        action_summary=action_summary,
        constraint_summary=constraint_summary,
        findings_summary=findings_summary,
        monitoring_summary=monitoring_summary,
        notable_patterns=notable_patterns,
        warnings=warnings,
    )
