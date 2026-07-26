from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.source import IngestionResult
from app.services.ingestion_service import ingest_all_enabled_sources

router = APIRouter(prefix="/ingestion", tags=["ingestion"])
DBSession = Annotated[Session, Depends(get_db)]


@router.post("/run", response_model=list[IngestionResult])
def run_ingestion(session: DBSession) -> list[IngestionResult]:
    return [
        IngestionResult(**asdict(item)) for item in ingest_all_enabled_sources(session)
    ]
