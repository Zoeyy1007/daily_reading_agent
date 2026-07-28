const app = document.querySelector("#app");
const menuButton = document.querySelector("#menu-button");
const drawer = document.querySelector("#navigation-drawer");
const drawerBackdrop = document.querySelector("#drawer-backdrop");
const feedbackDialog = document.querySelector("#feedback-dialog");
const feedbackForm = document.querySelector("#feedback-form");
const feedbackKicker = document.querySelector("#feedback-kicker");
const reasonOptions = document.querySelector("#reason-options");
const toast = document.querySelector("#toast");

const icons = {
  back: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>',
  like: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 10v11H3V10h4Zm0 10h10.3a2 2 0 0 0 2-1.7l1.1-7A2 2 0 0 0 18.4 9H14l.7-3.2A2.3 2.3 0 0 0 12.5 3L7 10Z"/></svg>',
  dislike: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 14V3H3v11h4Zm0-10h10.3a2 2 0 0 1 2 1.7l1.1 7a2 2 0 0 1-2 2.3H14l.7 3.2a2.3 2.3 0 0 1-2.2 2.8L7 14Z"/></svg>',
  save: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
};

const feedbackReasons = {
  like: [
    ["strong_evidence", "Strong evidence"],
    ["good_writing", "Good writing"],
  ],
  dislike: [
    ["not_interested", "Not interested"],
    ["too_long", "Too long"],
    ["too_repetitive", "Too repetitive"],
    ["too_technical", "Too technical"],
  ],
};

const state = {
  sources: new Map(),
  publishers: new Map(),
  sourcePromise: null,
  feedbackArticleId: null,
  feedbackType: null,
  toastTimer: null,
};

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (options.allow404 && response.status === 404) return null;
  if (!response.ok) {
    let message = `${response.status} ${response.statusText}`;
    try {
      const payload = await response.json();
      message = payload.detail || message;
    } catch (_error) {
      // Keep the HTTP status when the response is not JSON.
    }
    throw new Error(message);
  }
  if (response.status === 204) return null;
  return response.json();
}

function showToast(message) {
  clearTimeout(state.toastTimer);
  toast.textContent = message;
  toast.hidden = false;
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 3200);
}

function setDocumentTitle(title) {
  document.title = title ? `${title} · Daily Reading` : "Daily Reading";
}

function setActiveNavigation(route) {
  document.querySelectorAll(".drawer-link").forEach((link) => {
    link.classList.toggle("active", link.dataset.route === route);
  });
}

function openDrawer() {
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  menuButton.setAttribute("aria-expanded", "true");
  drawerBackdrop.hidden = false;
  requestAnimationFrame(() => drawerBackdrop.classList.add("visible"));
}

function closeDrawer() {
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  menuButton.setAttribute("aria-expanded", "false");
  drawerBackdrop.classList.remove("visible");
  setTimeout(() => {
    drawerBackdrop.hidden = true;
  }, 180);
}

function loadingView() {
  app.replaceChildren();
  const shell = element("section", "page-shell loading-view");
  shell.append(element("div", "loading-line loading-line-short"));
  shell.append(element("div", "loading-line"));
  const grid = element("div", "card-skeleton-grid");
  grid.append(element("div", "card-skeleton"));
  grid.append(element("div", "card-skeleton"));
  grid.append(element("div", "card-skeleton"));
  shell.append(grid);
  app.append(shell);
}

function messageView(title, message, error = false) {
  app.replaceChildren();
  const shell = element("section", `page-shell ${error ? "error-state" : "empty-state"}`);
  shell.append(element("div", "eyebrow", error ? "Something went wrong" : "Nothing here yet"));
  shell.append(element("h1", "", title));
  shell.append(element("p", "", message));
  app.append(shell);
}

async function loadSourceMaps() {
  if (state.sourcePromise) return state.sourcePromise;
  state.sourcePromise = Promise.allSettled([api("/sources"), api("/publishers")]).then(
    ([sourceResult, publisherResult]) => {
      if (sourceResult.status === "fulfilled") {
        sourceResult.value.forEach((source) => state.sources.set(source.id, source));
      }
      if (publisherResult.status === "fulfilled") {
        publisherResult.value.forEach((publisher) =>
          state.publishers.set(publisher.id, publisher),
        );
      }
    },
  );
  return state.sourcePromise;
}

