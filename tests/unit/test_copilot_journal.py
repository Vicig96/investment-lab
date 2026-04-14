"""Unit tests for the local decision journal service.

All tests use a temporary journal path so the real data/copilot/journal.jsonl
is never touched.  Tests are pure Python — no FastAPI, no DB, no mocks needed.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.services.copilot_journal as journal_service
from app.schemas.copilot_journal import (
    DecisionCreateRequest,
    DecisionPatch,
    DecisionRecord,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _jp(tmp_path: Path) -> Path:
    """Return a temp journal path (file does not need to exist beforehand)."""
    return tmp_path / "journal.jsonl"


def _req(**kwargs) -> DecisionCreateRequest:
    defaults: dict = {
        "user_query": "Rank SPY, QQQ, TLT",
        "detected_intent": "asset_ranking",
        "top_deterministic_result": "SPY",
        "recommendation_status": "eligible",
        "recommended_action_type": "open_new_position",
    }
    defaults.update(kwargs)
    return DecisionCreateRequest(**defaults)


def _save(tmp_path: Path, **kwargs) -> DecisionRecord:
    jp = _jp(tmp_path)
    record = journal_service.create_decision(_req(**kwargs))
    return journal_service.save_decision(record, journal_path=jp)


# ── save_decision ──────────────────────────────────────────────────────────────

def test_save_creates_file(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    assert not jp.exists()
    record = journal_service.create_decision(_req())
    journal_service.save_decision(record, journal_path=jp)
    assert jp.exists()


def test_save_writes_valid_json_line(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    record = journal_service.create_decision(_req())
    journal_service.save_decision(record, journal_path=jp)
    lines = [ln for ln in jp.read_text().splitlines() if ln.strip()]
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["user_query"] == "Rank SPY, QQQ, TLT"
    assert obj["top_deterministic_result"] == "SPY"
    assert "decision_id" in obj
    assert "timestamp" in obj


def test_save_appends_multiple_records(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for i in range(4):
        r = journal_service.create_decision(_req(user_query=f"Query {i}"))
        journal_service.save_decision(r, journal_path=jp)
    lines = [ln for ln in jp.read_text().splitlines() if ln.strip()]
    assert len(lines) == 4


def test_save_returns_the_record(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    record = journal_service.create_decision(_req())
    returned = journal_service.save_decision(record, journal_path=jp)
    assert returned.decision_id == record.decision_id


def test_create_decision_generates_unique_ids() -> None:
    r1 = journal_service.create_decision(_req())
    r2 = journal_service.create_decision(_req())
    assert r1.decision_id != r2.decision_id


def test_create_decision_with_initial_action_sets_timestamp() -> None:
    record = journal_service.create_decision(_req(action_taken="watchlist"))
    assert record.action_taken == "watchlist"
    assert record.action_taken_timestamp is not None


def test_create_decision_without_action_no_timestamp() -> None:
    record = journal_service.create_decision(_req())
    assert record.action_taken is None
    assert record.action_taken_timestamp is None


# ── get_decision ───────────────────────────────────────────────────────────────

def test_get_retrieves_by_id(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req(user_query="Find GLD opportunity"))
    journal_service.save_decision(r, journal_path=jp)

    retrieved = journal_service.get_decision(r.decision_id, journal_path=jp)
    assert retrieved is not None
    assert retrieved.decision_id == r.decision_id
    assert retrieved.user_query == "Find GLD opportunity"


def test_get_returns_none_for_unknown_id(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    result = journal_service.get_decision("nonexistent-uuid-999", journal_path=jp)
    assert result is None


def test_get_missing_file_returns_none(tmp_path: Path) -> None:
    jp = tmp_path / "does_not_exist.jsonl"
    result = journal_service.get_decision("anything", journal_path=jp)
    assert result is None


# ── update_decision ────────────────────────────────────────────────────────────

def test_update_action_accepted(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    updated = journal_service.update_decision(
        r.decision_id, DecisionPatch(action_taken="accepted"), journal_path=jp
    )
    assert updated is not None
    assert updated.action_taken == "accepted"


def test_update_action_rejected(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    updated = journal_service.update_decision(
        r.decision_id, DecisionPatch(action_taken="rejected"), journal_path=jp
    )
    assert updated is not None
    assert updated.action_taken == "rejected"


def test_update_action_watchlist(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    updated = journal_service.update_decision(
        r.decision_id, DecisionPatch(action_taken="watchlist"), journal_path=jp
    )
    assert updated is not None
    assert updated.action_taken == "watchlist"


def test_update_action_paper_only(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    updated = journal_service.update_decision(
        r.decision_id, DecisionPatch(action_taken="paper_only"), journal_path=jp
    )
    assert updated is not None
    assert updated.action_taken == "paper_only"


def test_update_auto_sets_action_timestamp(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)
    assert r.action_taken_timestamp is None

    updated = journal_service.update_decision(
        r.decision_id, DecisionPatch(action_taken="accepted"), journal_path=jp
    )
    assert updated is not None
    assert updated.action_taken_timestamp is not None


def test_update_explicit_timestamp_is_respected(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    explicit_ts = "2024-01-01T00:00:00+00:00"
    updated = journal_service.update_decision(
        r.decision_id,
        DecisionPatch(action_taken="accepted", action_taken_timestamp=explicit_ts),
        journal_path=jp,
    )
    assert updated is not None
    assert updated.action_taken_timestamp == explicit_ts


def test_update_review_and_outcome_notes(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    updated = journal_service.update_decision(
        r.decision_id,
        DecisionPatch(review_date="2024-09-01", outcome_notes="SPY +6% over test window."),
        journal_path=jp,
    )
    assert updated is not None
    assert updated.review_date == "2024-09-01"
    assert updated.outcome_notes == "SPY +6% over test window."


def test_update_nonexistent_returns_none(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    result = journal_service.update_decision(
        "nonexistent-uuid", DecisionPatch(action_taken="accepted"), journal_path=jp
    )
    assert result is None


def test_update_missing_file_returns_none(tmp_path: Path) -> None:
    jp = tmp_path / "no_file.jsonl"
    result = journal_service.update_decision(
        "anything", DecisionPatch(action_taken="accepted"), journal_path=jp
    )
    assert result is None


def test_update_preserves_other_records(tmp_path: Path) -> None:
    """Updating one record must not corrupt or remove other records."""
    jp = _jp(tmp_path)
    records = []
    for i in range(3):
        r = journal_service.create_decision(_req(user_query=f"Query {i}"))
        journal_service.save_decision(r, journal_path=jp)
        records.append(r)

    # Update the middle one.
    journal_service.update_decision(
        records[1].decision_id,
        DecisionPatch(action_taken="accepted"),
        journal_path=jp,
    )

    all_results = journal_service.list_decisions(journal_path=jp)
    assert len(all_results) == 3

    updated = journal_service.get_decision(records[1].decision_id, journal_path=jp)
    assert updated is not None
    assert updated.action_taken == "accepted"

    untouched = journal_service.get_decision(records[0].decision_id, journal_path=jp)
    assert untouched is not None
    assert untouched.action_taken is None


def test_update_is_persisted(tmp_path: Path) -> None:
    """Updated value must survive a second read from disk."""
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    journal_service.update_decision(
        r.decision_id,
        DecisionPatch(action_taken="rejected", outcome_notes="Changed mind."),
        journal_path=jp,
    )

    # Re-read from disk.
    re_read = journal_service.get_decision(r.decision_id, journal_path=jp)
    assert re_read is not None
    assert re_read.action_taken == "rejected"
    assert re_read.outcome_notes == "Changed mind."


# ── list_decisions ─────────────────────────────────────────────────────────────

def test_list_missing_file_returns_empty(tmp_path: Path) -> None:
    jp = tmp_path / "no_file.jsonl"
    result = journal_service.list_decisions(journal_path=jp)
    assert result == []


def test_list_returns_all_records(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for i in range(5):
        r = journal_service.create_decision(_req(user_query=f"Q{i}"))
        journal_service.save_decision(r, journal_path=jp)
    results = journal_service.list_decisions(journal_path=jp)
    assert len(results) == 5


def test_list_newest_first(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    saved_records = []
    for i in range(3):
        r = journal_service.create_decision(_req(user_query=f"Q{i}"))
        journal_service.save_decision(r, journal_path=jp)
        saved_records.append(r)

    results = journal_service.list_decisions(journal_path=jp)
    # Timestamps are monotonically non-decreasing; list should be newest-first.
    for i in range(len(results) - 1):
        assert results[i].timestamp >= results[i + 1].timestamp


def test_list_filter_ticker(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for ticker in ["SPY", "QQQ", "SPY", "TLT", "SPY"]:
        r = journal_service.create_decision(_req(top_deterministic_result=ticker))
        journal_service.save_decision(r, journal_path=jp)

    results = journal_service.list_decisions(ticker="SPY", journal_path=jp)
    assert len(results) == 3
    assert all(r.top_deterministic_result == "SPY" for r in results)


def test_list_filter_ticker_case_insensitive(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req(top_deterministic_result="SPY"))
    journal_service.save_decision(r, journal_path=jp)

    assert len(journal_service.list_decisions(ticker="spy", journal_path=jp)) == 1
    assert len(journal_service.list_decisions(ticker="SPY", journal_path=jp)) == 1


def test_list_filter_ticker_matches_final_recommended_entity(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(
        _req(
            top_deterministic_result="QQQ",
            final_recommendation={
                "headline": "Alternative surfaced",
                "summary": "QQQ was blocked, so SPY became the portfolio-safe alternative.",
                "recommended_entity": "SPY",
                "recommended_entity_type": "asset",
            },
        )
    )
    journal_service.save_decision(r, journal_path=jp)

    results = journal_service.list_decisions(ticker="SPY", journal_path=jp)
    assert len(results) == 1
    assert results[0].decision_id == r.decision_id


def test_list_filter_recommendation_status(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for status in ["eligible", "eligible", "rejected_by_profile", "eligible_with_cautions"]:
        r = journal_service.create_decision(_req(recommendation_status=status))
        journal_service.save_decision(r, journal_path=jp)

    eligible = journal_service.list_decisions(recommendation_status="eligible", journal_path=jp)
    assert len(eligible) == 2

    rejected = journal_service.list_decisions(recommendation_status="rejected_by_profile", journal_path=jp)
    assert len(rejected) == 1


def test_list_filter_action_taken(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    ids = []
    for i in range(4):
        r = journal_service.create_decision(_req(user_query=f"Q{i}"))
        journal_service.save_decision(r, journal_path=jp)
        ids.append(r.decision_id)

    # Accept first two, reject third, leave fourth unset.
    for did in ids[:2]:
        journal_service.update_decision(did, DecisionPatch(action_taken="accepted"), journal_path=jp)
    journal_service.update_decision(ids[2], DecisionPatch(action_taken="rejected"), journal_path=jp)

    accepted = journal_service.list_decisions(action_taken="accepted", journal_path=jp)
    assert len(accepted) == 2

    rejected = journal_service.list_decisions(action_taken="rejected", journal_path=jp)
    assert len(rejected) == 1

    # The fourth has no action_taken, so action_taken filter "pending" returns 0
    # (field is None, not "pending").
    pending = journal_service.list_decisions(action_taken="pending", journal_path=jp)
    assert len(pending) == 0


def test_list_filter_date_from(tmp_path: Path) -> None:
    """Records with timestamp date < date_from are excluded."""
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    # Use a future date_from so the record is excluded.
    results = journal_service.list_decisions(date_from="2099-01-01", journal_path=jp)
    assert len(results) == 0

    # Use a past date_from so the record is included.
    results2 = journal_service.list_decisions(date_from="2000-01-01", journal_path=jp)
    assert len(results2) == 1


def test_list_filter_date_to(tmp_path: Path) -> None:
    """Records with timestamp date > date_to are excluded."""
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)

    # Use a past date_to so the record is excluded.
    results = journal_service.list_decisions(date_to="2000-01-01", journal_path=jp)
    assert len(results) == 0

    # Use a future date_to so the record is included.
    results2 = journal_service.list_decisions(date_to="2099-12-31", journal_path=jp)
    assert len(results2) == 1


def test_list_respects_limit(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for i in range(10):
        r = journal_service.create_decision(_req(user_query=f"Q{i}"))
        journal_service.save_decision(r, journal_path=jp)

    results = journal_service.list_decisions(limit=3, journal_path=jp)
    assert len(results) == 3


def test_count_decisions_ignores_limit(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    for i in range(6):
        r = journal_service.create_decision(_req(recommendation_status="eligible", user_query=f"Q{i}"))
        journal_service.save_decision(r, journal_path=jp)

    assert len(journal_service.list_decisions(recommendation_status="eligible", limit=2, journal_path=jp)) == 2
    assert journal_service.count_decisions(recommendation_status="eligible", journal_path=jp) == 6


def test_list_skips_malformed_lines(tmp_path: Path) -> None:
    jp = _jp(tmp_path)
    r = journal_service.create_decision(_req())
    journal_service.save_decision(r, journal_path=jp)
    # Inject a malformed line.
    with jp.open("a", encoding="utf-8") as fh:
        fh.write("not valid json at all\n")

    results = journal_service.list_decisions(journal_path=jp)
    assert len(results) == 1  # Malformed line is skipped, valid record is returned.


def test_list_combined_filters(tmp_path: Path) -> None:
    jp = _jp(tmp_path)

    r1 = journal_service.create_decision(_req(top_deterministic_result="SPY", recommendation_status="eligible"))
    r2 = journal_service.create_decision(_req(top_deterministic_result="QQQ", recommendation_status="eligible"))
    r3 = journal_service.create_decision(_req(top_deterministic_result="SPY", recommendation_status="rejected_by_profile"))

    for r in [r1, r2, r3]:
        journal_service.save_decision(r, journal_path=jp)

    # SPY + eligible = only r1.
    results = journal_service.list_decisions(
        ticker="SPY", recommendation_status="eligible", journal_path=jp
    )
    assert len(results) == 1
    assert results[0].decision_id == r1.decision_id
