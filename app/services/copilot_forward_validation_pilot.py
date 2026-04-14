"""Deterministic local forward-validation pilot review over journal, monitoring, and paper outputs."""
from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.copilot_forward_validation_pilot import (
    ForwardPilotBenchmarkSummary,
    ForwardPilotCohortComparisonSummary,
    ForwardPilotCountItem,
    ForwardPilotDecisionSummary,
    ForwardPilotDirectionalComparison,
    ForwardPilotMonitoringSummary,
    ForwardPilotOperationalSummary,
    ForwardPilotPaperPortfolioSummary,
    ForwardPilotReviewProtocol,
    ForwardPilotWindow,
    ForwardValidationPilotRequest,
    ForwardValidationPilotResponse,
)
from app.schemas.copilot_outcomes import OutcomeReviewRequest
from app.schemas.copilot_paper_portfolio_nav import PaperPortfolioNavRequest
from app.schemas.copilot_scorecard import ScorecardRequest
from app.services import copilot_outcomes as outcome_service
from app.services import copilot_paper_portfolio_nav as paper_nav_service
from app.services import copilot_scorecard as scorecard_service


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _top_items(counter: Counter[str], *, limit: int = 5) -> list[ForwardPilotCountItem]:
    return [
        ForwardPilotCountItem(item=item, count=count)
        for item, count in sorted(counter.items(), key=lambda pair: (-pair[1], pair[0]))[:limit]
    ]


def _pilot_window_label(start: str | None, end: str | None) -> str:
    if start or end:
        return f"{start or 'start'} to {end or 'latest'}"
    return "all available local history"


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _sample_size_note(total_decisions: int) -> str | None:
    if total_decisions == 0:
        return "No pilot decisions were available in this local window."
    if total_decisions < 3:
        return "This pilot window has fewer than three decisions, so interpretations are only directional."
    return None


def _accepted_vs_paper_only_summary(accepted_nav, paper_only_nav) -> ForwardPilotDirectionalComparison:
    notes: list[str] = []
    if accepted_nav.nav_summary.supported_positions == 0 or paper_only_nav.nav_summary.supported_positions == 0:
        notes.append("At least one cohort did not have enough supported local paper positions for a directional comparison.")
        return ForwardPilotDirectionalComparison(
            supported=False,
            interpretation="Accepted versus paper-only ideas could not be compared reliably from the available local pilot data.",
            left_label="Accepted",
            right_label="Paper only",
            left_value=accepted_nav.nav_summary.total_portfolio_simple_return_pct,
            right_value=paper_only_nav.nav_summary.total_portfolio_simple_return_pct,
            notes=notes,
        )

    accepted_return = accepted_nav.nav_summary.total_portfolio_simple_return_pct
    paper_only_return = paper_only_nav.nav_summary.total_portfolio_simple_return_pct
    if accepted_return is None or paper_only_return is None:
        notes.append("At least one cohort did not produce a supported simple-return path.")
        return ForwardPilotDirectionalComparison(
            supported=False,
            interpretation="Accepted versus paper-only ideas could not be compared reliably from the available local pilot data.",
            left_label="Accepted",
            right_label="Paper only",
            left_value=accepted_return,
            right_value=paper_only_return,
            notes=notes,
        )

    if accepted_nav.nav_summary.supported_positions < 2 or paper_only_nav.nav_summary.supported_positions < 2:
        notes.append("At least one cohort has fewer than two supported paper positions, so this is only a directional comparison.")

    if accepted_return == paper_only_return:
        interpretation = "Accepted and paper-only ideas looked similar in this pilot window on a simple local paper basis."
    elif accepted_return > paper_only_return:
        interpretation = "Accepted ideas looked stronger than paper-only ideas in this pilot window on a simple local paper basis."
    else:
        interpretation = "Accepted ideas looked weaker than paper-only ideas in this pilot window on a simple local paper basis."

    return ForwardPilotDirectionalComparison(
        supported=True,
        interpretation=interpretation,
        left_label="Accepted",
        right_label="Paper only",
        left_value=accepted_return,
        right_value=paper_only_return,
        notes=notes,
    )


