import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.agent.runner import execute_agent_run, resume_agent_run
from app.api.dependencies import get_current_user_id
from app.config import get_settings
from app.db.models import AgentRunStatus
from app.db.session import get_db
from app.schemas.agent_run import AgentRunCreate, AgentRunRead, RunEventRead
from app.services.reading_list_service import local_today
from app.services.run_service import create_agent_run, get_agent_run, list_agent_runs

router = APIRouter(prefix="/agent/runs", tags=["agent runs"])
DBSession = Annotated[Session, Depends(get_db)]
CurrentUserID = Annotated[int, Depends(get_current_user_id)]
logger = logging.getLogger("daily_reading.agent.api")


def _run_in_background(run_id: int, regenerate: bool, resume: bool = False) -> None:
    try:
        if resume:
            resume_agent_run(run_id)
        else:
            execute_agent_run(run_id, regenerate=regenerate)
    except Exception:
        logger.exception("Background agent execution failed run_id=%s", run_id)


def _owned_run(session: Session, run_id: int, user_id: int):
    run = get_agent_run(session, run_id)
    if run is None or run.user_id != user_id:
        raise HTTPException(status_code=404, detail="Agent run not found")
    return run


@router.post("", response_model=AgentRunRead, status_code=202)
def create_run(
    payload: AgentRunCreate,
    background_tasks: BackgroundTasks,
    session: DBSession,
    user_id: CurrentUserID,
) -> object:
    settings = get_settings()
    try:
        run = create_agent_run(
            session,
            user_id=user_id,
            list_date=payload.list_date or local_today(),
            max_expansion_rounds=(
                payload.max_expansion_rounds
                if payload.max_expansion_rounds is not None
                else settings.agent_max_expansion_rounds
            ),
        )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    use_background = (
        settings.agent_run_in_background
        if payload.background is None
        else payload.background
    )
    if use_background:
        background_tasks.add_task(
            _run_in_background, run.id, payload.regenerate, False
        )
    else:
        try:
            execute_agent_run(run.id, regenerate=payload.regenerate)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        session.expire_all()
    return get_agent_run(session, run.id) or run


@router.get("", response_model=list[AgentRunRead])
def get_runs(
    session: DBSession,
    user_id: CurrentUserID,
    limit: int = Query(default=50, ge=1, le=200),
) -> object:
    return list_agent_runs(session, user_id, limit=limit)


@router.get("/{run_id}", response_model=AgentRunRead)
def get_run(run_id: int, session: DBSession, user_id: CurrentUserID) -> object:
    return _owned_run(session, run_id, user_id)


@router.get("/{run_id}/events", response_model=list[RunEventRead])
def get_run_events(
    run_id: int, session: DBSession, user_id: CurrentUserID
) -> object:
    return _owned_run(session, run_id, user_id).events


@router.post("/{run_id}/resume", response_model=AgentRunRead, status_code=202)
def resume_run(
    run_id: int,
    background_tasks: BackgroundTasks,
    session: DBSession,
    user_id: CurrentUserID,
    background: bool = True,
) -> object:
    run = _owned_run(session, run_id, user_id)
    if run.status == AgentRunStatus.COMPLETE.value:
        raise HTTPException(status_code=409, detail="Completed runs do not need resuming")
    if background:
        background_tasks.add_task(_run_in_background, run.id, True, True)
    else:
        try:
            resume_agent_run(run.id)
        except LookupError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        session.expire_all()
    return get_agent_run(session, run.id) or run
