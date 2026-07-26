from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.daily_reading import DailyReadingGenerate, DailyReadingListRead
from app.services.reading_list_service import (
    generate_daily_reading_list,
    get_daily_reading_list,
    local_today,
)

router = APIRouter(prefix="/daily-reading", tags=["daily reading"])
DBSession = Annotated[Session, Depends(get_db)]


@router.post("/generate", response_model=DailyReadingListRead)
def generate_list(
    payload: DailyReadingGenerate,
    session: DBSession,
) -> object:
    return generate_daily_reading_list(
        session,
        payload.list_date or local_today(),
        regenerate=payload.regenerate,
    )


@router.get("/today", response_model=DailyReadingListRead)
def get_today_list(session: DBSession) -> object:
    reading_list = get_daily_reading_list(session, local_today())
    if reading_list is None:
        raise HTTPException(status_code=404, detail="Today's reading list has not been generated")
    return reading_list


@router.get("/{list_date}", response_model=DailyReadingListRead)
def get_list(list_date: date, session: DBSession) -> object:
    reading_list = get_daily_reading_list(session, list_date)
    if reading_list is None:
        raise HTTPException(status_code=404, detail="Reading list not found")
    return reading_list
