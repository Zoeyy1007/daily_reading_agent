import hashlib
import json
import logging
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.ai.factory import build_supplement_provider
from app.ai.client import StructuredOutputError
from app.ai.providers import ProviderResult, SupplementProvider
from app.ai.schemas import SupplementDraft, SupplementPlan, SupplementVerification
from app.agent.tool_executor import ToolCallRejected, extract_tool_pair
from app.agent.tool_policy import ToolPolicy, SupplementToolPolicy, load_supplement_tool_policy
from app.config import Settings
from app.db.session import SessionLocal
from app.db.models import (
    Article,
    ArticleAIClassification,
    DailyReadingItem,
    DailyReadingList,
    ModelCall,
    StoryCluster,
    StoryClusterMember,
    SupplementCard,
    SupplementCardCitation,
    SupplementEvidenceItem,
    SupplementRun,
    SupplementStatus,
)
from app.tools.supplement_search import (
    DocumentFetcher,
    ExternalSearchProvider,
    HttpDocumentFetcher,
    best_document_excerpt,
    collect_chunk,
    domain_allowed,
    local_cluster_search,
)
from app.tools.tavily_provider import TavilyExtractFetcher, TavilySearchProvider
from app.utils.concurrency import bounded_to_thread_map

logger = logging.getLogger("daily_reading.supplements")

COVERAGE_AREAS = (
    "earlier_events_and_timeline",
    "affected_people_and_effects",
    "missing_information_from_other_reporting",
    "disagreement_or_uncertainty",
)
MAX_EVIDENCE_PER_COVERAGE_AREA = 3


@dataclass(frozen=True, slots=True)
class SupplementBatchStats:
    complete: int = 0
    skipped: int = 0
    insufficient: int = 0
    failed: int = 0
    evidence_items: int = 0
    cards: int = 0


class VerificationContractError(ValueError):
    pass


def is_supplement_eligible(
    classification: ArticleAIClassification | None,
) -> bool:
    return classification is not None and classification.is_news


def _coverage_gaps(plan: SupplementPlan) -> list[str]:
    return [
        name
        for name in COVERAGE_AREAS
        if getattr(plan.coverage, name).needed
    ]


def _update_coverage_ledger(
    plan: SupplementPlan,
    *,
    target_gaps: set[str],
    evidence_by_area: dict[str, set[int]],
    satisfied_areas: set[str],
    valid_evidence_ids: set[int],
) -> None:
    """Apply cited coverage evidence while keeping targets and satisfaction monotonic."""
    for name in target_gaps:
        decision = getattr(plan.coverage, name)
        cited = [
            evidence_id
            for evidence_id in decision.evidence_ids
            if evidence_id in valid_evidence_ids
        ]
        remaining = MAX_EVIDENCE_PER_COVERAGE_AREA - len(evidence_by_area[name])
        evidence_by_area[name].update(cited[: max(0, remaining)])
        if not decision.needed:
            satisfied_areas.add(name)


def _coverage_target_payload(
    *,
    target_gaps: set[str] | None,
    evidence_by_area: dict[str, set[int]],
    satisfied_areas: set[str],
) -> dict[str, dict[str, object]]:
    if target_gaps is None:
        return {name: {"status": "unassessed"} for name in COVERAGE_AREAS}
    payload: dict[str, dict[str, object]] = {}
    for name in COVERAGE_AREAS:
        evidence_ids = sorted(evidence_by_area[name])
        if name not in target_gaps:
            status = "not_needed"
        elif name in satisfied_areas:
            status = "satisfied"
        elif len(evidence_ids) >= MAX_EVIDENCE_PER_COVERAGE_AREA:
            status = "max_target_reached"
        else:
            status = "search_needed"
        payload[name] = {
            "status": status,
            "evidence_ids": evidence_ids,
            "remaining_slots": max(
                0, MAX_EVIDENCE_PER_COVERAGE_AREA - len(evidence_ids)
            ),
        }
    return payload


def _coverage_research_complete(
    target_gaps: set[str],
    evidence_by_area: dict[str, set[int]],
    satisfied_areas: set[str],
) -> bool:
    return all(
        name in satisfied_areas
        or len(evidence_by_area[name]) >= MAX_EVIDENCE_PER_COVERAGE_AREA
        for name in target_gaps
    )


def _fingerprint(*values: str) -> str:
    return hashlib.sha256("\n".join(values).encode("utf-8")).hexdigest()


def _expiry(settings: Settings) -> datetime:
    return datetime.now(UTC) + timedelta(days=settings.supplement_retention_days)


def _record_model_result(
    session: Session,
    *,
    run_id: int | None,
    role: str,
    provider: SupplementProvider,
    input_hash: str,
    result: ProviderResult[object],
    settings: Settings,
) -> None:
    session.add(
        ModelCall(
            run_id=run_id,
            role=role,
            provider=provider.provider_name,
            model=provider.model,
            status="complete",
            input_hash=input_hash,
            provider_request_id=result.request_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            elapsed_ms=result.elapsed_ms,
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.model_call_log_retention_days),
        )
    )


