import asyncio
import inspect
import threading
import time

from app.agent.graph import DEFAULT_HANDLERS
from app.config import Settings
from app.services import phase_five_service
from app.utils.concurrency import bounded_to_thread_map


def test_io_bound_graph_handlers_are_async() -> None:
    expected = {
        "collect",
        "extract",
        "ai_classify",
        "embed_articles",
        "embed_chunks",
        "extract_claims",
        "compare_evidence",
        "supplement",
    }
    assert all(inspect.iscoroutinefunction(DEFAULT_HANDLERS[name]) for name in expected)


def test_bounded_thread_map_enforces_limit() -> None:
    lock = threading.Lock()
    active = 0
    peak = 0

    def worker(value: int) -> int:
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.02)
        with lock:
            active -= 1
        return value * 2

    result = asyncio.run(
        bounded_to_thread_map(range(6), worker, max_concurrency=2)
    )

    assert result == [0, 2, 4, 6, 8, 10]
    assert peak == 2


def test_async_classification_uses_one_session_per_worker(monkeypatch) -> None:
    created_sessions: list[object] = []
    session_threads: dict[int, int] = {}

    class FakeContext:
        def __init__(self) -> None:
            self.session = object()

        def __enter__(self) -> object:
            created_sessions.append(self.session)
            session_threads[id(self.session)] = threading.get_ident()
            return self.session

        def __exit__(self, *_args: object) -> None:
            return None

    def fake_classify(session: object, article_ids: list[int], **_kwargs: object) -> int:
        assert session_threads[id(session)] == threading.get_ident()
        assert len(article_ids) == 1
        time.sleep(0.01)
        return 1

    monkeypatch.setattr(phase_five_service, "SessionLocal", FakeContext)
    monkeypatch.setattr(
        phase_five_service, "classify_articles_with_model", fake_classify
    )
    settings = Settings(
        _env_file=None,
        phase_five_max_articles=10,
        llm_max_concurrency=3,
    )

    count = asyncio.run(
        phase_five_service.classify_articles_with_model_async(
            [1, 2, 3, 4], run_id=1, settings=settings
        )
    )

    assert count == 4
    assert len(created_sessions) == 4
    assert len({id(session) for session in created_sessions}) == 4