function sourceLabel(article) {
  const source = state.sources.get(article.source_id);
  const publisher = source ? state.publishers.get(source.publisher_id) : null;
  const name = publisher?.name || source?.name || "Unknown source";
  return source?.category ? `${name} · ${source.category}` : name;
}

function humanDate(value, options = {}) {
  if (!value) return "Date unavailable";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.valueOf())) return "Date unavailable";
  return new Intl.DateTimeFormat(undefined, {
    month: "long",
    day: "numeric",
    year: "numeric",
    ...options,
  }).format(parsed);
}

function cardForArticle(article, { rank = null, itemId = null, savedAt = null } = {}) {
  const card = element("article", "reading-card");
  const suffix = itemId ? `?item=${itemId}` : "";
  const link = element("a", "card-link");
  link.href = `#/article/${article.id}${suffix}`;
  link.append(element("div", "card-rank", rank ? `No. ${String(rank).padStart(2, "0")}` : "Saved"));
  link.append(element("h2", "card-title", article.title));
  const detail = savedAt
    ? `${sourceLabel(article)} · Saved ${humanDate(savedAt)}`
    : sourceLabel(article);
  link.append(element("div", "card-source", detail));
  card.append(link);
  return card;
}

async function renderHome() {
  loadingView();
  setDocumentTitle("");
  setActiveNavigation("home");
  try {
    const [readingList] = await Promise.all([api("/daily-reading/today"), loadSourceMaps()]);
    app.replaceChildren();
    const shell = element("section", "page-shell");
    const heading = element("header", "page-heading");
    const titleGroup = element("div");
    titleGroup.append(element("div", "eyebrow", "Your selected stories"));
    titleGroup.append(element("h1", "", "Today’s reading"));
    heading.append(titleGroup);
    heading.append(element("div", "date-label", humanDate(`${readingList.list_date}T12:00:00`)));
    shell.append(heading);

    if (!readingList.items.length) {
      shell.append(element("p", "article-source", "Today’s list is empty."));
    } else {
      const grid = element("div", "reading-grid");
      readingList.items.forEach((item) => {
        grid.append(cardForArticle(item.article, { rank: item.rank, itemId: item.id }));
      });
      shell.append(grid);
    }
    app.append(shell);
  } catch (error) {
    if (String(error.message).includes("404")) {
      messageView(
        "Today’s list is not ready",
        "Run the daily agent, then return here to read the selected articles.",
      );
    } else {
      messageView("Could not load today’s reading", error.message, true);
    }
  }
}

async function renderSaved() {
  loadingView();
  setDocumentTitle("Saved");
  setActiveNavigation("saved");
  try {
    const [saved] = await Promise.all([api("/saved-articles"), loadSourceMaps()]);
    app.replaceChildren();
    const shell = element("section", "page-shell");
    const heading = element("header", "page-heading");
    const titleGroup = element("div");
    titleGroup.append(element("div", "eyebrow", "Your library"));
    titleGroup.append(element("h1", "", "Saved"));
    heading.append(titleGroup);
    heading.append(element("div", "date-label", `${saved.length} article${saved.length === 1 ? "" : "s"}`));
    shell.append(heading);
    if (!saved.length) {
      const empty = element("div", "empty-state");
      empty.append(element("h1", "", "No saved stories yet"));
      empty.append(element("p", "", "Save an article from its reading page and it will appear here."));
      shell.append(empty);
    } else {
      const grid = element("div", "reading-grid");
      saved.forEach((entry) => {
        grid.append(cardForArticle(entry.article, { savedAt: entry.saved_at }));
      });
      shell.append(grid);
    }
    app.append(shell);
  } catch (error) {
    messageView("Could not load saved articles", error.message, true);
  }
}

function articleParagraphs(content) {
  const container = element("div", "article-content");
  const paragraphs = String(content || "")
    .split(/\n\s*\n/)
    .map((part) => part.trim())
    .filter(Boolean);
  if (!paragraphs.length) {
    container.append(element("p", "", "The full article text is unavailable."));
  } else {
    paragraphs.forEach((paragraph) => container.append(element("p", "", paragraph)));
  }
  return container;
}

