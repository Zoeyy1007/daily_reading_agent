import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, selectinload

from app.ai.factory import build_model_providers
from app.ai.providers import ModelProviders, ProviderResult
from app.ai.schemas import EvidenceClaimInput, EvidenceLinkResult, EvidencePairInput
from app.config import Settings
from app.db.models import (
    Article,
    ArticleAIClassification,
    ArticleChunk,
    ArticleClaim,
    ArticleFeature,
    ArticleFeatureType,
    ClaimLink,
    ClusterComparison,
    ModelCall,
    Source,
    StoryCluster,
    StoryClusterMember,
)

WORD_PATTERN = re.compile(r"\S+")
TERM_PATTERN = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True, slots=True)
class RankedChunk:
    chunk: ArticleChunk
    bm25_score: float
    vector_score: float
    hybrid_score: float


@dataclass(frozen=True, slots=True)
class ClaimPairCandidate:
    left: ArticleClaim
    right: ArticleClaim
    retrieval_score: float


def content_fingerprint(*parts: str) -> str:
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def _expiry(days: int) -> datetime:
    return datetime.now(UTC) + timedelta(days=days)


def _providers(settings: Settings, supplied: ModelProviders | None) -> ModelProviders:
    return supplied or build_model_providers(settings)


def _record_success(
    session: Session,
    *,
    run_id: int,
    role: str,
    provider: str,
    model: str,
    input_hash: str,
    result: ProviderResult[object] | object,
    settings: Settings,
) -> None:
    session.add(
        ModelCall(
            run_id=run_id,
            role=role,
            provider=provider,
            model=model,
            status="complete",
            input_hash=input_hash,
            provider_request_id=getattr(result, "request_id", None),
            input_tokens=getattr(result, "input_tokens", None),
            output_tokens=getattr(result, "output_tokens", None),
            elapsed_ms=getattr(result, "elapsed_ms", None),
            expires_at=_expiry(settings.model_call_log_retention_days),
        )
    )


def _record_failure(
    session: Session,
    *,
    run_id: int,
    role: str,
    provider: str,
    model: str,
    input_hash: str,
    error: Exception,
    settings: Settings,
) -> None:
    session.add(
        ModelCall(
            run_id=run_id,
            role=role,
            provider=provider,
            model=model,
            status="failed",
            input_hash=input_hash,
            error=str(error)[:4000],
            expires_at=_expiry(settings.model_call_log_retention_days),
        )
    )
    session.commit()


def _articles(session: Session, article_ids: list[int]) -> list[Article]:
    if not article_ids:
        return []
    return list(
        session.scalars(
            select(Article)
            .where(Article.id.in_(article_ids))
            .options(selectinload(Article.source))
            .order_by(Article.id)
        )
    )


def classify_articles_with_model(
    session: Session,
    article_ids: list[int],
    *,
    run_id: int,
    settings: Settings,
    providers: ModelProviders | None = None,
) -> int:
    provider = _providers(settings, providers).classification
    if provider is None:
        return 0
    processed = 0
    for article in _articles(session, article_ids)[: settings.phase_five_max_articles]:
        content = article.content_text or ""
        input_hash = content_fingerprint(article.title, content, settings.prompt_version)
        cached = session.scalar(
            select(ArticleAIClassification).where(
                ArticleAIClassification.article_id == article.id
            )
        )
        if (
            cached is not None
            and cached.input_hash == input_hash
            and cached.model == provider.model
        ):
            continue
        try:
            result = provider.classify(title=article.title, content=content)
        except Exception as exc:
            _record_failure(
                session,
                run_id=run_id,
                role="classification",
                provider=provider.provider_name,
                model=provider.model,
                input_hash=input_hash,
                error=exc,
                settings=settings,
            )
            raise
        value = result.value
        if cached is None:
            cached = ArticleAIClassification(article_id=article.id)
            session.add(cached)
        cached.content_type = value.content_type
        cached.is_news = value.is_news
        cached.confidence = value.confidence
        cached.provider = provider.provider_name
        cached.model = provider.model
        cached.prompt_version = settings.prompt_version
        cached.input_hash = input_hash
        article.content_type = value.content_type
        content_type_feature = session.scalar(
            select(ArticleFeature).where(
                ArticleFeature.article_id == article.id,
                ArticleFeature.feature_type == ArticleFeatureType.CONTENT_TYPE.value,
            )
        )
        if content_type_feature is None:
            session.add(
                ArticleFeature(
                    article_id=article.id,
                    feature_type=ArticleFeatureType.CONTENT_TYPE.value,
                    feature_value=value.content_type,
                    confidence=value.confidence,
                )
            )
        else:
            content_type_feature.feature_value = value.content_type
            content_type_feature.confidence = value.confidence
        existing_topics = set(
            session.scalars(
                select(ArticleFeature.feature_value).where(
                    ArticleFeature.article_id == article.id,
                    ArticleFeature.feature_type == ArticleFeatureType.TOPIC.value,
                )
            )
        )
        for topic in value.topics:
            normalized = topic.strip().casefold()[:200]
            if normalized and normalized not in existing_topics:
                session.add(
                    ArticleFeature(
                        article_id=article.id,
                        feature_type=ArticleFeatureType.TOPIC.value,
                        feature_value=normalized,
                        confidence=value.confidence,
                    )
                )
                existing_topics.add(normalized)
        _record_success(
            session,
            run_id=run_id,
            role="classification",
            provider=provider.provider_name,
            model=provider.model,
            input_hash=input_hash,
            result=result,
            settings=settings,
        )
        session.commit()
        processed += 1
    return processed


