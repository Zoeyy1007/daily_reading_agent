import asyncio
from collections.abc import Callable, Iterable
from typing import TypeVar


ItemT = TypeVar("ItemT")
ResultT = TypeVar("ResultT")


async def bounded_to_thread_map(
    items: Iterable[ItemT],
    worker: Callable[[ItemT], ResultT],
    *,
    max_concurrency: int,
) -> list[ResultT]:
    """Run blocking, independent units in threads with a hard concurrency cap.

    The worker owns all state it touches. In particular, callers must create a
    separate SQLAlchemy Session inside each worker instead of sharing one.
    """
    values = list(items)
    if not values:
        return []
    semaphore = asyncio.Semaphore(max(1, max_concurrency))

    async def run(item: ItemT) -> ResultT:
        async with semaphore:
            return await asyncio.to_thread(worker, item)

    results = await asyncio.gather(
        *(run(item) for item in values), return_exceptions=True
    )
    errors = [result for result in results if isinstance(result, BaseException)]
    if errors:
        raise errors[0]
    return [result for result in results if not isinstance(result, BaseException)]
