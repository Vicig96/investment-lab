"""Local investor-profile, knowledge retrieval, and policy evaluation helpers."""
from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.schemas.backtest import BacktestMetrics
from app.schemas.copilot import (
    InvestorProfile,
    KnowledgeBaseMatch,
    KnowledgeBaseQueryRequest,
    KnowledgeBaseQueryResponse,
    LocalPortfolio,
    PortfolioContextApplied,
    ProfileConstraintApplied,
    PositionContext,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
COPILOT_DATA_DIR = REPO_ROOT / "data" / "copilot"
PROFILE_PATH = COPILOT_DATA_DIR / "profile.json"
KNOWLEDGE_DIR = COPILOT_DATA_DIR / "knowledge"
PORTFOLIO_PATH = COPILOT_DATA_DIR / "portfolio.json"

STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "your", "have", "has",
    "will", "not", "use", "using", "when", "what", "which", "then", "than", "only",
    "across", "over", "under", "should", "would", "could", "about", "them", "they",
    "their", "there", "here", "where", "been", "being", "because", "while", "also",
    "note", "notes", "document", "documents", "query", "local", "project",
}
SUPPORTIVE_TERMS = {"prefer", "preferred", "robust", "default", "acceptable", "supported", "useful", "core", "aligns"}
BLOCK_TERMS = {"avoid", "disallow", "blocked", "reject", "rejected", "not eligible", "unsupported", "forbidden"}
CAUTION_TERMS = {"caution", "review", "limit", "careful", "volatile", "drawdown", "breach", "exceed", "risk"}
STRATEGY_KEYWORDS = {
    "rotation", "cross-preset", "cross preset", "walk-forward", "walk forward",
    "parameter sweep", "compare variants", "defensive asset", "cash",
}
EXPOSURE_GROUPS = {
    "SPY": "us_large_cap_core",
    "VOO": "us_large_cap_core",
    "IVV": "us_large_cap_core",
    "QQQ": "us_large_cap_growth",
    "IWM": "us_small_cap",
    "TLT": "long_treasury",
    "IEF": "intermediate_treasury",
    "GLD": "gold",
    "XLE": "sector_energy",
    "XLF": "sector_financials",
}
DEFAULT_CONCENTRATION_LIMIT = 0.35


@dataclass(slots=True)
class LocalKnowledgeDocument:
    title: str
    source: str
    doc_type: str
    tags: list[str]
    aliases: list[str]
    priority: int
    status: str
    body: str
    body_tokens: set[str]
    title_tokens: set[str]
    tag_tokens: set[str]
    alias_tokens: set[str]


def _tokenize(text: str) -> list[str]:
    return [
        token
        for token in re.findall(r"[a-z0-9]{2,}", text.lower())
        if token not in STOPWORDS and len(token) >= 2
    ]


def load_investor_profile() -> tuple[InvestorProfile | None, list[str]]:
    if not PROFILE_PATH.exists():
        return None, [f"Investor profile file is missing: {PROFILE_PATH.name}."]

    try:
        raw = PROFILE_PATH.read_text(encoding="utf-8")
        return InvestorProfile.model_validate_json(raw), []
    except Exception as exc:  # pragma: no cover - defensive file handling
        return None, [f"Investor profile could not be loaded: {exc}"]


def load_local_portfolio() -> tuple[LocalPortfolio | None, list[str]]:
    if not PORTFOLIO_PATH.exists():
        return None, [f"Local portfolio file is missing: {PORTFOLIO_PATH.name}."]

    try:
        raw = PORTFOLIO_PATH.read_text(encoding="utf-8")
        return LocalPortfolio.model_validate_json(raw), []
    except Exception as exc:  # pragma: no cover - defensive file handling
        return None, [f"Local portfolio could not be loaded: {exc}"]


