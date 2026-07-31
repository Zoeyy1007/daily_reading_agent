const app = document.querySelector("#app");
const menuButton = document.querySelector("#menu-button");
const drawer = document.querySelector("#navigation-drawer");
const drawerBackdrop = document.querySelector("#drawer-backdrop");
const feedbackDialog = document.querySelector("#feedback-dialog");
const feedbackForm = document.querySelector("#feedback-form");
const feedbackKicker = document.querySelector("#feedback-kicker");
const reasonOptions = document.querySelector("#reason-options");
const toast = document.querySelector("#toast");
const drawerAccount = document.querySelector("#drawer-account");
const accountName = document.querySelector("#account-name");
const logoutButton = document.querySelector("#logout-button");
const analyticsStorageKey = "daily_reading_visitor_id";

const icons = {
  back: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m15 18-6-6 6-6"/></svg>',
  like: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 10v11H3V10h4Zm0 10h10.3a2 2 0 0 0 2-1.7l1.1-7A2 2 0 0 0 18.4 9H14l.7-3.2A2.3 2.3 0 0 0 12.5 3L7 10Z"/></svg>',
  dislike: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M7 14V3H3v11h4Zm0-10h10.3a2 2 0 0 1 2 1.7l1.1 7a2 2 0 0 1-2 2.3H14l.7 3.2a2.3 2.3 0 0 1-2.2 2.8L7 14Z"/></svg>',
  save: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M6 3h12v18l-6-4-6 4z"/></svg>',
  eye: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6Z"/><circle cx="12" cy="12" r="2.5"/></svg>',
  eyeOff: '<svg aria-hidden="true" viewBox="0 0 24 24"><path d="m3 3 18 18M10.6 6.2A9.8 9.8 0 0 1 12 6c6 0 9.5 6 9.5 6a15 15 0 0 1-2.1 2.8M6.2 6.2C3.8 8 2.5 12 2.5 12s3.5 6 9.5 6a9 9 0 0 0 3-.5M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>',
};

const topicFeedbackReasons = [
  ["topic_politics", "Politics"],
  ["topic_technology", "Technology"],
  ["topic_artificial_intelligence", "Artificial intelligence"],
  ["topic_science", "Science"],
  ["topic_business", "Business"],
  ["topic_health", "Health"],
  ["topic_climate", "Climate"],
  ["topic_sports", "Sports"],
  ["topic_culture", "Culture"],
  ["topic_crime", "Crime"],
];

const feedbackReasons = {
  like: [
    ["strong_evidence", "Strong evidence"],
    ["good_writing", "Good writing"],
    ...topicFeedbackReasons,
  ],
  dislike: [
    ["not_interested", "Not interested"],
    ["too_long", "Too long"],
    ["too_repetitive", "Too repetitive"],
    ["too_technical", "Too technical"],
    ...topicFeedbackReasons,
  ],
};

const state = {
  sources: new Map(),
  publishers: new Map(),
  sourcePromise: null,
  feedbackArticleId: null,
  feedbackType: null,
  toastTimer: null,
  currentUser: null,
  fallbackVisitorId: null,
  lastTrackedPath: null,
  lastTrackedAt: 0,
};

function randomVisitorId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  const bytes = new Uint8Array(16);
  if (globalThis.crypto?.getRandomValues) {
    globalThis.crypto.getRandomValues(bytes);
  } else {
    for (let index = 0; index < bytes.length; index += 1) {
      bytes[index] = Math.floor(Math.random() * 256);
    }
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((value) => value.toString(16).padStart(2, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}

function visitorId() {
  try {
    let value = localStorage.getItem(analyticsStorageKey);
    if (!value) {
      value = randomVisitorId();
      localStorage.setItem(analyticsStorageKey, value);
    }
    return value;
  } catch (_error) {
    if (!state.fallbackVisitorId) state.fallbackVisitorId = randomVisitorId();
    return state.fallbackVisitorId;
  }
}

function trackPageView(path) {
  if (navigator.doNotTrack === "1") return;
  const now = Date.now();
  if (state.lastTrackedPath === path && now - state.lastTrackedAt < 1500) return;
  state.lastTrackedPath = path;
  state.lastTrackedAt = now;
  fetch("/analytics/events", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      visitor_id: visitorId(),
      event_type: "page_view",
      path,
    }),
  }).catch(() => {
    // Analytics must never interrupt reading or authentication.
  });
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
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
    const error = new Error(message);
    error.status = response.status;
    throw error;
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