def _record_model_failure(
    session: Session,
    *,
    run_id: int | None,
    role: str,
    provider: SupplementProvider,
    input_hash: str,
    error: Exception,
    settings: Settings,
) -> None:
    session.add(
        ModelCall(
            run_id=run_id,
            role=role,
            provider=provider.provider_name,
            model=provider.model,
            status="failed",
            input_hash=input_hash,
            error=str(error)[:4000],
            expires_at=datetime.now(UTC)
            + timedelta(days=settings.model_call_log_retention_days),
        )
    )
    session.commit()


def _evidence_payload(items: list[SupplementEvidenceItem]) -> list[dict[str, object]]:
    return [
        {
            "evidence_id": item.id,
            "source_type": item.source_type,
            "title": item.title,
            "publisher": item.publisher,
            "published_at": item.published_at.isoformat() if item.published_at else None,
            "url": item.url,
            "excerpt": item.excerpt[:5000],
            "jurisdiction": item.jurisdiction,
            "agency": item.agency,
            "document_type": item.document_type,
        }
        for item in items
        if item.reliability_status == "trusted"
    ]


def _load_item(session: Session, item_id: int) -> DailyReadingItem | None:
    return session.scalar(
        select(DailyReadingItem)
        .where(DailyReadingItem.id == item_id)
        .options(
            selectinload(DailyReadingItem.article),
            selectinload(DailyReadingItem.supplement_run)
            .selectinload(SupplementRun.evidence_items),
            selectinload(DailyReadingItem.supplement_run)
            .selectinload(SupplementRun.cards)
            .selectinload(SupplementCard.citations),
        )
    )


def _prepare_run(
    session: Session,
    *,
    item: DailyReadingItem,
    daily_run_id: int | None,
    settings: Settings,
) -> SupplementRun:
    article = item.article
    original_words = article.word_count or len((article.content_text or "").split())
    word_budget = int(original_words * settings.supplement_word_ratio)
    run = item.supplement_run
    if run is None:
        run = SupplementRun(
            daily_reading_item=item,
            daily_run_id=daily_run_id,
            status=SupplementStatus.RUNNING.value,
            original_word_count=original_words,
            word_budget=word_budget,
            expires_at=_expiry(settings),
        )
        session.add(run)
    else:
        run.cards.clear()
        session.flush()
        run.evidence_items.clear()
        session.flush()
        run.daily_run_id = daily_run_id
        run.status = SupplementStatus.RUNNING.value
        run.detected_gaps = None
        run.decision_reason = None
        run.tool_history = None
        run.original_word_count = original_words
        run.word_budget = word_budget
        run.iteration_count = 0
        run.tool_call_count = 0
        run.last_error = None
        run.expires_at = _expiry(settings)
        run.completed_at = None
    run.started_at = datetime.now(UTC)
    session.commit()
    return run


def _cluster_event(session: Session, article_id: int) -> str | None:
    cluster = session.scalar(
        select(StoryCluster)
        .join(StoryClusterMember, StoryClusterMember.cluster_id == StoryCluster.id)
        .where(StoryClusterMember.article_id == article_id)
    )
    if cluster is None:
        return None
    return cluster.event_summary or cluster.representative_title


def _save_local_evidence(
    session: Session,
    *,
    run: SupplementRun,
    selected_article_id: int,
    query: str,
    start_date: date | None,
    end_date: date | None,
    settings: Settings,
    tool: ToolPolicy,
    collector: ToolPolicy,
    result_limit: int,
) -> int:
    if (
        not tool.enabled
        or not collector.enabled
        or not collector.permissions.persist_evidence
        or "local_article" not in tool.permissions.allowed_source_types
        or "local_article" not in collector.permissions.allowed_source_types
    ):
        return 0
    _cluster_id, matches = local_cluster_search(
        session,
        selected_article_id=selected_article_id,
        query=query,
        settings=settings,
        limit=result_limit,
        allowed_relationships=set(tool.permissions.allowed_relationships),
        start_date=start_date,
        end_date=end_date,
    )
    existing = {item.content_hash for item in run.evidence_items}
    added = 0
    for match in matches:
        collected = collect_chunk(
            text=match.excerpt,
            url=match.url,
            max_words=min(
                tool.permissions.max_excerpt_words,
                collector.permissions.max_excerpt_words,
            ),
        )
        excerpt = collected.excerpt
        content_hash = collected.content_hash
        if content_hash in existing:
            continue
        session.add(
            SupplementEvidenceItem(
                supplement_run=run,
                source_type="local_article",
                source_article_id=match.article_id,
                source_chunk_id=match.chunk_id,
                query=query,
                title=match.title,
                publisher=match.publisher,
                url=match.url,
                published_at=match.published_at,
                excerpt=excerpt,
                content_hash=content_hash,
                retrieval_score=match.score,
                reliability_status="trusted",
                selected=False,
                expires_at=_expiry(settings),
            )
        )
        existing.add(content_hash)
        added += 1
    session.commit()
    return added


