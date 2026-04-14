from fastapi import APIRouter, HTTPException, Query

from app.core.dependencies import SessionDep
from app.schemas.copilot import (
    CopilotChatRequest,
    CopilotChatResponse,
    CopilotToolsResponse,
    ExplainRecommendationRequest,
    KnowledgeBaseQueryRequest,
    KnowledgeBaseQueryResponse,
    MarketSnapshotRequest,
    MarketSnapshotResponse,
    RankAssetsRequest,
    RankAssetsResponse,
    RecommendationPayload,
    StrategyEvaluationRequest,
    StrategyEvaluationResponse,
)
from app.schemas.copilot_journal import (
    DecisionCreateRequest,
    DecisionPatch,
    DecisionRecord,
    JournalListResponse,
)
from app.schemas.copilot_monitoring import (
    FindingsListResponse,
    MonitoringRunRequest,
    MonitoringRunResponse,
)
from app.schemas.copilot_comparative_validation import (
    ComparativeValidationRequest,
    ComparativeValidationResponse,
)
from app.schemas.copilot_forward_validation_pilot import (
    ForwardValidationPilotRequest,
    ForwardValidationPilotResponse,
)
from app.schemas.copilot_outcomes import OutcomeReviewRequest, OutcomeReviewResponse
from app.schemas.copilot_paper_portfolio_nav import (
    PaperPortfolioNavRequest,
    PaperPortfolioNavResponse,
)
from app.schemas.copilot_scorecard import ScorecardRequest, ScorecardResponse
from app.schemas.copilot_shadow_portfolio import ShadowPortfolioRequest, ShadowPortfolioResponse
import app.services.copilot as copilot_service
import app.services.copilot_comparative_validation as comparative_validation_service
import app.services.copilot_forward_validation_pilot as forward_validation_service
import app.services.copilot_journal as journal_service
import app.services.copilot_monitoring as monitoring_service
import app.services.copilot_outcomes as outcome_service
import app.services.copilot_paper_portfolio_nav as paper_portfolio_nav_service
import app.services.copilot_scorecard as scorecard_service
import app.services.copilot_shadow_portfolio as shadow_portfolio_service

router = APIRouter(prefix="/copilot", tags=["copilot"])


@router.get("/tools", response_model=CopilotToolsResponse)
async def list_copilot_tools() -> CopilotToolsResponse:
    return CopilotToolsResponse(tools=copilot_service.list_tools())


@router.post("/get_market_snapshot", response_model=MarketSnapshotResponse)
async def get_market_snapshot(
    body: MarketSnapshotRequest,
    session: SessionDep,
) -> MarketSnapshotResponse:
    return await copilot_service.get_market_snapshot_tool(session, body)


@router.post("/rank_assets", response_model=RankAssetsResponse)
async def rank_assets(
    body: RankAssetsRequest,
    session: SessionDep,
) -> RankAssetsResponse:
    return await copilot_service.rank_assets_tool(session, body)


@router.post("/run_strategy_evaluation", response_model=StrategyEvaluationResponse)
async def run_strategy_evaluation(
    body: StrategyEvaluationRequest,
    session: SessionDep,
) -> StrategyEvaluationResponse:
    return await copilot_service.run_strategy_evaluation_tool(session, body)


@router.post("/explain_recommendation", response_model=RecommendationPayload)
async def explain_recommendation(
    body: ExplainRecommendationRequest,
) -> RecommendationPayload:
    return copilot_service.explain_recommendation_tool(body)


@router.post("/query_knowledge_base", response_model=KnowledgeBaseQueryResponse)
async def query_knowledge_base(
    body: KnowledgeBaseQueryRequest,
) -> KnowledgeBaseQueryResponse:
    return copilot_service.query_knowledge_base_tool(body)


@router.post("/chat", response_model=CopilotChatResponse)
async def copilot_chat(
    body: CopilotChatRequest,
    session: SessionDep,
) -> CopilotChatResponse:
    return await copilot_service.copilot_chat_tool(session, body)


@router.post("/monitoring/run", response_model=MonitoringRunResponse)
async def run_monitoring_checks(
    body: MonitoringRunRequest,
    session: SessionDep,
) -> MonitoringRunResponse:
    return await monitoring_service.run_monitoring_checks(session, body)