function setAuthenticatedUser(user) {
  state.currentUser = user;
  document.body.classList.remove("auth-pending", "signed-out");
  document.body.classList.add("signed-in");
  menuButton.disabled = false;
  accountName.textContent = user.display_name || user.login_id;
  drawerAccount.hidden = false;
}

function setSignedOut() {
  state.currentUser = null;
  state.sources.clear();
  state.publishers.clear();
  state.sourcePromise = null;
  closeDrawer();
  document.body.classList.remove("auth-pending", "signed-in");
  document.body.classList.add("signed-out");
  menuButton.disabled = true;
  drawerAccount.hidden = true;
}

function authField(labelText, name, type, autocomplete, minimumLength) {
  const field = element("label", "auth-field");
  field.append(element("span", "", labelText));
  const input = document.createElement("input");
  input.name = name;
  input.type = type;
  input.autocomplete = autocomplete;
  input.required = true;
  input.minLength = minimumLength;
  input.maxLength = name === "login_id" ? 64 : 256;
  field.append(input);
  return field;
}

function renderAuth(mode = "login", notice = "") {
  setSignedOut();
  setDocumentTitle(mode === "register" ? "Create account" : "Log in");
  app.replaceChildren();
  const shell = element("section", "auth-shell");
  const panel = element("div", "auth-panel");
  panel.append(element("div", "eyebrow", "Your personal reading list"));
  panel.append(element("h1", "", mode === "register" ? "Create an account" : "Welcome back"));
  panel.append(
    element(
      "p",
      "auth-copy",
      mode === "register"
        ? "Choose a user ID and password to start reading."
        : "Log in to see today’s articles and your saved stories.",
    ),
  );
  const tabs = element("div", "auth-tabs");
  const loginTab = element("button", mode === "login" ? "active" : "", "Log in");
  const registerTab = element(
    "button",
    mode === "register" ? "active" : "",
    "Create account",
  );
  loginTab.type = registerTab.type = "button";
  loginTab.addEventListener("click", () => renderAuth("login"));
  registerTab.addEventListener("click", () => renderAuth("register"));
  tabs.append(loginTab, registerTab);
  panel.append(tabs);

  const form = element("form", "auth-form");
  form.append(authField("User ID", "login_id", "text", "username", 2));
  form.append(
    authField(
      "Password",
      "password",
      "password",
      mode === "register" ? "new-password" : "current-password",
      6,
    ),
  );
  const message = element("div", "auth-message", notice);
  message.hidden = !notice;
  form.append(message);
  const submit = element(
    "button",
    "button button-primary auth-submit",
    mode === "register" ? "Create account" : "Log in",
  );
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.hidden = true;
    const data = new FormData(form);
    try {
      const user = await api(mode === "register" ? "/auth/register" : "/auth/login", {
        method: "POST",
        body: JSON.stringify({
          login_id: data.get("login_id"),
          password: data.get("password"),
        }),
      });
      setAuthenticatedUser(user);
      if (location.hash !== "#/") {
        location.hash = "#/";
      } else {
        await renderRoute();
      }
    } catch (error) {
      message.textContent = error.message;
      message.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
  panel.append(form);
  shell.append(panel);
  app.append(shell);
  form.querySelector('input[name="login_id"]').focus();
  trackPageView(mode === "register" ? "/register" : "/login");
}

function handleUnauthorized(error) {
  if (error.status !== 401) return false;
  renderAuth("login", "Your session expired. Please log in again.");
  return true;
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
    if (handleUnauthorized(error)) return;
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
    if (handleUnauthorized(error)) return;
    messageView("Could not load saved articles", error.message, true);
  }
}