def _save_external_evidence(
    session: Session,
    *,
    run: SupplementRun,
    query: str,
    start_date: date | None,
    end_date: date | None,
    source_type: str,
    allowed_domains: set[str],
    settings: Settings,
    search_provider: ExternalSearchProvider | None,
    document_fetcher: DocumentFetcher,
    tool: ToolPolicy,
    collector: ToolPolicy,
    result_limit: int,
) -> int:
    if (
        search_provider is None
        or not allowed_domains
        or not tool.enabled
        or not collector.enabled
        or not collector.permissions.persist_evidence
        or source_type not in tool.permissions.allowed_source_types
        or source_type not in collector.permissions.allowed_source_types
    ):
        return 0
    hits = search_provider.search(
        query=query,
        allowed_domains=allowed_domains,
        max_results=result_limit,
        start_date=start_date,
        end_date=end_date,
    )
    existing = {item.content_hash for item in run.evidence_items}
    added = 0
    for index, hit in enumerate(hits[:result_limit]):
        if not domain_allowed(hit.url, allowed_domains):
            logger.warning(
                "supplement search rejected untrusted domain url=%s provider=%s",
                hit.url,
                search_provider.provider_name,
            )
            continue
        try:
            document = document_fetcher.fetch(hit.url)
            excerpt = best_document_excerpt(
                document.content,
                query,
                target_words=min(
                    tool.permissions.max_excerpt_words,
                    collector.permissions.max_excerpt_words,
                ),
            )
            if not excerpt:
                continue
            collected = collect_chunk(
                text=excerpt,
                url=hit.url,
                max_words=min(
                    tool.permissions.max_excerpt_words,
                    collector.permissions.max_excerpt_words,
                ),
            )
            excerpt = collected.excerpt
            content_hash = collected.content_hash
            if content_hash in existing:
                continue
            session.add(
                SupplementEvidenceItem(
                    supplement_run=run,
                    source_type=source_type,
                    query=query,
                    title=hit.title or document.title,
                    publisher=hit.publisher,
                    url=hit.url,
                    published_at=hit.published_at,
                    excerpt=excerpt,
                    content_hash=content_hash,
                    retrieval_score=1.0 / (index + 1),
                    reliability_status="trusted",
                    selected=False,
                    jurisdiction=hit.jurisdiction if source_type == "government" else None,
                    agency=hit.agency if source_type == "government" else None,
                    document_type=(
                        hit.document_type if source_type == "government" else None
                    ),
                    document_identifier=(
                        hit.document_identifier if source_type == "government" else None
                    ),
                    effective_date=(
                        hit.effective_date if source_type == "government" else None
                    ),
                    expires_at=_expiry(settings),
                )
            )
            existing.add(content_hash)
            added += 1
        except Exception:
            logger.exception("supplement document fetch failed url=%s", hit.url)
    session.commit()
    return added


def supported_statement_rows(
    draft: SupplementDraft,
    verification: SupplementVerification,
    valid_evidence_ids: set[int],
    word_budget: int,
) -> list[tuple[int, int, str, str, list[int]]]:
    """Fail closed: keep whole statements only when direct support was verified."""
    verified = {
        (item.card_index, item.statement_index): item
        for item in verification.statements
        if item.supported
    }
    rows: list[tuple[int, int, str, str, list[int]]] = []
    used_words = 0
    for card_index, card in enumerate(draft.cards):
        for statement_index, statement in enumerate(card.statements):
            result = verified.get((card_index, statement_index))
            if result is None:
                continue
            cited = [
                evidence_id
                for evidence_id in result.evidence_ids
                if evidence_id in valid_evidence_ids
                and evidence_id in statement.evidence_ids
            ]
            cited = list(dict.fromkeys(cited))
            statement_words = len(statement.text.split())
            if not cited or used_words + statement_words > word_budget:
                continue
            rows.append(
                (
                    card_index,
                    statement_index,
                    card.card_type,
                    statement.text.strip(),
                    cited,
                )
            )
            used_words += statement_words
    return rows


