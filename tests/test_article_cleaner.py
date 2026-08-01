from app.services.article_cleaner import clean_article_text, prune_page_html


def test_prune_page_html_removes_navigation_and_related_regions() -> None:
    html = """
    <html><body>
      <nav><a>Home</a><a>News</a><a>Sport</a></nav>
      <main>
        <article><h1>Policy changes announced</h1><p>The government announced a new policy today.</p></article>
        <section class="related-stories"><a>Another headline</a></section>
      </main>
      <footer>Subscribe</footer>
    </body></html>
    """

    cleaned = prune_page_html(html)

    assert "Policy changes announced" in cleaned
    assert "The government announced" in cleaned
    assert "Another headline" not in cleaned
    assert ">Home<" not in cleaned
    assert "Subscribe" not in cleaned


def test_clean_article_text_removes_media_and_repeated_category_noise() -> None:
    text = """
    Subscribe
    Home
    News
    1:32
    Watch: A related video headline
    Europe
    The first substantive paragraph explains what happened in detail.
    Europe
    The second substantive paragraph explains who will be affected.
    """

    cleaned = clean_article_text(text)

    assert "Subscribe" not in cleaned
    assert "Watch:" not in cleaned
    assert "1:32" not in cleaned
    assert "Europe" not in cleaned
    assert "first substantive paragraph" in cleaned
    assert "second substantive paragraph" in cleaned


def test_clean_article_text_preserves_short_legitimate_paragraphs() -> None:
    cleaned = clean_article_text(
        "Officials disagreed.\n\nThe vote failed.\n\nResidents responded the next day."
    )

    assert cleaned == (
        "Officials disagreed.\n\nThe vote failed.\n\nResidents responded the next day."
    )


def test_clean_article_text_does_not_truncate_unrelated_explore_more_phrase() -> None:
    cleaned = clean_article_text(
        "The report asks readers to explore more.\n\nThe article continues with evidence."
    )

    assert "article continues" in cleaned