function signedScore(value) {
  const number = Number(value || 0);
  return `${number > 0 ? "+" : ""}${number.toFixed(2)}`;
}

function scoringBreakdown(item, profile) {
  if (!item) return null;
  const details = element("details", "score-section");
  details.append(
    element("summary", "", `Why this article scored ${Number(item.total_score).toFixed(2)}`),
  );
  const weights = profile.component_weights;
  const rows = [
    ["Freshness", item.freshness_score, weights.freshness],
    ["Configured topics", item.topic_score, weights.configured_topics],
    ["Preferred sources", item.source_score, weights.preferred_sources],
    ["Length fit", item.length_score, weights.length_fit],
  ];
  const grid = element("div", "score-breakdown");
  rows.forEach(([label, score, maximum]) => {
    const row = element("div", "score-row");
    const heading = element("div", "score-row-heading");
    heading.append(element("span", "", label));
    heading.append(element("strong", "", `${Number(score).toFixed(2)} / ${maximum}`));
    const track = element("div", "score-track");
    const fill = element("div", "score-fill");
    fill.style.width = `${Math.max(0, Math.min(100, (Number(score) / maximum) * 100))}%`;
    track.append(fill);
    row.append(heading, track);
    grid.append(row);
  });
  const personal = element("div", "personalization-result");
  personal.append(element("span", "", "Learned personalization"));
  const personalValue = element(
    "strong",
    Number(item.personalization_score) < 0 ? "negative" : "positive",
    signedScore(item.personalization_score),
  );
  personal.append(personalValue);
  grid.append(personal);
  grid.append(element("p", "score-reason", item.selection_reason));
  details.append(grid);
  return details;
}

async function renderScoring() {
  loadingView();
  setDocumentTitle("Scoring");
  setActiveNavigation("scoring");
  try {
    const profile = await api("/preferences/scoring");
    app.replaceChildren();
    const shell = element("section", "page-shell scoring-shell");
    const heading = element("header", "page-heading");
    const titleGroup = element("div");
    titleGroup.append(element("div", "eyebrow", "Transparent ranking"));
    titleGroup.append(element("h1", "", "Your scoring system"));
    heading.append(titleGroup);
    shell.append(heading);
    shell.append(
      element(
        "p",
        "scoring-intro",
        "Every article starts with the same four base components. Your latest likes, dislikes, and saves adjust future regenerated lists through a learned personalization score.",
      ),
    );

    const labels = {
      freshness: "Freshness",
      configured_topics: "Configured topics",
      preferred_sources: "Preferred sources",
      length_fit: "Length fit",
      personalization_max_adjustment: "Personalization range",
    };
    const weightGrid = element("div", "weight-grid");
    Object.entries(profile.component_weights).forEach(([name, value]) => {
      const card = element("div", "weight-card");
      card.append(element("span", "", labels[name] || name));
      card.append(
        element(
          "strong",
          "",
          name === "personalization_max_adjustment" ? `\u00b1${value}` : `${value} max`,
        ),
      );
      weightGrid.append(card);
    });
    shell.append(weightGrid);

    const preferenceSection = element("section", "preference-section");
    preferenceSection.append(element("h2", "", "Learned from your feedback"));
    preferenceSection.append(
      element(
        "p",
        "",
        "Potential adjustment is shown before article-feature confidence and averaging across multiple matches.",
      ),
    );
    if (!profile.preference_impacts.length) {
      preferenceSection.append(
        element("div", "preference-empty", "Like or dislike articles to build your profile."),
      );
    } else {
      const list = element("div", "preference-list");
      profile.preference_impacts.forEach((preference) => {
        const row = element("div", "preference-row");
        const name = element("div");
        name.append(element("strong", "", preference.feature_value));
        name.append(
          element(
            "span",
            "",
            `${preference.feature_type} \u00b7 ${preference.positive_count} positive \u00b7 ${preference.negative_count} negative`,
          ),
        );
        row.append(name);
        row.append(
          element(
            "strong",
            preference.potential_adjustment < 0 ? "negative" : "positive",
            signedScore(preference.potential_adjustment),
          ),
        );
        list.append(row);
      });
      preferenceSection.append(list);
    }
    shell.append(preferenceSection);
    app.append(shell);
  } catch (error) {
    if (handleUnauthorized(error)) return;
    messageView("Could not load your scoring profile", error.message, true);
  }
}

