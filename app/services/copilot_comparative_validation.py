"""Deterministic local comparative validation over journal decisions and follow-up outcome states."""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.schemas.copilot_journal import DecisionRecord
from app.schemas.copilot_outcomes import DecisionOutcomeRecord, OutcomeReviewRequest
from app.schemas.copilot_comparative_validation import (
    CohortSummary,
    ComparisonGroup,
    ComparativeCountItem,
    ComparativeValidationDateRange,
    ComparativeValidationRequest,
    ComparativeValidationResponse,
    LaterSignalComparisonSummary,
    RateComparisonSummary,
)
from app.services import copilot_journal as journal_service
from app.services import copilot_outcomes as outcome_service

_USABLE_STATUSES = {
    "eligible",
    "eligible_with_cautions",
    "eligible_new_position",
    "eligible_add_to_existing",
}
_NEGATIVE_FINDING_TYPES = {
    "holding_rule_violation",
    "holding_drawdown_breach",
    "thesis_support_missing",
    "portfolio_concentration_warning",
    "missing_data",
}
_COHORT_DEFINITIONS: list[tuple[str, str, Any]] = [
    ("accepted", "Accepted", lambda decision: decision.action_taken == "accepted"),
    ("rejected", "Rejected", lambda decision: decision.action_taken == "rejected"),
    ("watchlist", "Watchlist", lambda decision: decision.action_taken == "watchlist"),
    ("paper_only", "Paper only", lambda decision: decision.action_taken == "paper_only"),
    ("eligible", "Eligible", lambda decision: decision.recommendation_status in _USABLE_STATUSES),
    ("rejected_by_profile", "Rejected by profile", lambda decision: decision.recommendation_status == "rejected_by_profile"),
    (
        "supported_by_knowledge",
        "Supported by knowledge",
        lambda decision: decision.recommendation_status != "unsupported_by_knowledge" and bool(decision.knowledge_sources_used),
    ),
    (
        "unsupported_by_knowledge",
        "Unsupported by knowledge",
        lambda decision: decision.recommendation_status == "unsupported_by_knowledge",
    ),
    (
        "open_new_position",
        "Open new position",
        lambda decision: decision.recommended_action_type == "open_new_position",
    ),
    (
        "add_to_existing_position",
        "Add to existing position",
        lambda decision: decision.recommended_action_type == "add_to_existing_position",
    ),
]
_COMPARISON_GROUPS = [
    ComparisonGroup(
        comparison_key="accepted_vs_rejected",
        left_cohort="accepted",
        right_cohort="rejected",
        left_label="Accepted",
        right_label="Rejected",
    ),
    ComparisonGroup(
        comparison_key="accepted_vs_watchlist",
        left_cohort="accepted",
        right_cohort="watchlist",
        left_label="Accepted",
        right_label="Watchlist",
    ),
    ComparisonGroup(
        comparison_key="watchlist_vs_paper_only",
        left_cohort="watchlist",
        right_cohort="paper_only",
        left_label="Watchlist",
        right_label="Paper only",
    ),
    ComparisonGroup(
        comparison_key="eligible_vs_rejected_by_profile",
        left_cohort="eligible",
        right_cohort="rejected_by_profile",
        left_label="Eligible",
        right_label="Rejected by profile",
    ),
    ComparisonGroup(
        comparison_key="supported_vs_unsupported_by_knowledge",
        left_cohort="supported_by_knowledge",
        right_cohort="unsupported_by_knowledge",
        left_label="Supported by knowledge",
        right_label="Unsupported by knowledge",
    ),
    ComparisonGroup(
        comparison_key="open_new_position_vs_add_to_existing_position",
        left_cohort="open_new_position",
        right_cohort="add_to_existing_position",
        left_label="Open new position",
        right_label="Add to existing position",
    ),
]


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