def _parse_list_value(raw: str) -> list[str]:
    value = raw.strip()
    if value.startswith("[") and value.endswith("]"):
        inner = value[1:-1].strip()
        if not inner:
            return []
        return [piece.strip().strip("\"'") for piece in inner.split(",") if piece.strip()]
    return [piece.strip().strip("\"'") for piece in value.split(",") if piece.strip()]


def _parse_scalar_value(raw: str) -> Any:
    value = raw.strip().strip("\"'")
    if value.isdigit():
        return int(value)
    return value


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---"):
        return {}, text

    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return {}, text

    metadata: dict[str, Any] = {}
    for line in lines[1:end_index]:
        if ":" not in line:
            continue
        key, raw_value = line.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        if key in {"tags", "aliases"}:
            metadata[key] = _parse_list_value(raw_value)
        else:
            metadata[key] = _parse_scalar_value(raw_value)
    body = "\n".join(lines[end_index + 1 :]).strip()
    return metadata, body


def _default_doc_type(path: Path, body: str) -> str:
    name = path.stem.lower()
    first_line = body.splitlines()[0].lower() if body.splitlines() else ""
    if "thesis" in name or "thesis" in first_line:
        return "investment_thesis"
    if "experiment" in name or "conclusion" in name:
        return "experiment_conclusion"
    if "risk" in name or "policy" in name:
        return "risk_policy"
    if "rule" in name:
        return "rule"
    if "strategy" in name:
        return "strategy_note"
    return "note"


def _default_title(path: Path, body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return path.stem.replace("_", " ").replace("-", " ").title()


def _display_source(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT.resolve())).replace("\\", "/")
    except ValueError:
        return str(path).replace("\\", "/")