function editablePasswordField(labelText, name, autocomplete) {
  const field = element("label", "settings-field");
  field.append(element("span", "settings-label", labelText));
  const wrapper = element("div", "password-input-wrapper");
  const input = document.createElement("input");
  input.type = "password";
  input.name = name;
  input.autocomplete = autocomplete;
  input.required = true;
  input.minLength = 6;
  input.maxLength = 256;
  const toggle = element("button", "password-toggle");
  toggle.type = "button";
  toggle.setAttribute("aria-label", `Show ${labelText.toLowerCase()}`);
  toggle.innerHTML = icons.eye;
  toggle.addEventListener("click", () => {
    const reveal = input.type === "password";
    input.type = reveal ? "text" : "password";
    toggle.innerHTML = reveal ? icons.eyeOff : icons.eye;
    toggle.setAttribute(
      "aria-label",
      `${reveal ? "Hide" : "Show"} ${labelText.toLowerCase()}`,
    );
  });
  wrapper.append(input, toggle);
  field.append(wrapper);
  return field;
}

function readingSettingField(labelText, name, value, minimum, maximum, helpText) {
  const field = element("label", "settings-field");
  field.append(element("span", "settings-label", labelText));
  const input = document.createElement("input");
  input.type = "number";
  input.name = name;
  input.value = String(value);
  input.min = String(minimum);
  input.max = String(maximum);
  input.step = "1";
  input.required = true;
  field.append(input, element("small", "field-help", helpText));
  return field;
}