@router.get("/monitoring/findings", response_model=FindingsListResponse)
def list_monitoring_findings(
    entity: str | None = Query(default=None, description="Substring match on ticker or entity"),
    finding_type: str | None = Query(default=None),
    severity: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD inclusive lower bound"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD inclusive upper bound"),
    limit: int = Query(default=50, ge=1, le=200),
) -> FindingsListResponse:
    return monitoring_service.list_findings(
        entity=entity,
        finding_type=finding_type,
        severity=severity,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )


@router.post("/scorecard", response_model=ScorecardResponse)
def get_scorecard(body: ScorecardRequest) -> ScorecardResponse:
    return scorecard_service.generate_scorecard(body)


@router.post("/outcomes", response_model=OutcomeReviewResponse)
def review_outcomes(body: OutcomeReviewRequest) -> OutcomeReviewResponse:
    return outcome_service.review_outcomes(body)


@router.post("/comparative_validation", response_model=ComparativeValidationResponse)
def get_comparative_validation(body: ComparativeValidationRequest) -> ComparativeValidationResponse:
    return comparative_validation_service.generate_comparative_validation(body)


@router.post("/forward_validation_pilot", response_model=ForwardValidationPilotResponse)
async def get_forward_validation_pilot(
    body: ForwardValidationPilotRequest,
    session: SessionDep,
) -> ForwardValidationPilotResponse:
    return await forward_validation_service.generate_forward_validation_pilot(session, body)


@router.post("/shadow_portfolio", response_model=ShadowPortfolioResponse)
async def run_shadow_portfolio(
    body: ShadowPortfolioRequest,
    session: SessionDep,
) -> ShadowPortfolioResponse:
    return await shadow_portfolio_service.build_shadow_portfolio(session, body)


@router.post("/paper_portfolio_nav", response_model=PaperPortfolioNavResponse)
async def run_paper_portfolio_nav(
    body: PaperPortfolioNavRequest,
    session: SessionDep,
) -> PaperPortfolioNavResponse:
    return await paper_portfolio_nav_service.build_paper_portfolio_nav(session, body)


# ── Decision journal endpoints ─────────────────────────────────────────────────


@router.post("/journal", response_model=DecisionRecord, status_code=201)
def save_journal_decision(body: DecisionCreateRequest) -> DecisionRecord:
    """Save a new decision record from a copilot chat response.

    Creates the journal file automatically if it does not yet exist.
    Returns the saved record including its generated decision_id and timestamp.
    """
    record = journal_service.create_decision(body)
    return journal_service.save_decision(record)


@router.patch("/journal/{decision_id}", response_model=DecisionRecord)
def update_journal_decision(decision_id: str, body: DecisionPatch) -> DecisionRecord:
    """Update action_taken, review_date, or outcome_notes on an existing entry.

    action_taken_timestamp is set automatically when action_taken is supplied
    without an explicit timestamp.  Returns 404 if the decision_id is not found.
    """
    record = journal_service.update_decision(decision_id, body)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Journal entry '{decision_id}' not found.",
        )
    return record


@router.get("/journal", response_model=JournalListResponse)
def list_journal_decisions(
    ticker: str | None = Query(default=None, description="Substring match on top_deterministic_result or final recommended entity"),
    recommendation_status: str | None = Query(default=None),
    action_taken: str | None = Query(default=None),
    date_from: str | None = Query(default=None, description="YYYY-MM-DD inclusive lower bound"),
    date_to: str | None = Query(default=None, description="YYYY-MM-DD inclusive upper bound"),
    limit: int = Query(default=50, ge=1, le=200),
) -> JournalListResponse:
    """List journal entries newest-first with optional filters."""
    entries = journal_service.list_decisions(
        ticker=ticker,
        recommendation_status=recommendation_status,
        action_taken=action_taken,
        date_from=date_from,
        date_to=date_to,
        limit=limit,
    )
    total = journal_service.count_decisions(
        ticker=ticker,
        recommendation_status=recommendation_status,
        action_taken=action_taken,
        date_from=date_from,
        date_to=date_to,
    )
    return JournalListResponse(entries=entries, total=total)


@router.get("/journal/{decision_id}", response_model=DecisionRecord)
def get_journal_decision(decision_id: str) -> DecisionRecord:
    """Retrieve a single journal entry by its decision_id."""
    record = journal_service.get_decision(decision_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=f"Journal entry '{decision_id}' not found.",
        )
    return record