def _load_knowledge_documents() -> tuple[list[LocalKnowledgeDocument], list[str]]:
    if not KNOWLEDGE_DIR.exists():
        return [], [f"Knowledge base directory is missing: {KNOWLEDGE_DIR.name}."]

    documents: list[LocalKnowledgeDocument] = []
    warnings: list[str] = []
    for path in sorted(KNOWLEDGE_DIR.glob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        try:
            raw_text = path.read_text(encoding="utf-8")
        except Exception as exc:  # pragma: no cover
            warnings.append(f"Could not read knowledge document {path.name}: {exc}")
            continue

        metadata, body = _parse_frontmatter(raw_text)
        title = str(metadata.get("title") or _default_title(path, body))
        doc_type = str(metadata.get("doc_type") or _default_doc_type(path, body))
        tags = [str(tag) for tag in metadata.get("tags", [])]
        aliases = [str(alias) for alias in metadata.get("aliases", [])]
        priority = int(metadata.get("priority", 0) or 0)
        status = str(metadata.get("status", "active") or "active")

        documents.append(
            LocalKnowledgeDocument(
                title=title,
                source=_display_source(path),
                doc_type=doc_type,
                tags=tags,
                aliases=aliases,
                priority=priority,
                status=status,
                body=body,
                body_tokens=set(_tokenize(body)),
                title_tokens=set(_tokenize(title)),
                tag_tokens=set(_tokenize(" ".join(tags))),
                alias_tokens=set(_tokenize(" ".join(aliases))),
            )
        )
    if not documents:
        warnings.append("Knowledge base is empty.")
    return documents, warnings


def _idf_weights(documents: list[LocalKnowledgeDocument]) -> dict[str, float]:
    doc_count = max(len(documents), 1)
    frequencies = Counter()
    for document in documents:
        for token in document.body_tokens | document.title_tokens | document.tag_tokens | document.alias_tokens:
            frequencies[token] += 1
    return {
        token: math.log((1 + doc_count) / (1 + count)) + 1.0
        for token, count in frequencies.items()
    }


def _best_snippet(body: str, query_tokens: set[str]) -> str:
    paragraphs = [chunk.strip() for chunk in re.split(r"\n\s*\n", body) if chunk.strip()]
    if not paragraphs:
        return ""

    best = paragraphs[0]
    best_score = -1
    for paragraph in paragraphs:
        overlap = len(query_tokens.intersection(_tokenize(paragraph)))
        if overlap > best_score:
            best = paragraph
            best_score = overlap
    snippet = re.sub(r"\s+", " ", best)
    return snippet[:260] + ("..." if len(snippet) > 260 else "")


def _confidence_tier(score: float) -> str:
    if score >= 8:
        return "high"
    if score >= 4:
        return "medium"
    return "low"


def _exact_query_tickers(query: str) -> set[str]:
    return {match.upper() for match in re.findall(r"\b[A-Z]{2,5}\b", query)}


def _strategy_keyword_matches(query: str) -> set[str]:
    q = query.lower()
    return {keyword for keyword in STRATEGY_KEYWORDS if keyword in q}


def query_local_knowledge_base(request: KnowledgeBaseQueryRequest) -> KnowledgeBaseQueryResponse:
    documents, warnings = _load_knowledge_documents()
    if request.active_only:
        documents = [document for document in documents if document.status.lower() == "active"]
    if request.doc_types:
        allowed = {doc_type.lower() for doc_type in request.doc_types}
        documents = [document for document in documents if document.doc_type.lower() in allowed]

    if not documents:
        return KnowledgeBaseQueryResponse(
            backend="local_filesystem",
            query=request.query,
            top_k=request.top_k,
            matches=[],
            warnings=warnings or ["No local knowledge documents are available after filtering."],
        )

    query_tokens = set(_tokenize(request.query))
    query_lower = request.query.lower()
    exact_tickers = {ticker.lower() for ticker in _exact_query_tickers(request.query)}
    strategy_hits = _strategy_keyword_matches(request.query)
    if not query_tokens and not exact_tickers and not strategy_hits:
        return KnowledgeBaseQueryResponse(
            backend="local_filesystem",
            query=request.query,
            top_k=request.top_k,
            matches=[],
            warnings=warnings + ["No meaningful query terms remained after normalization."],
        )

    idf = _idf_weights(documents)
    scored: list[KnowledgeBaseMatch] = []
    for document in documents:
        body_overlap = query_tokens.intersection(document.body_tokens)
        title_overlap = query_tokens.intersection(document.title_tokens)
        tag_overlap = query_tokens.intersection(document.tag_tokens)

        matched_terms = set(body_overlap) | set(title_overlap) | set(tag_overlap)
        alias_hits = [alias for alias in document.aliases if alias.lower() in query_lower]
        matched_terms.update(alias_hits)

        score = sum(idf.get(token, 1.0) for token in body_overlap)
        score += 1.25 * len(title_overlap)
        score += 1.5 * len(tag_overlap)
        score += 2.0 * len(alias_hits)

        if exact_tickers:
            ticker_hits = exact_tickers.intersection(document.body_tokens | document.title_tokens | document.tag_tokens | document.alias_tokens)
            matched_terms.update(ticker_hits)
            score += 2.0 * len(ticker_hits)
        else:
            ticker_hits = set()

        strategy_bonus_hits = [
            keyword
            for keyword in strategy_hits
            if keyword in document.body.lower() or keyword in document.title.lower() or keyword in " ".join(document.tags).lower()
        ]
        matched_terms.update(strategy_bonus_hits)
        relevance_hits = body_overlap or title_overlap or tag_overlap or alias_hits or ticker_hits or strategy_bonus_hits
        if not relevance_hits:
            continue
        score += 1.75 * len(strategy_bonus_hits)
        score += 0.15 * document.priority

        if score <= 0:
            continue

        scored.append(
            KnowledgeBaseMatch(
                title=document.title,
                source=document.source,
                snippet=_best_snippet(document.body, query_tokens or set(_tokenize(" ".join(strategy_bonus_hits)))),
                score=round(score, 4),
                doc_type=document.doc_type,
                matched_terms=sorted(str(term) for term in matched_terms),
                confidence_tier=_confidence_tier(score),
            )
        )

    scored.sort(key=lambda item: (-item.score, item.title))
    matches = scored[: request.top_k]
    if not matches:
        warnings.append("No relevant local knowledge documents matched this query.")

    return KnowledgeBaseQueryResponse(
        backend="local_filesystem",
        query=request.query,
        top_k=request.top_k,
        matches=matches,
        warnings=warnings,
    )


def _append_constraint(
    constraints: list[ProfileConstraintApplied],
    *,
    hard_conflicts: list[str],
    soft_conflicts: list[str],
    preference_matches: list[str],
    constraint: str,
    category: str,
    detail: str,
) -> None:
    constraints.append(ProfileConstraintApplied(constraint=constraint, category=category, detail=detail))
    if category == "hard_block":
        hard_conflicts.append(detail)
    elif category == "soft_caution":
        soft_conflicts.append(detail)
    elif category == "preferred":
        preference_matches.append(detail)


def _append_portfolio_context(
    contexts: list[PortfolioContextApplied],
    *,
    check: str,
    status: str,
    detail: str,
) -> None:
    contexts.append(PortfolioContextApplied(check=check, status=status, detail=detail))


def _knowledge_signal_category(match: KnowledgeBaseMatch, entity: str | None) -> tuple[str, str] | None:
    text = " ".join([match.title, match.snippet, " ".join(match.matched_terms)]).lower()
    entity_lower = entity.lower() if entity else None
    if entity_lower and entity_lower not in text and match.doc_type in {"risk_policy", "rule", "investment_thesis"}:
        return None

    if match.doc_type in {"risk_policy", "rule"}:
        if any(term in text for term in BLOCK_TERMS):
            return "hard_block", f"KB risk-policy note flags {entity or 'this result'} as blocked: {match.title}."
        if any(term in text for term in CAUTION_TERMS):
            return "soft_caution", f"KB risk-policy note raises caution for {entity or 'this result'}: {match.title}."

    if match.doc_type in {"experiment_conclusion", "investment_thesis", "strategy_note"}:
        if any(term in text for term in SUPPORTIVE_TERMS):
            return "preferred", f"KB support found for {entity or 'this result'}: {match.title}."
        if any(term in text for term in BLOCK_TERMS | CAUTION_TERMS):
            return "soft_caution", f"KB note tempers confidence in {entity or 'this result'}: {match.title}."

    return None


def evaluate_policy_context(
    *,
    recommended_entity_type: str,
    recommended_entity: str | None,
    tickers: list[str] | None,
    metrics: BacktestMetrics | None,
    profile: InvestorProfile | None,
    knowledge_matches: list[KnowledgeBaseMatch],
) -> dict[str, Any]:
    constraints: list[ProfileConstraintApplied] = []
    hard_conflicts: list[str] = []
    soft_conflicts: list[str] = []
    preference_matches: list[str] = []
    warnings: list[str] = []

    if profile is None:
        warnings.append("No active investor profile is loaded, so no personalization constraints were applied.")
    else:
        _append_constraint(
            constraints,
            hard_conflicts=hard_conflicts,
            soft_conflicts=soft_conflicts,
            preference_matches=preference_matches,
            constraint="active_profile",
            category="neutral",
            detail=f"Using investor profile '{profile.profile_name}'.",
        )

        profile_preferred = {ticker.upper() for ticker in profile.preferred_assets}
        profile_disallowed = {ticker.upper() for ticker in profile.disallowed_assets}
        active_tickers = {ticker.upper() for ticker in (tickers or [])}
        entity_upper = recommended_entity.upper() if recommended_entity else None

        disallowed_overlap = sorted(active_tickers.intersection(profile_disallowed))
        if disallowed_overlap:
            detail = f"Requested universe includes disallowed assets: {', '.join(disallowed_overlap)}."
            _append_constraint(
                constraints,
                hard_conflicts=hard_conflicts,
                soft_conflicts=soft_conflicts,
                preference_matches=preference_matches,
                constraint="disallowed_assets",
                category="soft_caution",
                detail=detail,
            )
            warnings.append(detail)

        if recommended_entity_type == "asset" and entity_upper:
            if entity_upper in profile_disallowed:
                detail = f"{entity_upper} is explicitly disallowed by the active investor profile."
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="recommended_asset_allowed",
                    category="hard_block",
                    detail=detail,
                )
                warnings.append(detail)
            elif entity_upper in profile_preferred:
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="preferred_assets",
                    category="preferred",
                    detail=f"{entity_upper} is listed as a preferred asset in the active profile.",
                )
            elif profile_preferred:
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="preferred_assets",
                    category="soft_caution",
                    detail=f"{entity_upper} is not in the preferred asset list: {', '.join(sorted(profile_preferred))}.",
                )

        if metrics is not None and metrics.max_drawdown is not None and profile.max_acceptable_drawdown is not None:
            actual_drawdown = abs(metrics.max_drawdown)
            if actual_drawdown <= profile.max_acceptable_drawdown:
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="max_acceptable_drawdown",
                    category="preferred",
                    detail=(
                        f"Observed drawdown {actual_drawdown:.2%} is within the profile limit "
                        f"of {profile.max_acceptable_drawdown:.2%}."
                    ),
                )
            else:
                detail = (
                    f"Observed drawdown {actual_drawdown:.2%} exceeds the profile limit "
                    f"of {profile.max_acceptable_drawdown:.2%}."
                )
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="max_acceptable_drawdown",
                    category="hard_block",
                    detail=detail,
                )
                warnings.append(detail)

        if recommended_entity_type == "strategy_config" and recommended_entity and profile.preferred_strategy_bias:
            entity_lower = recommended_entity.lower()
            bias_lower = profile.preferred_strategy_bias.lower()
            if "defensive" in bias_lower and ("defensive" in entity_lower or "cash" in entity_lower):
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="preferred_strategy_bias",
                    category="preferred",
                    detail=f"The selected configuration aligns with the profile bias: {profile.preferred_strategy_bias}.",
                )
            elif "defensive" in bias_lower:
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="preferred_strategy_bias",
                    category="soft_caution",
                    detail=f"The selected configuration may be more aggressive than the profile bias: {profile.preferred_strategy_bias}.",
                )
            else:
                _append_constraint(
                    constraints,
                    hard_conflicts=hard_conflicts,
                    soft_conflicts=soft_conflicts,
                    preference_matches=preference_matches,
                    constraint="preferred_strategy_bias",
                    category="neutral",
                    detail=f"Profile bias noted: {profile.preferred_strategy_bias}.",
                )

        if profile.liquidity_needs:
            _append_constraint(
                constraints,
                hard_conflicts=hard_conflicts,
                soft_conflicts=soft_conflicts,
                preference_matches=preference_matches,
                constraint="liquidity_needs",
                category="neutral",
                detail=f"Liquidity preference recorded for context: {profile.liquidity_needs}.",
            )

    for match in knowledge_matches:
        signal = _knowledge_signal_category(match, recommended_entity)
        if signal is None:
            continue
        category, detail = signal
        _append_constraint(
            constraints,
            hard_conflicts=hard_conflicts,
            soft_conflicts=soft_conflicts,
            preference_matches=preference_matches,
            constraint=f"knowledge::{match.doc_type or 'note'}",
            category=category,
            detail=detail,
        )

    if hard_conflicts:
        recommendation_status = "rejected_by_profile"
        constraint_summary = f"Rejected for the active profile: {hard_conflicts[0]}"
    elif not knowledge_matches:
        recommendation_status = "unsupported_by_knowledge"
        constraint_summary = "Deterministic result is available, but no relevant local knowledge support was found."
    elif soft_conflicts:
        recommendation_status = "eligible_with_cautions"
        constraint_summary = f"Eligible with cautions: {soft_conflicts[0]}"
    else:
        recommendation_status = "eligible"
        if preference_matches:
            constraint_summary = f"Eligible and aligned: {preference_matches[0]}"
        else:
            constraint_summary = "Eligible under the active profile and supported by local knowledge."

    return {
        "constraints": constraints,
        "hard_conflicts": hard_conflicts,
        "soft_conflicts": soft_conflicts,
        "preference_matches": preference_matches,
        "constraint_summary": constraint_summary,
        "recommendation_status": recommendation_status,
        "warnings": warnings,
    }