async function renderSettings() {
  loadingView();
  setDocumentTitle("User Settings");
  setActiveNavigation("settings");
  app.replaceChildren();
  const shell = element("section", "page-shell settings-shell");
  const heading = element("header", "page-heading");
  const titleGroup = element("div");
  titleGroup.append(element("div", "eyebrow", "Account"));
  titleGroup.append(element("h1", "", "User settings"));
  heading.append(titleGroup);
  shell.append(heading);

  const account = element("section", "settings-card");
  const idRow = element("div", "settings-row");
  idRow.append(element("span", "settings-label", "User ID"));
  idRow.append(element("strong", "", state.currentUser.login_id));
  const passwordRow = element("div", "settings-row");
  passwordRow.append(element("span", "settings-label", "Password"));
  passwordRow.append(element("strong", "masked-password", "••••••••"));
  account.append(idRow, passwordRow);
  account.append(
    element(
      "p",
      "settings-note",
      "Your existing password is stored as a one-way hash, so it cannot be displayed or recovered.",
    ),
  );

  const change = element("details", "password-change");
  change.append(element("summary", "", "Change password"));
  const form = element("form", "password-change-form");
  form.append(
    editablePasswordField("Current password", "current_password", "current-password"),
    editablePasswordField("New password", "new_password", "new-password"),
  );
  const message = element("div", "auth-message");
  message.hidden = true;
  form.append(message);
  const submit = element("button", "button button-primary", "Save new password");
  submit.type = "submit";
  form.append(submit);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    submit.disabled = true;
    message.hidden = true;
    const data = new FormData(form);
    try {
      await api("/auth/password", {
        method: "PATCH",
        body: JSON.stringify({
          current_password: data.get("current_password"),
          new_password: data.get("new_password"),
        }),
      });
      form.reset();
      form.querySelectorAll('input[type="text"]').forEach((input) => {
        input.type = "password";
      });
      form.querySelectorAll(".password-toggle").forEach((button) => {
        button.innerHTML = icons.eye;
        button.setAttribute("aria-label", "Show password");
      });
      showToast("Password updated");
      change.open = false;
    } catch (error) {
      if (handleUnauthorized(error)) return;
      message.textContent = error.message;
      message.hidden = false;
    } finally {
      submit.disabled = false;
    }
  });
  change.append(form);
  account.append(change);
  shell.append(account);
  app.append(shell);

  try {
    const readingSettings = await api("/auth/reading-settings");
    const readingSection = element("section", "reading-settings-section");
    readingSection.append(element("div", "eyebrow", "Daily list"));
    readingSection.append(element("h2", "", "Reading preferences"));
    const readingForm = element("form", "reading-settings-form settings-card");
    const listLength = readingSettingField(
      "Articles per daily list",
      "daily_list_length",
      readingSettings.daily_list_length,
      1,
      10,
      "Between 1 and 10 articles.",
    );
    const articleMinutes = readingSettingField(
      "Expected minutes per article",
      "expected_reading_minutes_per_article",
      readingSettings.expected_reading_minutes_per_article,
      2,
      25,
      "Between 2 and 25 minutes; articles near this length receive a stronger length-fit score.",
    );
    const total = element(
      "p",
      "reading-budget",
      `Daily reading budget: ${readingSettings.total_daily_reading_minutes} minutes`,
    );
    const updateBudget = () => {
      const count = Number(listLength.querySelector("input").value || 0);
      const minutes = Number(articleMinutes.querySelector("input").value || 0);
      total.textContent = `Daily reading budget: ${count * minutes} minutes`;
    };
    listLength.querySelector("input").addEventListener("input", updateBudget);
    articleMinutes.querySelector("input").addEventListener("input", updateBudget);
    const readingMessage = element("div", "auth-message");
    readingMessage.hidden = true;
    const saveReading = element("button", "button button-primary", "Save preferences");
    saveReading.type = "submit";
    readingForm.append(
      listLength,
      articleMinutes,
      total,
      element(
        "p",
        "settings-note",
        "Changes apply the next time a daily list is generated or regenerated.",
      ),
      readingMessage,
      saveReading,
    );
    readingForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      saveReading.disabled = true;
      readingMessage.hidden = true;
      const data = new FormData(readingForm);
      try {
        const updated = await api("/auth/reading-settings", {
          method: "PATCH",
          body: JSON.stringify({
            daily_list_length: Number(data.get("daily_list_length")),
            expected_reading_minutes_per_article: Number(
              data.get("expected_reading_minutes_per_article"),
            ),
          }),
        });
        total.textContent = `Daily reading budget: ${updated.total_daily_reading_minutes} minutes`;
        showToast("Reading preferences updated");
      } catch (error) {
        if (handleUnauthorized(error)) return;
        readingMessage.textContent = error.message;
        readingMessage.hidden = false;
      } finally {
        saveReading.disabled = false;
      }
    });
    readingSection.append(readingForm);
    shell.append(readingSection);
  } catch (error) {
    if (handleUnauthorized(error)) return;
    console.warn("Reading settings unavailable", error);
  }

  try {
    const summary = await api("/analytics/summary?days=30");
    const usage = element("section", "usage-section");
    usage.append(element("div", "eyebrow", "Last 30 days"));
    usage.append(element("h2", "", "Website usage"));
    const cards = element("div", "usage-grid");
    [
      [summary.total_page_views, "Page views"],
      [summary.unique_visitors, "Approx. unique visitors"],
      [summary.signed_in_users, "Signed-in users"],
    ].forEach(([value, label]) => {
      const card = element("div", "usage-card");
      card.append(element("strong", "", String(value)));
      card.append(element("span", "", label));
      cards.append(card);
    });
    usage.append(cards);
    usage.append(
      element(
        "p",
        "settings-note usage-note",
        "Unique visitors are approximate browser installations. No IP addresses or plaintext visitor IDs are stored.",
      ),
    );
    if (summary.daily.length) {
      const daily = element("div", "usage-daily");
      summary.daily.slice(-14).reverse().forEach((row) => {
        const entry = element("div", "usage-day");
        entry.append(element("time", "", row.day));
        entry.append(element("span", "", `${row.page_views} views`));
        entry.append(element("span", "", `${row.unique_visitors} visitors`));
        entry.append(element("span", "", `${row.signed_in_users} users`));
        daily.append(entry);
      });
      usage.append(daily);
    }
    shell.append(usage);
  } catch (error) {
    if (error.status !== 403 && !handleUnauthorized(error)) {
      console.warn("Usage metrics unavailable", error);
    }
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
  try {
    const list = await api("/daily-reading/today");
    if (requestedItemId) {
      return list.items.find((item) => item.id === requestedItemId) || null;
    }
    return list.items.find((item) => item.article.id === articleId) || null;
  } catch (_error) {
    return null;
  }
}