def article_embedding_text(article: Article) -> str:
    summary = article.rss_summary or ""
    content = article.content_text or ""
    return f"Title: {article.title}\nSummary: {summary}\nArticle: {content[:24000]}"


def embed_articles(
    session: Session,
    article_ids: list[int],
    *,
    run_id: int,
    settings: Settings,
    providers: ModelProviders | None = None,
) -> int:
    provider = _providers(settings, providers).embedding
    if provider is None:
        return 0
    articles = [
        article
        for article in _articles(session, article_ids)[: settings.phase_five_max_articles]
        if article.embedding is None or article.embedding_model != provider.model
    ]
    processed = 0
    for start in range(0, len(articles), settings.embedding_batch_size):
        batch = articles[start : start + settings.embedding_batch_size]
        texts = [article_embedding_text(article) for article in batch]
        input_hash = content_fingerprint(*texts, provider.model)
        try:
            result = provider.embed(texts)
        except Exception as exc:
            _record_failure(
                session,
                run_id=run_id,
                role="article_embedding",
                provider=provider.provider_name,
                model=provider.model,
                input_hash=input_hash,
                error=exc,
                settings=settings,
            )
            raise
        for article, vector in zip(batch, result.vectors, strict=True):
            article.embedding = vector
            article.embedding_model = provider.model
            article.embedded_at = datetime.now(UTC)
        _record_success(
            session,
            run_id=run_id,
            role="article_embedding",
            provider=provider.provider_name,
            model=provider.model,
            input_hash=input_hash,
            result=result,
            settings=settings,
        )
        session.commit()
        processed += len(batch)
    return processed


def _mean_vectors(left: list[float], right: list[float], left_weight: int) -> list[float]:
    denominator = left_weight + 1
    return [
        (float(old) * left_weight + float(new)) / denominator
        for old, new in zip(left, right, strict=True)
    ]


