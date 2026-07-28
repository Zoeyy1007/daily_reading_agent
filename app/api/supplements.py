from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.api.dependencies import get_current_user_id
from app.config import get_settings
from app.db.models import (
    DailyReadingItem,
    DailyReadingList,
    DailyRun,
    SupplementCard,
    SupplementRun,
)
from app.db.session import get_db
from app.schemas.supplement import SupplementRunRead
from app.services.supplement_service import generate_supplement_for_item

router = APIRouter(prefix="/supplements", tags=["supplements"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUserID = Annotated[int, Depends(get_current_user_id)]


def _owned_item(session: Session, item_id: int, user_id: int) -> DailyReadingItem:
    item = session.scalar(
        select(DailyReadingItem)
        .join(DailyReadingList, DailyReadingList.id == DailyReadingItem.reading_list_id)
        .where(DailyReadingItem.id == item_id, DailyReadingList.user_id == user_id)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Daily reading item not found")
    return item


def _run_query():
    return select(SupplementRun).options(
        selectinload(SupplementRun.evidence_items),
        selectinload(SupplementRun.cards).selectinload(SupplementCard.citations),
    )


@router.get("/items/{item_id}", response_model=SupplementRunRead)
def get_item_supplement(
    item_id: int, session: DBSession, user_id: CurrentUserID
) -> object:
    _owned_item(session, item_id, user_id)
    run = session.scalar(
        _run_query().where(SupplementRun.daily_reading_item_id == item_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Supplement has not been generated")
    return run


@router.get("/reading-lists/{reading_list_id}", response_model=list[SupplementRunRead])
def get_list_supplements(
    reading_list_id: int, session: DBSession, user_id: CurrentUserID
) -> object:
    reading_list = session.scalar(
        select(DailyReadingList).where(
            DailyReadingList.id == reading_list_id,
            DailyReadingList.user_id == user_id,
        )
    )
    if reading_list is None:
        raise HTTPException(status_code=404, detail="Daily reading list not found")
    return list(
        session.scalars(
            _run_query()
            .join(
                DailyReadingItem,
                DailyReadingItem.id == SupplementRun.daily_reading_item_id,
            )
            .where(DailyReadingItem.reading_list_id == reading_list_id)
            .order_by(DailyReadingItem.rank)
        ).unique()
    )


@router.post("/items/{item_id}/generate", response_model=SupplementRunRead)
def generate_item_supplement(
    item_id: int, session: DBSession, user_id: CurrentUserID
) -> object:
    item = _owned_item(session, item_id, user_id)
    daily_run_id = session.scalar(
        select(DailyRun.id)
        .where(DailyRun.reading_list_id == item.reading_list_id)
        .order_by(DailyRun.id.desc())
        .limit(1)
    )
    try:
        generate_supplement_for_item(
            session,
            item_id,
            daily_run_id=daily_run_id,
            settings=get_settings(),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return session.scalar(
        _run_query().where(SupplementRun.daily_reading_item_id == item_id)
    )
