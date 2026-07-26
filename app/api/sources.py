from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import Publisher, Source
from app.db.session import get_db
from app.schemas.source import IngestionResult, SourceCreate, SourceRead, SourceUpdate
from app.services.ingestion_service import ingest_source

router = APIRouter(prefix="/sources", tags=["sources"])
DBSession = Annotated[Session, Depends(get_db)]


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
def create_source(payload: SourceCreate, session: DBSession) -> Source:
    publisher = (
        session.get(Publisher, payload.publisher_id) if payload.publisher_id else None
    )
    if payload.publisher_id and publisher is None:
        raise HTTPException(status_code=404, detail="Publisher not found")
    if publisher is None and payload.site_url:
        publisher = session.scalar(
            select(Publisher).where(Publisher.site_url == str(payload.site_url))
        )
    if publisher is None:
        publisher = Publisher(
            name=payload.name,
            site_url=str(payload.site_url) if payload.site_url else None,
        )
        session.add(publisher)
        session.flush()
    source = Source(
        publisher_id=publisher.id,
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


@router.get("", response_model=list[SourceRead])
def list_sources(session: DBSession) -> list[Source]:
    return list(session.scalars(select(Source).order_by(Source.name)))


@router.patch("/{source_id}", response_model=SourceRead)
def update_source(source_id: int, payload: SourceUpdate, session: DBSession) -> Source:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    values = payload.model_dump(exclude_unset=True)
    if "publisher_id" in values:
        if values["publisher_id"] is None:
            raise HTTPException(status_code=422, detail="publisher_id cannot be null")
        if session.get(Publisher, values["publisher_id"]) is None:
            raise HTTPException(status_code=404, detail="Publisher not found")
    for key, value in values.items():
        setattr(source, key, value)
    session.commit()
    session.refresh(source)
    return source


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_source(source_id: int, session: DBSession) -> Response:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    session.delete(source)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{source_id}/fetch", response_model=IngestionResult)
def fetch_source(source_id: int, session: DBSession) -> IngestionResult:
    try:
        stats = ingest_source(session, source_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return IngestionResult(**asdict(stats))