def _top_items(counter: Counter[str], *, limit: int = 5) -> list[ComparativeCountItem]:
    return [
        ComparativeCountItem(item=item, count=count)
        for item, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def _filtered_decisions(request: ComparativeValidationRequest) -> tuple[list[DecisionRecord], int]:
    records: list[DecisionRecord] = []
    for obj in _read_jsonl(journal_service.JOURNAL_PATH):
        try:
            record = DecisionRecord.model_validate(obj)
        except Exception:
            continue
        if _in_range(record.timestamp, request.date_from, request.date_to):
            records.append(record)
    records.sort(key=lambda item: item.timestamp, reverse=True)
    total_available = len(records)
    return records[: request.limit], total_available


def _signal_type(signal: str) -> str:
    return signal.split(":", 1)[0].strip()


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _cohort_summary(
    cohort_key: str,
    label: str,
    records: list[tuple[DecisionRecord, DecisionOutcomeRecord]],
) -> CohortSummary:
    consistency_counter = Counter(outcome.later_recommendation_consistency for _, outcome in records)
    relevance_counter = Counter(outcome.current_relevance_status for _, outcome in records)
    signal_counter = Counter(
        _signal_type(signal)
        for _, outcome in records
        for signal in outcome.later_monitoring_signals
    )
    watchlist_counter = Counter(outcome.watchlist_transition_status for _, outcome in records)
    total = len(records)
    negative_findings = sum(
        1
        for _, outcome in records
        if any(_signal_type(signal) in _NEGATIVE_FINDING_TYPES for signal in outcome.later_monitoring_signals)
    )
    still_actionable = sum(
        1
        for _, outcome in records
        if outcome.current_relevance_status in {"still_best_eligible", "still_actionable_but_not_best"}
    )

    insufficient_data_markers: list[str] = []
    if total == 0:
        insufficient_data_markers.append("No local decisions were available for this cohort in the selected range.")
    elif total < 2:
        insufficient_data_markers.append("This cohort has fewer than two decisions, so comparison strength is limited.")
    if not signal_counter:
        insufficient_data_markers.append("No later monitoring signals were recorded for this cohort.")
    if all(
        outcome.watchlist_transition_status == "not_watchlist_or_paper_only"
        for _, outcome in records
    ) and total > 0:
        insufficient_data_markers.append("Watchlist transition metrics are not relevant for this cohort.")
    if consistency_counter.get("insufficient_data", 0) == total and total > 0:
        insufficient_data_markers.append("Later recommendation consistency could not be checked reliably for this cohort.")

    return CohortSummary(
        cohort_key=cohort_key,
        label=label,
        total_decisions=total,
        later_recommendation_consistency_distribution=_top_items(consistency_counter, limit=10),
        current_relevance_status_distribution=_top_items(relevance_counter, limit=10),
        later_monitoring_signals_frequency=_top_items(signal_counter, limit=10),
        watchlist_transition_status_distribution=_top_items(watchlist_counter, limit=10),
        proportion_operationally_consistent=_rate(consistency_counter.get("consistent", 0), total),
        proportion_still_actionable=_rate(still_actionable, total),
        proportion_later_deteriorated=_rate(relevance_counter.get("later_deteriorated", 0), total),
        proportion_still_best_eligible=_rate(relevance_counter.get("still_best_eligible", 0), total),
        proportion_superseded_or_not_current=_rate(relevance_counter.get("superseded_or_not_current", 0), total),
        proportion_later_receiving_negative_findings=_rate(negative_findings, total),
        insufficient_data_markers=insufficient_data_markers,
    )


def _compare_rates(
    comparison: ComparisonGroup,
    left_summary: CohortSummary,
    right_summary: CohortSummary,
    *,
    metric_name: str,
    left_rate: float | None,
    right_rate: float | None,
    higher_is_better: bool,
    neutral_text: str,
) -> RateComparisonSummary:
    notes: list[str] = []
    supported = True
    if left_summary.total_decisions == 0 or right_summary.total_decisions == 0:
        supported = False
        notes.append("At least one cohort had no local decisions in the selected range.")
    if left_summary.total_decisions < 2 or right_summary.total_decisions < 2:
        notes.append("At least one cohort has fewer than two decisions, so this comparison is only directional.")

    if left_rate is None or right_rate is None:
        supported = False
        interpretation = f"{comparison.left_label} versus {comparison.right_label} could not be compared for {metric_name} from the available local data."
    elif left_rate == right_rate:
        interpretation = neutral_text.format(left=comparison.left_label, right=comparison.right_label)
    else:
        left_better = left_rate > right_rate if higher_is_better else left_rate < right_rate
        better_label = comparison.left_label if left_better else comparison.right_label
        metric_text = {
            "consistency": "were operationally more consistent later",
            "deterioration": "later deteriorated less often",
            "watchlist_transition": "more often later became actionable",
        }[metric_name]
        interpretation = f"{better_label} {metric_text} in this local sample."

    return RateComparisonSummary(
        comparison_key=comparison.comparison_key,
        left_cohort=comparison.left_cohort,
        right_cohort=comparison.right_cohort,
        left_total=left_summary.total_decisions,
        right_total=right_summary.total_decisions,
        left_rate=left_rate,
        right_rate=right_rate,
        interpretation=interpretation,
        supported=supported,
        notes=notes,
    )


def _watchlist_transition_rate(summary: CohortSummary) -> float | None:
    applicable = 0
    later_actionable = 0
    for item in summary.watchlist_transition_status_distribution:
        if item.item == "not_watchlist_or_paper_only":
            continue
        applicable += item.count
        if item.item == "later_became_actionable":
            later_actionable += item.count
    return _rate(later_actionable, applicable) if applicable else None


def _later_signal_comparison(
    comparison: ComparisonGroup,
    left_summary: CohortSummary,
    right_summary: CohortSummary,
) -> LaterSignalComparisonSummary:
    notes: list[str] = []
    supported = True
    if left_summary.total_decisions == 0 or right_summary.total_decisions == 0:
        supported = False
        notes.append("At least one cohort had no local decisions in the selected range.")
    if left_summary.total_decisions < 2 or right_summary.total_decisions < 2:
        notes.append("At least one cohort has fewer than two decisions, so later-signal comparisons are only directional.")

    left_rate = left_summary.proportion_later_receiving_negative_findings
    right_rate = right_summary.proportion_later_receiving_negative_findings
    if left_rate is None or right_rate is None:
        supported = False
        interpretation = f"{comparison.left_label} versus {comparison.right_label} could not be compared for later negative findings from the available local data."
    elif left_rate == right_rate:
        interpretation = f"{comparison.left_label} and {comparison.right_label} later received negative findings at similar rates in this local sample."
    else:
        better_label = comparison.left_label if left_rate < right_rate else comparison.right_label
        interpretation = f"{better_label} later received negative findings less often in this local sample."

    return LaterSignalComparisonSummary(
        comparison_key=comparison.comparison_key,
        left_cohort=comparison.left_cohort,
        right_cohort=comparison.right_cohort,
        left_total=left_summary.total_decisions,
        right_total=right_summary.total_decisions,
        left_negative_findings_rate=left_rate,
        right_negative_findings_rate=right_rate,
        left_top_signals=left_summary.later_monitoring_signals_frequency[:3],
        right_top_signals=right_summary.later_monitoring_signals_frequency[:3],
        interpretation=interpretation,
        supported=supported,
        notes=notes,
    )


def generate_comparative_validation(request: ComparativeValidationRequest) -> ComparativeValidationResponse:
    warnings: list[str] = [
        "Comparative validation is operational only. It does not infer returns, PnL, fills, or broker execution outcomes."
    ]
    missing_data_notes: list[str] = []

    decisions, total_available = _filtered_decisions(request)
    if total_available > request.limit:
        warning = (
            f"Comparative validation was limited to the most recent {request.limit} decision(s) "
            f"out of {total_available} available in the selected range."
        )
        warnings.append(warning)
        missing_data_notes.append(warning)

    if not decisions:
        note = "No journal decisions were available for comparative validation in the selected date range."
        warnings.append(note)
        missing_data_notes.append(note)

    outcome_review = outcome_service.review_outcomes(
        OutcomeReviewRequest(
            date_from=request.date_from,
            date_to=request.date_to,
            limit=request.limit,
        )
    )
    outcome_by_id = {entry.decision_id: entry for entry in outcome_review.entries}
    joined_records = [
        (decision, outcome_by_id[decision.decision_id])
        for decision in decisions
        if decision.decision_id in outcome_by_id
    ]
    if decisions and len(joined_records) != len(decisions):
        note = "Some decisions could not be matched to outcome-review records, so cohort comparisons may be incomplete."
        warnings.append(note)
        missing_data_notes.append(note)

    cohort_summaries: list[CohortSummary] = []
    summary_by_key: dict[str, CohortSummary] = {}
    for cohort_key, label, predicate in _COHORT_DEFINITIONS:
        cohort_records = [
            (decision, outcome)
            for decision, outcome in joined_records
            if predicate(decision)
        ]
        summary = _cohort_summary(cohort_key, label, cohort_records)
        cohort_summaries.append(summary)
        summary_by_key[cohort_key] = summary
        missing_data_notes.extend(
            note for note in summary.insufficient_data_markers if note not in missing_data_notes
        )

    consistency_summary: list[RateComparisonSummary] = []
    deterioration_summary: list[RateComparisonSummary] = []
    later_signal_summary: list[LaterSignalComparisonSummary] = []
    watchlist_transition_summary: list[RateComparisonSummary] = []
    for comparison in _COMPARISON_GROUPS:
        left_summary = summary_by_key[comparison.left_cohort]
        right_summary = summary_by_key[comparison.right_cohort]
        consistency_summary.append(
            _compare_rates(
                comparison,
                left_summary,
                right_summary,
                metric_name="consistency",
                left_rate=left_summary.proportion_operationally_consistent,
                right_rate=right_summary.proportion_operationally_consistent,
                higher_is_better=True,
                neutral_text="{left} and {right} looked similarly consistent later in this local sample.",
            )
        )
        deterioration_summary.append(
            _compare_rates(
                comparison,
                left_summary,
                right_summary,
                metric_name="deterioration",
                left_rate=left_summary.proportion_later_deteriorated,
                right_rate=right_summary.proportion_later_deteriorated,
                higher_is_better=False,
                neutral_text="{left} and {right} later deteriorated at similar rates in this local sample.",
            )
        )
        later_signal_summary.append(_later_signal_comparison(comparison, left_summary, right_summary))
        watchlist_transition_summary.append(
            _compare_rates(
                comparison,
                left_summary,
                right_summary,
                metric_name="watchlist_transition",
                left_rate=_watchlist_transition_rate(left_summary),
                right_rate=_watchlist_transition_rate(right_summary),
                higher_is_better=True,
                neutral_text="{left} and {right} later became actionable at similar rates where watchlist-style follow-up was relevant.",
            )
        )

    notable_patterns: list[str] = []
    actionable_leaders = sorted(
        (
            summary for summary in cohort_summaries
            if summary.total_decisions > 0 and summary.proportion_still_actionable is not None
        ),
        key=lambda summary: (-(summary.proportion_still_actionable or 0.0), -summary.total_decisions, summary.label),
    )
    if actionable_leaders:
        leader = actionable_leaders[0]
        notable_patterns.append(
            f"{leader.label} most often remained actionable later ({leader.proportion_still_actionable:.0%} of this local cohort)."
        )
    deterioration_leaders = sorted(
        (
            summary for summary in cohort_summaries
            if summary.total_decisions > 0 and summary.proportion_later_deteriorated is not None
        ),
        key=lambda summary: (-(summary.proportion_later_deteriorated or 0.0), -summary.total_decisions, summary.label),
    )
    if deterioration_leaders:
        leader = deterioration_leaders[0]
        notable_patterns.append(
            f"{leader.label} later deteriorated most often ({leader.proportion_later_deteriorated:.0%} of this local cohort)."
        )
    watchlist_summary = summary_by_key["watchlist"]
    paper_summary = summary_by_key["paper_only"]
    watchlist_rate = _watchlist_transition_rate(watchlist_summary)
    paper_rate = _watchlist_transition_rate(paper_summary)
    if watchlist_rate is not None or paper_rate is not None:
        notable_patterns.append(
            "Watchlist versus paper-only comparisons describe how often ideas later became actionable, not how they performed financially."
        )
    if not notable_patterns:
        notable_patterns.append("No strong comparative patterns were available from the selected local data range.")

    for note in outcome_review.warnings:
        if note not in warnings:
            warnings.append(note)
    range_label = "all available local history"
    if request.date_from or request.date_to:
        range_label = f"{request.date_from or 'start'} to {request.date_to or 'latest'}"

    return ComparativeValidationResponse(
        generated_at=_now_utc(),
        date_range=ComparativeValidationDateRange(
            start=request.date_from,
            end=request.date_to,
            label=range_label,
        ),
        comparison_groups=_COMPARISON_GROUPS,
        cohort_summaries=cohort_summaries,
        consistency_summary=consistency_summary,
        deterioration_summary=deterioration_summary,
        later_signal_summary=later_signal_summary,
        watchlist_transition_summary=watchlist_transition_summary,
        notable_patterns=notable_patterns,
        warnings=warnings,
        missing_data_notes=missing_data_notes,
    )
