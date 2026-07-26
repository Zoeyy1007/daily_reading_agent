import logging
from collections.abc import Iterator
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def timed_stage(
    logger: logging.Logger,
    stage: str,
    **context: object,
) -> Iterator[None]:
    started = perf_counter()
    status = "ok"
    try:
        yield
    except Exception:
        status = "error"
        raise
    finally:
        elapsed_ms = (perf_counter() - started) * 1000
        details = " ".join(f"{key}={value}" for key, value in context.items())
        logger.info(
            "timing stage=%s status=%s elapsed_ms=%.2f%s",
            stage,
            status,
            elapsed_ms,
            f" {details}" if details else "",
        )
