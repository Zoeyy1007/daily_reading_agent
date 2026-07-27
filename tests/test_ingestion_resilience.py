from types import SimpleNamespace

from app.services import ingestion_service


class FakeSession:
    def __init__(self) -> None:
        self.rollback_count = 0

    def scalars(self, _query):
        return SimpleNamespace(all=lambda: [1, 2])

    def rollback(self) -> None:
        self.rollback_count += 1


def test_bulk_discovery_skips_one_failed_source(monkeypatch) -> None:
    session = FakeSession()

    def fake_discover(_session, source_id: int):
        if source_id == 1:
            raise RuntimeError("403 Forbidden")
        return ingestion_service.IngestionStats(source_id=source_id, discovered=3)

    monkeypatch.setattr(ingestion_service, "discover_source", fake_discover)

    results = ingestion_service.discover_all_enabled_sources(session)  # type: ignore[arg-type]

    assert [result.source_id for result in results] == [1, 2]
    assert results[0].error == "403 Forbidden"
    assert results[1].discovered == 3
    assert session.rollback_count == 1