function supplementDetails(supplement) {
  if (!supplement || supplement.status !== "complete" || !supplement.cards.length) return null;
  const details = element("details", "supplement-section");
  details.append(element("summary", "", "Additional context"));
  details.append(
    element(
      "p",
      "supplement-intro",
      "AI-organized context drawn only from the cited reporting below. It is separate from the original article.",
    ),
  );
  const evidence = new Map(supplement.evidence_items.map((item) => [item.id, item]));
  supplement.cards.forEach((card) => {
    const cardNode = element("section", "supplement-card");
    cardNode.append(element("h3", "", card.heading));
    cardNode.append(element("p", "", card.summary_text));
    const citedIds = [...new Set(card.citations.map((citation) => citation.evidence_item_id))];
    if (citedIds.length) {
      const links = element("div", "citation-links");
      citedIds.forEach((evidenceId, index) => {
        const item = evidence.get(evidenceId);
        if (!item) return;
        const link = element("a", "citation-link", `${index + 1}. ${item.publisher}`);
        link.href = item.url;
        link.target = "_blank";
        link.rel = "noopener noreferrer";
        link.title = item.title;
        links.append(link);
      });
      cardNode.append(links);
    }
    details.append(cardNode);
  });
  return details;
}

function latestReaction(feedback, articleId) {
  return feedback.find(
    (event) => event.article_id === articleId && ["like", "dislike"].includes(event.event_type),
  )?.event_type;
}

function feedbackPanel(articleId, reaction) {
  const panel = element("section", "feedback-panel");
  panel.append(element("h2", "", "Was this worth your time?"));
  panel.append(element("p", "", "Your feedback improves future reading lists."));
  const actions = element("div", "feedback-actions");
  const like = element("button", `action-button ${reaction === "like" ? "selected-like" : ""}`);
  like.type = "button";
  like.dataset.feedback = "like";
  like.innerHTML = `${icons.like}<span>Like</span>`;
  like.addEventListener("click", () => openFeedbackDialog(articleId, "like"));
  const dislike = element(
    "button",
    `action-button ${reaction === "dislike" ? "selected-dislike" : ""}`,
  );
  dislike.type = "button";
  dislike.dataset.feedback = "dislike";
  dislike.innerHTML = `${icons.dislike}<span>Dislike</span>`;
  dislike.addEventListener("click", () => openFeedbackDialog(articleId, "dislike"));
  actions.append(like, dislike);
  panel.append(actions);
  return panel;
}

async function resolveReadingItem(articleId, requestedItemId) {
  if (requestedItemId) return requestedItemId;
  try {
    const list = await api("/daily-reading/today");
    return list.items.find((item) => item.article.id === articleId)?.id || null;
  } catch (_error) {
    return null;
  }
}

async function renderArticle(articleId, requestedItemId) {
  loadingView();
  setActiveNavigation("");
  try {
    const [article, _sources, saved, feedback, itemId] = await Promise.all([
      api(`/articles/${articleId}`),
      loadSourceMaps(),
      api("/saved-articles"),
      api("/feedback?limit=500"),
      resolveReadingItem(articleId, requestedItemId),
    ]);
    const supplement = itemId
      ? await api(`/supplements/items/${itemId}`, { allow404: true })
      : null;
    let isSaved = saved.some((entry) => entry.article.id === articleId);
    setDocumentTitle(article.title);
    app.replaceChildren();
    const shell = element("article", "page-shell article-shell");
    const back = element("a", "back-link");
    back.href = "#/";
    back.innerHTML = `${icons.back}<span>Today’s reading</span>`;
    shell.append(back);

    const header = element("header", "article-header");
    header.append(element("div", "eyebrow", sourceLabel(article)));
    header.append(element("h1", "article-title", article.title));
    const metaRow = element("div", "article-meta-row");
    const byline = [article.author, humanDate(article.published_at)].filter(Boolean).join(" · ");
    metaRow.append(element("div", "article-source", byline));
    const saveButton = element("button", `save-button ${isSaved ? "saved" : ""}`);
    saveButton.type = "button";
    saveButton.innerHTML = `${icons.save}<span>${isSaved ? "Saved" : "Save"}</span>`;
    saveButton.addEventListener("click", async () => {
      saveButton.disabled = true;
      try {
        await submitFeedback(articleId, isSaved ? "unstar" : "star", null);
        isSaved = !isSaved;
        saveButton.classList.toggle("saved", isSaved);
        saveButton.querySelector("span").textContent = isSaved ? "Saved" : "Save";
        showToast(isSaved ? "Article saved" : "Article removed from saved");
      } catch (error) {
        showToast(`Could not update saved article: ${error.message}`);
      } finally {
        saveButton.disabled = false;
      }
    });
    metaRow.append(saveButton);
    header.append(metaRow);
    shell.append(header);
    shell.append(articleParagraphs(article.content_text));

    const supplementNode = supplementDetails(supplement);
    if (supplementNode) shell.append(supplementNode);
    shell.append(feedbackPanel(articleId, latestReaction(feedback, articleId)));
    app.append(shell);
  } catch (error) {
    messageView("Could not load this article", error.message, true);
  }
}