def _hold_vs_exit_summary(hold_nav, exit_nav) -> ForwardPilotDirectionalComparison:
    notes: list[str] = []
    hold_return = hold_nav.nav_summary.total_portfolio_simple_return_pct
    exit_return = exit_nav.nav_summary.total_portfolio_simple_return_pct
    delta = exit_nav.comparison_summary.exit_policy_ending_value_difference

    if hold_return is None or exit_return is None or delta is None:
        notes.append("Hold-only versus exit-policy comparison was not fully supported by the local paper NAV outputs.")
        return ForwardPilotDirectionalComparison(
            supported=False,
            interpretation="Hold-only versus exit-policy comparison could not be supported from the available local pilot data.",
            left_label="Hold only",
            right_label="Exit policy v1",
            left_value=hold_return,
            right_value=exit_return,
            notes=notes,
        )

    if delta > 0:
        interpretation = "Exit policy increased paper outcome versus hold-only in this pilot window."
    elif delta < 0:
        interpretation = "Exit policy reduced paper outcome versus hold-only in this pilot window."
    else:
        interpretation = "Exit policy finished in line with hold-only in this pilot window."

    return ForwardPilotDirectionalComparison(
        supported=True,
        interpretation=interpretation,
        left_label="Hold only",
        right_label="Exit policy v1",
        left_value=hold_return,
        right_value=exit_return,
        notes=notes,
    )


