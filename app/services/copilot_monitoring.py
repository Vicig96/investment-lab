"""Deterministic local monitoring checks for the personalized Investment Copilot."""
from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.copilot import RecommendationStatus
from app.schemas.copilot_monitoring import (
    FindingsListResponse,
    HoldingMonitoringState,
    MonitoringAssetState,
    MonitoringFinding,
    MonitoringRunRequest,
    MonitoringRunResponse,
    MonitoringSnapshotRecord,
    SnapshotComparison,
)
from app.services import copilot_journal as journal_service
from app.services.copilot_personalization import (
    DEFAULT_CONCENTRATION_LIMIT,
    load_investor_profile,
    load_local_portfolio,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_COPILOT_DIR = _REPO_ROOT / "data" / "copilot"

FINDINGS_PATH: Path = _COPILOT_DIR / "findings.jsonl"
SNAPSHOTS_PATH: Path = _COPILOT_DIR / "monitoring_snapshots.jsonl"

_TICKER_PATTERN = re.compile(r"^[A-Z][A-Z0-9.\-]{0,9}$")
_USABLE_STATUSES: set[str] = {
    "eligible",
    "eligible_with_cautions",
    "eligible_new_position",
    "eligible_add_to_existing",
}


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path: Path | None, default: Path) -> Path:
    return path if path is not None else default


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