def validate_verification_contract(
    draft: SupplementDraft,
    verification: SupplementVerification,
    *,
    valid_evidence_ids: set[int],
) -> None:
    """Require one correctly typed, correctly cited result for every draft statement."""
    expected = {
        (card_index, statement_index)
        for card_index, card in enumerate(draft.cards)
        for statement_index, _statement in enumerate(card.statements)
    }
    actual = {
        (statement.card_index, statement.statement_index)
        for statement in verification.statements
    }
    missing = sorted(expected - actual)
    unexpected = sorted(actual - expected)
    if missing or unexpected:
        raise VerificationContractError(
            f"Verification coordinates mismatch; missing={missing}, "
            f"unexpected={unexpected}"
        )
    for result in verification.statements:
        statement = draft.cards[result.card_index].statements[result.statement_index]
        invalid_ids = sorted(
            evidence_id
            for evidence_id in result.evidence_ids
            if evidence_id not in valid_evidence_ids
            or evidence_id not in statement.evidence_ids
        )
        if invalid_ids:
            raise VerificationContractError(
                "Verification cited evidence IDs that are unavailable or were not "
                f"cited by the draft statement at "
                f"({result.card_index}, {result.statement_index}): {invalid_ids}"
            )


def _persist_verified_cards(
    session: Session,
    *,
    run: SupplementRun,
    draft: SupplementDraft,
    verification: SupplementVerification,
) -> int:
    evidence_by_id = {
        item.id: item
        for item in run.evidence_items
        if item.reliability_status == "trusted"
    }
    rows = supported_statement_rows(
        draft, verification, set(evidence_by_id), run.word_budget
    )
    by_card: dict[int, list[tuple[int, str, list[int]]]] = {}
    for card_index, statement_index, _card_type, text, evidence_ids in rows:
        by_card.setdefault(card_index, []).append(
            (statement_index, text, evidence_ids)
        )
    created = 0
    for card_index in sorted(by_card):
        draft_card = draft.cards[card_index]
        statements = by_card[card_index]
        summary = "\n\n".join(text for _index, text, _ids in statements)
        card = SupplementCard(
            supplement_run=run,
            card_type=draft_card.card_type,
            heading=draft_card.heading,
            summary_text=summary,
            word_count=len(summary.split()),
            display_order=created + 1,
            verification_status="verified",
        )
        session.add(card)
        session.flush()
        for statement_index, text, evidence_ids in statements:
            for citation_order, evidence_id in enumerate(evidence_ids, start=1):
                evidence = evidence_by_id[evidence_id]
                evidence.selected = True
                session.add(
                    SupplementCardCitation(
                        card=card,
                        evidence_item=evidence,
                        statement_index=statement_index,
                        citation_order=citation_order,
                        statement_text=text,
                    )
                )
        created += 1
    session.commit()
    return created


