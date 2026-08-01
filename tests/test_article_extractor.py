import httpx
import pytest

from app.services.article_extractor import (
    ArticleExtractor,
    ExtractionFailedError,
    is_probable_media_page,
)


def test_jina_fallback_requests_structural_html_removal() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "example.com":
            return httpx.Response(403, request=request)
        return httpx.Response(
            200,
            text="Navigation\nA sufficiently long article body for this extraction test.",
            request=request,
        )

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        result = ArticleExtractor(
            client,
            minimum_words=5,
            jina_api_key="test-key",
            jina_no_cache=True,
        ).extract("https://example.com/story")

    jina_request = requests[-1]
    assert jina_request.url.host == "r.jina.ai"
    assert jina_request.headers["x-respond-with"] == "content"
    assert "nav" in jina_request.headers["x-remove-selector"]
    assert "footer" in jina_request.headers["x-remove-selector"]
    assert '[role="navigation"]' in jina_request.headers["x-remove-selector"]
    assert '[data-testid*="vertical-video"]' in jina_request.headers[
        "x-remove-selector"
    ]
    assert '[data-component*="advertisement"]' in jina_request.headers[
        "x-remove-selector"
    ]
    assert jina_request.headers["x-retain-images"] == "none"
    assert jina_request.headers["x-retain-media"] == "none"
    assert jina_request.headers["x-retain-links"] == "text"
    assert jina_request.headers["x-no-cache"] == "true"
    assert jina_request.headers["authorization"] == "Bearer test-key"
    assert result.extractor == "jina"


@pytest.mark.parametrize(
    ("url", "title"),
    [
        ("https://example.com/news/videos/story-id", "A report"),
        ("https://example.com/news/live/story-id", "Breaking coverage"),
        ("https://example.com/news/articles/story-id", "Watch: A video report"),
        ("https://example.com/story", "Listen live: Election coverage"),
    ],
)
def test_probable_media_pages_are_detected(url: str, title: str) -> None:
    assert is_probable_media_page(url, title)


def test_written_article_is_not_detected_as_media() -> None:
    assert not is_probable_media_page(
        "https://example.com/sport/football/articles/story-id",
        "Coach discusses the club's future",
    )


def test_media_page_is_rejected_before_http_request() -> None:
    requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(200, text="unused", request=request)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        extractor = ArticleExtractor(client, minimum_words=1)
        with pytest.raises(ExtractionFailedError, match="unsupported video"):
            extractor.extract(
                "https://example.com/news/articles/story-id",
                title="Watch: Live report",
            )

    assert not requested
