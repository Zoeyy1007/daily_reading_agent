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


def test_prune_page_html_removes_advertisement_containers() -> None:
    html = """
    <main>
      <div data-component="ad-slot">Sponsored retirement offers</div>
      <article>
        <p>The facility is being constructed inside the mountain.</p>
        <div data-component="advertisement-block">Another advertisement</div>
      </article>
    </main>
    """

    cleaned = prune_page_html(html)

    assert "facility is being constructed" in cleaned
    assert "Sponsored retirement offers" not in cleaned
    assert "Another advertisement" not in cleaned


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


def test_clean_article_text_keeps_link_words_without_href_targets() -> None:
    text = (
        "The building was damaged after "
        "[a suspected sabotage operation in July 2020.]"
        "(https://www.bbc.co.uk/news/example)\n\n"
        "Ali Akbar Salehi [said in September 2020]\n"
        "(https://www.example.com/a-very-long-source-url) that a new facility "
        "would be built."
    )

    cleaned = clean_article_text(text)

    assert "a suspected sabotage operation in July 2020." in cleaned
    assert "said in September 2020" in cleaned
    assert "that a new facility would be built" in cleaned
    assert "https://" not in cleaned
    assert "](" not in cleaned


def test_clean_article_text_removes_markdown_images() -> None:
    text = (
        "The site is buried inside the mountain.\n\n"
        "![Image 2: Satellite view of the site](https://ichef.example/image.jpg)\n\n"
        "Construction continued in June."
    )

    cleaned = clean_article_text(text)

    assert "Satellite view" not in cleaned
    assert "image.jpg" not in cleaned
    assert "site is buried" in cleaned
    assert "Construction continued" in cleaned
