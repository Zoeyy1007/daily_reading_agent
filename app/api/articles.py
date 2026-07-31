from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user_id
from app.db.models import Article
from app.db.session import get_db
from app.schemas.article import ArticleDetail, ArticleRead

router = APIRouter(prefix="/articles", tags=["articles"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUserID = Annotated[int, Depends(get_current_user_id)]


@router.get("", response_model=list[ArticleRead])
def list_articles(
    session: DBSession,
    _user_id: CurrentUserID,
    status: str | None = None,
    source_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[Article]:
    statement = select(Article)
    if status:
        statement = statement.where(Article.status == status)
    if source_id:
        statement = statement.where(Article.source_id == source_id)
    statement = statement.order_by(Article.published_at.desc().nullslast()).offset(offset).limit(limit)
    return list(session.scalars(statement))


@router.get("/{article_id}", response_model=ArticleDetail)
def get_article(
    article_id: int, session: DBSession, _user_id: CurrentUserID
) -> Article:
    article = session.get(Article, article_id)
    if article is None:
        raise HTTPException(status_code=404, detail="Article not found")
    return article