function openFeedbackDialog(articleId, type) {
  state.feedbackArticleId = articleId;
  state.feedbackType = type;
  feedbackKicker.textContent = type === "like" ? "You liked this article" : "You disliked this article";
  reasonOptions.replaceChildren();
  [["", "No specific reason"], ...feedbackReasons[type]].forEach(([value, label]) => {
    const wrapper = element("div", "reason-option");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "feedback-reason";
    input.id = `reason-${value}`;
    input.value = value;
    const optionLabel = element("label", "", label);
    optionLabel.htmlFor = input.id;
    wrapper.append(input, optionLabel);
    reasonOptions.append(wrapper);
  });
  feedbackDialog.showModal();
}

async function submitFeedback(articleId, eventType, reason) {
  return api(`/articles/${articleId}/feedback`, {
    method: "POST",
    body: JSON.stringify({ event_type: eventType, reason }),
  });
}

async function saveReaction() {
  const selected = feedbackForm.querySelector('input[name="feedback-reason"]:checked');
  const reason = selected?.value || null;
  const articleId = state.feedbackArticleId;
  const eventType = state.feedbackType;
  if (!articleId || !eventType) return;
  const submitButton = document.querySelector("#feedback-submit");
  submitButton.disabled = true;
  try {
    await submitFeedback(articleId, eventType, reason);
    feedbackDialog.close();
    document.querySelectorAll("[data-feedback]").forEach((button) => {
      button.classList.remove("selected-like", "selected-dislike");
      if (button.dataset.feedback === eventType) {
        button.classList.add(eventType === "like" ? "selected-like" : "selected-dislike");
      }
    });
    showToast(reason ? "Feedback saved with your reason" : "Feedback saved");
  } catch (error) {
    showToast(`Could not save feedback: ${error.message}`);
  } finally {
    submitButton.disabled = false;
  }
}

function parseRoute() {
  const raw = location.hash.slice(1) || "/";
  const [path, query = ""] = raw.split("?");
  const match = path.match(/^\/article\/(\d+)$/);
  if (match) {
    return {
      name: "article",
      articleId: Number(match[1]),
      itemId: Number(new URLSearchParams(query).get("item")) || null,
    };
  }
  if (path === "/saved") return { name: "saved" };
  return { name: "home" };
}

async function renderRoute() {
  closeDrawer();
  window.scrollTo(0, 0);
  const route = parseRoute();
  if (route.name === "article") {
    await renderArticle(route.articleId, route.itemId);
  } else if (route.name === "saved") {
    await renderSaved();
  } else {
    await renderHome();
  }
  app.focus({ preventScroll: true });
}

menuButton.addEventListener("click", () => {
  if (drawer.classList.contains("open")) closeDrawer();
  else openDrawer();
});
drawerBackdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
});
window.addEventListener("hashchange", renderRoute);
feedbackForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveReaction();
});
document.querySelector("#feedback-cancel").addEventListener("click", (event) => {
  event.preventDefault();
  feedbackDialog.close();
});

renderRoute();