async function renderArticle(articleId, requestedItemId) {
  loadingView();
  setActiveNavigation("");
  try {
    const [article, _sources, saved, feedback, readingItem, scoringProfile] = await Promise.all([
      api(`/articles/${articleId}`),
      loadSourceMaps(),
      api("/saved-articles"),
      api("/feedback?limit=500"),
      resolveReadingItem(articleId, requestedItemId),
      api("/preferences/scoring"),
    ]);
    const itemId = readingItem?.id || null;
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
        if (handleUnauthorized(error)) return;
        showToast(`Could not update saved article: ${error.message}`);
      } finally {
        saveButton.disabled = false;
      }
    });
    metaRow.append(saveButton);
    header.append(metaRow);
    shell.append(header);
    const scoreNode = scoringBreakdown(readingItem, scoringProfile);
    if (scoreNode) shell.append(scoreNode);
    shell.append(articleParagraphs(article.content_text));

    const supplementNode = supplementDetails(supplement);
    if (supplementNode) shell.append(supplementNode);
    shell.append(feedbackPanel(articleId, latestReaction(feedback, articleId)));
    app.append(shell);
  } catch (error) {
    if (handleUnauthorized(error)) return;
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
    if (handleUnauthorized(error)) return;
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
  if (path === "/scoring") return { name: "scoring" };
  if (path === "/settings") return { name: "settings" };
  return { name: "home" };
}

async function renderRoute() {
  if (!state.currentUser) {
    renderAuth("login");
    return;
  }
  closeDrawer();
  window.scrollTo(0, 0);
  const route = parseRoute();
  let analyticsPath = "/";
  if (route.name === "article") {
    await renderArticle(route.articleId, route.itemId);
    analyticsPath = "/article";
  } else if (route.name === "saved") {
    await renderSaved();
    analyticsPath = "/saved";
  } else if (route.name === "scoring") {
    await renderScoring();
    analyticsPath = "/scoring";
  } else if (route.name === "settings") {
    await renderSettings();
    analyticsPath = "/settings";
  } else {
    await renderHome();
  }
  trackPageView(analyticsPath);
  app.focus({ preventScroll: true });
}

menuButton.addEventListener("click", () => {
  if (!state.currentUser) return;
  if (drawer.classList.contains("open")) closeDrawer();
  else openDrawer();
});
drawerBackdrop.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && drawer.classList.contains("open")) closeDrawer();
});
window.addEventListener("hashchange", () => {
  if (state.currentUser) renderRoute();
});
feedbackForm.addEventListener("submit", (event) => {
  event.preventDefault();
  saveReaction();
});
document.querySelector("#feedback-cancel").addEventListener("click", (event) => {
  event.preventDefault();
  feedbackDialog.close();
});

logoutButton.addEventListener("click", async () => {
  logoutButton.disabled = true;
  try {
    await api("/auth/logout", { method: "POST" });
  } catch (error) {
    showToast(`Could not contact the server: ${error.message}`);
  } finally {
    logoutButton.disabled = false;
    renderAuth("login", "You have been logged out.");
  }
});

async function initialize() {
  try {
    const user = await api("/auth/me");
    setAuthenticatedUser(user);
    await renderRoute();
  } catch (error) {
    if (error.status === 401) {
      renderAuth("login");
    } else {
      setSignedOut();
      messageView("Could not start Daily Reading", error.message, true);
    }
  }
}

initialize();