def _append_jsonl(path: Path, rows: list[Any]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            if hasattr(row, "model_dump_json"):
                handle.write(row.model_dump_json() + "\n")
            else:
                handle.write(json.dumps(row) + "\n")


def _normalize_tickers(tickers: list[str] | None) -> list[str]:
    if not tickers:
        return []
    normalized: list[str] = []
    for ticker in tickers:
        value = ticker.strip().upper()
        if not value or value in normalized:
            continue
        normalized.append(value)
    return normalized


def _watchlist_tickers_from_journal() -> list[str]:
    tickers: list[str] = []
    for entry in journal_service.list_decisions(limit=500):
        if entry.action_taken not in {"watchlist", "paper_only"}:
            continue
        entity = None
        if entry.final_recommendation is not None and entry.final_recommendation.recommended_entity_type == "asset":
            entity = entry.final_recommendation.recommended_entity
        if entity is None:
            entity = entry.top_deterministic_result
        if not entity:
            continue
        candidate = entity.strip().upper()
        if not _TICKER_PATTERN.match(candidate) or candidate in tickers:
            continue
        tickers.append(candidate)
    return tickers


def _default_universe(
    *,
    profile,
    portfolio,
    watchlist_tickers: list[str],
    fallback_tickers: list[str],
) -> list[str]:
    combined: list[str] = []
    for ticker in fallback_tickers:
        if ticker not in combined:
            combined.append(ticker)
    if profile is not None:
        for ticker in [*profile.preferred_assets, *profile.disallowed_assets]:
            candidate = ticker.strip().upper()
            if candidate and candidate not in combined:
                combined.append(candidate)
    if portfolio is not None:
        for position in portfolio.positions:
            candidate = position.ticker.strip().upper()
            if candidate and candidate not in combined:
                combined.append(candidate)
    for ticker in watchlist_tickers:
        if ticker not in combined:
            combined.append(ticker)
    return combined


def _portfolio_weights(portfolio) -> dict[str, dict[str, float | None]]:
    if portfolio is None:
        return {}

    nav_estimate = float(portfolio.cash_available)
    values: dict[str, float] = {}
    for position in portfolio.positions:
        if position.avg_cost is None:
            continue
        value = float(position.quantity) * float(position.avg_cost)
        values[position.ticker.upper()] = value
        nav_estimate += value

    result: dict[str, dict[str, float | None]] = {}
    for position in portfolio.positions:
        ticker = position.ticker.upper()
        value = values.get(ticker)
        result[ticker] = {
            "estimated_weight_pct": (value / nav_estimate) if value is not None and nav_estimate > 0 else None,
            "concentration_limit_pct": float(position.max_position_size_pct)
            if position.max_position_size_pct is not None
            else DEFAULT_CONCENTRATION_LIMIT,
        }
    return result


def build_snapshot_comparison(
    previous: MonitoringSnapshotRecord | None,
    current: MonitoringSnapshotRecord,
) -> SnapshotComparison:
    if previous is None:
        return SnapshotComparison(
            has_prior_snapshot=False,
            current_best_eligible_asset=current.best_eligible_asset,
            current_recommendation_status=current.best_eligible_status,
        )

    previous_warnings = set(previous.key_warnings)
    current_warnings = set(current.key_warnings)
    return SnapshotComparison(
        has_prior_snapshot=True,
        previous_best_eligible_asset=previous.best_eligible_asset,
        current_best_eligible_asset=current.best_eligible_asset,
        best_eligible_asset_changed=previous.best_eligible_asset != current.best_eligible_asset,
        previous_recommendation_status=previous.best_eligible_status,
        current_recommendation_status=current.best_eligible_status,
        recommendation_status_changed=previous.best_eligible_status != current.best_eligible_status,
        new_key_warnings=sorted(current_warnings - previous_warnings),
        cleared_key_warnings=sorted(previous_warnings - current_warnings),
    )


def latest_snapshot(*, snapshots_path: Path | None = None) -> MonitoringSnapshotRecord | None:
    path = _resolve_path(snapshots_path, SNAPSHOTS_PATH)
    latest: MonitoringSnapshotRecord | None = None
    for obj in _read_jsonl(path):
        try:
            record = MonitoringSnapshotRecord.model_validate(obj)
        except Exception:
            continue
        if latest is None or record.timestamp > latest.timestamp:
            latest = record
    return latest


def _save_snapshot(record: MonitoringSnapshotRecord, *, snapshots_path: Path | None = None) -> MonitoringSnapshotRecord:
    _append_jsonl(_resolve_path(snapshots_path, SNAPSHOTS_PATH), [record])
    return record


def _save_findings(findings: list[MonitoringFinding], *, findings_path: Path | None = None) -> list[MonitoringFinding]:
    _append_jsonl(_resolve_path(findings_path, FINDINGS_PATH), findings)
    return findings


def _filtered_findings(
    findings: list[MonitoringFinding],
    *,
    entity: str | None = None,
    finding_type: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[MonitoringFinding]:
    filtered: list[MonitoringFinding] = []
    needle = entity.upper() if entity else None
    for finding in findings:
        if needle and needle not in (finding.entity or "").upper():
            continue
        if finding_type and finding.finding_type != finding_type:
            continue
        if severity and finding.severity != severity:
            continue
        ts_date = finding.timestamp[:10]
        if date_from and ts_date < date_from:
            continue
        if date_to and ts_date > date_to:
            continue
        filtered.append(finding)
    filtered.sort(key=lambda item: item.timestamp, reverse=True)
    return filtered


def list_findings(
    *,
    entity: str | None = None,
    finding_type: str | None = None,
    severity: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    findings_path: Path | None = None,
) -> FindingsListResponse:
    path = _resolve_path(findings_path, FINDINGS_PATH)
    findings: list[MonitoringFinding] = []
    for obj in _read_jsonl(path):
        try:
            findings.append(MonitoringFinding.model_validate(obj))
        except Exception:
            continue
    filtered = _filtered_findings(
        findings,
        entity=entity,
        finding_type=finding_type,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
    )
    return FindingsListResponse(entries=filtered[:limit], total=len(filtered))


def _finding(
    *,
    finding_type,
    severity,
    entity,
    headline,
    summary,
    why_it_matters,
    suggested_next_action,
    source_snapshot_ref: str,
    timestamp: str,
) -> MonitoringFinding:
    return MonitoringFinding(
        finding_id=str(uuid.uuid4()),
        timestamp=timestamp,
        finding_type=finding_type,
        severity=severity,
        entity=entity,
        headline=headline,
        summary=summary,
        why_it_matters=why_it_matters,
        suggested_next_action=suggested_next_action,
        source_snapshot_ref=source_snapshot_ref,
    )


def _asset_state_by_ticker(snapshot: MonitoringSnapshotRecord) -> dict[str, MonitoringAssetState]:
    return {item.ticker: item for item in snapshot.monitored_assets}


def _is_usable(status: RecommendationStatus | None) -> bool:
    return status in _USABLE_STATUSES


async def run_monitoring_checks(
    session: AsyncSession,
    request: MonitoringRunRequest,
    *,
    findings_path: Path | None = None,
    snapshots_path: Path | None = None,
) -> MonitoringRunResponse:
    import app.services.copilot as copilot_service

    warnings: list[str] = []
    profile, profile_warnings = load_investor_profile()
    portfolio, portfolio_warnings = load_local_portfolio()
    warnings.extend(profile_warnings)
    warnings.extend(portfolio_warnings)

    watchlist_tickers = _watchlist_tickers_from_journal()
    universe = _normalize_tickers(request.instrument_tickers)

    if not universe:
        universe = _default_universe(
            profile=profile,
            portfolio=portfolio,
            watchlist_tickers=watchlist_tickers,
            fallback_tickers=list(copilot_service.DEFAULT_CHAT_TICKERS),
        )

    try:
        known_tickers = await copilot_service._get_known_tickers(session)
    except Exception:
        known_tickers = set()

    if known_tickers:
        unknown = [ticker for ticker in universe if ticker not in known_tickers]
        if unknown:
            warnings.append(
                "Some monitoring tickers are not available in the local instrument universe: "
                + ", ".join(unknown)
                + "."
            )
        universe = [ticker for ticker in universe if ticker in known_tickers]

    previous_snapshot = latest_snapshot(snapshots_path=snapshots_path)
    timestamp = _now_utc()
    snapshot_id = str(uuid.uuid4())

    if not universe:
        current_snapshot = MonitoringSnapshotRecord(
            snapshot_id=snapshot_id,
            timestamp=timestamp,
            universe_tickers=[],
            watchlist_tickers=watchlist_tickers,
            key_warnings=[],
            monitored_assets=[],
            holdings=[],
        )
        comparison = build_snapshot_comparison(previous_snapshot, current_snapshot)
        if request.save_snapshot:
            _save_snapshot(current_snapshot, snapshots_path=snapshots_path)
        warnings.append("Monitoring could not run because no eligible local tickers were available.")
        return MonitoringRunResponse(
            summary="Monitoring could not evaluate any local tickers, so no findings were produced.",
            current_snapshot=current_snapshot,
            comparison=comparison,
            findings=[],
            warnings=warnings,
        )

    dfs = await copilot_service.load_ohlcv_multi(session, universe, None, None)
    ranking = None
    explanation = None
    if dfs:
        ranking = copilot_service._build_rank_assets_response(dfs, top_n=len(dfs))
        explanation = copilot_service.explain_recommendation_tool(
            copilot_service.ExplainRecommendationRequest(source="rank_assets", ranking=ranking)
        )
        warnings.extend(ranking.warnings)
        warnings.extend(explanation.caveats)
    else:
        warnings.append("No local price data was available for the monitoring universe.")

    monitored_assets: list[MonitoringAssetState] = []
    for rank_index, asset in enumerate(ranking.ranked_assets if ranking is not None else [], start=1):
        policy, kb, portfolio_context = copilot_service._ranked_asset_policy_snapshot(
            asset,
            profile=profile,
            portfolio=portfolio,
        )
        monitored_assets.append(
            MonitoringAssetState(
                ticker=asset.ticker,
                rank=rank_index,
                recommendation_status=portfolio_context["recommendation_status"],
                recommended_action_type=portfolio_context["recommended_action_type"],
                is_watchlist=asset.ticker in watchlist_tickers,
                is_holding=portfolio is not None and any(position.ticker.upper() == asset.ticker for position in portfolio.positions),
                has_knowledge_support=bool(kb.matches),
                drawdown_60d=asset.drawdown_60d,
                hard_conflicts=list(policy["hard_conflicts"]),
                concentration_notes=list(portfolio_context["concentration_notes"]),
                warnings=[*policy["warnings"], *portfolio_context["warnings"], *kb.warnings],
            )
        )

    asset_map = {item.ticker: item for item in monitored_assets}
    weight_map = _portfolio_weights(portfolio)
    holdings: list[HoldingMonitoringState] = []
    missing_tickers = sorted(set(universe) - set(dfs.keys()))
    key_warnings: list[str] = []

    if explanation is not None:
        key_warnings.extend(explanation.caveats[:5])

    for ticker in missing_tickers:
        if ticker in watchlist_tickers or (portfolio is not None and any(position.ticker.upper() == ticker for position in portfolio.positions)):
            key_warnings.append(f"Missing local market data for monitored ticker {ticker}.")

    if portfolio is not None:
        for position in portfolio.positions:
            ticker = position.ticker.upper()
            state = asset_map.get(ticker)
            weights = weight_map.get(ticker, {})
            if state is None:
                key_warnings.append(f"Missing local market data for held ticker {ticker}.")
                holdings.append(
                    HoldingMonitoringState(
                        ticker=ticker,
                        data_status="missing_data",
                        estimated_weight_pct=weights.get("estimated_weight_pct"),
                        concentration_limit_pct=weights.get("concentration_limit_pct"),
                        warnings=[f"No local market data was available for held ticker {ticker}."],
                    )
                )
                continue

            holdings.append(
                HoldingMonitoringState(
                    ticker=ticker,
                    data_status="ok",
                    recommendation_status=state.recommendation_status,
                    drawdown_60d=state.drawdown_60d,
                    drawdown_limit=(profile.max_acceptable_drawdown if profile is not None else None),
                    estimated_weight_pct=weights.get("estimated_weight_pct"),
                    concentration_limit_pct=weights.get("concentration_limit_pct"),
                    hard_conflicts=state.hard_conflicts,
                    concentration_notes=state.concentration_notes,
                    warnings=state.warnings,
                )
            )
            if state.hard_conflicts:
                key_warnings.append(f"Holding {ticker} conflicts with the active profile or policy.")
            if (
                weights.get("estimated_weight_pct") is not None
                and weights.get("concentration_limit_pct") is not None
                and weights["estimated_weight_pct"] > weights["concentration_limit_pct"]
            ):
                key_warnings.append(f"Holding {ticker} exceeds the local concentration limit.")
            if (
                state.drawdown_60d is not None
                and profile is not None
                and profile.max_acceptable_drawdown is not None
                and abs(state.drawdown_60d) > profile.max_acceptable_drawdown
            ):
                key_warnings.append(f"Holding {ticker} exceeds the active drawdown threshold.")

    current_snapshot = MonitoringSnapshotRecord(
        snapshot_id=snapshot_id,
        timestamp=timestamp,
        universe_tickers=universe,
        watchlist_tickers=watchlist_tickers,
        top_deterministic_result=(explanation.top_deterministic_result if explanation is not None else None),
        best_eligible_asset=(explanation.recommended_entity if explanation is not None else None),
        best_eligible_status=(explanation.recommendation_status if explanation is not None else None),
        best_eligible_action=(explanation.recommended_action_type if explanation is not None else None),
        key_warnings=sorted(dict.fromkeys(key_warnings)),
        monitored_assets=monitored_assets,
        holdings=holdings,
    )
    comparison = build_snapshot_comparison(previous_snapshot, current_snapshot)

    findings: list[MonitoringFinding] = []

    if previous_snapshot is not None and current_snapshot.best_eligible_asset and _is_usable(current_snapshot.best_eligible_status):
        if not _is_usable(previous_snapshot.best_eligible_status):
            findings.append(
                _finding(
                    finding_type="newly_eligible_recommendation",
                    severity="info",
                    entity=current_snapshot.best_eligible_asset,
                    headline=f"New eligible idea: {current_snapshot.best_eligible_asset}",
                    summary=(
                        f"{current_snapshot.best_eligible_asset} is now the current usable recommendation "
                        f"with status {current_snapshot.best_eligible_status}."
                    ),
                    why_it_matters="A previously non-actionable recommendation has become usable under the current profile, knowledge, and portfolio context.",
                    suggested_next_action="Review the latest copilot recommendation details and decide whether to journal or paper-track it.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )

    if comparison.has_prior_snapshot and comparison.best_eligible_asset_changed and current_snapshot.best_eligible_asset:
        findings.append(
            _finding(
                finding_type="best_eligible_asset_changed",
                severity="warning",
                entity=current_snapshot.best_eligible_asset,
                headline="Best eligible asset changed",
                summary=(
                    f"Best eligible asset changed from {comparison.previous_best_eligible_asset or 'none'} "
                    f"to {current_snapshot.best_eligible_asset}."
                ),
                why_it_matters="The leading personalized idea is no longer the same as the last saved monitoring snapshot.",
                suggested_next_action="Compare the new leader with the prior idea before acting.",
                source_snapshot_ref=current_snapshot.snapshot_id,
                timestamp=timestamp,
            )
        )

    previous_asset_map = _asset_state_by_ticker(previous_snapshot) if previous_snapshot is not None else {}
    for state in current_snapshot.monitored_assets:
        previous_state = previous_asset_map.get(state.ticker)
        if state.is_watchlist and _is_usable(state.recommendation_status) and not _is_usable(previous_state.recommendation_status if previous_state else None):
            findings.append(
                _finding(
                    finding_type="watchlist_became_eligible",
                    severity="info",
                    entity=state.ticker,
                    headline=f"Watchlist item became eligible: {state.ticker}",
                    summary=f"{state.ticker} now has status {state.recommendation_status}.",
                    why_it_matters="A watchlist or paper-only idea has moved into a usable state.",
                    suggested_next_action="Review the latest recommendation and decide whether to keep it on watchlist or promote it.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )

    for holding in current_snapshot.holdings:
        if holding.data_status == "missing_data":
            findings.append(
                _finding(
                    finding_type="missing_data",
                    severity="warning",
                    entity=holding.ticker,
                    headline=f"Missing monitoring data for {holding.ticker}",
                    summary=holding.warnings[0] if holding.warnings else f"No monitoring data was available for held ticker {holding.ticker}.",
                    why_it_matters="This holding could not be fully checked during the current monitoring pass.",
                    suggested_next_action="Load or repair local market data before relying on monitoring conclusions for this holding.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )
            continue

        if holding.hard_conflicts:
            findings.append(
                _finding(
                    finding_type="holding_rule_violation",
                    severity="critical",
                    entity=holding.ticker,
                    headline=f"Holding violates profile or policy: {holding.ticker}",
                    summary=holding.hard_conflicts[0],
                    why_it_matters="A currently held asset now conflicts with the active profile or policy constraints.",
                    suggested_next_action="Review the conflict and decide whether the holding needs an exception, reduction, or exit plan.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )

        if (
            holding.drawdown_60d is not None
            and holding.drawdown_limit is not None
            and abs(holding.drawdown_60d) > holding.drawdown_limit
        ):
            findings.append(
                _finding(
                    finding_type="holding_drawdown_breach",
                    severity="warning",
                    entity=holding.ticker,
                    headline=f"Holding drawdown threshold breached: {holding.ticker}",
                    summary=(
                        f"Observed drawdown {abs(holding.drawdown_60d):.2%} exceeds the profile limit "
                        f"of {holding.drawdown_limit:.2%}."
                    ),
                    why_it_matters="The holding has moved beyond the current drawdown budget used by the personalized copilot.",
                    suggested_next_action="Review downside risk, thesis durability, and whether the position still fits the profile.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )

        if (
            holding.estimated_weight_pct is not None
            and holding.concentration_limit_pct is not None
            and holding.estimated_weight_pct > holding.concentration_limit_pct
        ):
            findings.append(
                _finding(
                    finding_type="portfolio_concentration_warning",
                    severity="warning",
                    entity=holding.ticker,
                    headline=f"Portfolio concentration warning: {holding.ticker}",
                    summary=(
                        f"Estimated weight {holding.estimated_weight_pct:.1%} exceeds the local concentration limit "
                        f"of {holding.concentration_limit_pct:.1%}."
                    ),
                    why_it_matters="An oversized holding can dominate portfolio behavior and weaken diversification discipline.",
                    suggested_next_action="Review sizing discipline before adding further exposure.",
                    source_snapshot_ref=current_snapshot.snapshot_id,
                    timestamp=timestamp,
                )
            )

    if explanation is not None and explanation.top_deterministic_result and explanation.recommendation_status == "unsupported_by_knowledge":
        findings.append(
            _finding(
                finding_type="thesis_support_missing",
                severity="warning",
                entity=explanation.top_deterministic_result,
                headline="Knowledge support missing for current candidate",
                summary=(
                    f"{explanation.top_deterministic_result} is the current deterministic leader, "
                    "but local thesis or rule support is missing."
                ),
                why_it_matters="The system has deterministic market evidence, but the personalized knowledge layer does not yet justify acting on it.",
                suggested_next_action="Add or review the relevant thesis, rule, or experiment note before treating the idea as actionable.",
                source_snapshot_ref=current_snapshot.snapshot_id,
                timestamp=timestamp,
            )
        )

    summary: str
    if not comparison.has_prior_snapshot:
        summary = "Monitoring baseline saved. No prior snapshot was available for change detection."
    elif not findings:
        summary = "No material monitoring changes were detected since the last saved snapshot."
    else:
        summary = f"{len(findings)} monitoring finding(s) were generated from the latest deterministic check."

    if request.save_snapshot:
        _save_snapshot(current_snapshot, snapshots_path=snapshots_path)
        _save_findings(findings, findings_path=findings_path)

    return MonitoringRunResponse(
        summary=summary,
        current_snapshot=current_snapshot,
        comparison=comparison,
        findings=findings,
        warnings=warnings,
    )
