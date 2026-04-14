"""Local decision journal JSONL store.

One ``DecisionRecord`` is stored per line. The journal is intentionally local,
lean, deterministic, and independent from the database.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

from app.schemas.copilot_journal import (
    DecisionCreateRequest,
    DecisionPatch,
    DecisionRecord,
)

_REPO_ROOT = Path(__file__).parent.parent.parent
_COPILOT_DIR = _REPO_ROOT / "data" / "copilot"

JOURNAL_PATH: Path = _COPILOT_DIR / "journal.jsonl"


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(journal_path: Path | None) -> Path:
    return journal_path if journal_path is not None else JOURNAL_PATH


def _read_all(path: Path) -> list[dict]:
    """Return all valid JSON objects from the journal file."""
    if not path.exists():
        return []

    records: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return records


def _ticker_strings(record: DecisionRecord) -> list[str]:
    values = [record.top_deterministic_result or ""]
    if record.final_recommendation is not None:
        values.append(record.final_recommendation.recommended_entity or "")
    return values


def _matches_ticker(record: DecisionRecord, ticker: str) -> bool:
    needle = ticker.upper()
    return any(needle in value.upper() for value in _ticker_strings(record) if value)


def _filter_records(
    records: list[DecisionRecord],
    *,
    ticker: str | None = None,
    recommendation_status: str | None = None,
    action_taken: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[DecisionRecord]:
    filtered: list[DecisionRecord] = []

    for record in records:
        if ticker and not _matches_ticker(record, ticker):
            continue
        if recommendation_status and record.recommendation_status != recommendation_status:
            continue
        if action_taken and record.action_taken != action_taken:
            continue

        ts_date = record.timestamp[:10]
        if date_from and ts_date < date_from:
            continue
        if date_to and ts_date > date_to:
            continue

        filtered.append(record)

    filtered.sort(key=lambda item: item.timestamp, reverse=True)
    return filtered


def create_decision(body: DecisionCreateRequest) -> DecisionRecord:
    """Build a new journal record without writing it to disk."""
    now = _now_utc()
    return DecisionRecord(
        decision_id=str(uuid.uuid4()),
        timestamp=now,
        user_query=body.user_query,
        detected_intent=body.detected_intent,
        top_deterministic_result=body.top_deterministic_result,
        final_recommendation=body.final_recommendation,
        recommendation_status=body.recommendation_status,
        recommended_action_type=body.recommended_action_type,
        profile_constraints_applied=body.profile_constraints_applied,
        knowledge_sources_used=body.knowledge_sources_used,
        portfolio_context_applied=body.portfolio_context_applied,
        portfolio_decision_summary=body.portfolio_decision_summary,
        action_taken=body.action_taken,
        action_taken_timestamp=(now if body.action_taken else None),
        review_date=body.review_date,
        outcome_notes=body.outcome_notes,
    )


def save_decision(
    record: DecisionRecord,
    *,
    journal_path: Path | None = None,
) -> DecisionRecord:
    """Append a journal record to the JSONL file."""
    path = _resolve_path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(record.model_dump_json() + "\n")
    return record


def get_decision(
    decision_id: str,
    *,
    journal_path: Path | None = None,
) -> DecisionRecord | None:
    """Return a journal record by ID, or ``None`` if it does not exist."""
    path = _resolve_path(journal_path)
    for obj in _read_all(path):
        if obj.get("decision_id") != decision_id:
            continue
        try:
            return DecisionRecord.model_validate(obj)
        except Exception:
            return None
    return None


def update_decision(
    decision_id: str,
    patch: DecisionPatch,
    *,
    journal_path: Path | None = None,
) -> DecisionRecord | None:
    """Apply a partial update to an existing journal record."""
    path = _resolve_path(journal_path)
    existing = _read_all(path)
    if not existing:
        return None

    updated_record: DecisionRecord | None = None
    new_lines: list[str] = []

    for obj in existing:
        if obj.get("decision_id") != decision_id:
            new_lines.append(json.dumps(obj))
            continue

        patch_data = patch.model_dump(exclude_none=True)
        if "action_taken" in patch_data and "action_taken_timestamp" not in patch_data:
            patch_data["action_taken_timestamp"] = _now_utc()
        obj.update(patch_data)

        try:
            record = DecisionRecord.model_validate(obj)
        except Exception:
            new_lines.append(json.dumps(obj))
            continue

        new_lines.append(record.model_dump_json())
        updated_record = record

    if updated_record is not None:
        path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    return updated_record


def list_decisions(
    ticker: str | None = None,
    recommendation_status: str | None = None,
    action_taken: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 50,
    *,
    journal_path: Path | None = None,
) -> list[DecisionRecord]:
    """Return filtered journal entries, newest first."""
    path = _resolve_path(journal_path)
    records: list[DecisionRecord] = []

    for obj in _read_all(path):
        try:
            records.append(DecisionRecord.model_validate(obj))
        except Exception:
            continue

    return _filter_records(
        records,
        ticker=ticker,
        recommendation_status=recommendation_status,
        action_taken=action_taken,
        date_from=date_from,
        date_to=date_to,
    )[:limit]


def count_decisions(
    *,
    ticker: str | None = None,
    recommendation_status: str | None = None,
    action_taken: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    journal_path: Path | None = None,
) -> int:
    """Return the number of matching journal entries before limiting."""
    path = _resolve_path(journal_path)
    records: list[DecisionRecord] = []

    for obj in _read_all(path):
        try:
            records.append(DecisionRecord.model_validate(obj))
        except Exception:
            continue

    return len(
        _filter_records(
            records,
            ticker=ticker,
            recommendation_status=recommendation_status,
            action_taken=action_taken,
            date_from=date_from,
            date_to=date_to,
        )
    )
