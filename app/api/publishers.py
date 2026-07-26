from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.db.models import Publisher, Source
from app.db.session import get_db
from app.schemas.source import (
    PublisherCreate,
    PublisherDetail,
    PublisherFeedCreate,
    PublisherRead,
    PublisherUpdate,
    SourceRead,
)

router = APIRouter(prefix="/publishers", tags=["publishers"])
DBSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=PublisherRead, status_code=status.HTTP_201_CREATED)
def create_publisher(payload: PublisherCreate, session: DBSession) -> Publisher:
    publisher = Publisher(
        name=payload.name,
        site_url=str(payload.site_url) if payload.site_url else None,
        enabled=payload.enabled,
    )
    session.add(publisher)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Publisher site URL already exists") from exc
    session.refresh(publisher)
    return publisher


@router.get("", response_model=list[PublisherRead])
def list_publishers(session: DBSession) -> list[Publisher]:
    return list(session.scalars(select(Publisher).order_by(Publisher.name)))


@router.get("/{publisher_id}", response_model=PublisherDetail)
def get_publisher(publisher_id: int, session: DBSession) -> Publisher:
    publisher = session.scalar(
        select(Publisher)
        .where(Publisher.id == publisher_id)
        .options(selectinload(Publisher.sources))
    )
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    return publisher


@router.patch("/{publisher_id}", response_model=PublisherRead)
def update_publisher(
    publisher_id: int,
    payload: PublisherUpdate,
    session: DBSession,
) -> Publisher:
    publisher = session.get(Publisher, publisher_id)
    if publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    values = payload.model_dump(exclude_unset=True)
    if "site_url" in values and values["site_url"] is not None:
        values["site_url"] = str(values["site_url"])
    for key, value in values.items():
        setattr(publisher, key, value)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Publisher site URL already exists") from exc
    session.refresh(publisher)
    return publisher


@router.post(
    "/{publisher_id}/sources",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
)
def add_publisher_source(
    publisher_id: int,
    payload: PublisherFeedCreate,
    session: DBSession,
) -> Source:
    if session.get(Publisher, publisher_id) is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    source = Source(
        publisher_id=publisher_id,
        name=payload.name,
        category=payload.category,
        feed_url=str(payload.feed_url),
        enabled=payload.enabled,
        poll_interval_minutes=payload.poll_interval_minutes,
    )
    session.add(source)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="Feed URL already exists") from exc
    session.refresh(source)
    return source