def generate_supplement_for_item(
    session: Session,
    item_id: int,
    *,
    daily_run_id: int | None,
    settings: Settings,
    provider: SupplementProvider | None = None,
    search_provider: ExternalSearchProvider | None = None,
    document_fetcher: DocumentFetcher | None = None,
    tool_policy: SupplementToolPolicy | None = None,
) -> SupplementRun:
    item_started = perf_counter()
    logger.info(
        "supplement stage=item_start item_id=%s daily_run_id=%s",
        item_id,
        daily_run_id,
    )
    item = _load_item(session, item_id)
    if item is None:
        raise LookupError("Daily reading item not found")
    article = item.article
    run = _prepare_run(
        session,
        item=item,
        daily_run_id=daily_run_id,
        settings=settings,
    )
    classification = session.scalar(
        select(ArticleAIClassification).where(
            ArticleAIClassification.article_id == article.id
        )
    )
    if not is_supplement_eligible(classification):
        run.status = SupplementStatus.SKIPPED.value
        run.decision_reason = (
            "Supplementation is limited to articles classified as news; "
            "this article is not classified as news."
        )
        run.completed_at = datetime.now(UTC)
        session.commit()
        logger.info(
            "supplement stage=eligibility status=skipped item_id=%s article_id=%s "
            "reason=not_classified_news",
            item_id,
            article.id,
        )
        return run

    provider = provider or build_supplement_provider(settings)
    if search_provider is None and settings.tavily_api_key is not None:
        search_provider = TavilySearchProvider(settings)
    tavily_fallback = (
        TavilyExtractFetcher(settings) if settings.tavily_api_key is not None else None
    )
    fetcher = document_fetcher or HttpDocumentFetcher(
        settings, fallback=tavily_fallback
    )
    policy = tool_policy or load_supplement_tool_policy(
        settings.supplement_tool_policy_path
    )
    logger.info(
        "supplement stage=setup status=ok item_id=%s article_id=%s model=%s "
        "web_search_available=%s max_iterations=%s verification_attempts=%s",
        item_id,
        article.id,
        provider.model,
        search_provider is not None,
        settings.supplement_max_iterations,
        settings.supplement_verification_max_attempts,
    )
    collector = policy.tool("collect_chunk")
    cluster_event = _cluster_event(session, article.id)
    gaps: list[str] = []
    history: list[dict[str, object]] = []
    decision_reason = ""
    tool_calls: Counter[str] = Counter()
    target_gaps: set[str] | None = None
    evidence_by_area = {name: set() for name in COVERAGE_AREAS}
    satisfied_areas: set[str] = set()
    try:
        for iteration in range(1, settings.supplement_max_iterations + 1):
            run.iteration_count = iteration
            available_search_names: list[str] = []
            local_tool = policy.tool("search_local")
            web_tool = policy.tool("web_search")
            government_tool = policy.tool("mcp_government_search")
            if local_tool.enabled and local_tool.agent_callable:
                available_search_names.append("search_local")
            if (
                search_provider is not None
                and web_tool.enabled
                and web_tool.agent_callable
                and web_tool.permissions.allowed_domain_set
            ):
                available_search_names.append("web_search")
            if (
                search_provider is not None
                and government_tool.enabled
                and government_tool.agent_callable
                and government_tool.permissions.allowed_domain_set
            ):
                available_search_names.append("mcp_government_search")
            available_tools = policy.llm_tool_list(
                [*available_search_names, "collect_chunk"]
                if available_search_names
                else []
            )
            evidence_payload = _evidence_payload(run.evidence_items)
            plan_hash = _fingerprint(
                article.title,
                article.content_hash or "",
                json.dumps(evidence_payload, sort_keys=True, default=str),
                json.dumps(history, sort_keys=True, default=str),
                provider.model,
            )
            logger.info(
                "supplement stage=planning status=start item_id=%s iteration=%s "
                "saved_evidence=%s available_tools=%s",
                item_id,
                iteration,
                len(evidence_payload),
                available_search_names,
            )
            plan_result: ProviderResult[SupplementPlan] | None = None
            planning_feedback: str | None = None
            for planning_attempt in range(
                1, settings.supplement_planning_max_attempts + 1
            ):
                attempt_hash = _fingerprint(
                    plan_hash, str(planning_attempt), planning_feedback or ""
                )
                retry_history = history
                if planning_feedback:
                    retry_history = [
                        *history,
                        {
                            "status": "structured_output_retry",
                            "validation_error": planning_feedback,
                            "instruction": (
                                "Return every required field with the exact schema type."
                            ),
                        },
                    ]
                try:
                    plan_result = provider.plan(
                        article_title=article.title,
                        article_content=article.content_text or "",
                        cluster_event=cluster_event,
                        evidence=evidence_payload,
                        tool_history=retry_history,
                        available_tools=available_tools,
                        coverage_targets=_coverage_target_payload(
                            target_gaps=target_gaps,
                            evidence_by_area=evidence_by_area,
                            satisfied_areas=satisfied_areas,
                        ),
                    )
                    break
                except StructuredOutputError as exc:
                    planning_feedback = str(exc)[:4000]
                    _record_model_failure(
                        session,
                        run_id=daily_run_id,
                        role="supplement_planning",
                        provider=provider,
                        input_hash=attempt_hash,
                        error=exc,
                        settings=settings,
                    )
                    logger.warning(
                        "supplement stage=planning status=retry item_id=%s "
                        "iteration=%s attempt=%s/%s error=%s",
                        item_id,
                        iteration,
                        planning_attempt,
                        settings.supplement_planning_max_attempts,
                        exc,
                    )
                    if planning_attempt >= settings.supplement_planning_max_attempts:
                        raise
                except Exception as exc:
                    _record_model_failure(
                        session,
                        run_id=daily_run_id,
                        role="supplement_planning",
                        provider=provider,
                        input_hash=attempt_hash,
                        error=exc,
                        settings=settings,
                    )
                    raise
            if plan_result is None:
                raise RuntimeError("Planning attempts ended without a result")
            _record_model_result(
                session,
                run_id=daily_run_id,
                role="supplement_planning",
                provider=provider,
                input_hash=plan_hash,
                result=plan_result,  # type: ignore[arg-type]
                settings=settings,
            )
            plan = plan_result.value
            gaps = _coverage_gaps(plan)
            logger.info(
                "supplement stage=planning status=ok item_id=%s iteration=%s "
                "elapsed_ms=%.2f supplement_needed=%s next_step=%s gaps=%s "
                "tool_calls=%s",
                item_id,
                iteration,
                plan_result.elapsed_ms,
                plan.supplement_needed,
                plan.next_step,
                gaps,
                [call.name for call in plan.tool_calls],
            )
            if target_gaps is None:
                target_gaps = set(gaps)
            _update_coverage_ledger(
                plan,
                target_gaps=target_gaps,
                evidence_by_area=evidence_by_area,
                satisfied_areas=satisfied_areas,
                valid_evidence_ids={int(item["evidence_id"]) for item in evidence_payload},
            )
            decision_reason = plan.reason
            run.detected_gaps = "\n".join(sorted(target_gaps)) or None
            run.decision_reason = decision_reason
            session.commit()

            if not plan.supplement_needed:
                run.status = SupplementStatus.SKIPPED.value
                run.completed_at = datetime.now(UTC)
                session.commit()
                logger.info(
                    "supplement stage=termination status=skipped item_id=%s "
                    "reason=no_supplement_needed",
                    item_id,
                )
                return run
            if _coverage_research_complete(
                target_gaps, evidence_by_area, satisfied_areas
            ):
                history.append(
                    {
                        "status": "research_complete",
                        "reason": (
                            "Every target area is satisfied or reached the maximum "
                            "of three relevant evidence chunks."
                        ),
                        "coverage_targets": _coverage_target_payload(
                            target_gaps=target_gaps,
                            evidence_by_area=evidence_by_area,
                            satisfied_areas=satisfied_areas,
                        ),
                    }
                )
                run.tool_history = json.dumps(history, ensure_ascii=False, default=str)
                session.commit()
                logger.info(
                    "supplement stage=termination status=research_complete "
                    "item_id=%s iteration=%s evidence=%s",
                    item_id,
                    iteration,
                    len(evidence_payload),
                )
                break
            if plan.next_step == "compose":
                logger.info(
                    "supplement stage=termination status=compose item_id=%s iteration=%s",
                    item_id,
                    iteration,
                )
                break
            if plan.next_step == "stop":
                run.status = SupplementStatus.INSUFFICIENT.value
                run.completed_at = datetime.now(UTC)
                session.commit()
                logger.info(
                    "supplement stage=termination status=insufficient item_id=%s "
                    "reason=planner_stop",
                    item_id,
                )
                return run

            try:
                extracted = extract_tool_pair(
                    plan,
                    policy=policy,
                    available_search_names=set(available_search_names),
                    allowed_purposes={
                        name
                        for name, target in _coverage_target_payload(
                            target_gaps=target_gaps,
                            evidence_by_area=evidence_by_area,
                            satisfied_areas=satisfied_areas,
                        ).items()
                        if target["status"] == "search_needed"
                    },
                    call_counts=tool_calls,
                )
            except ToolCallRejected as exc:
                result_payload = {
                    "tool_calls": [
                        call.model_dump(mode="json") for call in plan.tool_calls
                    ],
                    "status": "rejected",
                    "error": str(exc),
                    "results": [],
                }
                history.append(result_payload)
                run.tool_history = json.dumps(history, ensure_ascii=False, default=str)
                session.commit()
                logger.warning(
                    "supplement stage=tool_validation status=rejected item_id=%s "
                    "iteration=%s error=%s",
                    item_id,
                    iteration,
                    exc,
                )
                continue

            search_call = extracted.search_call
            search_name = search_call.name
            search_tool = extracted.search_policy
            collector = extracted.collect_policy
            search_arguments = search_call.arguments
            query = extracted.query
            before_ids = {item.id for item in run.evidence_items}
            tool_calls[search_name] += 1
            tool_calls["collect_chunk"] += 1
            run.tool_call_count += 2
            tool_started = perf_counter()
            logger.info(
                "supplement stage=tool_call status=start item_id=%s iteration=%s "
                "tool=%s purpose=%s query_hash=%s result_limit=%s domains=%s "
                "start_date=%s end_date=%s",
                item_id,
                iteration,
                search_name,
                search_arguments.purpose,
                _fingerprint(query)[:12],
                extracted.result_limit,
                len(extracted.allowed_domains),
                search_arguments.start_date,
                search_arguments.end_date,
            )
            if search_name == "search_local":
                added = _save_local_evidence(
                    session,
                    run=run,
                    selected_article_id=article.id,
                    query=query,
                    start_date=search_arguments.start_date,
                    end_date=search_arguments.end_date,
                    settings=settings,
                    tool=search_tool,
                    collector=collector,
                    result_limit=extracted.result_limit,
                )
            elif search_name == "web_search":
                added = _save_external_evidence(
                    session,
                    run=run,
                    query=query,
                    start_date=search_arguments.start_date,
                    end_date=search_arguments.end_date,
                    source_type="web",
                    allowed_domains=set(extracted.allowed_domains),
                    settings=settings,
                    search_provider=search_provider,
                    document_fetcher=fetcher,
                    tool=search_tool,
                    collector=collector,
                    result_limit=extracted.result_limit,
                )
            else:
                added = _save_external_evidence(
                    session,
                    run=run,
                    query=query,
                    start_date=search_arguments.start_date,
                    end_date=search_arguments.end_date,
                    source_type="government",
                    allowed_domains=set(extracted.allowed_domains),
                    settings=settings,
                    search_provider=search_provider,
                    document_fetcher=fetcher,
                    tool=search_tool,
                    collector=collector,
                    result_limit=extracted.result_limit,
                )
            session.commit()
            session.refresh(run)
            new_evidence = [
                payload
                for payload in _evidence_payload(run.evidence_items)
                if int(payload["evidence_id"]) not in before_ids
            ]
            history.append(
                {
                    "tool_calls": [
                        call.model_dump(mode="json") for call in plan.tool_calls
                    ],
                    "status": "complete",
                    "saved_count": added,
                    "results": new_evidence,
                }
            )
            run.tool_history = json.dumps(history, ensure_ascii=False, default=str)
            session.commit()
            logger.info(
                "supplement stage=tool_call status=ok item_id=%s iteration=%s "
                "tool=%s elapsed_ms=%.2f saved=%s total_evidence=%s",
                item_id,
                iteration,
                search_name,
                (perf_counter() - tool_started) * 1000,
                added,
                len(run.evidence_items),
            )

        evidence_payload = _evidence_payload(run.evidence_items)
        if target_gaps is not None:
            gaps = sorted(target_gaps)
        if not evidence_payload or run.word_budget <= 0:
            run.status = SupplementStatus.INSUFFICIENT.value
            run.completed_at = datetime.now(UTC)
            session.commit()
            logger.info(
                "supplement stage=termination status=insufficient item_id=%s "
                "reason=no_evidence_or_budget evidence=%s word_budget=%s",
                item_id,
                len(evidence_payload),
                run.word_budget,
            )
            return run

        compose_hash = _fingerprint(
            article.title,
            json.dumps(gaps),
            json.dumps(evidence_payload, sort_keys=True, default=str),
            str(run.word_budget),
            provider.model,
        )
        logger.info(
            "supplement stage=composition status=start item_id=%s gaps=%s "
            "evidence=%s word_budget=%s",
            item_id,
            gaps,
            len(evidence_payload),
            run.word_budget,
        )
        try:
            draft_result = provider.compose(
                article_title=article.title,
                gaps=gaps,
                evidence=evidence_payload,
                word_budget=run.word_budget,
            )
        except Exception as exc:
            _record_model_failure(
                session,
                run_id=daily_run_id,
                role="supplement_composition",
                provider=provider,
                input_hash=compose_hash,
                error=exc,
                settings=settings,
            )
            raise
        _record_model_result(
            session,
            run_id=daily_run_id,
            role="supplement_composition",
            provider=provider,
            input_hash=compose_hash,
            result=draft_result,  # type: ignore[arg-type]
            settings=settings,
        )
        session.commit()
        draft = draft_result.value
        statement_count = sum(len(card.statements) for card in draft.cards)
        logger.info(
            "supplement stage=composition status=ok item_id=%s elapsed_ms=%.2f "
            "cards=%s statements=%s",
            item_id,
            draft_result.elapsed_ms,
            len(draft.cards),
            statement_count,
        )
        verify_hash = _fingerprint(
            draft.model_dump_json(),
            json.dumps(evidence_payload, sort_keys=True, default=str),
            provider.model,
        )
        verification_result: ProviderResult[SupplementVerification] | None = None
        validation_feedback: str | None = None
        for verification_attempt in range(
            1, settings.supplement_verification_max_attempts + 1
        ):
            attempt_hash = _fingerprint(
                verify_hash, str(verification_attempt), validation_feedback or ""
            )
            logger.info(
                "supplement stage=verification status=start item_id=%s attempt=%s/%s "
                "statements=%s evidence=%s",
                item_id,
                verification_attempt,
                settings.supplement_verification_max_attempts,
                statement_count,
                len(evidence_payload),
            )
            try:
                candidate_result = provider.verify(
                    draft=draft,
                    evidence=evidence_payload,
                    validation_feedback=validation_feedback,
                )
                validate_verification_contract(
                    draft,
                    candidate_result.value,
                    valid_evidence_ids={int(item["evidence_id"]) for item in evidence_payload},
                )
                verification_result = candidate_result
                logger.info(
                    "supplement stage=verification status=ok item_id=%s attempt=%s "
                    "elapsed_ms=%.2f verified_rows=%s",
                    item_id,
                    verification_attempt,
                    candidate_result.elapsed_ms,
                    len(candidate_result.value.statements),
                )
                break
            except (StructuredOutputError, VerificationContractError) as exc:
                validation_feedback = str(exc)[:4000]
                _record_model_failure(
                    session,
                    run_id=daily_run_id,
                    role="supplement_verification",
                    provider=provider,
                    input_hash=attempt_hash,
                    error=exc,
                    settings=settings,
                )
                logger.warning(
                    "supplement stage=verification status=retry item_id=%s attempt=%s/%s "
                    "error=%s",
                    item_id,
                    verification_attempt,
                    settings.supplement_verification_max_attempts,
                    exc,
                )
                if verification_attempt >= settings.supplement_verification_max_attempts:
                    raise
            except Exception as exc:
                _record_model_failure(
                    session,
                    run_id=daily_run_id,
                    role="supplement_verification",
                    provider=provider,
                    input_hash=attempt_hash,
                    error=exc,
                    settings=settings,
                )
                logger.exception(
                    "supplement stage=verification status=error item_id=%s attempt=%s",
                    item_id,
                    verification_attempt,
                )
                raise
        if verification_result is None:
            raise RuntimeError("Verification attempts ended without a result")
        _record_model_result(
            session,
            run_id=daily_run_id,
            role="supplement_verification",
            provider=provider,
            input_hash=_fingerprint(verify_hash, "success"),
            result=verification_result,  # type: ignore[arg-type]
            settings=settings,
        )
        session.commit()
        card_count = _persist_verified_cards(
            session,
            run=run,
            draft=draft,
            verification=verification_result.value,
        )
        run.status = (
            SupplementStatus.COMPLETE.value
            if card_count
            else SupplementStatus.INSUFFICIENT.value
        )
        run.completed_at = datetime.now(UTC)
        session.commit()
        logger.info(
            "supplement stage=item_complete status=%s item_id=%s elapsed_ms=%.2f "
            "cards=%s evidence=%s tool_calls=%s",
            run.status,
            item_id,
            (perf_counter() - item_started) * 1000,
            card_count,
            len(run.evidence_items),
            run.tool_call_count,
        )
        return run
    except Exception as exc:
        run.status = SupplementStatus.FAILED.value
        run.last_error = str(exc)[:4000]
        run.completed_at = datetime.now(UTC)
        session.commit()
        logger.exception(
            "supplement stage=item_complete status=failed item_id=%s elapsed_ms=%.2f "
            "error=%s",
            item_id,
            (perf_counter() - item_started) * 1000,
            exc,
        )
        raise