async def generate_forward_validation_pilot(
    session: AsyncSession,
    request: ForwardValidationPilotRequest,
) -> ForwardValidationPilotResponse:
    warnings: list[str] = [
        "Forward validation is cautious and local only. It does not infer real profitability, alpha, fills, or broker-grade execution outcomes."
    ]
    missing_data_notes: list[str] = []

    scorecard = scorecard_service.generate_scorecard(
        ScorecardRequest(date_from=request.date_from, date_to=request.date_to)
    )
    outcomes = outcome_service.review_outcomes(
        OutcomeReviewRequest(date_from=request.date_from, date_to=request.date_to, limit=request.limit)
    )
    paper_hold = await paper_nav_service.build_paper_portfolio_nav(
        session,
        PaperPortfolioNavRequest(
            cohort_definition=request.paper_cohort_definition,
            date_from=request.date_from,
            date_to=request.date_to,
            initial_capital=request.initial_capital,
            benchmark_ticker=request.benchmark_ticker,
            apply_exit_policy=False,
            limit=request.limit,
        ),
    )
    paper_exit = await paper_nav_service.build_paper_portfolio_nav(
        session,
        PaperPortfolioNavRequest(
            cohort_definition=request.paper_cohort_definition,
            date_from=request.date_from,
            date_to=request.date_to,
            initial_capital=request.initial_capital,
            benchmark_ticker=request.benchmark_ticker,
            apply_exit_policy=True,
            limit=request.limit,
        ),
    )
    accepted_nav = await paper_nav_service.build_paper_portfolio_nav(
        session,
        PaperPortfolioNavRequest(
            cohort_definition="accepted",
            date_from=request.date_from,
            date_to=request.date_to,
            initial_capital=request.initial_capital,
            benchmark_ticker=request.benchmark_ticker,
            apply_exit_policy=True,
            limit=request.limit,
        ),
    )
    paper_only_nav = await paper_nav_service.build_paper_portfolio_nav(
        session,
        PaperPortfolioNavRequest(
            cohort_definition="paper_only",
            date_from=request.date_from,
            date_to=request.date_to,
            initial_capital=request.initial_capital,
            benchmark_ticker=request.benchmark_ticker,
            apply_exit_policy=True,
            limit=request.limit,
        ),
    )

    decisions = scorecard_service._filtered_decisions(ScorecardRequest(date_from=request.date_from, date_to=request.date_to))
    findings = scorecard_service._filtered_findings(ScorecardRequest(date_from=request.date_from, date_to=request.date_to))
    snapshots = scorecard_service._filtered_snapshots(ScorecardRequest(date_from=request.date_from, date_to=request.date_to))

    action_counter = Counter(record.action_taken for record in decisions if record.action_taken)
    status_counter = Counter(record.recommendation_status for record in decisions if record.recommendation_status)
    blocked_reason_counter: Counter[str] = Counter()
    for record in decisions:
        if record.recommendation_status in scorecard_service._BLOCKED_STATUSES:
            for reason in scorecard_service._blocked_reason_strings(record):
                blocked_reason_counter[reason] += 1

    findings_by_severity = Counter(finding.severity for finding in findings)
    findings_by_type = Counter(finding.finding_type for finding in findings)
    warning_patterns = Counter(
        warning
        for snapshot in snapshots
        for warning in snapshot.key_warnings
    )

    still_actionable_count = sum(
        1
        for entry in outcomes.entries
        if entry.current_relevance_status in {"still_best_eligible", "still_actionable_but_not_best"}
    )
    deteriorated_count = sum(
        1
        for entry in outcomes.entries
        if entry.current_relevance_status == "later_deteriorated"
    )

    accepted_vs_paper_only = _accepted_vs_paper_only_summary(accepted_nav, paper_only_nav)
    hold_vs_exit = _hold_vs_exit_summary(paper_hold, paper_exit)

    benchmark_supported = (
        paper_exit.benchmark_summary.supported
        and paper_exit.benchmark_summary.simple_return_pct is not None
        and paper_exit.comparison_summary.benchmark_comparison_supported
    )
    benchmark_summary = ForwardPilotBenchmarkSummary(
        supported=bool(benchmark_supported),
        benchmark_ticker=paper_exit.benchmark_summary.benchmark_ticker,
        simple_return_pct=paper_exit.benchmark_summary.simple_return_pct,
        interpretation=(
            "Benchmark comparison is only directional and uses the same broad local paper window."
            if benchmark_supported
            else "Benchmark comparison was not supported by the available local pilot data."
        ),
        notes=list(paper_exit.comparison_summary.notes),
    )

    note = _sample_size_note(len(decisions))
    if note:
        missing_data_notes.append(note)
        warnings.append(note)

    if not accepted_vs_paper_only.supported:
        missing_data_notes.extend(accepted_vs_paper_only.notes)
    if not hold_vs_exit.supported:
        missing_data_notes.extend(hold_vs_exit.notes)

    operational_summary = ForwardPilotOperationalSummary(
        total_decisions=len(decisions),
        reviewed_decisions=outcomes.summary.reviewed_decisions,
        still_actionable_count=still_actionable_count,
        deteriorated_count=deteriorated_count,
        decisions_with_later_findings=outcomes.summary.decisions_with_later_findings,
        snapshots_in_period=len(snapshots),
        sample_size_note=note,
    )
    decision_summary = ForwardPilotDecisionSummary(
        decisions_by_action_taken=_top_items(action_counter, limit=10),
        decisions_by_recommendation_status=_top_items(status_counter, limit=10),
        top_blocked_reasons=_top_items(blocked_reason_counter),
    )
    monitoring_summary = ForwardPilotMonitoringSummary(
        findings_generated=len(findings),
        findings_by_severity=_top_items(findings_by_severity, limit=10),
        findings_by_type=_top_items(findings_by_type, limit=10),
        snapshots_in_period=len(snapshots),
        top_warning_patterns=_top_items(warning_patterns),
    )
    paper_portfolio_summary = ForwardPilotPaperPortfolioSummary(
        cohort_definition=request.paper_cohort_definition,
        supported_positions=paper_exit.nav_summary.supported_positions,
        unsupported_positions=paper_exit.nav_summary.unsupported_positions,
        hold_only_simple_return_pct=paper_hold.nav_summary.total_portfolio_simple_return_pct,
        exit_policy_simple_return_pct=paper_exit.nav_summary.total_portfolio_simple_return_pct,
        exit_policy_ending_value_difference=paper_exit.comparison_summary.exit_policy_ending_value_difference,
        active_positions_count=paper_exit.active_positions_count,
        exited_positions_count=paper_exit.exited_positions_count,
        unsupported_exit_count=paper_exit.unsupported_exit_count,
        exit_reason_distribution=[ForwardPilotCountItem(item=item.item, count=item.count) for item in paper_exit.exit_reason_distribution],
    )
    cohort_comparison_summary = ForwardPilotCohortComparisonSummary(
        accepted_vs_paper_only=accepted_vs_paper_only,
        hold_only_vs_exit_policy=hold_vs_exit,
    )

    notable_patterns: list[str] = []
    if accepted_vs_paper_only.supported:
        notable_patterns.append(accepted_vs_paper_only.interpretation)
    if hold_vs_exit.supported:
        notable_patterns.append(hold_vs_exit.interpretation)
    if operational_summary.still_actionable_count:
        notable_patterns.append(
            f"{operational_summary.still_actionable_count} pilot decision(s) still look locally actionable in later review."
        )
    if monitoring_summary.findings_by_type:
        top_finding = monitoring_summary.findings_by_type[0]
        notable_patterns.append(f"Most frequent pilot warning pattern: {top_finding.item} ({top_finding.count}).")
    if not notable_patterns:
        notable_patterns.append("No strong forward-validation patterns were available from the selected local pilot window.")

    next_review_actions: list[str] = []
    if findings_by_severity.get("critical", 0):
        next_review_actions.append("Review critical monitoring findings before the next weekly pilot check.")
    if paper_exit.unsupported_exit_count or paper_exit.nav_summary.unsupported_positions:
        next_review_actions.append("Repair missing local price or monitoring coverage for unsupported pilot positions or exits.")
    if blocked_reason_counter:
        next_review_actions.append("Review the most common blocked reasons and decide whether profile, policy, or knowledge notes need refinement.")
    if outcomes.summary.watchlist_or_paper_only_later_actionable:
        next_review_actions.append("Revisit watchlist or paper-only ideas that later became actionable before the next review cycle.")
    if not next_review_actions:
        next_review_actions.append("Run the same weekly pilot review again next period to keep the local forward-validation trail consistent.")

    warnings.extend(scorecard.warnings)
    warnings.extend(outcomes.warnings)
    warnings.extend(paper_exit.warnings)
    missing_data_notes.extend(scorecard.journal_summary.missing_data_notes)
    missing_data_notes.extend(scorecard.findings_summary.missing_data_notes)
    missing_data_notes.extend(scorecard.monitoring_summary.missing_data_notes)
    missing_data_notes.extend(paper_exit.missing_data_notes)
    missing_data_notes.extend(accepted_vs_paper_only.notes)
    missing_data_notes.extend(hold_vs_exit.notes)

    pilot_window = ForwardPilotWindow(
        pilot_start=request.date_from,
        pilot_end=request.date_to,
        label=_pilot_window_label(request.date_from, request.date_to),
    )
    review_protocol = ForwardPilotReviewProtocol(
        pilot_start=pilot_window.pilot_start,
        pilot_end=pilot_window.pilot_end,
        review_cadence=request.review_cadence,
        total_decisions_in_period=len(decisions),
        accepted_count=action_counter.get("accepted", 0),
        rejected_count=action_counter.get("rejected", 0),
        watchlist_count=action_counter.get("watchlist", 0),
        paper_only_count=action_counter.get("paper_only", 0),
        eligible_count=sum(count for status, count in status_counter.items() if status in scorecard_service._USABLE_STATUSES),
        blocked_count=sum(count for status, count in status_counter.items() if status in scorecard_service._BLOCKED_STATUSES),
        findings_generated=len(findings),
        findings_by_severity=_top_items(findings_by_severity, limit=10),
        accepted_vs_paper_only_supported=accepted_vs_paper_only.supported,
        hold_only_vs_exit_policy_supported=hold_vs_exit.supported,
        benchmark_comparison_supported=benchmark_summary.supported,
    )

    return ForwardValidationPilotResponse(
        generated_at=_now_utc(),
        pilot_window=pilot_window,
        review_protocol=review_protocol,
        operational_summary=operational_summary,
        decision_summary=decision_summary,
        monitoring_summary=monitoring_summary,
        paper_portfolio_summary=paper_portfolio_summary,
        cohort_comparison_summary=cohort_comparison_summary,
        benchmark_summary=benchmark_summary,
        notable_patterns=notable_patterns,
        next_review_actions=next_review_actions,
        warnings=_unique(warnings),
        missing_data_notes=_unique(missing_data_notes),
    )
