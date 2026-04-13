from fastapi import APIRouter

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
import app.services.copilot as copilot_service

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