def generate_supplements_for_list(
    session: Session,
    reading_list_id: int,
    *,
    daily_run_id: int | None,
    settings: Settings,
    provider: SupplementProvider | None = None,
    search_provider: ExternalSearchProvider | None = None,
    document_fetcher: DocumentFetcher | None = None,
    tool_policy: SupplementToolPolicy | None = None,
) -> SupplementBatchStats:
    reading_list = session.scalar(
        select(DailyReadingList)
        .where(DailyReadingList.id == reading_list_id)
        .options(selectinload(DailyReadingList.items))
    )
    if reading_list is None:
        raise LookupError("Daily reading list not found")
    counts = {
        "complete": 0,
        "skipped": 0,
        "insufficient": 0,
        "failed": 0,
        "evidence_items": 0,
        "cards": 0,
    }
    for item in reading_list.items:
        try:
            run = generate_supplement_for_item(
                session,
                item.id,
                daily_run_id=daily_run_id,
                settings=settings,
                provider=provider,
                search_provider=search_provider,
                document_fetcher=document_fetcher,
                tool_policy=tool_policy,
            )
            counts[run.status] += 1
            counts["evidence_items"] += len(run.evidence_items)
            counts["cards"] += len(run.cards)
        except Exception:
            counts["failed"] += 1
            logger.exception(
                "supplement generation failed item_id=%s daily_run_id=%s",
                item.id,
                daily_run_id,
            )
    return SupplementBatchStats(**counts)


