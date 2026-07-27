from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id
from app.db.models import (
    Article,
    ArticleClaim,
    ClaimLink,
    ClusterComparison,
    DailyRun,
    ModelCall,
    StoryCluster,
    StoryClusterMember,
)
from app.db.session import get_db
from app.schemas.evidence import ModelCallRead, StoryClusterDetail, StoryClusterRead

router = APIRouter(prefix="/evidence", tags=["evidence"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUserID = Annotated[int, Depends(get_current_user_id)]


@router.get("/clusters", response_model=list[StoryClusterRead])
def list_clusters(
    session: DBSession,
    _user_id: CurrentUserID,
    limit: int = Query(default=50, ge=1, le=200),
) -> object:
    member_count = (
        select(func.count(StoryClusterMember.id))
        .where(StoryClusterMember.cluster_id == StoryCluster.id)
        .correlate(StoryCluster)
        .scalar_subquery()
    )
    rows = session.execute(
        select(StoryCluster, member_count.label("member_count"))
        .order_by(StoryCluster.event_date.desc(), StoryCluster.id.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": cluster.id,
            "representative_title": cluster.representative_title,
            "event_summary": cluster.event_summary,
            "event_date": cluster.event_date,
            "representative_article_id": cluster.representative_article_id,
            "comparison_status": cluster.comparison_status,
            "embedding_model": cluster.embedding_model,
            "expires_at": cluster.expires_at,
            "member_count": count,
        }
        for cluster, count in rows
    ]


@router.get("/clusters/{cluster_id}", response_model=StoryClusterDetail)
def get_cluster(
    cluster_id: int, session: DBSession, _user_id: CurrentUserID
) -> object:
    cluster = session.get(StoryCluster, cluster_id)
    if cluster is None:
        raise HTTPException(status_code=404, detail="Story cluster not found")
    member_rows = session.execute(
        select(StoryClusterMember, Article)
        .join(Article, Article.id == StoryClusterMember.article_id)
        .where(StoryClusterMember.cluster_id == cluster_id)
        .order_by(Article.id)
    ).all()
    claims = list(
        session.scalars(
            select(ArticleClaim)
            .where(ArticleClaim.cluster_id == cluster_id)
            .order_by(ArticleClaim.article_id, ArticleClaim.id)
        )
    )
    links = list(
        session.scalars(
            select(ClaimLink)
            .where(ClaimLink.cluster_id == cluster_id)
            .order_by(ClaimLink.id)
        )
    )
    comparison = session.scalar(
        select(ClusterComparison).where(ClusterComparison.cluster_id == cluster_id)
    )
    return {
        "id": cluster.id,
        "representative_title": cluster.representative_title,
        "event_summary": cluster.event_summary,
        "event_date": cluster.event_date,
        "representative_article_id": cluster.representative_article_id,
        "comparison_status": cluster.comparison_status,
        "embedding_model": cluster.embedding_model,
        "expires_at": cluster.expires_at,
        "member_count": len(member_rows),
        "members": [
            {
                "article_id": article.id,
                "title": article.title,
                "source_id": article.source_id,
                "similarity_score": member.similarity_score,
                "relationship": member.relationship,
            }
            for member, article in member_rows
        ],
        "claims": claims,
        "links": links,
        "comparison": comparison,
    }


@router.get("/model-calls", response_model=list[ModelCallRead])
def list_model_calls(
    session: DBSession,
    user_id: CurrentUserID,
    limit: int = Query(default=100, ge=1, le=500),
    run_id: int | None = Query(default=None, ge=1),
) -> object:
    statement = (
        select(ModelCall)
        .join(DailyRun, DailyRun.id == ModelCall.run_id)
        .where(DailyRun.user_id == user_id)
    )
    if run_id is not None:
        statement = statement.where(ModelCall.run_id == run_id)

    return list(
        session.scalars(
            statement.order_by(ModelCall.created_at.desc()).limit(limit)
        )
    )