def _cosine(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def _select_cluster_articles(
    articles: list[Article],
    *,
    article_groups: dict[int, int],
    centroid: list[float],
    max_articles: int,
    redundancy_threshold: float,
) -> set[int]:
    """Keep source diversity first, then add novel coverage with MMR."""
    candidates = [article for article in articles if article.embedding is not None]
    if len(candidates) <= max_articles:
        return {article.id for article in candidates}

    relevance = {
        article.id: _cosine(list(article.embedding), centroid) for article in candidates
    }
    source_best: dict[int, Article] = {}
    for article in sorted(candidates, key=lambda item: relevance[item.id], reverse=True):
        source_best.setdefault(article_groups[article.id], article)

    selected = sorted(
        source_best.values(), key=lambda item: relevance[item.id], reverse=True
    )[:max_articles]
    selected_ids = {article.id for article in selected}
    remaining = [article for article in candidates if article.id not in selected_ids]

    while remaining and len(selected) < max_articles:
        scored: list[tuple[float, float, Article]] = []
        for article in remaining:
            max_similarity = max(
                _cosine(list(article.embedding), list(kept.embedding))
                for kept in selected
                if kept.embedding is not None
            )
            if max_similarity >= redundancy_threshold:
                continue
            novelty = 1.0 - max_similarity
            mmr_score = 0.65 * relevance[article.id] + 0.35 * novelty
            scored.append((mmr_score, relevance[article.id], article))
        if not scored:
            break
        _score, _relevance, chosen = max(
            scored, key=lambda row: (row[0], row[1], -row[2].id)
        )
        selected.append(chosen)
        selected_ids.add(chosen.id)
        remaining = [article for article in remaining if article.id != chosen.id]
    return selected_ids


def _prune_cluster_members(
    session: Session, cluster_id: int, *, settings: Settings
) -> tuple[int, int]:
    cluster = session.get(StoryCluster, cluster_id)
    if cluster is None:
        return 0, 0
    rows = session.execute(
        select(StoryClusterMember, Article, Source.publisher_id)
        .join(Article, Article.id == StoryClusterMember.article_id)
        .join(Source, Source.id == Article.source_id)
        .where(StoryClusterMember.cluster_id == cluster_id)
        .order_by(StoryClusterMember.id)
    ).all()
    articles = [article for _member, article, _publisher_id in rows]
    article_groups = {
        article.id: publisher_id for _member, article, publisher_id in rows
    }
    selected_ids = _select_cluster_articles(
        articles,
        article_groups=article_groups,
        centroid=list(cluster.centroid_embedding),
        max_articles=settings.story_cluster_max_articles,
        redundancy_threshold=settings.story_cluster_redundancy_threshold,
    )
    changed = False
    for member, article, _publisher_id in rows:
        relationship = "coverage" if article.id in selected_ids else "redundant"
        if member.relationship != relationship:
            member.relationship = relationship
            changed = True
    if changed:
        cluster.comparison_status = "pending"
    session.commit()
    active_sources = len(
        {
            publisher_id
            for _member, article, publisher_id in rows
            if article.id in selected_ids
        }
    )
    return len(selected_ids), active_sources


def cluster_articles(
    session: Session,
    article_ids: list[int],
    *,
    settings: Settings,
) -> tuple[list[int], list[int]]:
    cluster_ids: set[int] = set()
    evidence_cluster_ids: list[int] = []
    cutoff = date.today() - timedelta(days=settings.story_cluster_lookback_days)
    classifications = {
        item.article_id: item
        for item in session.scalars(
            select(ArticleAIClassification).where(
                ArticleAIClassification.article_id.in_(article_ids)
            )
        )
    }
    for article in _articles(session, article_ids):
        classification = classifications.get(article.id)
        if article.embedding is None or not (
            classification.is_news if classification is not None else article.content_type == "news"
        ):
            continue
        existing_member = session.scalar(
            select(StoryClusterMember).where(
                StoryClusterMember.article_id == article.id
            )
        )
        if existing_member is not None:
            cluster_ids.add(existing_member.cluster_id)
            continue
        distance = StoryCluster.centroid_embedding.cosine_distance(article.embedding)
        row = session.execute(
            select(StoryCluster, distance.label("distance"))
            .where(
                StoryCluster.event_date >= cutoff,
                StoryCluster.embedding_model == article.embedding_model,
            )
            .order_by(distance)
            .limit(1)
        ).first()
        cluster: StoryCluster | None = None
        similarity = 1.0
        if row is not None:
            candidate, candidate_distance = row
            candidate_similarity = 1.0 - float(candidate_distance)
            if candidate_similarity >= settings.story_cluster_similarity_threshold:
                cluster = candidate
                similarity = candidate_similarity
        article_date = (
            article.published_at.date()
            if article.published_at is not None
            else article.discovered_at.date()
        )
        if cluster is None:
            cluster = StoryCluster(
                representative_title=article.title,
                event_summary=article.rss_summary,
                event_date=article_date,
                centroid_embedding=list(article.embedding),
                representative_article_id=article.id,
                comparison_status="singleton",
                embedding_model=article.embedding_model or settings.embedding_model,
                expires_at=_expiry(settings.cluster_metadata_retention_days),
            )
            session.add(cluster)
            session.flush()
        else:
            member_count = session.scalar(
                select(func.count()).select_from(StoryClusterMember).where(
                    StoryClusterMember.cluster_id == cluster.id
                )
            ) or 0
            cluster.centroid_embedding = _mean_vectors(
                list(cluster.centroid_embedding), list(article.embedding), int(member_count)
            )
            cluster.comparison_status = "pending"
            cluster.expires_at = _expiry(settings.cluster_metadata_retention_days)
        session.add(
            StoryClusterMember(
                cluster_id=cluster.id,
                article_id=article.id,
                similarity_score=similarity,
                relationship="coverage",
            )
        )
        session.commit()
        cluster_ids.add(cluster.id)

    for cluster_id in sorted(cluster_ids):
        active_count, source_count = _prune_cluster_members(
            session, cluster_id, settings=settings
        )
        cluster = session.get(StoryCluster, cluster_id)
        if source_count >= 2:
            evidence_cluster_ids.append(cluster_id)
        elif cluster is not None:
            cluster.comparison_status = (
                "single_source" if active_count > 1 else "singleton"
            )
            session.commit()
    return sorted(cluster_ids), evidence_cluster_ids


def split_article_content(
    content: str, *, target_words: int, overlap_words: int
) -> list[tuple[str, int, int]]:
    matches = list(WORD_PATTERN.finditer(content))
    if not matches:
        return []
    step = max(1, target_words - overlap_words)
    chunks: list[tuple[str, int, int]] = []
    for word_start in range(0, len(matches), step):
        word_end = min(len(matches), word_start + target_words)
        character_start = matches[word_start].start()
        character_end = matches[word_end - 1].end()
        chunks.append((content[character_start:character_end], character_start, character_end))
        if word_end == len(matches):
            break
    return chunks


def chunk_cluster_articles(
    session: Session,
    cluster_ids: list[int],
    *,
    settings: Settings,
) -> int:
    if not cluster_ids:
        return 0
    articles = list(
        session.scalars(
            select(Article)
            .join(StoryClusterMember, StoryClusterMember.article_id == Article.id)
            .where(
                StoryClusterMember.cluster_id.in_(cluster_ids),
                StoryClusterMember.relationship == "coverage",
            )
        )
    )
    created = 0
    for article in articles:
        if not article.content_text:
            continue
        if session.scalar(
            select(func.count()).select_from(ArticleChunk).where(
                ArticleChunk.article_id == article.id
            )
        ):
            continue
        if (article.word_count or 0) < settings.article_chunk_word_threshold:
            pieces = [(article.content_text, 0, len(article.content_text))]
        else:
            pieces = split_article_content(
                article.content_text,
                target_words=settings.article_chunk_target_words,
                overlap_words=settings.article_chunk_overlap_words,
            )
        for index, (text, character_start, character_end) in enumerate(pieces):
            session.add(
                ArticleChunk(
                    article_id=article.id,
                    chunk_index=index,
                    chunk_text=text,
                    word_count=len(text.split()),
                    character_start=character_start,
                    character_end=character_end,
                    content_hash=content_fingerprint(text),
                    expires_at=_expiry(settings.unselected_chunk_retention_days),
                )
            )
            created += 1
        session.commit()
    return created


def embed_chunks(
    session: Session,
    cluster_ids: list[int],
    *,
    run_id: int,
    settings: Settings,
    providers: ModelProviders | None = None,
) -> int:
    if not cluster_ids:
        return 0
    provider = _providers(settings, providers).embedding
    if provider is None:
        return 0
    chunks = list(
        session.scalars(
            select(ArticleChunk)
            .join(StoryClusterMember, StoryClusterMember.article_id == ArticleChunk.article_id)
            .where(
                StoryClusterMember.cluster_id.in_(cluster_ids),
                StoryClusterMember.relationship == "coverage",
                ArticleChunk.embedding.is_(None),
            )
            .order_by(ArticleChunk.id)
        )
    )
    processed = 0
    for start in range(0, len(chunks), settings.embedding_batch_size):
        batch = chunks[start : start + settings.embedding_batch_size]
        texts = [chunk.chunk_text for chunk in batch]
        input_hash = content_fingerprint(*texts, provider.model)
        try:
            result = provider.embed(texts)
        except Exception as exc:
            _record_failure(
                session,
                run_id=run_id,
                role="chunk_embedding",
                provider=provider.provider_name,
                model=provider.model,
                input_hash=input_hash,
                error=exc,
                settings=settings,
            )
            raise
        for chunk, vector in zip(batch, result.vectors, strict=True):
            chunk.embedding = vector
            chunk.embedding_model = provider.model
        _record_success(
            session,
            run_id=run_id,
            role="chunk_embedding",
            provider=provider.provider_name,
            model=provider.model,
            input_hash=input_hash,
            result=result,
            settings=settings,
        )
        session.commit()
        processed += len(batch)
    return processed


def _terms(text: str) -> list[str]:
    return TERM_PATTERN.findall(text.casefold())


def _bm25_scores(query: str, documents: list[str]) -> list[float]:
    """Small in-memory Okapi BM25 ranker for one story cluster."""
    if not documents:
        return []
    query_terms = set(_terms(query))
    tokenized = [_terms(document) for document in documents]
    if not query_terms:
        return [0.0] * len(documents)
    average_length = sum(len(tokens) for tokens in tokenized) / len(tokenized) or 1.0
    document_frequency = {
        term: sum(term in set(tokens) for tokens in tokenized) for term in query_terms
    }
    k1 = 1.5
    b = 0.75
    scores: list[float] = []
    for tokens in tokenized:
        frequencies = Counter(tokens)
        document_length = len(tokens)
        score = 0.0
        for term in query_terms:
            frequency = frequencies.get(term, 0)
            if not frequency:
                continue
            frequency_in_documents = document_frequency[term]
            inverse_document_frequency = math.log(
                1
                + (len(documents) - frequency_in_documents + 0.5)
                / (frequency_in_documents + 0.5)
            )
            denominator = frequency + k1 * (
                1 - b + b * document_length / average_length
            )
            score += inverse_document_frequency * frequency * (k1 + 1) / denominator
        scores.append(score)
    return scores


def _normalize_scores(scores: list[float]) -> list[float]:
    if not scores:
        return []
    minimum = min(scores)
    maximum = max(scores)
    if math.isclose(minimum, maximum):
        return [1.0 if maximum > 0 else 0.0 for _score in scores]
    return [(score - minimum) / (maximum - minimum) for score in scores]


def retrieve_cluster_chunks(
    session: Session, cluster_id: int, *, settings: Settings
) -> list[RankedChunk]:
    cluster = session.get(StoryCluster, cluster_id)
    if cluster is None:
        return []
    rows = session.execute(
        select(ArticleChunk, Article.title)
        .join(Article, Article.id == ArticleChunk.article_id)
        .join(StoryClusterMember, StoryClusterMember.article_id == Article.id)
        .where(
            StoryClusterMember.cluster_id == cluster_id,
            StoryClusterMember.relationship == "coverage",
        )
        .order_by(ArticleChunk.article_id, ArticleChunk.chunk_index)
    ).all()
    if not rows:
        return []
    chunks = [chunk for chunk, _title in rows]
    titles = list(dict.fromkeys(title for _chunk, title in rows))
    query = " ".join(
        part
        for part in [cluster.representative_title, cluster.event_summary, *titles]
        if part
    )
    normalized_bm25 = _normalize_scores(
        _bm25_scores(query, [chunk.chunk_text for chunk in chunks])
    )
    vector_scores = [
        max(
            0.0,
            min(
                1.0,
                (
                    _cosine(list(chunk.embedding), list(cluster.centroid_embedding))
                    + 1.0
                )
                / 2.0,
            ),
        )
        if chunk.embedding is not None
        else 0.0
        for chunk in chunks
    ]
    total_weight = settings.evidence_bm25_weight + settings.evidence_vector_weight
    bm25_weight = settings.evidence_bm25_weight / total_weight if total_weight else 0.5
    vector_weight = settings.evidence_vector_weight / total_weight if total_weight else 0.5
    ranked = [
        RankedChunk(
            chunk=chunk,
            bm25_score=bm25,
            vector_score=vector,
            hybrid_score=bm25_weight * bm25 + vector_weight * vector,
        )
        for chunk, bm25, vector in zip(
            chunks, normalized_bm25, vector_scores, strict=True
        )
    ]
    ranked.sort(key=lambda item: (item.hybrid_score, -item.chunk.id), reverse=True)

    selected: list[RankedChunk] = []
    selected_ids: set[int] = set()
    for article_id in dict.fromkeys(item.chunk.article_id for item in ranked):
        best = next(item for item in ranked if item.chunk.article_id == article_id)
        selected.append(best)
        selected_ids.add(best.chunk.id)
        if len(selected) >= settings.evidence_retrieval_chunk_limit:
            return selected
    for item in ranked:
        if item.chunk.id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(item.chunk.id)
        if len(selected) >= settings.evidence_retrieval_chunk_limit:
            break
    return selected


def _excerpt_present(excerpt: str, content: str) -> bool:
    normalize = lambda value: " ".join(value.casefold().split())
    return normalize(excerpt) in normalize(content)


def extract_cluster_claims(
    session: Session,
    cluster_ids: list[int],
    *,
    run_id: int,
    settings: Settings,
    providers: ModelProviders | None = None,
) -> int:
    if not cluster_ids:
        return 0
    model_provider = _providers(settings, providers)
    provider = model_provider.claim_extraction
    embedding_provider = model_provider.embedding
    if provider is None:
        return 0
    created_claims: list[ArticleClaim] = []
    rows = session.execute(
        select(StoryClusterMember.cluster_id, Article)
        .join(Article, Article.id == StoryClusterMember.article_id)
        .where(
            StoryClusterMember.cluster_id.in_(cluster_ids),
            StoryClusterMember.relationship == "coverage",
        )
        .order_by(StoryClusterMember.cluster_id, Article.id)
    ).all()
    retrieved_by_cluster = {
        cluster_id: retrieve_cluster_chunks(session, cluster_id, settings=settings)
        for cluster_id in cluster_ids
    }
    for cluster_id, article in rows:
        if session.scalar(
            select(func.count()).select_from(ArticleClaim).where(
                ArticleClaim.article_id == article.id,
                ArticleClaim.model == provider.model,
                ArticleClaim.prompt_version == settings.prompt_version,
            )
        ):
            continue
        article_chunks = sorted(
            (
                item.chunk
                for item in retrieved_by_cluster.get(cluster_id, [])
                if item.chunk.article_id == article.id
            ),
            key=lambda chunk: chunk.chunk_index,
        )
        content = (
            "\n\n".join(chunk.chunk_text for chunk in article_chunks)
            if article_chunks
            else article.content_text or ""
        )
        input_hash = content_fingerprint(article.title, content, settings.prompt_version)
        try:
            result = provider.extract_claims(
                article_id=article.id, title=article.title, content=content
            )
        except Exception as exc:
            _record_failure(
                session,
                run_id=run_id,
                role="claim_extraction",
                provider=provider.provider_name,
                model=provider.model,
                input_hash=input_hash,
                error=exc,
                settings=settings,
            )
            raise
        session.execute(
            delete(ArticleClaim).where(ArticleClaim.article_id == article.id)
        )
        cluster = session.get(StoryCluster, cluster_id)
        if cluster is not None:
            cluster.comparison_status = "pending"
        for claim in result.value.claims:
            if not _excerpt_present(claim.supporting_excerpt, content):
                continue
            claim_hash = content_fingerprint(claim.claim_text.casefold())
            db_claim = ArticleClaim(
                article_id=article.id,
                cluster_id=cluster_id,
                claim_text=claim.claim_text,
                claim_hash=claim_hash,
                claim_type=claim.claim_type,
                supporting_excerpt=claim.supporting_excerpt,
                attribution=claim.attribution,
                primary_source_url=claim.primary_source_url,
                confidence=claim.confidence,
                provider=provider.provider_name,
                model=provider.model,
                prompt_version=settings.prompt_version,
                expires_at=_expiry(settings.unselected_evidence_retention_days),
            )
            session.add(db_claim)
            created_claims.append(db_claim)
        _record_success(
            session,
            run_id=run_id,
            role="claim_extraction",
            provider=provider.provider_name,
            model=provider.model,
            input_hash=input_hash,
            result=result,
            settings=settings,
        )
        session.commit()

    if embedding_provider is not None:
        pending = [claim for claim in created_claims if claim.embedding is None]
        for start in range(0, len(pending), settings.embedding_batch_size):
            batch = pending[start : start + settings.embedding_batch_size]
            texts = [claim.claim_text for claim in batch]
            input_hash = content_fingerprint(*texts, embedding_provider.model)
            try:
                result = embedding_provider.embed(texts)
            except Exception as exc:
                _record_failure(
                    session,
                    run_id=run_id,
                    role="claim_embedding",
                    provider=embedding_provider.provider_name,
                    model=embedding_provider.model,
                    input_hash=input_hash,
                    error=exc,
                    settings=settings,
                )
                raise
            for claim, vector in zip(batch, result.vectors, strict=True):
                claim.embedding = vector
            _record_success(
                session,
                run_id=run_id,
                role="claim_embedding",
                provider=embedding_provider.provider_name,
                model=embedding_provider.model,
                input_hash=input_hash,
                result=result,
                settings=settings,
            )
            session.commit()
    return len(created_claims)


def _lexical_similarity(left: str, right: str) -> float:
    left_terms = set(_terms(left))
    right_terms = set(_terms(right))
    union = left_terms | right_terms
    return len(left_terms & right_terms) / len(union) if union else 0.0


def _select_claim_pairs(
    claims: list[ArticleClaim],
    article_publishers: dict[int, int],
    *,
    max_pairs: int,
) -> list[ClaimPairCandidate]:
    candidates: list[ClaimPairCandidate] = []
    for index, left in enumerate(claims):
        for right in claims[index + 1 :]:
            if left.article_id == right.article_id:
                continue
            if article_publishers.get(left.article_id) == article_publishers.get(
                right.article_id
            ):
                continue
            vector_score = (
                max(
                    0.0,
                    min(
                        1.0,
                        (
                            _cosine(list(left.embedding), list(right.embedding)) + 1.0
                        )
                        / 2.0,
                    ),
                )
                if left.embedding is not None and right.embedding is not None
                else 0.0
            )
            lexical_score = _lexical_similarity(left.claim_text, right.claim_text)
            candidates.append(
                ClaimPairCandidate(
                    left=left,
                    right=right,
                    retrieval_score=0.8 * vector_score + 0.2 * lexical_score,
                )
            )
    candidates.sort(
        key=lambda item: (
            item.retrieval_score,
            -min(item.left.id, item.right.id),
            -max(item.left.id, item.right.id),
        ),
        reverse=True,
    )

    selected: list[ClaimPairCandidate] = []
    selected_pairs: set[tuple[int, int]] = set()
    represented_source_pairs: set[tuple[int, int]] = set()
    for candidate in candidates:
        source_pair = tuple(
            sorted(
                (
                    article_publishers[candidate.left.article_id],
                    article_publishers[candidate.right.article_id],
                )
            )
        )
        if source_pair in represented_source_pairs:
            continue
        selected.append(candidate)
        selected_pairs.add(tuple(sorted((candidate.left.id, candidate.right.id))))
        represented_source_pairs.add(source_pair)
        if len(selected) >= max_pairs:
            return selected
    for candidate in candidates:
        pair = tuple(sorted((candidate.left.id, candidate.right.id)))
        if pair in selected_pairs:
            continue
        selected.append(candidate)
        selected_pairs.add(pair)
        if len(selected) >= max_pairs:
            break
    return selected


def _choose_representative(
    claims: list[ArticleClaim],
    links: list[EvidenceLinkResult],
    article_word_counts: dict[int, int],
) -> tuple[int, str]:
    """Choose deterministically after the model classifies claim relationships."""
    scores: dict[int, float] = {}
    claim_counts: dict[int, int] = {}
    claim_by_id = {claim.id: claim for claim in claims}
    for claim in claims:
        claim_counts[claim.article_id] = claim_counts.get(claim.article_id, 0) + 1
        scores[claim.article_id] = scores.get(claim.article_id, 0.0) + (
            0.25 * claim.confidence
        )

    relationship_weights = {
        "equivalent": 2.0,
        "supports": 1.5,
        "related": 0.25,
        "contradicts": 0.1,
        "unrelated": 0.0,
    }
    for link in links:
        left = claim_by_id.get(link.left_claim_id)
        right = claim_by_id.get(link.right_claim_id)
        if left is None or right is None:
            continue
        contribution = relationship_weights[link.relationship] * link.confidence
        scores[left.article_id] = scores.get(left.article_id, 0.0) + contribution
        scores[right.article_id] = scores.get(right.article_id, 0.0) + contribution

    representative_id = max(
        scores,
        key=lambda article_id: (
            scores[article_id],
            claim_counts.get(article_id, 0),
            article_word_counts.get(article_id, 0),
            -article_id,
        ),
    )
    reason = (
        "Selected deterministically from the model-labeled evidence links: "
        f"evidence_score={scores[representative_id]:.3f}, "
        f"extracted_claims={claim_counts.get(representative_id, 0)}, "
        f"word_count={article_word_counts.get(representative_id, 0)}."
    )
    return representative_id, reason


def compare_cluster_evidence(
    session: Session,
    cluster_ids: list[int],
    *,
    run_id: int,
    settings: Settings,
    providers: ModelProviders | None = None,
) -> int:
    if not cluster_ids:
        return 0
    provider = _providers(settings, providers).evidence_comparison
    if provider is None:
        return 0
    compared = 0
    for cluster_id in cluster_ids:
        cluster = session.get(StoryCluster, cluster_id)
        existing_comparison = session.scalar(
            select(ClusterComparison).where(
                ClusterComparison.cluster_id == cluster_id
            )
        )
        cached = session.scalar(
            select(ClusterComparison).where(
                ClusterComparison.cluster_id == cluster_id,
                ClusterComparison.model == provider.model,
                ClusterComparison.prompt_version == settings.prompt_version,
            )
        )
        if (
            cached is not None
            and cluster is not None
            and cluster.comparison_status == "complete"
        ):
            continue
        claims = list(
            session.scalars(
                select(ArticleClaim)
                .join(
                    StoryClusterMember,
                    StoryClusterMember.article_id == ArticleClaim.article_id,
                )
                .where(
                    ArticleClaim.cluster_id == cluster_id,
                    StoryClusterMember.cluster_id == cluster_id,
                    StoryClusterMember.relationship == "coverage",
                )
                .order_by(ArticleClaim.article_id, ArticleClaim.id)
            )
        )
        article_ids = sorted({claim.article_id for claim in claims})
        if len(article_ids) < 2:
            continue
        article_rows = session.execute(
            select(
                Article.id, Article.title, Article.word_count, Source.publisher_id
            )
            .join(Source, Source.id == Article.source_id)
            .where(Article.id.in_(article_ids))
        ).all()
        titles = {
            article_id: title
            for article_id, title, _word_count, _source_id in article_rows
        }
        word_counts = {
            article_id: word_count or 0
            for article_id, _title, word_count, _source_id in article_rows
        }
        article_publishers = {
            article_id: publisher_id
            for article_id, _title, _word_count, publisher_id in article_rows
        }
        selected_pairs = _select_claim_pairs(
            claims,
            article_publishers,
            max_pairs=settings.evidence_max_claim_pairs,
        )
        if not selected_pairs:
            if cluster is not None:
                cluster.comparison_status = "insufficient_evidence"
                session.commit()
            continue
        claim_by_id = {
            claim.id: claim
            for pair in selected_pairs
            for claim in (pair.left, pair.right)
        }
        valid_links: dict[tuple[int, int], EvidenceLinkResult] = {}
        summaries: list[str] = []
        confidences: list[float] = []
        for start in range(0, len(selected_pairs), settings.evidence_pair_batch_size):
            batch = selected_pairs[start : start + settings.evidence_pair_batch_size]
            inputs = [
                EvidencePairInput(
                    pair_id=start + offset + 1,
                    left=EvidenceClaimInput(
                        claim_id=pair.left.id,
                        article_id=pair.left.article_id,
                        claim_text=pair.left.claim_text,
                        attribution=pair.left.attribution,
                    ),
                    right=EvidenceClaimInput(
                        claim_id=pair.right.id,
                        article_id=pair.right.article_id,
                        claim_text=pair.right.claim_text,
                        attribution=pair.right.attribution,
                    ),
                    retrieval_score=pair.retrieval_score,
                )
                for offset, pair in enumerate(batch)
            ]
            input_hash = content_fingerprint(
                *(
                    f"{pair.left.claim_text}\n{pair.right.claim_text}"
                    for pair in batch
                ),
                settings.prompt_version,
            )
            try:
                result = provider.compare(article_titles=titles, pairs=inputs)
            except Exception as exc:
                _record_failure(
                    session,
                    run_id=run_id,
                    role="evidence_comparison",
                    provider=provider.provider_name,
                    model=provider.model,
                    input_hash=input_hash,
                    error=exc,
                    settings=settings,
                )
                raise
            allowed_pairs = {
                tuple(sorted((pair.left.id, pair.right.id))) for pair in batch
            }
            for link in result.value.links:
                pair = tuple(sorted((link.left_claim_id, link.right_claim_id)))
                if pair not in allowed_pairs:
                    continue
                left = claim_by_id.get(link.left_claim_id)
                right = claim_by_id.get(link.right_claim_id)
                if left is None or right is None:
                    continue
                valid_links[pair] = link
            summaries.append(result.value.batch_summary)
            confidences.append(result.value.confidence)
            _record_success(
                session,
                run_id=run_id,
                role="evidence_comparison",
                provider=provider.provider_name,
                model=provider.model,
                input_hash=input_hash,
                result=result,
                settings=settings,
            )
            session.commit()
        session.execute(delete(ClaimLink).where(ClaimLink.cluster_id == cluster_id))
        for (left_id, right_id), link in valid_links.items():
            session.add(
                ClaimLink(
                    cluster_id=cluster_id,
                    left_claim_id=left_id,
                    right_claim_id=right_id,
                    relationship=link.relationship,
                    confidence=link.confidence,
                    rationale=link.rationale,
                    expires_at=_expiry(settings.unselected_evidence_retention_days),
                )
            )
        representative_id, deterministic_reason = _choose_representative(
            list(claim_by_id.values()), list(valid_links.values()), word_counts
        )
        relationships = [link.relationship for link in valid_links.values()]
        comparison = existing_comparison or ClusterComparison(cluster_id=cluster_id)
        comparison.representative_article_id = representative_id
        comparison.shared_claim_count = sum(
            value in {"equivalent", "supports"} for value in relationships
        )
        comparison.disputed_claim_count = sum(
            value == "contradicts" for value in relationships
        )
        comparison.unsupported_claim_count = sum(
            value == "unrelated" for value in relationships
        )
        comparison.selection_reason = (
            f"{deterministic_reason} Model batches: {' '.join(summaries)}"
        )
        comparison.confidence = (
            sum(confidences) / len(confidences) if confidences else 0.0
        )
        comparison.provider = provider.provider_name
        comparison.model = provider.model
        comparison.prompt_version = settings.prompt_version
        comparison.expires_at = _expiry(settings.unselected_evidence_retention_days)
        if existing_comparison is None:
            session.add(comparison)
        if cluster is not None:
            cluster.representative_article_id = representative_id
            cluster.comparison_status = "complete"
        session.commit()
        compared += 1
    return compared


def apply_representative_selection(
    session: Session, article_ids: list[int], cluster_ids: list[int]
) -> list[int]:
    if not cluster_ids:
        return article_ids
    redundant_ids = set(
        session.scalars(
            select(StoryClusterMember.article_id).where(
                StoryClusterMember.cluster_id.in_(cluster_ids),
                StoryClusterMember.relationship == "redundant",
            )
        )
    )
    rows = session.execute(
        select(StoryClusterMember.article_id, StoryCluster.representative_article_id)
        .join(StoryCluster, StoryCluster.id == StoryClusterMember.cluster_id)
        .where(
            StoryClusterMember.cluster_id.in_(cluster_ids),
            StoryCluster.comparison_status == "complete",
        )
    ).all()
    clustered_members = {article_id for article_id, _representative in rows}
    representatives = {
        representative for _article_id, representative in rows if representative is not None
    }
    return sorted(
        ((set(article_ids) - redundant_ids) - clustered_members) | representatives
    )


def extend_selected_evidence_retention(
    session: Session,
    selected_article_ids: list[int],
    *,
    settings: Settings,
) -> None:
    if not selected_article_ids:
        return
    expires_at = _expiry(min(settings.selected_evidence_retention_days, 30))
    cluster_ids = list(
        session.scalars(
            select(StoryClusterMember.cluster_id).where(
                StoryClusterMember.article_id.in_(selected_article_ids)
            )
        )
    )
    session.query(ArticleChunk).filter(
        ArticleChunk.article_id.in_(selected_article_ids)
    ).update({ArticleChunk.expires_at: expires_at}, synchronize_session=False)
    if cluster_ids:
        session.query(ArticleClaim).filter(
            ArticleClaim.cluster_id.in_(cluster_ids)
        ).update({ArticleClaim.expires_at: expires_at}, synchronize_session=False)
        session.query(ClaimLink).filter(ClaimLink.cluster_id.in_(cluster_ids)).update(
            {ClaimLink.expires_at: expires_at}, synchronize_session=False
        )
        session.query(ClusterComparison).filter(
            ClusterComparison.cluster_id.in_(cluster_ids)
        ).update({ClusterComparison.expires_at: expires_at}, synchronize_session=False)
        session.query(StoryCluster).filter(StoryCluster.id.in_(cluster_ids)).update(
            {StoryCluster.expires_at: expires_at}, synchronize_session=False
        )
    session.commit()


def cleanup_expired_evidence(session: Session, *, now: datetime | None = None) -> int:
    current_time = now or datetime.now(UTC)
    deleted = 0
    for model in (ClaimLink, ClusterComparison, ArticleClaim, ArticleChunk, ModelCall):
        result = session.execute(delete(model).where(model.expires_at < current_time))
        deleted += result.rowcount or 0
    expired_clusters = session.execute(
        delete(StoryCluster).where(StoryCluster.expires_at < current_time)
    )
    deleted += expired_clusters.rowcount or 0
    session.commit()
    return deleted