async def generate_supplements_for_list_async(
    session: Session,
    reading_list_id: int,
    *,
    daily_run_id: int | None,
    settings: Settings,
    provider: SupplementProvider | None = None,
    search_provider: ExternalSearchProvider | None = None,
    document_fetcher: DocumentFetcher | None = None,
    tool_policy: SupplementToolPolicy | None = None,
) -> SupplementBatchStats:
    """Generate distinct reading-list items concurrently with isolated sessions.

    The planning/tool/composition loop inside one item remains ordered. This
    prevents an LLM iteration from reading evidence while another tool call is
    still writing that same supplement run.
    """
    reading_list = session.scalar(
        select(DailyReadingList)
        .where(DailyReadingList.id == reading_list_id)
        .options(selectinload(DailyReadingList.items))
    )
    if reading_list is None:
        raise LookupError("Daily reading list not found")
    item_ids = [item.id for item in reading_list.items]

    def generate_one(item_id: int) -> tuple[str, int, int]:
        with SessionLocal() as worker_session:
            try:
                run = generate_supplement_for_item(
                    worker_session,
                    item_id,
                    daily_run_id=daily_run_id,
                    settings=settings,
                    provider=provider,
                    search_provider=search_provider,
                    document_fetcher=document_fetcher,
                    tool_policy=tool_policy,
                )
                return run.status, len(run.evidence_items), len(run.cards)
            except Exception:
                logger.exception(
                    "supplement generation failed item_id=%s daily_run_id=%s",
                    item_id,
                    daily_run_id,
                )
                return "failed", 0, 0

    results = await bounded_to_thread_map(
        item_ids,
        generate_one,
        max_concurrency=settings.supplement_max_concurrency,
    )
    counts = {
        "complete": 0,
        "skipped": 0,
        "insufficient": 0,
        "failed": 0,
        "evidence_items": 0,
        "cards": 0,
    }
    for status, evidence_count, card_count in results:
        counts[status] += 1
        counts["evidence_items"] += evidence_count
        counts["cards"] += card_count
    return SupplementBatchStats(**counts)