def _exposure_group_for_ticker(ticker: str | None) -> str | None:
    if not ticker:
        return None
    normalized = ticker.upper()
    return EXPOSURE_GROUPS.get(normalized, normalized)


def evaluate_portfolio_context(
    *,
    recommended_entity_type: str,
    recommended_entity: str | None,
    portfolio: LocalPortfolio | None,
    base_status: str,
) -> dict[str, Any]:
    contexts: list[PortfolioContextApplied] = []
    concentration_notes: list[str] = []
    warnings: list[str] = []

    if portfolio is None:
        warnings.append("No active portfolio file is loaded, so portfolio constraints were not applied.")
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": "No active portfolio file is loaded, so portfolio constraints were not applied.",
            "recommended_action_type": "review_only" if recommended_entity_type != "asset" else None,
            "position_context": None,
            "concentration_notes": concentration_notes,
            "recommendation_status": base_status,
            "warnings": warnings,
        }

    _append_portfolio_context(
        contexts,
        check="active_portfolio",
        status="context",
        detail=f"Using local portfolio '{portfolio.portfolio_name}' in {portfolio.base_currency}.",
    )

    if base_status not in {"eligible", "eligible_with_cautions"}:
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": (
                "Portfolio context was loaded, but the result was already non-actionable before portfolio checks."
            ),
            "recommended_action_type": "no_action",
            "position_context": None,
            "concentration_notes": concentration_notes,
            "recommendation_status": base_status,
            "warnings": warnings,
        }

    if recommended_entity_type != "asset" or not recommended_entity:
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": "Portfolio loaded for context, but this recommendation is a strategy configuration rather than an asset-level trade.",
            "recommended_action_type": "review_only",
            "position_context": None,
            "concentration_notes": concentration_notes,
            "recommendation_status": base_status,
            "warnings": warnings,
        }

    positions = list(portfolio.positions)
    candidate_ticker = recommended_entity.upper()
    held_position = next((position for position in positions if position.ticker.upper() == candidate_ticker), None)
    candidate_exposure_group = _exposure_group_for_ticker(candidate_ticker)

    nav_estimate = float(portfolio.cash_available)
    missing_cost_positions: list[str] = []
    for position in positions:
        if position.avg_cost is None:
            missing_cost_positions.append(position.ticker.upper())
            continue
        nav_estimate += float(position.quantity) * float(position.avg_cost)

    if missing_cost_positions:
        detail = (
            "Estimated portfolio exposure excludes positions without avg_cost: "
            + ", ".join(sorted(missing_cost_positions))
            + "."
        )
        _append_portfolio_context(
            contexts,
            check="valuation_completeness",
            status="caution",
            detail=detail,
        )
        warnings.append(detail)

    group_value = 0.0
    estimated_value = None
    max_position_limit = None
    for position in positions:
        if position.avg_cost is None:
            continue
        current_value = float(position.quantity) * float(position.avg_cost)
        if _exposure_group_for_ticker(position.ticker) == candidate_exposure_group:
            group_value += current_value
        if held_position is not None and position.ticker.upper() == candidate_ticker:
            estimated_value = current_value
            if position.max_position_size_pct is not None:
                max_position_limit = float(position.max_position_size_pct)

    position_weight_pct = (estimated_value / nav_estimate) if estimated_value is not None and nav_estimate > 0 else None
    group_weight_pct = (group_value / nav_estimate) if nav_estimate > 0 else None

    position_context = PositionContext(
        ticker=candidate_ticker,
        is_held=held_position is not None,
        quantity=float(held_position.quantity) if held_position is not None else None,
        avg_cost=float(held_position.avg_cost) if held_position is not None and held_position.avg_cost is not None else None,
        estimated_value=estimated_value,
        estimated_weight_pct=position_weight_pct,
        exposure_group=candidate_exposure_group,
        asset_type=held_position.asset_type if held_position is not None else None,
        strategy_bucket=held_position.strategy_bucket if held_position is not None else None,
    )

    if held_position is not None:
        detail = f"{candidate_ticker} is already held in the current portfolio."
        _append_portfolio_context(
            contexts,
            check="existing_position",
            status="preferred",
            detail=detail,
        )
    elif group_weight_pct and group_weight_pct >= 0.25:
        detail = (
            f"Current portfolio already has meaningful exposure to {candidate_exposure_group}: "
            f"{group_weight_pct:.1%} estimated weight."
        )
        _append_portfolio_context(
            contexts,
            check="redundant_exposure",
            status="caution",
            detail=detail,
        )
        concentration_notes.append(detail)

    if portfolio.cash_available <= 0:
        detail = "No cash is currently available for a new purchase or add-on."
        _append_portfolio_context(
            contexts,
            check="cash_available",
            status="block",
            detail=detail,
        )
        warnings.append(detail)
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": detail,
            "recommended_action_type": "no_action",
            "position_context": position_context,
            "concentration_notes": concentration_notes,
            "recommendation_status": "not_actionable_without_cash",
            "warnings": warnings,
        }

    effective_limit = max_position_limit or DEFAULT_CONCENTRATION_LIMIT
    if position_weight_pct is not None and position_weight_pct > effective_limit:
        detail = (
            f"{candidate_ticker} is already above the estimated concentration limit at "
            f"{position_weight_pct:.1%} versus {effective_limit:.1%}."
        )
        _append_portfolio_context(
            contexts,
            check="position_concentration",
            status="block",
            detail=detail,
        )
        concentration_notes.append(detail)
        warnings.append(detail)
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": detail,
            "recommended_action_type": "avoid",
            "position_context": position_context,
            "concentration_notes": concentration_notes,
            "recommendation_status": "eligible_but_overconcentrated",
            "warnings": warnings,
        }

    if held_position is None and group_weight_pct is not None and group_weight_pct >= 0.25:
        detail = (
            f"{candidate_ticker} looks redundant with the existing {candidate_exposure_group} sleeve "
            f"at an estimated {group_weight_pct:.1%} weight."
        )
        if group_weight_pct > effective_limit:
            detail += " The existing sleeve is already concentrated."
        _append_portfolio_context(
            contexts,
            check="redundant_exposure",
            status="block",
            detail=detail,
        )
        concentration_notes.append(detail)
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": detail,
            "recommended_action_type": "avoid",
            "position_context": position_context,
            "concentration_notes": concentration_notes,
            "recommendation_status": "redundant_exposure",
            "warnings": warnings,
        }

    if held_position is not None:
        detail = (
            f"{candidate_ticker} is already held, so the portfolio-aware action is an add-to-existing-position review."
        )
        _append_portfolio_context(
            contexts,
            check="action_type",
            status="preferred",
            detail=detail,
        )
        return {
            "portfolio_context_applied": contexts,
            "portfolio_decision_summary": detail,
            "recommended_action_type": "add_to_existing_position",
            "position_context": position_context,
            "concentration_notes": concentration_notes,
            "recommendation_status": "eligible_add_to_existing",
            "warnings": warnings,
        }

    detail = f"{candidate_ticker} is not currently held and cash is available, so this is a new-position candidate."
    _append_portfolio_context(
        contexts,
        check="action_type",
        status="preferred",
        detail=detail,
    )
    return {
        "portfolio_context_applied": contexts,
        "portfolio_decision_summary": detail,
        "recommended_action_type": "open_new_position",
        "position_context": position_context,
        "concentration_notes": concentration_notes,
        "recommendation_status": "eligible_new_position",
        "warnings": warnings,
    }
